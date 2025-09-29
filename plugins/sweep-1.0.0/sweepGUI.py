import os
import time
import copy
import numpy as np
import pandas as pd
from pathvalidate import is_valid_filename
from datetime import datetime

from MplCanvas import MplCanvas  # this should be moved to some pluginsShare
from PyQt6 import uic
from PyQt6.QtCore import QObject, Qt, pyqtSlot
from PyQt6.QtWidgets import QComboBox, QFileDialog, QLabel, QVBoxLayout, QWidget
from plugins.plugin_components import LoggingHelper, CloseLockSignalProvider, public, get_public_methods
from sweepCommon import create_file_header, create_sweep_reciepe
from threadStopped import (  # this should be moved to some pluginsShare
    ThreadStopped,
    thread_with_exception,
)


class sweepException(Exception):
    pass


class sweepGUI(QObject):
    """Basic sweep module"""

    non_public_methods = []  # add function names here, if they should not be exported as public to another plugins
    public_methods = [
        "parse_settings_widget",
        "set_running",
        "setSettings",
        "sequenceStep",
        "set_gui_from_settings",
    ]  # necessary for descendents of QObject, otherwise _get_public_methods returns a lot of QObject methods
    ####################################  threads

    ################################### internal functions

    ########Slots

    ########Signals

    def __init__(self):
        super(sweepGUI, self).__init__()
        self.verbose = True  # Enable verbose logging
        self.logger = LoggingHelper(self)
        self.closelock = CloseLockSignalProvider()
        # List of functions from another plugins required for functioning
        self.dependency = {
            "smu": [
                "parse_settings_widget",
                "smu_connect",
                "smu_init",
                "smu_runSweep",
                "smu_abort",
                "smu_outputOFF",
                "smu_disconnect",
                "smu_getLastBufferValue",
                "smu_bufferRead",
                "set_running",
                "smu_channelNames",
            ],
        }

        # Load the settings based on the name of this file.
        self.path = os.path.dirname(__file__) + os.path.sep
        self.settingsWidget = uic.loadUi(self.path + "sweep_settingsWidget.ui")
        self.MDIWidget = uic.loadUi(self.path + "sweep_MDIWidget.ui")
        self._connect_signals()
        self.settings = {}
        self._create_plt()
        self.logger.log_info("sweepGUI initialized.")

    ########Functions

    def _create_plt(self):
        self.sc = MplCanvas(self, width=5, height=4, dpi=100)
        self.axes = self.sc.fig.add_subplot(111)

        self.axes.set_xlabel("Voltage (V)")
        self.axes.set_ylabel("Current (A)")

        layout = QVBoxLayout()
        layout.addWidget(self.sc._create_toolbar(self.MDIWidget))
        layout.addWidget(self.sc)
        self.MDIWidget.setLayout(layout)

    def _connect_signals(self):
        # Connect the channel combobox

        # Connect the inject type combobox
        inject_box = self.settingsWidget.findChild(QComboBox, "comboBox_inject")
        delay_continuous = self.settingsWidget.findChild(QComboBox, "comboBox_continuousDelayMode")
        delay_pulsed = self.settingsWidget.findChild(QComboBox, "comboBox_pulsedDelayMode")
        delay_drain = self.settingsWidget.findChild(QComboBox, "comboBox_drainDelayMode")

        # the overhead created by just calling _update_GUI_state instead of the smaller updates is negligible,
        # but it helps to keep the code simpler IMO
        inject_box.currentIndexChanged.connect(self._update_GUI_state)
        self.settingsWidget.comboBox_mode.currentIndexChanged.connect(self._update_GUI_state)
        delay_continuous.currentIndexChanged.connect(self._update_GUI_state)
        delay_pulsed.currentIndexChanged.connect(self._update_GUI_state)
        delay_drain.currentIndexChanged.connect(self._update_GUI_state)
        self.settingsWidget.smuBox.activated.connect(self._update_GUI_state)
        self.settingsWidget.checkBox_singleChannel.stateChanged.connect(self._update_GUI_state)

        self.settingsWidget.directoryButton.clicked.connect(self._getAddress)
        self.settingsWidget.stopButton.clicked.connect(self._stopAction)
        self.settingsWidget.runButton.clicked.connect(self._runAction)

    ########Functions
    ###############GUI setting up

    def _initGUI(
        self,
        plugin_info: dict,
    ) -> int:
        """populates GUI with values stored in settings

        Args:
            plugin_info (dict): dictionary with settings obtained from plugin_data in pyIVLS_*_plugin

        Returns:
            int: status code
        """
        ##populates GUI with values stored in settings

        self.logger.log_debug("Initializing GUI with plugin_info: " + str(plugin_info))

        default_smu = plugin_info["smu"]
        # get channel names
        try:
            self.settingsWidget.comboBox_channel.addItems(self.function_dict["smu"][default_smu]["smu_channelNames"]())
        except KeyError:
            self.logger.log_warn(f"SMU {default_smu} not found in function_dict")
        self.settingsWidget.smuBox.clear()  # clear previous items
        self.settingsWidget.smuBox.addItems(list(self.function_dict["smu"].keys()))
        # set default SMU
        if default_smu in self.function_dict["smu"]:
            self.settingsWidget.smuBox.setCurrentText(default_smu)
        self.parse_settings_widget()
        self.settings.update(plugin_info)
        self.logger.log_debug(f"Settings after update: {self.settings}")
        self.set_gui_from_settings()
        return 0

    def _getAddress(self):
        self.logger.log_debug("Opening directory selection dialog.")
        address = self.settingsWidget.lineEdit_path.text()
        if not (os.path.exists(address)):
            address = self.path
        address = QFileDialog.getExistingDirectory(
            None,
            "Select directory for saving",
            address,
            options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if address:
            self.settingsWidget.lineEdit_path.setText(address)

    ########Functions
    ###############GUI react to change
    def _update_GUI_state(self):
        self.logger.log_debug("Updating GUI state.")
        self._mode_changed(self.settingsWidget.comboBox_mode.currentIndex())
        self._inject_changed(self.settingsWidget.comboBox_inject.currentIndex())
        self._delay_continuous_mode_changed(self.settingsWidget.comboBox_continuousDelayMode.currentIndex())
        self._delay_pulsed_mode_changed(self.settingsWidget.comboBox_pulsedDelayMode.currentIndex())
        self._delay_drain_mode_changed(self.settingsWidget.comboBox_drainDelayMode.currentIndex())
        self._smu_plugin_changed()

    def _mode_changed(self, index):
        """Handles the visibility of the mode input fields based on the selected mode."""
        group_continuous = self.settingsWidget.findChild(QWidget, "groupBox_continuousSweep")
        group_pulsed = self.settingsWidget.findChild(QWidget, "groupBox_pulsedSweep")

        mode = self.settingsWidget.comboBox_mode.currentText()
        if mode == "Continuous":
            group_continuous.setEnabled(True)
            group_pulsed.setEnabled(False)
        elif mode == "Pulsed":
            group_continuous.setEnabled(False)
            group_pulsed.setEnabled(True)
        elif mode == "Mixed":
            group_continuous.setEnabled(True)
            group_pulsed.setEnabled(True)

        self.settingsWidget.update()

    def _inject_changed(self, index):
        """Changes the unit labels based on the selected injection type."""
        continuous_start_label = self.settingsWidget.findChild(QLabel, "label_continuousStartUnits")
        pulse_start_label = self.settingsWidget.findChild(QLabel, "label_pulsedStartUnits")
        drain_start_label = self.settingsWidget.findChild(QLabel, "label_drainStartUnits")
        continuous_end_label = self.settingsWidget.findChild(QLabel, "label_continuousEndUnits")

        pulse_end_label = self.settingsWidget.findChild(QLabel, "label_pulsedEndUnits")

        drain_end_label = self.settingsWidget.findChild(QLabel, "label_drainEndUnits")

        continuous_limit_label = self.settingsWidget.findChild(QLabel, "label_continuousLimitUnits")
        pulse_limit_label = self.settingsWidget.findChild(QLabel, "label_pulsedLimitUnits")
        drain_limit_label = self.settingsWidget.findChild(QLabel, "label_drainLimitUnits")

        inject_type = self.settingsWidget.comboBox_inject.currentText()
        if inject_type == "Voltage":
            continuous_start_label.setText("V")
            pulse_start_label.setText("V")
            drain_start_label.setText("V")
            continuous_end_label.setText("V")
            pulse_end_label.setText("V")
            drain_end_label.setText("V")
            continuous_limit_label.setText("A")
            pulse_limit_label.setText("A")
            drain_limit_label.setText("A")
        else:
            continuous_start_label.setText("A")
            pulse_start_label.setText("A")
            drain_start_label.setText("A")
            continuous_end_label.setText("A")
            pulse_end_label.setText("A")
            drain_end_label.setText("A")
            continuous_limit_label.setText("V")
            pulse_limit_label.setText("V")
            drain_limit_label.setText("V")

    def _delay_continuous_mode_changed(self, index):
        """Handles the visibility of the delay input fields based on the selected mode."""
        if self.settingsWidget.comboBox_continuousDelayMode.currentText() == "Auto":
            self.settingsWidget.label_continuousDelay.setEnabled(False)
            self.settingsWidget.lineEdit_continuousDelay.setEnabled(False)
            self.settingsWidget.label_continuousDelayUnits.setEnabled(False)
        else:
            self.settingsWidget.label_continuousDelay.setEnabled(True)
            self.settingsWidget.lineEdit_continuousDelay.setEnabled(True)
            self.settingsWidget.label_continuousDelayUnits.setEnabled(True)

        self.settingsWidget.update()

    def _delay_pulsed_mode_changed(self, index):
        """Handles the visibility of the delay input fields based on the selected mode."""
        if self.settingsWidget.comboBox_pulsedDelayMode.currentText() == "Auto":
            self.settingsWidget.label_pulsedDelay.setEnabled(False)
            self.settingsWidget.lineEdit_pulsedDelay.setEnabled(False)
            self.settingsWidget.label_pulsedDelayUnits.setEnabled(False)
        else:
            self.settingsWidget.label_pulsedDelay.setEnabled(True)
            self.settingsWidget.lineEdit_pulsedDelay.setEnabled(True)
            self.settingsWidget.label_pulsedDelayUnits.setEnabled(True)

        self.settingsWidget.update()

    def _delay_drain_mode_changed(self, index):
        """Handles the visibility of the delay input fields based on the selected mode."""
        if self.settingsWidget.comboBox_drainDelayMode.currentText() == "Auto":
            self.settingsWidget.label_drainDelay.setEnabled(False)
            self.settingsWidget.lineEdit_drainDelay.setEnabled(False)
            self.settingsWidget.label_drainDelayUnits.setEnabled(False)
        else:
            self.settingsWidget.label_drainDelay.setEnabled(True)
            self.settingsWidget.lineEdit_drainDelay.setEnabled(True)
            self.settingsWidget.label_drainDelayUnits.setEnabled(True)

        self.settingsWidget.update()

    def _single_channel_changed(self):
        """Handles the visibility of the drain input fields based use single chennel box"""
        if self.settingsWidget.checkBox_singleChannel.isChecked():
            self.settingsWidget.groupBox_drainSweep.setEnabled(False)
        else:
            self.settingsWidget.groupBox_drainSweep.setEnabled(True)

        self.settingsWidget.update()

    def _smu_plugin_changed(self):
        self.logger.log_debug("SMU plugin changed to: " + self.settingsWidget.smuBox.currentText())
        """Handles the visibility of the SMU settings based on the selected SMU plugin."""
        smu_selection = self.settingsWidget.smuBox.currentText()
        if smu_selection in self.function_dict["smu"]:
            # update smu:
            self.function_dict["smu"][smu_selection]["parse_settings_widget"]()
            available_channels = self.function_dict["smu"][smu_selection]["smu_channelNames"]()
            # get channel names from the selected SMU plugin
            self.settingsWidget.comboBox_channel.clear()
            self.settingsWidget.comboBox_channel.addItems(available_channels)

            # set the current channel to the saved channel if the selected smu is the saved smu:
            if self.settings.get("smu") == smu_selection:
                current_channel = self.settings.get("channel", available_channels[0])
                if current_channel in available_channels:
                    self.settingsWidget.comboBox_channel.setCurrentText(current_channel)
                else:
                    self.settingsWidget.comboBox_channel.setCurrentIndex(0)
        self.settingsWidget.update()

    ########Functions
    ########plugins interraction

    def _getPublicFunctions(self, function_dict):
        self.missing_functions = []
        for dependency_plugin in list(self.dependency.keys()):
            if dependency_plugin not in function_dict:
                self.missing_functions.append(dependency_plugin)
                continue
            for dependency_function in self.dependency[dependency_plugin]:
                if dependency_function not in function_dict[dependency_plugin]:
                    self.missing_functions.append(f"{dependency_plugin}:{dependency_function}")
        if not self.missing_functions:
            self.function_dict = function_dict
        else:
            self.function_dict = {}

        return self.missing_functions

    def _get_public_methods(self):
        return get_public_methods(self)

    def _getLogSignal(self):
        return self.logger.logger_signal

    def _getInfoSignal(self):
        return self.logger.info_popup_signal

    def _getCloseLockSignal(self):
        return self.closelock.closeLock

    ########Functions to be used externally
    ###############get settings from GUI
    @public
    def parse_settings_widget(self):
        """Parses the settings widget for the plugin. Extracts current values. Checks if values are allowed. Provides settings of sweep plugin to an external plugin

        Returns [status, settings_dict]:
            status: 0 - no error, ~0 - error
            self.settings
        """
        smu_selection = self.settingsWidget.smuBox.currentText()
        if not self.function_dict:
            return [
                3,
                {
                    "Error message": "Missing functions in sweep plugin. Check log",
                    "Missing functions": self.missing_functions,
                },
            ]
        if smu_selection not in self.function_dict["smu"]:
            return [3, {"Error message": "SMU plugin not found in function_dict"}]

        self.settings = {}
        self.settings["smu"] = smu_selection
        [status, self.smu_settings] = self.function_dict["smu"][self.settings["smu"]]["parse_settings_widget"]()
        if status:
            return [2, self.smu_settings]

        self.settings["smu_settings"] = self.smu_settings

        # Determine source channel: may take values depending on the channel names in smu, e.g. for Keithley 2612B [smua, smub]
        self.settings["channel"] = (self.settingsWidget.comboBox_channel.currentText()).lower()
        currentIndex = self.settingsWidget.comboBox_channel.currentIndex()
        if self.settingsWidget.comboBox_channel.count() > 1:
            if currentIndex == 0:
                self.settings["drainchannel"] = self.settingsWidget.comboBox_channel.itemText(1)
            else:
                self.settings["drainchannel"] = self.settingsWidget.comboBox_channel.itemText(0)
        else:
            self.settings["drainchannel"] = "xxx"  # for compatability if the smu does not support second channel
        # Determine source type: may take values [current, voltage]
        self.settings["inject"] = (self.settingsWidget.comboBox_inject.currentText()).lower()
        # Determine pulse/continuous mode: may take values [continuous, pulsed, mixed]
        self.settings["mode"] = (self.settingsWidget.comboBox_mode.currentText()).lower()
        # Determine delay mode for continuous sweep: may take values [auto, manual]
        self.settings["continuousdelaymode"] = (self.settingsWidget.comboBox_continuousDelayMode.currentText()).lower()
        # Determine delay mode for pulsed sweep: may take values [auto, manual]
        self.settings["pulseddelaymode"] = (self.settingsWidget.comboBox_pulsedDelayMode.currentText()).lower()
        # Determine delay mode for drain: may take values [auto, manual]
        self.settings["draindelaymode"] = (self.settingsWidget.comboBox_drainDelayMode.currentText()).lower()
        # Determine source sence mode: may take values [2 wire, 4 wire, 2 & 4 wire]
        self.settings["sourcesensemode"] = (self.settingsWidget.comboBox_sourceSenseMode.currentText()).lower()
        # Determine drain sence mode: may take values [2 wire, 4 wire, 2 & 4 wire]
        self.settings["drainsensemode"] = (self.settingsWidget.comboBox_drainSenseMode.currentText()).lower()

        # Determine a single channel mode: may be True or False
        if self.settingsWidget.checkBox_singleChannel.isChecked():
            self.settings["singlechannel"] = True
        else:
            self.settings["singlechannel"] = False

        # Determine repeat count: should be int >0
        try:
            self.settings["repeat"] = int(self.settingsWidget.lineEdit_repeat.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: repeat field should be integer"}]
        if self.settings["repeat"] < 1:
            return [1, {"Error message": "Value error in sweep plugin: repeat field can not be less than 1"}]

        # Determine settings for continuous mode
        # start should be float
        try:
            self.settings["continuousstart"] = float(self.settingsWidget.lineEdit_continuousStart.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: continuous start field should be numeric"}]

        # end should be float
        try:
            self.settings["continuousend"] = float(self.settingsWidget.lineEdit_continuousEnd.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: continuous end field should be numeric"}]

        # number of points should be int >0
        try:
            self.settings["continuouspoints"] = int(self.settingsWidget.lineEdit_continuousPoints.text())
        except ValueError:
            return [
                1,
                {"Error message": "Value error in sweep plugin: continuous number of points field should be integer"},
            ]
        if self.settings["continuouspoints"] < 1:
            return [
                1,
                {
                    "Error message": "Value error in sweep plugin: continuous number of points field can not be less than 1"
                },
            ]

        # limit should be float >0
        try:
            self.settings["continuouslimit"] = float(self.settingsWidget.lineEdit_continuousLimit.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: continuous limit field should be numeric"}]
        if self.settings["continuouslimit"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: continuous limit field should be positive"}]

        # continuous nplc (in fact it is integration time for the measurement) is calculated from line frequency, should be float >0
        try:
            if "lineFrequency" not in self.smu_settings:
                return [1, {"Error message": "Missing lineFrequency in SMU settings"}]
            line_freq = self.smu_settings["lineFrequency"]
            self.settings["continuousnplc"] = (
                0.001 * line_freq * float(self.settingsWidget.lineEdit_continuousNPLC.text())
            )
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: continuous nplc field should be numeric"}]
        if self.settings["continuousnplc"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: continuous nplc field should be positive"}]

        # delay (in fact it is stabilization time before the measurement), should be >0:
        try:
            self.settings["continuousdelay"] = float(self.settingsWidget.lineEdit_continuousDelay.text()) / 1000
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: continuous delay field should be numeric"}]
        if self.settings["continuousdelay"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: continuous delay field should be positive"}]

        # Determine settings for pulsed mode
        # start should be float
        try:
            self.settings["pulsedstart"] = float(self.settingsWidget.lineEdit_pulsedStart.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: pulsed start field should be numeric"}]

        # end should be float
        try:
            self.settings["pulsedend"] = float(self.settingsWidget.lineEdit_pulsedEnd.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: pulsed end field should be numeric"}]

        # number of points should be int >0
        try:
            self.settings["pulsedpoints"] = int(self.settingsWidget.lineEdit_pulsedPoints.text())
        except ValueError:
            return [
                1,
                {"Error message": "Value error in sweep plugin: pulsed number of points field should be integer"},
            ]
        if self.settings["pulsedpoints"] < 1:
            return [
                1,
                {"Error message": "Value error in sweep plugin: pulsed number of points field can not be less than 1"},
            ]

        # limit should be float >0
        try:
            self.settings["pulsedlimit"] = float(self.settingsWidget.lineEdit_pulsedLimit.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: pulsed limit field should be numeric"}]
        if self.settings["pulsedlimit"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: pulsed limit field should be positive"}]

        # pulsed nplc (in fact it is integration time for the measurement) is calculated from line frequency, should be float >0
        try:
            if "lineFrequency" not in self.smu_settings:
                return [1, {"Error message": "Missing lineFrequency in SMU settings"}]
            line_freq = self.smu_settings["lineFrequency"]
            self.settings["pulsednplc"] = 0.001 * line_freq * float(self.settingsWidget.lineEdit_pulsedNPLC.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: pulsed nplc field should be numeric"}]
        if self.settings["pulsednplc"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: pulsed nplc field should be positive"}]

        # delay (in fact it is stabilization time before the measurement) should be >0
        try:
            self.settings["pulseddelay"] = float(self.settingsWidget.lineEdit_pulsedDelay.text()) / 1000
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: pulsed delay field should be numeric"}]
        if self.settings["pulseddelay"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: pulsed delay field should be positive"}]

        # pause between pulses should be >0
        try:
            self.settings["pulsedpause"] = float(self.settingsWidget.lineEdit_pulsedPause.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: pulse pause field should be numeric"}]
        if self.settings["pulsedpause"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: pulse pause field should be positive"}]

        # Determine settings for drain mode
        # start should be float
        try:
            self.settings["drainstart"] = float(self.settingsWidget.lineEdit_drainStart.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: drain start field should be numeric"}]

        # end should be float
        try:
            self.settings["drainend"] = float(self.settingsWidget.lineEdit_drainEnd.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: drain end field should be numeric"}]

        # number of points should be int >0
        try:
            self.settings["drainpoints"] = int(self.settingsWidget.lineEdit_drainPoints.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: drain number of points field should be integer"}]
        if self.settings["drainpoints"] < 1:
            return [
                1,
                {"Error message": "Value error in sweep plugin: drain number of points field can not be less than 1"},
            ]

        # limit should be float >0
        try:
            self.settings["drainlimit"] = float(self.settingsWidget.lineEdit_drainLimit.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: drain limit field should be numeric"}]
        if self.settings["drainlimit"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: drain limit field should be positive"}]

        # drain nplc (in fact it is integration time for the measurement) should be float >0
        try:
            if "lineFrequency" not in self.smu_settings:
                return [1, {"Error message": "Missing lineFrequency in SMU settings"}]
            line_freq = self.smu_settings["lineFrequency"]
            self.settings["drainnplc"] = 0.001 * line_freq * float(self.settingsWidget.lineEdit_drainNPLC.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: drain nplc field should be numeric"}]
        if self.settings["drainnplc"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: drain nplc field should be positive"}]

        # delay (in fact it is stabilization time before the measurement) should be >0
        try:
            self.settings["draindelay"] = float(self.settingsWidget.lineEdit_drainDelay.text()) / 1000
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: drain delay field should be numeric"}]
        if self.settings["draindelay"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: drain delay field should be positive"}]

        self.settings["plotupdate"] = self.settingsWidget.spinBox_plotUpdate.value()
        try:
            self.settings["prescaler"] = float(self.settingsWidget.prescalerEdit.text())
        except ValueError:
            return [1, {"Error message": "Value error in sweep plugin: SMU limit prescaler field should be numeric"}]
        if self.settings["prescaler"] > 1:
            return [1, {"Error message": "Value error in sweep plugin: SMU limit prescaler can not be greater than 1"}]
        if self.settings["prescaler"] <= 0:
            return [1, {"Error message": "Value error in sweep plugin: SMU limit prescaler should be greater than 0"}]

        self.settings["address"] = self.settingsWidget.lineEdit_path.text()
        if not os.path.isdir(self.settings["address"] + os.sep):
            return [
                1,
                {"Error message": "Value error in sweep plugin: address string should point to a valid directory"},
            ]
        self.settings["filename"] = self.settingsWidget.lineEdit_filename.text()
        if not is_valid_filename(self.settings["filename"]):
            return [1, {"Error message": "Value error in sweep plugin: File name is not valid"}]

        self.settings["samplename"] = self.settingsWidget.lineEdit_sampleName.text()
        self.settings["comment"] = self.settingsWidget.lineEdit_comment.text()
        return [0, self.settings]

    @public
    def setSettings(self, settings):
        self.logger.log_debug("Setting settings for sweep plugin: " + str(settings))
        # the filename in settings may be modified, as settings parameter is pointer, it will modify also the original data. So need to make sure that the original data is intact
        self.settings = {}
        self.settings = copy.deepcopy(settings)
        self.smu_settings = settings["smu_settings"]

        # this function is called not from the main thread. Direct addressing of qt elements not from te main thread causes segmentation fault crash. Using a signal-slot interface between different threads should make it work
        #        self._setGUIfromSettings()

    ###############GUI enable/disable
    @pyqtSlot(bool)
    def set_running(self, status):
        self.settingsWidget.groupBox_general.setEnabled(not status)
        self.settingsWidget.groupBox_sweep.setEnabled(not status)
        if not status:
            self._update_GUI_state()
        self.settingsWidget.groupBox.setEnabled(not status)
        self.settingsWidget.fileBox.setEnabled(not status)
        self.settingsWidget.stopButton.setEnabled(status)
        self.settingsWidget.runButton.setEnabled(not status)
        self.settingsWidget.groupBox_dep.setEnabled(not status)
        self.closelock.emit_close_lock(status)

    ########sweep implementation

    def _stopAction(self):
        self.run_thread.thread_stop()

    def _runAction(self):
        #### disable interface controls. It is important to disable interfaces befor getting the data from them to assure that the input is not changed after it was checked
        # NOTE: smu set running was moved here since parsing needs to be done before setting running on the smu. It shouldn't cause issues since changing to the smu widget
        # is not possible while this is running.
        self.set_running(True)
        [status, message] = self.parse_settings_widget()
        self.function_dict["smu"][self.settings["smu"]]["set_running"](True)

        if status:
            if status == 1:
                self.logger.log_warn(str(message))
            else:
                self.logger.log_info(str(message))
            self.logger.log_info(message["Error message"])
            self.set_running(False)
            self.function_dict["smu"][self.settings["smu"]]["set_running"](False)

            return [status, message]

        # check the needed devices are connected
        [status, message] = self.function_dict["smu"][self.settings["smu"]]["smu_connect"]()
        if status:
            if status == 1:
                self.logger.log_warn(str(message))
            else:
                self.logger.log_info(str(message))
            self.logger.log_info(message["Error message"])
            self.set_running(False)
            self.function_dict["smu"][self.settings["smu"]]["set_running"](False)

            return [status, message]

        ##IRtodo#### check that the new file will not overwrite existing data -> implement dialog

        self.run_thread = thread_with_exception(self._sequenceImplementation)
        self.run_thread.start()
        return [0, "OK"]

    def _sweepImplementation(self):
        [recipe, drainsteps, sensesteps, modesteps] = create_sweep_reciepe(self.settings, self.smu_settings)
        data = np.array([])
        for recipeStep, measurement in enumerate(recipe):
            if self.function_dict["smu"][self.settings["smu"]]["smu_init"](
                measurement
            ):  # reinitialization at every step is needed because limits for pused and continuous may be deffierent
                raise sweepException("sweep plugin : smu_init failed")
            # creating a new header
            if recipeStep % (sensesteps * modesteps) == 0:
                columnheader = ""
                if not measurement["single_ch"]:
                    fileheader = create_file_header(
                        self.settings,
                        self.smu_settings,
                        backVoltage=measurement["drainvoltage"],
                    )
                else:
                    fileheader = create_file_header(self.settings, self.smu_settings)
            if measurement["pulse"]:
                headerpostfix = "_pulsed"
            else:
                headerpostfix = ""
            if measurement["sourcesense"]:
                columnheader = f"{columnheader} IS_4pr{headerpostfix}, VS_4pr{headerpostfix},"
            else:
                columnheader = f"{columnheader} IS_2pr{headerpostfix}, VS_2pr{headerpostfix},"
            if not measurement["single_ch"]:
                if measurement["drainsense"]:
                    columnheader = f"{columnheader} ID_4pr{headerpostfix}, VD_4pr{headerpostfix},"
                else:
                    columnheader = f"{columnheader} ID_2pr{headerpostfix}, VD_2pr{headerpostfix},"
            # running sweep
            if self.function_dict["smu"][self.settings["smu"]]["smu_runSweep"](measurement):
                raise sweepException("sweep plugin : smu_runSweep failed")

            # plotting while measuring
            self.axes.cla()
            self.axes.set_xlabel("Voltage (V)")
            self.axes.set_ylabel("Current (A)")
            self.sc.draw()
            buffer_prev = 0
            while True:
                time.sleep(self.settings["plotupdate"])
                [lastI, lastV, lastPoints] = self.function_dict["smu"][self.settings["smu"]]["smu_getLastBufferValue"](
                    measurement["source"]
                )
                if lastPoints >= measurement["steps"] * measurement["repeat"]:
                    break
                if lastPoints > buffer_prev:
                    if buffer_prev == 0:
                        Xdata_source = [lastV]
                        Ydata_source = [lastI]
                        plot_refs = self.axes.plot(Xdata_source, Ydata_source, "bo")
                        _plot_ref_source = plot_refs[0]
                        if not measurement["single_ch"]:
                            [lastI_drain, lastV_drain, lastPoints_drain] = self.function_dict["smu"][
                                self.settings["smu"]
                            ]["smu_getLastBufferValue"](measurement["source"], lastPoints)
                            Xdata_drain = [lastV]
                            Ydata_drain = [lastI]
                            plot_refs = self.axes.plot(Xdata_drain, Ydata_drain, "go")
                            _plot_ref_drain = plot_refs[0]
                    else:
                        Xdata_source.append(lastV)
                        Ydata_source.append(lastI)
                        _plot_ref_source.set_xdata(Xdata_source)
                        _plot_ref_source.set_ydata(Ydata_source)
                        if not measurement["single_ch"]:
                            [lastI_drain, lastV_drain, lastPoints_drain] = self.function_dict["smu"][
                                self.settings["smu"]
                            ]["smu_getLastBufferValue"](measurement["drain"], lastPoints)
                            Xdata_drain.append(lastV_drain)
                            Ydata_drain.append(lastI_drain)
                            _plot_ref_drain.set_xdata(Xdata_source)
                            _plot_ref_drain.set_ydata(Ydata_drain)
                    self.axes.relim()
                    self.axes.autoscale_view()
                    self.sc.draw()
                    if (
                        measurement["type"] == "i"
                        and (abs(lastV) > self.settings["prescaler"] * abs(measurement["limit"]))
                    ) or (
                        measurement["type"] == "i"
                        and (abs(lastV) > self.settings["prescaler"] * abs(measurement["limit"]))
                    ):
                        self.function_dict["smu"][self.settings["smu"]]["smu_abort"](measurement["source"])
                        break
                    buffer_prev = lastPoints
            #### Keithley may produce a 5042 error, so make a delay here
            time.sleep(self.settings["plotupdate"])
            self.function_dict["smu"][self.settings["smu"]]["smu_outputOFF"]()
            IV_source = self.function_dict["smu"][self.settings["smu"]]["smu_bufferRead"](measurement["source"])
            self.axes.cla()
            self.axes.set_xlabel("Voltage (V)")
            self.axes.set_ylabel("Current (A)")
            plot_refs = self.axes.plot(IV_source[:, 1], IV_source[:, 0], "bo")
            if not measurement["single_ch"]:
                IV_drain = self.function_dict["smu"][self.settings["smu"]]["smu_bufferRead"](measurement["drain"])
                plot_refs = self.axes.plot(IV_source[:, 1], IV_drain[:, 0], "go")
            self.sc.draw()
            IVresize = 0
            if data.size == 0:
                data = IV_source
            else:
                dataLength = np.size(data, 0)
                IVLength = np.size(IV_source, 0)
                if dataLength < IVLength:
                    data = np.vstack([data, np.full((IVLength - dataLength, np.size(data, 1)), "")])
                else:
                    IVresize = dataLength - IVLength
                    IV_source = np.vstack([IV_source, np.full((IVresize, 2), "")])
                data = np.hstack([data, IV_source])
            if not measurement["single_ch"]:
                if IVresize:
                    IV_drain = np.vstack([IV_drain, np.full((IVresize, 2), "")])
                data = np.hstack([data, IV_drain])
            if drainsteps > 1:
                fulladdress = (
                    self.settings["address"]
                    + os.sep
                    + self.settings["filename"]
                    + f"{measurement['drainvoltage']}V"
                    + ".dat"
                )
            else:
                fulladdress = self.settings["address"] + os.sep + self.settings["filename"] + ".dat"
            with open(fulladdress, "w") as f:
                f.write(fileheader + f"{columnheader[1:-1]}" + "\n")
                pd.DataFrame(data).to_csv(f, index=False, header=False, float_format="%.12e", sep=",")
        #                np.savetxt(fulladdress, data, fmt='%.12e', delimiter=',', newline='\n', header=fileheader + columnheader, comments='#')
        return [0, "sweep finished"]

    @public
    def sequenceStep(self, postfix):
        self.settings["filename"] = self.settings["filename"] + postfix
        [status, message] = self.function_dict["smu"][self.settings["smu"]]["smu_connect"]()
        if status:
            return [status, message]
        self._sweepImplementation()
        self.function_dict["smu"][self.settings["smu"]]["smu_disconnect"]()
        return [0, "sweep finished"]

    def _sequenceImplementation(self):
        """
        Performs an IV sweep on SMU, saves the result in a file

        Returns [status, message]:
               status: 0 - no error, ~0 - error
        """
        try:
            exception = 0  # handling turning off smu in case of exceptions. 0 = no exception, 1 - failure in smu, 2 - threadStopped, 3 - unexpected
            self._sweepImplementation()
        except sweepException as e:
            self.logger.log_info(datetime.now().strftime("%H:%M:%S.%f") + f"{e}")
            exception = 1
        except ThreadStopped:
            self.logger.log_info(datetime.now().strftime("%H:%M:%S.%f") + ": sweep plugin implementation aborted")
            exception = 2
        except Exception as e:
            self.logger.log_info(
                datetime.now().strftime("%H:%M:%S.%f")
                + f": sweep plugin implementation stopped because of unexpected exception: {e}"
            )
            exception = 3
        finally:
            try:
                if exception > 1:
                    self.function_dict["smu"][self.settings["smu"]]["smu_abort"](self.settings["channel"])
                    if not self.settings["singlechannel"]:
                        self.function_dict["smu"][self.settings["smu"]]["smu_abort"](self.settings["drainchannel"])
                self.function_dict["smu"][self.settings["smu"]]["smu_outputOFF"]()
                self.function_dict["smu"][self.settings["smu"]]["smu_disconnect"]()
                if exception == 3 or exception == 1:
                    self.logger.info_popup("Implementation stopped because of exception. Check log")
            except Exception as e:
                self.logger.log_error(
                    datetime.now().strftime("%H:%M:%S.%f")
                    + f" : sweep plugin: smu turn off failed because of unexpected exception: {e}"
                )
                self.logger.info_popup("SMU turn off failed. Check log")
            self.set_running(False)

    @public
    def set_gui_from_settings(self):
        """
        Updates the GUI fields based on the internal settings dictionary.
        This function assumes that the settings have already been set using the `setSettings` function.
        """

        def set_combobox_value(combobox, value):
            """
            Helper function to set the value of a QComboBox in a case-insensitive manner.

            Args:
                combobox (QComboBox): The combobox to set the value for.
                value (str): The value to set.

            Returns:
                bool: True if the value was found and set, False otherwise.
            """
            self.logger.log_debug(f"Setting combobox {combobox.objectName()} to value: {value}")
            index = combobox.findText(value, Qt.MatchFlag.MatchFixedString)
            if index != -1:
                combobox.setCurrentIndex(index)
                return True
            return False

        self.logger.log_debug("Setting GUI from internal settings")
        self.settingsWidget.lineEdit_path.setText(self.settings["address"])
        self.settingsWidget.lineEdit_filename.setText(self.settings["filename"])
        self.settingsWidget.lineEdit_sampleName.setText(self.settings["samplename"])
        self.settingsWidget.lineEdit_comment.setText(self.settings["comment"])

        set_combobox_value(self.settingsWidget.comboBox_channel, self.settings["channel"])
        set_combobox_value(self.settingsWidget.comboBox_inject, self.settings["inject"])
        set_combobox_value(self.settingsWidget.comboBox_mode, self.settings["mode"])
        set_combobox_value(self.settingsWidget.comboBox_continuousDelayMode, self.settings["continuousdelaymode"])
        set_combobox_value(self.settingsWidget.comboBox_pulsedDelayMode, self.settings["pulseddelaymode"])
        set_combobox_value(self.settingsWidget.comboBox_drainDelayMode, self.settings["draindelaymode"])
        set_combobox_value(self.settingsWidget.comboBox_sourceSenseMode, self.settings["sourcesensemode"])
        set_combobox_value(self.settingsWidget.comboBox_drainSenseMode, self.settings["drainsensemode"])

        line_freq = self.smu_settings["lineFrequency"]
        self.settingsWidget.lineEdit_continuousNPLC.setText(
            str(float(self.settings["continuousnplc"]) * 1000 / line_freq)
        )
        self.settingsWidget.lineEdit_continuousDelay.setText(str(float(self.settings["continuousdelay"]) * 1000))
        self.settingsWidget.lineEdit_pulsedNPLC.setText(str(float(self.settings["pulsednplc"]) * 1000 / line_freq))
        self.settingsWidget.lineEdit_pulsedDelay.setText(str(float(self.settings["pulseddelay"]) * 1000))
        self.settingsWidget.lineEdit_drainNPLC.setText(str(float(self.settings["drainnplc"]) * 1000 / line_freq))
        self.settingsWidget.lineEdit_drainDelay.setText(str(float(self.settings["draindelay"]) * 1000))
        self.settingsWidget.spinBox_plotUpdate.setValue(int(self.settings["plotupdate"]))
        self.settingsWidget.prescalerEdit.setText(str(self.settings["prescaler"]))

        self.settingsWidget.lineEdit_continuousStart.setText(str(self.settings["continuousstart"]))
        self.settingsWidget.lineEdit_continuousEnd.setText(str(self.settings["continuousend"]))
        self.settingsWidget.lineEdit_continuousPoints.setText(str(self.settings["continuouspoints"]))
        self.settingsWidget.lineEdit_continuousLimit.setText(str(self.settings["continuouslimit"]))

        self.settingsWidget.lineEdit_pulsedStart.setText(str(self.settings["pulsedstart"]))
        self.settingsWidget.lineEdit_pulsedEnd.setText(str(self.settings["pulsedend"]))
        self.settingsWidget.lineEdit_pulsedPoints.setText(str(self.settings["pulsedpoints"]))
        self.settingsWidget.lineEdit_pulsedLimit.setText(str(self.settings["pulsedlimit"]))
        self.settingsWidget.lineEdit_pulsedPause.setText(str(self.settings["pulsedpause"]))

        self.settingsWidget.lineEdit_drainStart.setText(str(self.settings["drainstart"]))
        self.settingsWidget.lineEdit_drainEnd.setText(str(self.settings["drainend"]))
        self.settingsWidget.lineEdit_drainPoints.setText(str(self.settings["drainpoints"]))
        self.settingsWidget.lineEdit_drainLimit.setText(str(self.settings["drainlimit"]))

        self.settingsWidget.lineEdit_repeat.setText(str(self.settings["repeat"]))
        if isinstance(self.settings["singlechannel"], bool):
            self.settingsWidget.checkBox_singleChannel.setChecked(self.settings["singlechannel"])
        elif isinstance(self.settings["singlechannel"], str):
            if self.settings["singlechannel"].lower() == "true":
                self.settingsWidget.checkBox_singleChannel.setChecked(True)
        else:
            raise ValueError(
                "Invalid type for singlechannel setting: expected bool or str, got {}".format(
                    type(self.settings["singlechannel"])
                )
            )
        self.logger.log_debug("GUI settings set from internal settings")
        self._update_GUI_state()
