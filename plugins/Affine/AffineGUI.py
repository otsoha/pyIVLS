import os
from datetime import datetime

from Affine_skimage import Affine, AffineError
from PyQt6 import QtWidgets, uic
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QImage, QPen, QPixmap
from PyQt6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QMenu
import csv
from affineDialog import dialog
from PyQt6.QtCore import pyqtSlot


class AffineGUI(QObject):
    """
    GUI implementation of the Affine plugin for pyIVLS.

    public API:

    -positioning_coords(coords: tuple[float, float]) -> tuple[float, float]

    revision 2.0.0
    -Added dialog for matching and manual mode. Added settings for preprocessing.
    -Formatted into proper pyIVLS plugin format.

    Revision 0.1.1
    -Manual mode implementeted.

    version 0.1
    2025.05.21
    otsoha
    """

    log_message = pyqtSignal(str)
    info_message = pyqtSignal(str)
    closeLock = pyqtSignal(bool)
    COORD_DATA = Qt.ItemDataRole.UserRole + 1

    @pyqtSlot(int, dict)
    def emit_log(self, status: int, state: dict) -> None:
        """
        Emits a standardized log message for status dicts or error lists.
        Args:
            status (int): status code, 0 for success, non-zero for error.
            state (dict): dictionary in the standard pyIVLS format

        """
        plugin_name = self.__class__.__name__
        # only emit if error occurred
        if status != 0:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")
            msg = state.get("Error message", "Unknown error")
            exception = state.get("Exception", "Not provided")

            log = f"{timestamp} : {plugin_name} : {status} : {msg} : Exception: {exception}"

            self.log_message.emit(log)

    def __init__(self, settings=None):
        super().__init__()
        # load ui files
        self.settingsWidget, self.MDIWidget = self._load_widgets()
        # init settings if needed
        self.settings = settings if settings is not None else {}

        # init core functionality
        self.affine = Affine(self.settings)
        self.dependency = ["camera"]

        # init dependency functions
        self.functions = {}

        self.mdi_img = None
        self.mdi_mask = None
        self.manual_mode = False
        self.expecting_img_click = False
        self.mask_points = []
        self.img_points = []
        self.num_needed = 4  # Read from user?
        self.tp_arr = []
        self.dialog = None

    # GUI initialization

    # TODO: Read settings from file, for instance latest points and mask + default names for text inputs.
    def _initGUI(self, settings):
        self._gui_change_mask_uploaded(False)
        self.settings = settings
        settingsWidget: QtWidgets.QWidget = self.settingsWidget
        MDIWidget = self.MDIWidget
        self.last_mask_path = settings.get("default_mask_path", None)
        pointcount = settings.get("pointcount", 2)
        addpointscheck = settings.get("addpointscheck", "False")
        centerclicks = settings.get("centerclicks", "False")
        centerclicks = True if centerclicks == "True" else False
        addpointscheck = True if addpointscheck == "True" else False
        ratiotest = float(settings["ratiotest"])
        residualthreshold = int(settings["residualthreshold"])
        crosscheck = True if settings["crosscheck"] == "True" else False

        # set the settings widget values
        self.settingsWidget.pointCount.setCurrentText(str(pointcount))
        self.settingsWidget.addPointsCheck.setChecked(addpointscheck)
        self.settingsWidget.centerClicks.setChecked(centerclicks)

        # read preprocessing settings
        s = {}
        s["sigmaimage"] = settings.get("sigmaimage")
        s["sigmamask"] = settings.get("sigmamask")
        s["sigmaimage"] = float(s["sigmaimage"])
        s["sigmamask"] = float(s["sigmamask"])
        s["blurmask"] = settings["blurmask"]
        s["invertmask"] = settings["invertmask"]
        s["equalizemask"] = settings["equalizemask"]
        s["cannymask"] = settings["cannymask"]
        s["blurimage"] = settings["blurimage"]
        s["invertimage"] = settings["invertimage"]
        s["equalizeimage"] = settings["equalizeimage"]
        s["cannyimage"] = settings["cannyimage"]
        # convert to boolean from string literals "True" and "False"
        s["blurmask"] = True if s["blurmask"] == "True" else False
        s["invertmask"] = True if s["invertmask"] == "True" else False
        s["equalizemask"] = True if s["equalizemask"] == "True" else False
        s["cannymask"] = True if s["cannymask"] == "True" else False
        s["blurimage"] = True if s["blurimage"] == "True" else False
        s["invertimage"] = True if s["invertimage"] == "True" else False
        s["equalizeimage"] = True if s["equalizeimage"] == "True" else False
        s["cannyimage"] = True if s["cannyimage"] == "True" else False
        s["ratiotest"] = ratiotest
        s["residualthreshold"] = residualthreshold
        s["crosscheck"] = crosscheck

        # set the preprocessing settings to the affine object
        self.affine.update_settings(s)

        if self.last_mask_path is not None:
            try:
                mask = self.affine.update_internal_mask(self.last_mask_path)
                self._update_MDI(mask, None)
                self.settingsWidget.label.setText(f"Mask loaded: {os.path.basename(self.last_mask_path)}")
                self._gui_change_mask_uploaded(mask_loaded=True)
            except AffineError:
                # I dont want to hear about this error, dont care.
                pass

        return settingsWidget, MDIWidget

    def _load_widgets(self):
        """Load the widgets from the UI files."""
        # Load the settings based on the name of this file.
        self.path = os.path.dirname(__file__) + os.path.sep
        for _, _, files in os.walk(self.path):
            for file in files:
                if file.endswith(".ui"):
                    try:
                        if file.split("_")[1].lower() == "settingswidget.ui":
                            settingsWidget = uic.loadUi(self.path + file)
                        elif file.split("_")[1].lower() == "mdiwidget.ui":
                            MDIWidget = uic.loadUi(self.path + file)
                    except IndexError:
                        continue

        self._find_labels(settingsWidget, MDIWidget)
        settingsWidget, MDIWidget = self._connect_buttons(settingsWidget, MDIWidget)
        return settingsWidget, MDIWidget

    def _find_labels(self, settingsWidget, MDIWidget):
        """Finds the labels in the settings widget."""

        # MDI labels
        self.camera_label = MDIWidget.findChild(QtWidgets.QGraphicsView, "Camera")
        self.gds_label = MDIWidget.findChild(QtWidgets.QGraphicsView, "Gds")
        self.gds_scene = QGraphicsScene(self.gds_label)
        self.camera_scene = QGraphicsScene(self.camera_label)
        self.gds_label.setScene(self.gds_scene)
        self.camera_label.setScene(self.camera_scene)

        # inputs
        self.dispKP = settingsWidget.findChild(QtWidgets.QCheckBox, "dispKP")
        self.pointCount = settingsWidget.findChild(QtWidgets.QComboBox, "pointCount")
        self.pointName = settingsWidget.findChild(QtWidgets.QLineEdit, "pointName")
        self.definedPoints = settingsWidget.findChild(QtWidgets.QListWidget, "definedPoints")
        self.cameraComboBox: QtWidgets.QComboBox = settingsWidget.cameraComboBox

    def _connect_buttons(self, settingsWidget, MDIWidget):
        """Connects the buttons, checkboxes and label clicks to their actions.

        Args:
            settingsWidget (_type_): _description_
            MDIWidget (_type_): _description_

        Returns:
            _type_: _description_
        """
        # Save inputs that are used in multiple functions
        self.centerCheckbox = settingsWidget.findChild(QtWidgets.QCheckBox, "centerClicks")

        # add a custom context menu in the list widget to allow point deletion
        self.definedPoints.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.definedPoints.customContextMenuRequested.connect(self._list_widget_context_menu)
        # connect item click to draw the points on the mask and image.
        self.definedPoints.itemClicked.connect(self._list_item_clicked_action)

        # connect the buttons to their actions
        settingsWidget.maskButton.clicked.connect(self._mask_button_action)
        settingsWidget.savePoints.clicked.connect(self.save_points_action)
        settingsWidget.importPoints.clicked.connect(self._import_points_action)
        settingsWidget.showButton.clicked.connect(self._open_dialog)
        # connect the label click on gds to a function
        self.gds_label.mousePressEvent = lambda event: self._gds_label_clicked(event)
        self.camera_label.mousePressEvent = lambda event: self._camera_label_clicked(event)

        return settingsWidget, MDIWidget

    # GUI Functionality

    def _gui_change_mask_uploaded(self, mask_loaded):
        self.settingsWidget.affineBox.setEnabled(mask_loaded)
        self.settingsWidget.groupBox.setEnabled(mask_loaded)

    def _list_widget_context_menu(self, pos):
        def remove_item(item):
            self.definedPoints.takeItem(self.definedPoints.row(item))

        item = self.definedPoints.itemAt(pos)
        if item is None:
            return

        menu = QMenu()
        delete_action = QAction("Delete", self.definedPoints)
        rename_action = QAction("Rename", self.definedPoints)
        rename_action.triggered.connect(lambda: item.setText("New name"))
        delete_action.triggered.connect(lambda: remove_item(item))
        menu.addAction(delete_action)
        menu.exec(self.definedPoints.mapToGlobal(pos))

    def save_points_action(self):
        """Action for the save button."""
        fileName, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.settingsWidget,
            "Save points",
            self.path + os.sep + "measurement_points",
            ".csv (*.csv);;All Files (*)",
        )
        if fileName:
            with open(fileName, "w", newline="") as csvfile:
                cswriter = csv.writer(csvfile, delimiter=",")
                fields = ["Name", "x_mask", "y_mask", "x_img", "y_img"]
                cswriter.writerow(fields)
                for i in range(self.definedPoints.count()):
                    item = self.definedPoints.item(i)
                    name = item.text()
                    points = item.data(self.COORD_DATA)
                    for x_mask, y_mask in points:
                        if self.affine.A is not None:
                            img_x, img_y = self.affine.coords((x_mask, y_mask))
                        else:
                            img_x, img_y = -1, -1
                        cswriter.writerow([name, x_mask, y_mask, img_x, img_y])

    def _import_points_action(self):
        """Action for the import points button."""
        fileName, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.settingsWidget,
            "Open points file",
            self.path + os.sep + "measurement_points",
            "comma-separated values (*.csv);;All Files (*)",
        )
        if fileName:
            point_dict = {}
            with open(fileName, "r") as csvfile:
                csreader = csv.reader(csvfile, delimiter=",")
                next(csreader)
                for row in csreader:
                    # extract the name and coordinates
                    name = row[0]
                    x_mask = float(row[1])
                    y_mask = float(row[2])
                    point_dict.setdefault(name, []).append((x_mask, y_mask))
            for name, points in point_dict.items():
                self.update_list_widget(points, name, clear_list=False)

    def _list_item_clicked_action(self, item):
        points = item.data(self.COORD_DATA)
        if not points:
            return
        self.draw_points_mdi(points, Qt.GlobalColor.red, clear_scene=True)

    def _manual_button_action(self):
        """Unused. Moved to dialog"""
        self.manual_mode = True
        camera_name = self.cameraComboBox.currentText()
        status, img = self.functions["camera"][camera_name]["camera_capture_image"]()
        if status != 0:
            self.log_message.emit(f"Affine: Error capturing image: {img}")
            return
        self._update_MDI(self.mdi_mask, img)

        self.info_message.emit(f"Manual mode enabled. Click on the GDS and then on the image to define points. {self.num_needed} points needed for transformation.")

    def _mask_button_action(self):
        """Interface for the gds mask loading button."""
        try:
            fileName, _ = QtWidgets.QFileDialog.getOpenFileName(
                self.settingsWidget,
                "Open .GDS, .png or .jpg file",
                self.path + os.sep + "masks",
                "Mask Files (*.gds);;Images (*.png *.jpg)",
            )
            if fileName:
                mask = self.affine.update_internal_mask(fileName)
                self.settingsWidget.label.setText(f"Mask loaded: {os.path.basename(fileName)}")
                self._update_MDI(mask, None)
                self._gui_change_mask_uploaded(mask_loaded=True)
                self.last_mask_path = self.affine.mask_path
        except AffineError as e:
            self.log_message.emit(e.message)

    def _open_dialog(self):
        def _on_close():
            self._update_MDI(self.dialog.mask, self.dialog.img, save_internal=True)
            res = self.affine.result.get("matches", None)
            if res is not None and len(res) > 0:
                self.log_message.emit(f"Affine: Transformation confirmed. {len(res)} matches found.")
            else:
                self.log_message.emit("Affine: No transformation confirmed")

            self.dialog = None

        img = self.functions["camera"][self.cameraComboBox.currentText()]["camera_capture_image"]()
        if img[0] != 0:
            self.log_message.emit(f"Affine: Error capturing image: {img[1]}")
            return
        # Get defined points as a flat list of (x_mask, y_mask)
        pointslist = []
        for i in range(self.definedPoints.count()):
            pts = self.definedPoints.item(i).data(self.COORD_DATA)
            if pts:
                pointslist.extend(pts)
        if not pointslist:
            pointslist = None
        status, settings = self.parse_settings_widget()
        if status == 0:
            # Pass the settings dict to the dialog
            self.dialog = dialog(self.affine, img[1], self.mdi_mask, settings, pointslist=pointslist)
            self.dialog.finished.connect(_on_close)
            self.dialog.show()
        else:
            self.log_message.emit(f"Affine: Error parsing settings widget: {settings['error message']} {settings['exception']}")

    def _gds_label_clicked(self, event):
        def measurement_point_mode(x, y):
            if self.settingsWidget.addPointsCheck.isChecked():
                try:
                    # "center on component" mode
                    if self.centerCheckbox.isChecked():
                        x, y = self.affine.center_on_component(x, y)

                    # draw the points
                    self.draw_points_mdi([(x, y)], Qt.GlobalColor.red, clear_scene=True)

                    # add the point to list, process point cluster if pointCount is reached
                    self.tp_arr += [(x, y)]
                    if len(self.tp_arr) == int(self.pointCount.currentText()):
                        # Create a widget item with the name and coordinates
                        self.update_list_widget(self.tp_arr, self.pointName.text(), clear_list=False)
                        self.tp_arr = []
                        name_idx = self.definedPoints.count()
                        self.pointName.setText("Measurement Point " + str(name_idx + 1))

                except AffineError as e:
                    if e.error_code != 4:
                        self.log_message.emit(e.message)

        def manual_mode(x, y):
            # Draw the point on the mask
            self.gds_scene.addEllipse(x - 3, y - 3, 6, 6, brush=QBrush(Qt.GlobalColor.blue))
            self.expecting_img_click = True
            self.mask_points.append((x, y))

        # Map from view coords -> scene coords
        pos = self.gds_label.mapToScene(event.pos())
        x, y = pos.x(), pos.y()
        # I thinks these are sometimes returned as floats from Qt
        x = int(x)
        y = int(y)

        # check if the mask is loaded
        if self.affine.internal_mask is None:
            return

        if not self.manual_mode:
            measurement_point_mode(x, y)
        elif not self.expecting_img_click:
            manual_mode(x, y)

    def _camera_label_clicked(self, event):
        """Handles camera label clicks."""
        if self.expecting_img_click:
            scene_pos = self.camera_label.mapToScene(event.pos())  # Convert view to scene coordinates
            x = int(scene_pos.x())
            y = int(scene_pos.y())

            self.camera_scene.addEllipse(x - 3, y - 3, 6, 6, brush=QBrush(Qt.GlobalColor.blue))
            self.img_points.append((x, y))
            self.expecting_img_click = False

            if len(self.img_points) == self.num_needed:
                try:
                    self.affine.manual_transform(self.mask_points, self.img_points, self.mdi_img, self.mdi_mask)
                    self._update_MDI(self.mdi_mask, self.mdi_img, save_internal=False)
                    self.info_message.emit("Manual transformation successful.")
                except AffineError as e:
                    self.info_message.emit(e.message)

                # reset the points
                self.mask_points = []
                self.img_points = []
                self.expecting_img_click = False
                self.manual_mode = False

    def _update_MDI(self, mask=None, img=None, save_internal=True):
        """
        Updates the MDI Widget with the given img and mask.
        Handles both grayscale and RGB images.

        Args:
            mask (np.ndarray, optional): The mask image.
            img (np.ndarray, optional): The camera image.
            save_internal (bool, optional): Whether to save the input internally.
        """

        def to_qpixmap(array):
            """
            Helper: Convert ndarray (grayscale or RGB) to QPixmap.

            Supports:
            - Grayscale (H, W)
            - RGB (H, W, 3)
            - RGBA (H, W, 4) → Converted to RGB
            """
            import cv2 as cv

            if array.ndim == 2:
                # Grayscale
                h, w = array.shape
                bytes_per_line = w
                qimage = QImage(array.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
            else:
                # Color image: RGB or RGBA
                if array.shape[2] == 4:
                    array = array[:, :, :3]  # Drop alpha
                elif array.shape[2] == 1:
                    array = cv.cvtColor(array, cv.COLOR_GRAY2RGB)

                h, w, ch = array.shape
                bytes_per_line = ch * w
                qimage = QImage(array.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

            return QPixmap.fromImage(qimage)

        if img is not None:
            pixmap = to_qpixmap(img)
            pixmap_item = QGraphicsPixmapItem(pixmap)

            self.camera_scene.clear()
            self.camera_scene.addItem(pixmap_item)

            if save_internal:
                self.mdi_img = img

        if mask is not None:
            pixmap = to_qpixmap(mask)
            pixmap_item = QGraphicsPixmapItem(pixmap)

            self.gds_scene.clear()
            self.gds_scene.addItem(pixmap_item)

            if save_internal:
                self.mdi_mask = mask

    def draw_points_mdi(self, points: list[tuple[float, float]], color, clear_scene: bool = True):
        """
        Draws points on the MDI scene.
        If clear_scene is True, clears the scene before drawing the points.
        """
        if clear_scene:
            self.gds_scene.clear()
            self.camera_scene.clear()
            self._update_MDI(self.mdi_mask, self.mdi_img, save_internal=False)

        for x, y in points:
            self.gds_scene.addEllipse(
                x - 3,
                y - 3,
                6,
                6,
                brush=QBrush(color),
                pen=QPen(Qt.GlobalColor.transparent),
            )

        if self.affine.A is not None:
            for x, y in points:
                # convert the clicked coords to the image coords
                x = int(x)
                y = int(y)

                # draw the point on the mask
                img_x, img_y = self.affine.coords((x, y))

                # Draw colored dot on the image
                self.camera_scene.addEllipse(
                    img_x - 3,
                    img_y - 3,
                    6,
                    6,
                    brush=QBrush(color),
                    pen=QPen(Qt.GlobalColor.transparent),
                )

    def update_list_widget(self, points: list[tuple[float, float]], name: str, clear_list: bool = False):
        """
        Updates the list widget with the given points and name.
        If clear_list is True, clears the list before adding the new points.
        """
        if clear_list:
            self.definedPoints.clear()

        item = QtWidgets.QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(self.COORD_DATA, points)
        self.definedPoints.addItem(item)

    # hook implementations

    def _getLogSignal(self):
        return self.log_message

    def _getInfoSignal(self):
        return self.info_message

    def _getCloseLockSignal(self):
        return self.closeLock

    def _fetch_dependency_functions(self, function_dict):
        self.missing_functions = []
        self.functions = {}

        for dep_category in self.dependency:
            if dep_category not in function_dict:
                self.missing_functions.append(dep_category)

            else:
                self.functions[dep_category] = function_dict[dep_category]

        # self.functions["camera"] is a list of nested dictionaries, iterate through every camera
        # FIXME: Currently the return is a dictrionary of dictionaries ONLY when multiple cameras are available.

        self.cameraComboBox.clear()
        cameras = self.functions.get("camera", {})
        if not cameras:
            return self.missing_functions
        else:
            for camera in self.functions["camera"]:
                # get the camera name (key of the dictionary)
                self.cameraComboBox.addItem(camera)

        return self.missing_functions

    def _get_public_methods(self, function: str) -> dict:
        """
        Returns a nested dictionary of public methods for the plugin
        """
        methods = {method: getattr(self, method) for method in dir(self) if callable(getattr(self, method)) and not method.startswith("__") and not method.startswith("_") and method.startswith(f"{function.lower()}_")}
        return methods

    # public API

    # FIXME: non standard return type for plugin
    def positioning_coords(self, coords: tuple[float, float]) -> tuple[float, float]:
        """Returns the transformed coordinates."""
        try:
            transformed = self.affine.coords(coords)
            return transformed
        except AffineError:
            return (-1, -1)

    def positioning_measurement_points(self):
        """Returns the measurement points defined in the list widget."""
        points = []
        names = []
        for i in range(self.definedPoints.count()):
            item = self.definedPoints.item(i)
            if item is not None:
                points.append(item.data(self.COORD_DATA))
                names.append(item.text())
        return points, names

    def parse_settings_widget(self):
        """Parse settings widget, return dict"""
        try:
            settings = {
                "pointcount": int(self.settingsWidget.pointCount.currentText()),
                "cameraComboBox": self.settingsWidget.cameraComboBox.currentText(),
                "addPointsCheck": self.settingsWidget.addPointsCheck.isChecked(),
                "default_mask_path": self.last_mask_path,
                "centerClicks": self.centerCheckbox.isChecked(),
            }
            # extend the settings with the preprprocessing settings
            s = self.affine.preprocessor.settings
            # convert prepro settings to correct types
            settings["ratiotest"] = float(self.affine.ratio_test)
            settings["residualthreshold"] = int(self.affine.residual_threshold)
            settings["crosscheck"] = True if self.affine.cross_check else False
            settings.update(s)

            assert settings["sigmaimage"] >= 0, "sigmaImage must be non-negative"
            assert settings["sigmamask"] >= 0, "sigmaMask must be non-negative"
        except AttributeError as e:
            return 2, {
                "Error message": "settings widget not initialized",
                "exception": str(e),
            }
        except (ValueError, AssertionError) as e:
            return 1, {"Error message": "Affine value error", "exception": str(e)}
        return 0, settings
