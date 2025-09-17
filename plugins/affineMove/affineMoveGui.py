import os
import numpy as np
import cv2
import copy

from PyQt6.QtCore import QObject, QEventLoop, QEvent, pyqtSignal
from PyQt6 import uic
from PyQt6.QtWidgets import QWidget, QComboBox, QGraphicsScene, QGraphicsView
from PyQt6.QtCore import Qt

from plugin_components import (
    public,
    get_public_methods,
    LoggingHelper,
    CloseLockSignalProvider,
    ConnectionIndicatorStyle,
    DependencyManager,
)
from collisionDetection import CollisionDetector
from affineMoveVisualization import AffineMoveVisualization
from components.threadStopped import ThreadStopped


class ViewportClickCatcher(QObject):
    def __init__(self, view: QGraphicsView):
        super().__init__()
        self.view = view
        self._clicked_pos = None
        self._cancelled = False
        self._loop = QEventLoop()
        self.view.viewport().installEventFilter(self)
        self.view.installEventFilter(self)  # To catch key events

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                scene_pos = self.view.mapToScene(event.pos())
                self._clicked_pos = (scene_pos.x(), scene_pos.y())
                self._loop.quit()
                return True
        elif event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancelled = True
                self._loop.quit()
                return True
        return False

    def wait_for_click(self):
        self._loop.exec()
        self.view.viewport().removeEventFilter(self)
        self.view.removeEventFilter(self)
        if self._cancelled:
            return None
        return self._clicked_pos


