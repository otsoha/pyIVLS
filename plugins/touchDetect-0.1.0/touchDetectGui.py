import os
import copy
from touchDetect import touchDetect, ManipulatorInfo
from PyQt6 import uic
from PyQt6.QtWidgets import QWidget, QComboBox, QGroupBox, QSpinBox
from plugins.plugin_components import (
    public,
    ConnectionIndicatorStyle,
    get_public_methods,
    LoggingHelper,
    DependencyManager,
)
from components.worker_thread import WorkerThread
from components.threadStopped import ThreadStopped


class touchDetectGUI:
    green_style = ConnectionIndicatorStyle.GREEN_CONNECTED.value
    red_style = ConnectionIndicatorStyle.RED_DISCONNECTED.value

    def __init__(self):
        self.path = os.path.dirname(__file__) + os.path.sep

        # Initialize LoggingHelper, functionality, ui
        self.logger = LoggingHelper(self)
        self.functionality = touchDetect(log=self.logger.log_debug)
        self.settingsWidget = uic.loadUi(self.path + "touchDetect_Settings.ui")

        # initialize dependencyManager
        dependencies = {
            "micromanipulator": ["parse_settings_widget"],
            "smu": ["parse_settings_widget"],
            "contacting": ["parse_settings_widget"],
        }
        dependency_map = {
            "micromanipulator": "micromanipulatorBox",
            "smu": "smuBox",
            "contacting": "condetBox",
        }
        self.dm = DependencyManager("touchDetect", dependencies, self.settingsWidget, dependency_map)

        # Initialize the combo boxes for dependencies
        self.smu_box: QComboBox = self.settingsWidget.smuBox
        self.micromanipulator_box: QComboBox = self.settingsWidget.micromanipulatorBox
        self.condet_box: QComboBox = self.settingsWidget.condetBox

        # find status labels and indicators
        self.smu_indicator = self.settingsWidget.smuIndicator
        self.mm_indicator = self.settingsWidget.mmIndicator
        self.con_indicator = self.settingsWidget.conIndicator
        # find manipulator boxes
        man1: QGroupBox = self.settingsWidget.manipulator1
        man2: QGroupBox = self.settingsWidget.manipulator2
        man3: QGroupBox = self.settingsWidget.manipulator3
        man4: QGroupBox = self.settingsWidget.manipulator4

        # find comboboxes in manipulator boxes
        man1_smu_box: QComboBox = man1.findChild(QComboBox, "mansmu_1")
        man1_con_box: QComboBox = man1.findChild(QComboBox, "mancon_1")
        man2_smu_box: QComboBox = man2.findChild(QComboBox, "mansmu_2")
        man2_con_box: QComboBox = man2.findChild(QComboBox, "mancon_2")
        man3_smu_box: QComboBox = man3.findChild(QComboBox, "mansmu_3")
        man3_con_box: QComboBox = man3.findChild(QComboBox, "mancon_3")
        man4_smu_box: QComboBox = man4.findChild(QComboBox, "mansmu_4")
        man4_con_box: QComboBox = man4.findChild(QComboBox, "mancon_4")

        # find spinboxes
        man1_res: QSpinBox = man1.findChild(QSpinBox, "manres_1")
        man2_res: QSpinBox = man2.findChild(QSpinBox, "manres_2")
        man3_res: QSpinBox = man3.findChild(QSpinBox, "manres_3")
        man4_res: QSpinBox = man4.findChild(QSpinBox, "manres_4")

        self.manipulator_boxes = [
            [man1, man1_smu_box, man1_con_box, man1_res],
            [man2, man2_smu_box, man2_con_box, man2_res],
            [man3, man3_smu_box, man3_con_box, man3_res],
            [man4, man4_smu_box, man4_con_box, man4_res],
        ]
        for box, smu_box, con_box, res_spin in self.manipulator_boxes:
            assert box is not None, f"Manipulator box {box} is None"
            assert smu_box is not None, f"SMU box {box.title()} is None"
            assert con_box is not None, f"Con box {box.title()} is None"
            assert res_spin is not None, f"Res spin {box.title()} is None"

        # Internal settings storage
        self.settings = {}

        # Thread management for monitoring
        self.monitoring_thread = None
        self.is_monitoring = False

        # line edits
        self.stride = self.settingsWidget.stride
        self.sample_width = self.settingsWidget.sample_width
        self.spectro_height = self.settingsWidget.spectro_height

        # buttons connected in init to prevent multiple connections:
        self.settingsWidget.initButton.clicked.connect(self.update_status)
        self.settingsWidget.pushButton.clicked.connect(self._test)
        self.settingsWidget.pushButton_2.clicked.connect(self._monitor_threaded)

    def _fetch_dep_plugins(self):
        self.logger.log_debug("Fetching dependency plugins")

        result = self.dm.validate_and_extract_dependency_settings(self.settings)
        status, state = result
        if status != 0:
            self.logger.log_warn(f"Dependency settings invalid: {state}")
            return None, None, None
        func_dict = self.dm.get_function_dict_for_dependencies()
        mm_functions = func_dict["micromanipulator"]
        contacting_functions = func_dict["contacting"]
        smu_functions = func_dict["smu"]

        # filter to just include the selected plugins of each type
        mm_functions = mm_functions[self.settings["micromanipulator"]]
        smu_functions = smu_functions[self.settings["smu"]]
        contacting_functions = contacting_functions[self.settings["contacting"]]

        return mm_functions, smu_functions, contacting_functions

    def update_status(self):
        """
        Updates the status of the mm, smu and contacting plugins.
        This function is called when the status changes.
        """
        self.logger.log_debug("Updating plugin status")
        mm, smu, con = self._fetch_dep_plugins()

        # Update SMU status
        # self.channel_names = smu.smu_channelNames() OLD
        self.channel_names = smu["smu_channelNames"]()  # new
        if self.channel_names is not None:
            self.smu_indicator.setStyleSheet(self.green_style)
            self.logger.log_debug(f"SMU channels available: {self.channel_names}")
        else:
            self.smu_indicator.setStyleSheet(self.red_style)
            self.logger.log_debug("SMU channels not available")

        # Update micromanipulator status
        status, state = mm["mm_devices"]()
        if status == 0:
            self.mm_indicator.setStyleSheet(self.green_style)
            self.logger.log_debug(f"Micromanipulator devices detected: {state}")
            num_dev, active_list = state
            for i, is_active in enumerate(active_list):
                if is_active:
                    self.logger.log_debug(f"Enabling manipulator {i + 1} controls")
                    box, smu_box, con_box, res_spin = self.manipulator_boxes[i]
                    box.setVisible(True)
                    self._setup_manipulator_controls(smu_box, con_box, res_spin, i)
        else:
            self.mm_indicator.setStyleSheet(self.red_style)
            self.logger.log_warn(f"Micromanipulator error: {state}")

        # Update contact detection status
        con_status, con_state = con["deviceConnect"]()
        if con_status == 0:
            self.con_indicator.setStyleSheet(self.green_style)
            self.logger.log_debug("Contact detection device connected successfully")
            con["deviceDisconnect"]()
        else:
            self.con_indicator.setStyleSheet(self.red_style)
            self.logger.log_warn(f"Contact detection error: {con_state}")

    def _setup_manipulator_controls(self, smu_box, con_box, res_spin, manipulator_index):
        """Setup controls for a specific manipulator"""
        smu_box.clear()
        con_box.clear()
        smu_box.addItems(self.channel_names)
        con_box.addItems(["Hi", "Lo", "none", "spectrometer"])
        smu_box.addItems(["none", "spectrometer"])

        # Apply settings from internal state
        manipulator_key = str(manipulator_index + 1)
        smu_key = f"{manipulator_key}_smu"
        con_key = f"{manipulator_key}_con"
        res_key = f"{manipulator_key}_res"

        if smu_key in self.settings:
            smu_box.setCurrentText(self.settings[smu_key])
        if con_key in self.settings:
            con_box.setCurrentText(self.settings[con_key])
        if res_key in self.settings:
            res_spin.setValue(int(self.settings[res_key]))

    def _get_public_methods(self) -> dict:
        """Returns a nested dictionary of public methods for the plugin"""
        return get_public_methods(self)

    def setup(self, settings) -> QWidget:
        """Sets up the GUI for the plugin. This function is called by hook to initialize the GUI."""
        self.logger.log_debug("Setting up touchDetect GUI")
        self.dm.setup(settings)

        # Hide all manipulator boxes initially
        for box, _, _, _ in self.manipulator_boxes:
            box.setVisible(False)

        # Store settings internally (maintain .ini format)
        self.settings = copy.deepcopy(settings)

        # Apply global settings to GUI controls
        self.stride.setValue(int(self.settings["stride"]))
        self.sample_width.setValue(int(self.settings["sample_width"]))
        self.spectro_height.setValue(int(self.settings["spectrometer_height"]))

        # Set initial button text
        self.settingsWidget.pushButton_2.setText("Start Monitoring")

        self.update_status()

        self.logger.log_debug("TouchDetect GUI setup completed")
        return self.settingsWidget

    def _create_manipulator_infos_from_settings(self, settings: dict) -> list[ManipulatorInfo]:
        """Convert settings dictionary to ManipulatorInfo objects for low-level functionality"""
        self.logger.log_debug("Converting settings to ManipulatorInfo objects")

        manipulator_infos = []
        for i in range(4):
            manipulator_number = i + 1
            smu_key = f"{manipulator_number}_smu"
            con_key = f"{manipulator_number}_con"
            res_key = f"{manipulator_number}_res"

            # Skip if manipulator is not configured
            smu_channel = settings[smu_key]
            con_channel = settings[con_key]

            if smu_channel in ["", "none"] and con_channel in ["", "none"]:
                self.logger.log_debug(f"Skipping unconfigured manipulator {manipulator_number}")
                continue

            self.logger.log_debug(f"Creating ManipulatorInfo for manipulator {manipulator_number}")

            # Create ManipulatorInfo object - validation happens in the ManipulatorInfo class
            manipulator_info = ManipulatorInfo(
                mm_number=manipulator_number,
                smu_channel=smu_channel,
                condet_channel=con_channel,
                threshold=settings[res_key],
                stride=settings["stride"],
                sample_width=settings["sample_width"],
                function="",  # Will be automatically determined in __post_init__
                spectrometer_height=settings["spectrometer_height"],
            )
            manipulator_infos.append(manipulator_info)

        self.logger.log_debug(f"Created {len(manipulator_infos)} ManipulatorInfo objects")
        return manipulator_infos

    def _monitor_worker(self, worker_thread):
        """Worker function that runs the monitoring in a separate thread."""
        try:
            self.logger.log_debug("Starting monitoring worker thread")
            mm, smu, con = self._fetch_dep_plugins()

            # Get configured manipulators and convert to ManipulatorInfo objects
            status, settings = self.parse_settings_widget()
            if status != 0:
                self.logger.log_debug("Settings parsing failed in monitor worker")
                worker_thread.error.emit(f"Settings parsing failed: {settings}")
                return (status, settings)

            manipulator_infos = self._create_manipulator_infos_from_settings(settings)

            # Define callbacks for the monitoring
            def progress_callback(message):
                worker_thread.progress.emit(message)

            def error_callback(message):
                worker_thread.error.emit(message)

            def stop_requested_callback():
                return worker_thread.is_stop_requested()

            # Use the touchDetect monitor_manual_contact_detection method
            status, result = self.functionality.monitor_manual_contact_detection(
                mm=mm,
                smu=smu,
                con=con,
                manipulator_infos=manipulator_infos,
                progress_callback=progress_callback,
                error_callback=error_callback,
                stop_requested_callback=stop_requested_callback,
            )

            return (status, result)

        except Exception as e:
            error_msg = f"Exception during monitoring: {str(e)}"
            self.logger.log_warn(error_msg)
            worker_thread.error.emit(error_msg)
            return (2, {"Error message": error_msg, "Exception": str(e)})

    def _monitor_threaded(self):
        """Starts or stops the monitoring process in a separate thread."""
        if not self.is_monitoring:
            self.logger.log_info("Starting threaded resistance monitoring for all manipulators")
            self.is_monitoring = True
            self.settingsWidget.pushButton_2.setText("Stop Monitoring")

            # Create and start the worker thread
            self.monitoring_thread = WorkerThread(self._monitor_worker)
            self.monitoring_thread.progress.connect(self._on_monitoring_progress)
            self.monitoring_thread.error.connect(self._on_monitoring_error)
            self.monitoring_thread.finished.connect(self._on_monitoring_finished)
            self.monitoring_thread.result_signal.connect(self._on_monitoring_result)
            self.monitoring_thread.start()
        else:
            self.logger.log_info("Stopping monitoring thread")
            if self.monitoring_thread:
                self.monitoring_thread.stop()

    def _on_monitoring_progress(self, message):
        """Handle progress updates from the monitoring thread."""
        self.logger.log_info(message)

    def _on_monitoring_error(self, error_message):
        """Handle error messages from the monitoring thread."""
        self.logger.log_warn(error_message)

    def _on_monitoring_result(self, result):
        """Handle the final result from the monitoring thread."""
        status, state = result
        if status != 0:
            self.logger.log_warn(f"Monitoring failed: {state.get('Error message', 'Unknown error')}")

    def _on_monitoring_finished(self):
        """Handle monitoring thread completion."""
        self.is_monitoring = False
        self.monitoring_thread = None
        self.settingsWidget.pushButton_2.setText("Start Monitoring")
        self.logger.log_info("Monitoring thread finished")

    def _test(self):
        self.logger.log_info("Testing move to contact functionality")
        status, state = self.move_to_contact()
        if status == 0:
            self.logger.log_info("Move to contact test completed successfully")
        else:
            self.logger.log_warn(f"Move to contact test failed: {state.get('Error message', 'Unknown error')}")

    @public
    def parse_settings_widget(self) -> tuple[int, dict]:
        """Parses the settings widget and returns error code and settings as a dictionary matching .ini keys."""
        self.logger.log_debug("Parsing settings widget")
        settings = {}

        # Collect manipulator settings
        for i, (box, smu_box, con_box, res_box) in enumerate(self.manipulator_boxes):
            smu_channel = smu_box.currentText()
            con_channel = con_box.currentText()
            res_value = res_box.value()

            # Store all settings in .ini format
            settings[f"{i + 1}_smu"] = smu_channel
            settings[f"{i + 1}_con"] = con_channel
            settings[f"{i + 1}_res"] = res_value

        # Validate contact detection channels are unique (excluding empty or none)
        con_channels = [settings[f"{i + 1}_con"] for i in range(4) if settings[f"{i + 1}_con"] not in ["", "none"]]
        if len(con_channels) != len(set(con_channels)):
            self.logger.log_debug("Contact detection channel validation failed - duplicate channels")
            return (
                1,
                {"Error message": "Contact detection channels must be unique across manipulators."},
            )

        # Get global settings from GUI controls
        settings["stride"] = self.stride.value()
        settings["sample_width"] = self.sample_width.value()
        settings["spectrometer_height"] = self.spectro_height.value()

        # add dependency settings
        result = self.dm.validate_and_extract_dependency_settings(self.settings)
        status, state = result
        if status != 0:
            return status, state
        self.settings.update(state)
        self.settings.update(settings)

        self.logger.log_debug(f"Parsed settings: {self.settings}")
        return (0, self.settings)

    @public
    def setSettings(self, settings: dict):
        """Sets the plugin settings from the sequence builder in .ini format."""
        self.logger.log_debug(f"Setting settings for touchDetect plugin: {settings}")
        self.settings = copy.deepcopy(settings)

    @public
    def set_gui_from_settings(self) -> tuple[int, dict]:
        """Updates the GUI controls based on the internal settings."""
        try:
            self.logger.log_debug("Updating GUI from internal settings")

            # Update global settings
            self.stride.setValue(int(self.settings["stride"]))
            self.sample_width.setValue(int(self.settings["sample_width"]))
            self.spectro_height.setValue(int(self.settings["spectrometer_height"]))

            # Update manipulator settings in GUI
            for i, (box, smu_box, con_box, res_spin) in enumerate(self.manipulator_boxes):
                manipulator_key = str(i + 1)
                smu_key = f"{manipulator_key}_smu"
                con_key = f"{manipulator_key}_con"
                res_key = f"{manipulator_key}_res"

                if smu_key in self.settings:
                    smu_channel = self.settings[smu_key]
                    if smu_channel:
                        index = smu_box.findText(smu_channel)
                        if index >= 0:
                            smu_box.setCurrentIndex(index)
                        else:
                            smu_box.addItem(smu_channel)
                            smu_box.setCurrentText(smu_channel)

                if con_key in self.settings:
                    con_channel = self.settings[con_key]
                    if con_channel:
                        index = con_box.findText(con_channel)
                        if index >= 0:
                            con_box.setCurrentIndex(index)
                        else:
                            con_box.addItem(con_channel)
                            con_box.setCurrentText(con_channel)

                if res_key in self.settings:
                    try:
                        res_spin.setValue(int(self.settings[res_key]))
                    except (ValueError, TypeError):
                        self.logger.log_warn(
                            f"Invalid resistance threshold for manipulator {i + 1}: {self.settings[res_key]}"
                        )

            self.logger.log_debug("GUI updated from internal settings successfully")
            return (0, {"Error message": "GUI updated from settings"})

        except Exception as e:
            error_msg = f"Error updating GUI from settings: {str(e)}"
            self.logger.log_warn(error_msg)
            return (1, {"Error message": error_msg, "Exception": str(e)})

    def move_to_contact(self):
        """Moves all configured manipulators to contact with the sample."""
        self.logger.log_info("Starting move to contact operation")

        try:
            mm, smu, con = self._fetch_dep_plugins()

            # Parse current settings
            status, settings = self.parse_settings_widget()
            if status != 0:
                self.logger.log_debug("Settings parsing failed in move_to_contact")
                return (status, settings)

            # Convert to ManipulatorInfo objects
            manipulator_infos = self._create_manipulator_infos_from_settings(settings)

            if not manipulator_infos:
                self.logger.log_debug("No configured manipulators found")
                return (1, {"Error message": "No configured manipulators found"})

            # Execute move to contact
            status, state = self.functionality.move_to_contact(mm, con, smu, manipulator_infos)

            if status != 0:
                self.logger.log_warn(f"Move to contact failed: {state.get('Error message', 'Unknown error')}")
                return (status, state)

            self.logger.log_info("Move to contact operation completed successfully")
            return (status, state)

        except Exception as e:
            error_msg = f"Exception in move_to_contact: {str(e)}"
            self.logger.log_warn(error_msg)
            return (2, {"Error message": error_msg, "Exception": str(e)})

    @public
    def sequenceStep(self, postfix: str) -> tuple[int, dict]:
        """Performs the sequence step by moving all configured manipulators to contact."""
        self.logger.log_info(f"Starting touchDetect sequence step with postfix: {postfix}")
        try:
            # Execute move to contact for all configured manipulators
            status, state = self.move_to_contact()

            if status != 0:
                self.logger.log_warn(f"TouchDetect sequence step failed: {state}")
                return (status, state)

            self.logger.log_info("TouchDetect sequence step completed successfully")
            return (
                0,
                {"Error message": "TouchDetect sequence step completed successfully"},
            )
        except ThreadStopped as _:
            return (3, {"Error message": "Thread stopped by user"})

    @public
    def verify_contact(self) -> tuple[int, dict]:
        """Verifies contact for all configured manipulators."""
        self.logger.log_info("Starting touchDetect verify_contact operation")

        # create infos
        infos = self._create_manipulator_infos_from_settings(self.settings)

        # fetch deps
        mm, smu, con = self._fetch_dep_plugins()

        # Execute verify contact for all configured manipulators
        status, state = self.functionality.verify_contact(mm, smu, con, infos)

        if status != 0:
            self.logger.log_warn(f"TouchDetect verify_contact operation failed: {state}")
            return (status, state)

        self.logger.log_info("TouchDetect verify_contact operation completed successfully")
        return (
            0,
            {"Error message": "TouchDetect verify_contact operation completed successfully"},
        )