class affineMoveGUI(QObject):
    """Affine Move GUI with dictionary-based plugin architecture."""

    # Signals for thread-safe communication
    update_planned_moves_signal = pyqtSignal(list)  # List of (manipulator_idx, current_pos, target_pos)
    clear_planned_moves_signal = pyqtSignal()
    sequence_completed_signal = pyqtSignal()

    ########Functions
    def __init__(self):
        super().__init__()
        self.path = os.path.dirname(__file__) + os.path.sep
        self.calibration_path = os.path.join(self.path, "calibration_data.npy")

        self.logger = LoggingHelper(self)
        self.cl = CloseLockSignalProvider()

        self.settingsWidget = uic.loadUi(self.path + "affinemove_Settings.ui")  # type: ignore
        self.MDIWidget = uic.loadUi(self.path + "affinemove_MDI.ui")  # type: ignore
        assert self.settingsWidget is not None, "AffineMove: settingsWidget is None"
        assert self.MDIWidget is not None, "AffineMove: MDIWidget is None"

        # Initialize dependency manager
        dependencies = {
            "micromanipulator": ["parse_settings_widget"],
            "camera": ["parse_settings_widget"],
            "positioning": ["parse_settings_widget"],
        }
        dependency_map = {
            "micromanipulator": "micromanipulatorBox",
            "camera": "cameraBox",
            "positioning": "positioningBox",
        }
        self.dm = DependencyManager("affineMove", dependencies, self.settingsWidget, dependency_map)

        # connect buttons to functions
        self.settingsWidget.findSutter.clicked.connect(self._find_sutter_functionality)
        self.settingsWidget.fetchMaskButton.clicked.connect(self._fetch_mask_functionality)
        self.settingsWidget.previewButton.clicked.connect(self._initialize_camera_preview)
        self.settingsWidget.saveCalibrationButton.clicked.connect(self._save_calibration)
        self.settingsWidget.loadCalibrationButton.clicked.connect(self._load_calibration)

        # bounding box UI connections
        self.settingsWidget.setBoundingBoxButton.clicked.connect(self._on_set_bounding_box_clicked)
        self.settingsWidget.clearBoundingBoxButton.clicked.connect(self._on_clear_bounding_box_clicked)
        self.settingsWidget.showBoundingBoxesCheckBox.toggled.connect(self._on_show_bounding_boxes_toggled)
        self.settingsWidget.refreshPositionsButton.clicked.connect(self._on_refresh_positions_clicked)

        # Initialize the combo boxes for dependencies
        self.camera_box: QComboBox = self.settingsWidget.cameraBox
        self.micromanipulator_box: QComboBox = self.settingsWidget.micromanipulatorBox
        self.positioning_box: QComboBox = self.settingsWidget.positioningBox
        self.manipulator_combo_box: QComboBox = self.settingsWidget.manipulatorComboBox
        self.show_bounding_boxes_checkbox = self.settingsWidget.showBoundingBoxesCheckBox
        self.camera_graphic_view: QGraphicsView = self.MDIWidget.cameraview

        # Initialize manipulator combo box with default options
        self._populate_manipulator_combo_box()
        self.camera_graphic_scene: QGraphicsScene = QGraphicsScene()
        self.camera_graphic_view.setScene(self.camera_graphic_scene)

        # Initialize visualization system
        self.visualization = AffineMoveVisualization(self.camera_graphic_view, self.camera_graphic_scene)

        # initialize internal state:
        self.iter = 0
        self.measurement_points = []
        self.measurement_point_names = []
        self.calibrations = {}  # manipulator 1, manipulator 2, ... calibration points
        self.settings = {}  # settings dictionary for sequence builder

        # Initialize collision detection system
        self.collision_detector = CollisionDetector()
        self.bounding_boxes_path = os.path.join(self.path, "bounding_boxes_data.npy")

        # Initialize position caching system
        self.cached_manipulator_positions = {}

        # Initialize planned moves tracking
        self.current_sequence = []  # Full sequence of planned moves
        self.sequence_iter = 0  # Current position in sequence
        self.planned_moves_cache = []  # Cache for next moves to display

        # Connect signals for thread-safe communication
        self.update_planned_moves_signal.connect(self._update_planned_moves_slot)
        self.clear_planned_moves_signal.connect(self._clear_planned_moves_slot)
        self.sequence_completed_signal.connect(self._sequence_completed_slot)

        # Load bounding boxes from file on startup
        self._load_bounding_boxes_from_file()

        # find status labels and indicators
        self.mm_status = self.settingsWidget.mmStatus
        self.sample_status = self.settingsWidget.sampleStatus
        self.points_status = self.settingsWidget.pointsStatus
        self.mm_indicator = self.settingsWidget.mmIndicator
        self.sample_indicator = self.settingsWidget.sampleIndicator
        self.points_indicator = self.settingsWidget.pointsIndicator

    ########Functions
    ########GUI Slots
    def _update_planned_moves_slot(self, planned_moves):
        """
        Thread-safe slot to update planned moves visualization.
        Args:
            planned_moves: List of (manipulator_idx, current_pos, target_pos) tuples
        """
        self.planned_moves_cache = planned_moves
        self._add_visual_overlays()  # Redraw overlays with new planned moves

    def _clear_planned_moves_slot(self):
        """Thread-safe slot to clear planned moves visualization."""
        self.planned_moves_cache = []
        self._add_visual_overlays()  # Redraw overlays without planned moves

    def _sequence_completed_slot(self):
        """Thread-safe slot called when movement sequence is completed."""
        self.current_sequence = []
        self.sequence_iter = 0
        self.planned_moves_cache = []
        self._add_visual_overlays()  # Redraw overlays

    ########Functions
    ################################### internal
    def _wait_for_input(self) -> tuple[float, float] | None:
        """
        Waits for a mouse click on the camera graphics view and returns the (x, y)
        position in scene coordinates. This method blocks until a click is received or Esc is pressed.
        Returns None if cancelled.
        """
        catcher = ViewportClickCatcher(self.camera_graphic_view)
        return catcher.wait_for_click()

    def _fetch_dep_plugins(self):
        """Returns the micromanipulator, camera and positioning plugins as dictionaries."""

        result = self.dm.validate_and_extract_dependency_settings(self.settings)
        status, state = result
        if status != 0:
            self.logger.log_warn(f"Dependency validation failed: {state}")
            return None, None, None

        func_dict = self.dm.get_function_dict_for_dependencies()
        mm_functions = func_dict["micromanipulator"]
        camera_functions = func_dict["camera"]
        positioning_functions = func_dict["positioning"]

        # Filter to include only the selected plugins of each type
        mm_functions = mm_functions[self.settings["micromanipulator"]]
        camera_functions = camera_functions[self.settings["camera"]]
        positioning_functions = positioning_functions[self.settings["positioning"]]

        return mm_functions, camera_functions, positioning_functions

    def _find_sutter_functionality(self):
        mm, _, _ = self._fetch_dep_plugins()
        if mm is None:
            self.logger.log_warn("Micromanipulator plugin not available")
            return

        status, state = mm["mm_open"]()
        if status:
            self.logger.log_info(f"{state['Error message']} {state.get('Exception', '')}")
            return
        status, ret = mm["mm_devices"]()
        if status:
            self.logger.log_info(f"{state['Error message']} {state.get('Exception', '')}")
            return
        dev_count, dev_statuses = ret
        # calibrate every available manipulator
        for i, status in enumerate(dev_statuses):
            if status == 1:
                code, status = mm["mm_change_active_device"](i + 1)
                self.logger.info_popup(
                    f"AffineMove: calibrating manipulator {i + 1}.\nClick on the camera view to set calibration points (Esc to cancel)"
                )
                # calibrate
                #status, state = mm["mm_calibrate"]()
                #self.logger.log_debug(
                #    f"Calibration status manipulator {i + 1}: {state.get('Error message', 'Success')}"
                #)
                """                
                # move to "home"
                status, state = mm["mm_move"](12500, 12500)
                self.logger.log_debug(f"Moved manipulator {i + 1} to home position: {state.get('Error message', 'Success')}")
                """

                points = []
                moves = [(0, 0), (3000, 0), (0, 3000)]
                for move in moves:
                    status, state = mm["mm_move_relative"](z_change=-1000)  # slightly up to avoid collisions
                    if status:
                        self.logger.log_info(
                            f"Error moving manipulator {i + 1} to calibration position: {state.get('Error message', 'Unknown error')}"
                        )
                        return
                    status, state = mm["mm_move_relative"](x_change=move[0], y_change=move[1])
                    if status:
                        self.logger.log_info(
                            f"Error moving manipulator {i + 1} to calibration position: {state.get('Error message', 'Unknown error')}"
                        )
                        return
                    status, state = mm["mm_move_relative"](z_change=1000) # back down after move
                    if status:
                        self.logger.log_info(
                            f"Error moving manipulator {i + 1} to calibration position: {state.get('Error message', 'Unknown error')}"
                        )
                        return
                    # Update cached position after move
                    try:
                        current_pos = mm["mm_current_position"]()
                        if current_pos and len(current_pos) >= 3:
                            self.update_manipulator_position(i + 1, current_pos)
                    except Exception as e:
                        self.logger.log_debug(f"Could not update cached position during calibration: {e}")

                    point = self._wait_for_input()
                    if point is None:
                        self.logger.info_popup("Calibration cancelled by user.")
                        return
                    ret = mm["mm_current_position"]()
                    if len(ret) < 3:
                        self.logger.log_warn(f"Could not retrieve current position for manipulator {i + 1}: {ret}")
                        return
                    x, y, z = ret

                    self.logger.log_debug(f"Clicked point: {point}, current position: ({x}, {y}, {z})")
                    mm_point = (x, y)
                    points.append((mm_point, point))

                # Compute the affine transformation
                mm_points = np.array([pt[0] for pt in points], dtype=np.float32)
                view_points = np.array([pt[1] for pt in points], dtype=np.float32)
                affine_transform = cv2.getAffineTransform(view_points, mm_points)
                self.calibrations[i + 1] = affine_transform

                """
                # back to home
                mm["mm_move"](12500, 12500)
                """

        self.update_status()

    def _fetch_mask_functionality(self):
        self.logger.log_debug("Fetching mask functionality from positioning plugin...")
        _, _, pos = self._fetch_dep_plugins()
        if pos is None:
            self.logger.log_warn("Positioning plugin is None in _fetch_mask_functionality")
            return
        points, names = pos["positioning_measurement_points"]()
        if points is None or names is None:
            self.logger.info_popup("AffineMove: No measurement points available in positioning plugin")
            self.logger.log_error("No measurement points or names returned from positioning plugin")
            return
        self.measurement_points = points
        self.measurement_point_names = names
        self.logger.log_info(f"Fetched {len(points)} measurement points from positioning plugin.")
        self.update_status()

    def _initialize_camera_preview(self):
        """
        Initializes the camera preview by starting the and updating the graphics view.
        This function is called when the camera plugin is selected.
        """
        self.logger.log_debug("Initializing camera preview")
        _, cam, _ = self._fetch_dep_plugins()
        thread = cam["get_thread"]()
        if thread is None:
            self.logger.log_warn("No active camera thread found")
            self.logger.info_popup("Start camera preview on the camera tab first")
            return
        # connect signal to update the graphics view
        thread.new_frame.connect(self.update_graphics_view)
        self.logger.log_info("Camera preview started")

    def _on_set_bounding_box_clicked(self):
        """Handle the Set Bounding Box button click"""
        # Get currently selected manipulator
        current_text = self.manipulator_combo_box.currentText()
        if not current_text:
            self.logger.info_popup("Please select a manipulator first")
            return

        # Extract manipulator number from text like "Manipulator 1", "Manipulator 2", etc.
        try:
            manipulator_id = int(current_text.split()[-1])
        except (ValueError, IndexError):
            self.logger.info_popup("Invalid manipulator selection")
            return

        self.setup_manipulator_bounding_box(manipulator_id)

    def _on_clear_bounding_box_clicked(self):
        """Handle the Clear Bounding Box button click"""
        # Get currently selected manipulator
        current_text = self.manipulator_combo_box.currentText()
        if not current_text:
            self.logger.info_popup("Please select a manipulator first")
            return

        # Extract manipulator number from text
        try:
            manipulator_id = int(current_text.split()[-1])
        except (ValueError, IndexError):
            self.logger.info_popup("Invalid manipulator selection")
            return

        self.clear_manipulator_bounding_box(manipulator_id)

    def _on_show_bounding_boxes_toggled(self, checked: bool):
        """Handle the Show Bounding Boxes checkbox toggle"""
        # Force a redraw of the overlay to show/hide bounding boxes
        if hasattr(self, "camera_graphic_view") and self.camera_graphic_view:
            self._add_visual_overlays()

    def _populate_manipulator_combo_box(self):
        """Populate the manipulator combo box with available manipulators"""
        self.manipulator_combo_box.clear()

        # Add default options (these can be updated when manipulators are detected)
        for i in range(1, 5):  # Support up to 4 manipulators
            self.manipulator_combo_box.addItem(f"Manipulator {i}")

    def _on_refresh_positions_clicked(self):
        """Handle the Refresh Positions button click"""
        success_count = self.refresh_all_manipulator_positions()
        if success_count > 0:
            self._add_visual_overlays()  # Redraw overlays with updated positions
        else:
            self.logger.info_popup("No manipulator positions updated")

    def _save_calibration(self):
        """Write the current calibration data to a file. This implemetation keeps a single calibration file
        for all manipulators instead of multiple files to choose from. TODO: implement a way to choose where to save and with what name (if really necessary)
        """
        if not self.calibrations:
            self.logger.log_info("No calibration data to save.")
            return

        # Define the file path
        file_path = os.path.join(self.calibration_path)

        # Save the calibration data
        np.save(file_path, self.calibrations)
        self.logger.info_popup(f"Calibration data saved to {file_path}")

    def _load_calibration(self) -> tuple[int, dict[str, str]]:
        """Load the calibration data from a file. This implemetation keeps a single calibration file
        for all manipulators instead of multiple files to choose from. TODO: implement a way to choose where to load from and with what name (if really necessary)
        """
        file_path = os.path.join(self.calibration_path)

        if not os.path.exists(file_path):
            self.logger.log_info(f"No calibration data found at {file_path}")
            return 1, {"Error message": f"No calibration data found at {file_path}"}

        # calibrate all manipulators
        mm, _, _ = self._fetch_dep_plugins()
        status, state = mm["mm_open"]()
        if status:
            self.logger.log_info(f"{state['Error message']} {state.get('Exception', '')}")
            return status, state
        status, ret = mm["mm_devices"]()
        if status:
            self.logger.log_info(f"{state['Error message']} {state.get('Exception', '')}")
            return status, state
        dev_count, dev_statuses = ret
        # calibrate every available manipulator
        for i, status in enumerate(dev_statuses):
            self.logger.log_info(f"Loading calibration for manipulator {i + 1}, status: {status}")
            if status == 1:
                code, status = mm["mm_change_active_device"](i + 1)
                self.logger.log_info(f"{code} - Changing active device to {i + 1} {status}")
                if code != 0:
                    return 1, {
                        "Error message": f"Error changing active device to {i + 1}: {status.get('Error message', 'Unknown error')}"
                    }
                status, state = mm["mm_calibrate"]()

        # Load the calibration data
        self.calibrations = np.load(file_path, allow_pickle=True).item()
        self.update_status()
        return 0, {"message": f"Calibration data loaded from {file_path}"}

    def convert_to_mm_coords(self, point: tuple[float, float], mm_dev: int) -> tuple[float, float] | None:
        """
        Converts a point from camera coordinates to micromanipulator coordinates
        using the previously computed affine transformation.

        Args:
            point (tuple): (x, y) point in camera coordinates.
            mm_dev (int): Manipulator device index.

        Returns:
            tuple: Transformed point in manipulator coordinates.
        """
        if mm_dev not in self.calibrations:
            return None

        calibration = self.calibrations[mm_dev]  # 2x3 matrix

        # Ensure point is shape (1, 2) — cv2.transform expects shape (N, 2) for 2x3 matrices
        point_np = np.array([point], dtype=np.float32)  # shape (1, 2)

        # Apply affine transformation
        mm_point = cv2.transform(point_np[None, :, :], calibration)[0][0]  # (1,1,2) -> (2,)

        return tuple(mm_point)

    def convert_mm_to_camera_coords(self, point: tuple[float, float], mm_dev: int) -> tuple[float, float] | None:
        """
        Converts a point from micromanipulator coordinates to camera coordinates
        using the previously computed affine transformation.

        Args:
            point (tuple): (x, y) point in micromanipulator coordinates.
            mm_dev (int): Manipulator device index.

        Returns:
            tuple: Transformed point in camera coordinates.
        """
        if mm_dev not in self.calibrations:
            return None

        calibration = self.calibrations[mm_dev]  # 2x3 matrix
        # Invert the affine transformation matrix
        inverse_calibration = cv2.invertAffineTransform(calibration)
        # Ensure point is shape (1, 2) — cv2.transform expects shape (N, 2) for 2x3 matrices
        point_np = np.array([point], dtype=np.float32)  # shape (1, 2)

        # Apply affine transformation
        camera_point = cv2.transform(point_np[None, :, :], inverse_calibration)[0][0]  # (1,1,2) -> (2,)

        return tuple(camera_point)

    def setup_manipulator_bounding_box(self, manipulator_idx: int) -> tuple[int, str]:
        """
        Interactive setup of manipulator bounding box by clicking two opposite corners on camera view.
        Creates an axis-aligned bounding box defined by two relative coordinates.

        Args:
            manipulator_idx: Manipulator index (1-based)

        Returns:
            tuple: (status, message)
        """
        try:
            self.logger.info_popup(
                f"Click 2 opposite corners to define axis-aligned bounding box for manipulator {manipulator_idx}. Press ESC to cancel."
            )

            corners = []
            for i in range(2):
                self.logger.log_info(f"Waiting for corner {i + 1}/2...")
                click_pos = self._wait_for_input()
                if click_pos is None:
                    return 1, "Bounding box setup cancelled"
                corners.append(click_pos)
                self.logger.log_info(f"Corner {i + 1}: ({click_pos[0]:.1f}, {click_pos[1]:.1f})")

            # Convert two corner points to axis-aligned bounding box coordinates
            x1, y1 = corners[0]
            x2, y2 = corners[1]

            # Create axis-aligned bounding box using min/max coordinates
            min_x, max_x = min(x1, x2), max(x1, x2)
            min_y, max_y = min(y1, y2), max(y1, y2)

            # Get current manipulator position in camera coordinates to compute relative coordinates
            current_tip_pos = None
            try:
                mm, _, _ = self._fetch_dep_plugins()
                assert mm is not None, "Micromanipulator plugin not available"
                # Switch to the manipulator and get its position
                code, status = mm["mm_change_active_device"](manipulator_idx)
                if code == 0:
                    mm_pos = mm["mm_current_position"]()
                    if mm_pos and len(mm_pos) >= 2 and manipulator_idx in self.calibrations:
                        # Convert MM coordinates to camera coordinates
                        current_tip_pos = self.convert_mm_to_camera_coords((mm_pos[0], mm_pos[1]), manipulator_idx)
                        if current_tip_pos:
                            self.logger.log_info(
                                f"Current tip position for manipulator {manipulator_idx}: {current_tip_pos}"
                            )
                            # Update cached position
                            self.update_manipulator_position(manipulator_idx, mm_pos)
            except Exception as e:
                self.logger.log_debug(f"Could not get current manipulator position: {e}")

            # If we have the tip position, store relative coordinates, otherwise store absolute
            if current_tip_pos:
                # Calculate relative coordinates from tip position
                tip_x, tip_y = current_tip_pos
                relative_coords = [(min_x - tip_x, min_y - tip_y), (max_x - tip_x, max_y - tip_y)]
                self.logger.log_info(f"Storing relative coordinates: {relative_coords}")
            else:
                raise ValueError("Current manipulator position not available, cannot set relative bounding box")

            # Set the bounding box
            status, message = self.set_manipulator_bounding_box(manipulator_idx, relative_coords)

            # If we have tip position, update the collision detector with it
            if current_tip_pos and status == 0:
                self.collision_detector.update_manipulator_tip_position(
                    manipulator_idx, current_tip_pos[0], current_tip_pos[1]
                )

            if status == 0:
                self._add_visual_overlays()  # Refresh visual overlays
                self.logger.info_popup(f"Axis-aligned bounding box set for manipulator {manipulator_idx}")

            return status, message

        except Exception as e:
            return 1, f"Error setting up bounding box: {e}"

    def set_manipulator_bounding_box(
        self, manipulator_idx: int, relative_coords: list[tuple[float, float]]
    ) -> tuple[int, str]:
        """
        Set a manipulator's bounding box using two relative coordinates.

        Args:
            manipulator_idx: Manipulator index (1-based)
            relative_coords: List of two tuples representing (min_x, min_y) and (max_x, max_y)

        Returns:
            tuple: (status, message)
        """
        try:
            if len(relative_coords) != 2:
                return 1, "Bounding box must be defined by exactly 2 coordinates"

            # Validate coordinates are axis-aligned
            (min_x, min_y), (max_x, max_y) = relative_coords
            if min_x >= max_x or min_y >= max_y:
                return 1, "Invalid bounding box coordinates: min values must be less than max values"

            # Store in CollisionDetector (source of truth)
            success = self.collision_detector.set_manipulator_bounding_box(manipulator_idx, relative_coords)

            if success:
                # Save to file
                self._save_bounding_boxes_to_file()
                return 0, f"Bounding box set for manipulator {manipulator_idx}"
            else:
                return 1, f"Failed to set bounding box for manipulator {manipulator_idx}"

        except Exception as e:
            return 1, f"Error setting bounding box: {e}"

    def clear_manipulator_bounding_box(self, manipulator_idx: int) -> tuple[int, str]:
        """
        Clear the bounding box for a manipulator.

        Args:
            manipulator_idx: Manipulator index (1-based)

        Returns:
            tuple: (status, message)
        """
        # Clear from CollisionDetector (source of truth)
        success = self.collision_detector.clear_manipulator_bounding_box(manipulator_idx)

        if success:
            self._save_bounding_boxes_to_file()  # Save updated bounding boxes to file
            self._add_visual_overlays()  # Refresh visual overlays
            return 0, f"Bounding box cleared for manipulator {manipulator_idx}"
        else:
            return 1, f"No bounding box found for manipulator {manipulator_idx}"

    def _save_bounding_boxes_to_file(self):
        """Save the current bounding box data to a file."""
        try:
            # Get current bounding boxes from CollisionDetector (source of truth)
            current_boxes = self.collision_detector.get_all_bounding_boxes()

            if not current_boxes:
                self.logger.log_debug("No bounding boxes to save")
                return

            # Convert AABB objects to serializable format
            serializable_boxes = {}
            for manipulator_idx, aabb in current_boxes.items():
                serializable_boxes[manipulator_idx] = aabb.get_corners()

            # Save to file
            np.save(self.bounding_boxes_path, serializable_boxes, allow_pickle=True)
            self.logger.log_info(f"Saved {len(current_boxes)} bounding box(es) to {self.bounding_boxes_path}")
        except Exception as e:
            self.logger.log_warn(f"Failed to save bounding box data: {e}")

    def _load_bounding_boxes_from_file(self):
        """Load bounding box data from file on startup and sync with CollisionDetector."""
        file_path = self.bounding_boxes_path

        if not os.path.exists(file_path):
            self.logger.log_debug(f"No bounding box data found at {file_path}")
            return

        try:
            loaded_boxes = np.load(file_path, allow_pickle=True).item()

            # Load bounding boxes into CollisionDetector
            loaded_count = 0
            for manipulator_idx, coords in loaded_boxes.items():
                if len(coords) == 2:
                    converted_coords = coords
                else:
                    self.logger.log_warn(
                        f"Invalid bounding box format for manipulator {manipulator_idx}: {len(coords)} coordinates"
                    )
                    continue

                # Store in CollisionDetector
                if self.collision_detector.set_manipulator_bounding_box(manipulator_idx, converted_coords):
                    loaded_count += 1

                # try to update the probe position if available
                try:
                    mm, _, _ = self._fetch_dep_plugins()
                    code, status = mm["mm_change_active_device"](manipulator_idx)
                    if code == 0:
                        mm_pos = mm["mm_current_position"]()
                        if mm_pos and len(mm_pos) >= 2:
                            self.update_manipulator_position(manipulator_idx, mm_pos)
                            self.collision_detector.update_manipulator_tip_position(
                                manipulator_idx, mm_pos[0], mm_pos[1]
                            )
                except Exception as e:
                    self.logger.log_info(f"Could not update cached tip position for manipulator {manipulator_idx}: {e}")

            self.logger.log_info(f"Loaded {loaded_count} bounding box(es) from {file_path}")
        except Exception as e:
            self.logger.log_warn(f"Failed to load bounding box data: {e}")

    ########Functions
    ###############GUI setting up

    def setup(self, settings) -> tuple[QWidget, QWidget]:
        """Sets up the GUI for the plugin. This function is called by hook to initialize the GUI."""
        self.logger.log_debug("Setting up affineMove GUI")
        self.dm.setup(settings)

        # Store settings internally (maintain .ini format)
        self.settings = copy.deepcopy(settings)

        self.logger.log_debug("AffineMove GUI setup completed")
        return self.settingsWidget

    ########Functions
    ###############GUI react to change

    def update_graphics_view(self, img):
        """Updates the graphics view with a new camera image using the visualization class."""
        self.visualization.update_graphics_view(img)
        self._add_visual_overlays()  # Redraw overlays after updating image

    def _add_visual_overlays(self):
        """Adds visual overlays using the visualization class."""
        try:
            # Get current manipulator positions in camera coordinates
            manipulator_positions = self._get_manipulator_positions_in_camera()

            # Get target coordinates if measurement points are available
            target_coords = self._get_target_coords_in_camera()
            # Prepare data for visualization
            bounding_boxes = self.collision_detector.get_all_bounding_boxes()
            # Use visualization class to draw overlays
            self.visualization.add_visual_overlays(
                manipulator_positions=manipulator_positions,
                target_positions=target_coords,
                planned_moves=self.planned_moves_cache,
                bounding_boxes=bounding_boxes,
            )

        except Exception as e:
            self.logger.log_warn(f"Error adding visual overlays: {e}")


    def _get_manipulator_positions_in_camera(self):
        """
        Get current positions of all manipulators in camera coordinates using cached positions.


        Returns:
            dict: Dictionary mapping manipulator index to camera coordinates (x, y) or None
        """
        positions = {}
        try:
            for manipulator_idx in self.cached_manipulator_positions.keys():
                try:
                    cached_pos = self.get_cached_manipulator_position(manipulator_idx)
                    if cached_pos and len(cached_pos) >= 2:
                        # Convert to camera coordinates
                        cam_pos = self.convert_mm_to_camera_coords((cached_pos[0], cached_pos[1]), manipulator_idx)
                        positions[manipulator_idx] = cam_pos
                    else:
                        positions[manipulator_idx] = None
                except Exception as e:
                    self.logger.log_debug(f"Could not convert cached position for manipulator {manipulator_idx}: {e}")
                    positions[manipulator_idx] = None

        except Exception as e:
            self.logger.log_warn(f"Error getting cached manipulator positions: {e}")

        return positions

    def update_manipulator_position(self, manipulator_idx: int, position: tuple) -> None:
        """Update cached position for a manipulator"""
        self.cached_manipulator_positions[manipulator_idx] = position

    def get_cached_manipulator_position(self, manipulator_idx: int) -> tuple | None:
        """Get cached position for a manipulator"""
        return self.cached_manipulator_positions.get(manipulator_idx)

    def refresh_all_manipulator_positions(self) -> int:
        """
        Refresh cached positions for all manipulators by querying hardware.
        This should only be called when the user explicitly requests it via the refresh button.
        Returns count of successfully updated positions.
        """
        success_count = 0
        try:
            mm, _, _ = self._fetch_dep_plugins()
            if mm is None:
                self.logger.log_warn("Micromanipulator plugin not available")
                return 0

            self.logger.log_info("Querying manipulator positions from hardware...")
            # get currently active manipulator
            status, active_manipulator = mm["mm_get_active_device"]()
            assert status == 0, (
                f"Failed to get active manipulator: {active_manipulator.get('Error message', 'Unknown error')}"
            )
            # Try to get positions for manipulators 1-4
            for manipulator_idx in range(1, 5):
                try:
                    # Change to this manipulator
                    code, status = mm["mm_change_active_device"](manipulator_idx)
                    if code == 0:  # Success
                        # Get current position from hardware
                        position = mm["mm_current_position"]()
                        if position and len(position) >= 3:
                            self.update_manipulator_position(manipulator_idx, position)

                            # Update bounding box tip position if calibration exists
                            if manipulator_idx in self.calibrations:
                                try:
                                    # Convert MM coordinates to camera coordinates
                                    cam_pos = self.convert_mm_to_camera_coords(
                                        (position[0], position[1]), manipulator_idx
                                    )
                                    if cam_pos:
                                        # Update collision detector with new tip position
                                        self.collision_detector.update_manipulator_tip_position(
                                            manipulator_idx, cam_pos[0], cam_pos[1]
                                        )
                                        self.logger.log_debug(
                                            f"Updated bounding box tip for manipulator {manipulator_idx}: {cam_pos}"
                                        )
                                except Exception as e:
                                    self.logger.log_debug(
                                        f"Could not update bounding box tip for manipulator {manipulator_idx}: {e}"
                                    )

                            success_count += 1
                            self.logger.log_debug(f"Updated position for manipulator {manipulator_idx}: {position}")
                except Exception as e:
                    self.logger.log_debug(f"Could not refresh position for manipulator {manipulator_idx}: {e}")

        except Exception as e:
            self.logger.log_warn(f"Error refreshing manipulator positions: {e}")

        # reset back to original manipulator
        if mm is not None:
            mm["mm_change_active_device"](active_manipulator)
        self.logger.log_info(f"Successfully updated {success_count} manipulator position(s)")
        return success_count

    def move_manipulator_and_update_bounding_box(
        self, manipulator_idx: int, x: float, y: float, z: float | None = None
    ) -> tuple[int, dict]:
        """
        Wrapper for moving a manipulator that also updates the bounding box tip position.

        Args:
            manipulator_idx: Manipulator index (1-based)
            x, y: Target coordinates in MM coordinates
            z: Optional Z coordinate, if None uses current Z

        Returns:
            tuple: (status, state_dict) from the movement operation
        """
        mm, _, _ = self._fetch_dep_plugins()
        if mm is None:
            return 1, {"Error message": "Micromanipulator plugin not available"}

        # Change to the target manipulator
        code, status = mm["mm_change_active_device"](manipulator_idx)
        if code != 0:
            return code, {"Error message": f"Failed to change to manipulator {manipulator_idx}"}
        if z is not None:
            mm["mm_move"](z=z)  # move z first to prevent scratches
        # Perform the move
        status, state = mm["mm_move"](x=x, y=y)
        if status == 0:  # Success
            # Update cached position
            final_pos = mm["mm_current_position"]()
            if final_pos and len(final_pos) >= 3:
                self.update_manipulator_position(manipulator_idx, final_pos)

                # Update bounding box tip position if calibration exists
                if manipulator_idx in self.calibrations:
                    # Convert MM coordinates to camera coordinates
                    cam_pos = self.convert_mm_to_camera_coords((final_pos[0], final_pos[1]), manipulator_idx)
                    if cam_pos:
                        # Update collision detector with new tip position
                        self.collision_detector.update_manipulator_tip_position(
                            manipulator_idx, cam_pos[0], cam_pos[1]
                        )
                        self.logger.log_debug(
                            f"Updated bounding box tip for manipulator {manipulator_idx} to camera coords: {cam_pos}"
                        )


            self.logger.log_debug(f"Successfully moved manipulator {manipulator_idx} to ({x}, {y})")

        return status, state



    def _get_target_coords_in_camera(self):
        """
        Get target coordinates for ALL measurement points in camera coordinates.

        Returns:
            dict: Dictionary mapping manipulator_index to camera_coordinates (x, y)
        """
        target_coords = {}

        if not self.measurement_points:
            return target_coords

        try:
            # Get positioning plugin to convert mask coordinates to camera coordinates
            _, _, pos = self._fetch_dep_plugins()
            if pos is None:
                self.logger.log_warn("No positioning plugin available for coordinate conversion")
                return target_coords

            for point_idx, point_set in enumerate(self.measurement_points):
                target_coords[point_idx] = {}

                for device_idx, point in enumerate(point_set, 1):  # device_idx starts from 1
                    if point and len(point) >= 2:
                        # Convert from mask coordinates to camera coordinates using positioning plugin
                        try:
                            camera_x, camera_y = pos["positioning_coords"](point)
                            target_coords[point_idx][device_idx] = (float(camera_x), float(camera_y))
                        except Exception as e:
                            self.logger.log_debug(
                                f"Error converting mask coordinates {point} to camera coordinates: {e}"
                            )

        except Exception as e:
            self.logger.log_warn(f"Error getting target coordinates: {e}")

        return target_coords

    def update_status(self):
        """
        Updates the status of the micromanipulator, sample and points.
        This function is called by the micromanipulator plugin when the status changes.
        """
        mm, cam, pos = self._fetch_dep_plugins()
        assert pos is not None, "Positioning plugin not available"
        if self.calibrations == {}:
            self.mm_indicator.setStyleSheet(ConnectionIndicatorStyle.RED_DISCONNECTED.value)
        else:
            self.mm_indicator.setStyleSheet(ConnectionIndicatorStyle.GREEN_CONNECTED.value)

        if pos["positioning_coords"]((0, 0)) == (-1, -1):
            self.sample_indicator.setStyleSheet(ConnectionIndicatorStyle.RED_DISCONNECTED.value)
        else:
            self.sample_indicator.setStyleSheet(ConnectionIndicatorStyle.GREEN_CONNECTED.value)

        if len(self.measurement_points) == 0:
            self.points_indicator.setStyleSheet(ConnectionIndicatorStyle.RED_DISCONNECTED.value)
        else:
            self.points_indicator.setStyleSheet(ConnectionIndicatorStyle.GREEN_CONNECTED.value)

    ########Functions
    ########plugins interraction
    def _get_public_methods(self):
        """
        Returns a nested dictionary of public methods for the plugin
        """
        # if the plugin type matches the requested type, return the functions

        return get_public_methods(self)

    def _getLogSignal(self):
        return self.logger.logger_signal

    def _getInfoSignal(self):
        return self.logger.info_popup_signal

    ########Functions to be used externally
    @public
    def parse_settings_widget(self) -> tuple[int, dict]:
        """
        Parses the settings widget and returns the settings as a dictionary.
        This function is called by the seq builder to get the settings for the plugin.
        """
        settings = {
            "micromanipulator": self.micromanipulator_box.currentText(),
            "camera": self.camera_box.currentText(),
            "positioning": self.positioning_box.currentText(),
        }
        # check if some dependencies are not set
        if not all(settings.values()):
            return 1, {"Error message": "AffineMove : Some dependencies are not set."}
        return 0, settings

    @public
    def setSettings(self, settings):
        """
        Sets the settings for the affineMove plugin. Called by the sequence builder.

        Args:
            settings (dict): A dictionary containing the settings for the affineMove plugin.
        """
        self.settings = settings
        self.logger.log_info(f"AffineMove settings updated: {settings}")

    @public
    def getIterations(self) -> int:
        """Get the number of iterations for the affineMove plugin. This is the number of measurement points available.

        Returns:
            int: The number of iterations.
        """
        return len(self.measurement_points)

    @public
    def loopingIteration(self, currentIteration):
        """
        Called by the sequence builder during loop execution. Moves to the measurement point
        corresponding to the current iteration with collision detection.

        Args:
            currentIteration (int): The current iteration index (0-based)

        Returns:
            tuple: [status, namePostfix] where status is 0 for success, namePostfix for file naming
        """
        try:
            mm, _, pos = self._fetch_dep_plugins()

            # check if plugins are available
            if mm is None or pos is None:
                return [3, "Dependencies not set for AffineMove"]

            # open mm and check for errors
            status, state = mm["mm_open"]()
            if status:
                self.logger.log_info(f"Error opening micromanipulator: {state.get('Error message', str(state))}")
                return [1, "Sutter HW error"]

            # check if there are measurement points available
            if len(self.measurement_points) == 0:
                self.logger.log_info("No measurement points available")
                return [3, "No measurement points available"]

            # check if currentIteration is valid
            if currentIteration >= len(self.measurement_points):
                self.logger.log_info(
                    f"Invalid iteration {currentIteration}, only {len(self.measurement_points)} points available"
                )
                return [3, f"Invalid iteration {currentIteration}"]

            points = self.measurement_points[currentIteration]  # these are stored as mask coordinates
            point_name = self.measurement_point_names[currentIteration]

            self.logger.log_info(f"Processing iteration {currentIteration}: {point_name}")

            # Convert mask coordinates to camera coordinates
            camera_target_points = []
            for device_idx, mask_point in enumerate(points, 1):
                # Convert mask coordinates to camera coordinates
                camera_coords = pos["positioning_coords"](mask_point)
                if camera_coords == (-1, -1):
                    self.logger.log_warn(
                        f"Failed to convert mask coordinates {mask_point} for manipulator {device_idx}"
                    )
                    continue
                camera_target_points.append((device_idx, camera_coords))

            if not camera_target_points:
                self.logger.log_warn("No valid target points after coordinate conversion")
                return [3, f"Invalid iteration {currentIteration}"]

            # Get current positions of all manipulators in camera coordinates
            current_positions = {}
            moves_dict = {}

            for manip_idx, target_camera_coords in camera_target_points:
                try:
                    current_mm_pos = mm["mm_current_position"](manip_idx)
                    if status != 0 or current_mm_pos is None:
                        self.logger.log_warn(f"Failed to get current position for manipulator {manip_idx}")
                        continue
                    # Cache the fresh position
                    self.update_manipulator_position(manip_idx, current_mm_pos)
                except Exception as e:
                    self.logger.log_warn(f"Exception getting position for manipulator {manip_idx}: {e}")
                    continue

                # Convert current MM position to camera coordinates
                current_camera_coords = self.convert_mm_to_camera_coords(current_mm_pos[:2], manip_idx)
                if current_camera_coords is None:
                    self.logger.log_warn(
                        f"Failed to convert current position to camera coordinates for manipulator {manip_idx}"
                    )
                    continue

                # Store for collision detection
                current_positions[manip_idx] = current_camera_coords
                moves_dict[manip_idx] = (current_camera_coords, target_camera_coords)

                self.logger.log_info(
                    f"Manipulator {manip_idx}: Current camera ({current_camera_coords[0]:.1f}, {current_camera_coords[1]:.1f}) -> Target ({target_camera_coords[0]:.1f}, {target_camera_coords[1]:.1f})"
                )

            if not moves_dict:
                self.logger.log_warn("No valid moves to execute after position validation")
                return [3, f"Invalid iteration {currentIteration}"]

            # Use collision detection to determine safe movement sequence
            self.logger.log_info("Starting collision detection analysis...")

            # Log bounding box information
            bbox_info = []
            for manip_idx in moves_dict.keys():
                bbox = self.collision_detector.get_bounding_box(manip_idx)
                if bbox:
                    corners = bbox.get_absolute_corners()
                    bbox_info.append(f"M{manip_idx}: tip=({bbox.tip_x:.1f},{bbox.tip_y:.1f}), bbox={corners}")
                else:
                    bbox_info.append(f"M{manip_idx}: no bounding box")
            self.logger.log_info(f"Bounding boxes: {bbox_info}")

            safe_sequence = self.collision_detector.generate_safe_movement_sequence(moves_dict)

            if not safe_sequence:
                self.logger.log_warn("No safe movement sequence found - potential collision risk")
                return [1, f"Invalid iteration {currentIteration} - no safe sequence"]

            self.logger.log_info(f"Safe movement sequence found with {len(safe_sequence)} moves: {safe_sequence}")

            # Preview the planned sequence before execution
            self._preview_planned_sequence(safe_sequence)

            # Execute the moves in the safe sequence
            status, message = self.execute_move_list(safe_sequence)

            if status == 0:
                self.logger.log_info(f"Successfully completed iteration {currentIteration}: {point_name}")
                return [0, f"_iter{currentIteration}_{point_name}"]
            else:
                self.logger.log_warn(f"Movement execution failed: {message}")
                return [1, "Error in movement execution"]

        except ThreadStopped as _:
            mm, _, _ = self._fetch_dep_plugins()
            if mm:
                mm["mm_stop"]()
            self.logger.log_info("Movement thread stopped by user")
            return (3, {"Error message": "Thread stopped by user"})
        except Exception as e:
            self.logger.log_info(f"Error in loopingIteration: {str(e)}")
            return [2, f"Error in looping iteration: {str(e)}"]

    def execute_move_list(self, move_sequence: list[tuple[int, tuple[float, float]]]) -> tuple[int, str]:
        """
        Execute a list of manipulator movements in the specified order.

        Args:
            move_sequence: List of (manipulator_idx, target_position) tuples from collision detector.
                          target_position is (x, y) in camera coordinates.

        Returns:
            tuple: (status, message) where status is 0 for success, 1+ for errors
        """
        mm, _, _ = self._fetch_dep_plugins()
        if mm is None:
            return 1, "Micromanipulator plugin not available"

        # Store the full sequence and reset iterator
        self.current_sequence = move_sequence.copy()
        self.sequence_iter = 0

        successful_moves = 0
        total_moves = len(move_sequence)

        self.logger.log_info(f"Executing {total_moves} manipulator moves in sequence")

        for move_idx, (manip_idx, (target_cam_x, target_cam_y)) in enumerate(move_sequence):
            # Update planned moves visualization for the NEXT move
            self._update_planned_moves_visualization(move_idx)

            # Convert target camera coordinates to MM coordinates
            target_mm_coords = self.convert_to_mm_coords((target_cam_x, target_cam_y), manip_idx)
            if target_mm_coords is None:
                self.logger.log_warn(f"Failed to convert coordinates for manipulator {manip_idx}, skipping")
                continue

            target_mm_x, target_mm_y = target_mm_coords

            self.logger.log_info(
                f"Moving manipulator {manip_idx}: Camera ({target_cam_x:.1f}, {target_cam_y:.1f}) -> MM ({target_mm_x:.3f}, {target_mm_y:.3f})"
            )

            # Execute the move using the wrapper that updates bounding box
            status, state = self.move_manipulator_and_update_bounding_box(manip_idx, target_mm_x, target_mm_y, z=0)

            if status == 0:  # Success
                successful_moves += 1
                self.sequence_iter += 1
                self.logger.log_info(f"Successfully moved manipulator {manip_idx}")

                # Update collision detector with new position
                if manip_idx in self.collision_detector.bounding_boxes:
                    self.collision_detector.bounding_boxes[manip_idx].move_bbox(target_cam_x, target_cam_y)
            else:
                error_msg = state.get("Error message", str(state))
                self.logger.log_warn(f"Failed to move manipulator {manip_idx}: {error_msg}")
                return 1, f"Movement failed for manipulator {manip_idx}: {error_msg}"

        # Signal that sequence is completed
        self.sequence_completed_signal.emit()

        if successful_moves == total_moves:
            self.logger.log_info(f"All {total_moves} manipulator movements completed successfully")
            return 0, f"Successfully completed {successful_moves}/{total_moves} moves"
        else:
            return 1, f"Only {successful_moves}/{total_moves} moves completed successfully"


    def _update_planned_moves_visualization(self, current_move_idx: int):
        """
        Update the visualization to show only the next planned move.
        Thread-safe: emits signal to update UI from main thread.

        Args:
            current_move_idx: Index of the move currently being executed
        """
        if current_move_idx >= len(self.current_sequence):
            # No more moves, clear visualization
            self.clear_planned_moves_signal.emit()
            return

        # Get the current move being executed
        manip_idx, (target_cam_x, target_cam_y) = self.current_sequence[current_move_idx]

        # Get current position in camera coordinates
        cached_pos = self.get_cached_manipulator_position(manip_idx)
        if cached_pos and len(cached_pos) >= 2:
            current_cam_pos = self.convert_mm_to_camera_coords((cached_pos[0], cached_pos[1]), manip_idx)
            if current_cam_pos:
                # Create planned move data: (manipulator_idx, current_pos, target_pos)
                planned_moves = [(manip_idx, current_cam_pos, (target_cam_x, target_cam_y))]

                # Emit signal to update visualization from main thread
                self.update_planned_moves_signal.emit(planned_moves)
                return


        # If we couldn't get current position, clear visualization
        self.clear_planned_moves_signal.emit()

    def _preview_planned_sequence(self, move_sequence: list[tuple[int, tuple[float, float]]]):
        """
        Preview the entire planned sequence by showing trajectory lines for all moves.
        This gives a visual overview before execution starts.

        Args:
            move_sequence: List of (manipulator_idx, target_position) tuples
        """
        preview_moves = []

        for manip_idx, (target_cam_x, target_cam_y) in move_sequence:
            # Get current position in camera coordinates
            cached_pos = self.get_cached_manipulator_position(manip_idx)
            if cached_pos and len(cached_pos) >= 2:
                current_cam_pos = self.convert_mm_to_camera_coords((cached_pos[0], cached_pos[1]), manip_idx)
                if current_cam_pos:
                    preview_moves.append((manip_idx, current_cam_pos, (target_cam_x, target_cam_y)))


        if preview_moves:
            # Emit signal to show preview
            self.update_planned_moves_signal.emit(preview_moves)
            self.logger.log_info(f"Previewing planned sequence with {len(preview_moves)} moves")
