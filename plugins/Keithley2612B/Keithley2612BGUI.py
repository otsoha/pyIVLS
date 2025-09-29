import os
from typing import Optional

# from Keithley2612B_test import Keithley2612B
from Keithley2612B import Keithley2612B

from PyQt6 import uic


"""
            settings dictionary for class
            
            
		# settings["channel"] source channel: may take values [smua, smub]
		# settings["inject"] source type: may take values [current, voltage]
		# settings["mode"] pulse/continuous operation: may take values [continuous, pulsed, mixed]
		# settings["continuousdelaymode"] stabilization time before measurement for continuous sweep: may take values [auto, manual]
		# settings["pulseddelaymode"] stabilization time before measurement for pulsed sweep: may take values [auto, manual]
		# settings["draindelaymode"] stabilization time before measurement for drain channel: may take values [auto, manual]
		# settings["sourcesensemode"] source sence mode: may take values [2 wire, 4 wire, 2 & 4 wire]		
		# settings["drainsensemode"] drain sence mode: may take values [2 wire, 4 wire, 2 & 4 wire]
		# settings["singlechannel"] single channel mode: may be True or False
		# settings["sourcehighc"] HighC mode for source: may be True or False        
		# settings["repeat"] repeat count: should be int >0
		# settings for continuous mode
		## settings["continuousstart"] start point
		## settings["continuousend"] end point
		## settings["continuouspoints"] number of points
		## settings["continuouslimit"] limit for current in voltage mode or for voltage in current mode
		## settings["continuousnplc"] integration time in nplc units
		## settings["continuousdelay"] stabilization time before the measurement
		# settings for pulsed mode
		## settings["pulsedstart"] start point
		## settings["pulsedend"] end point
		## settings["pulsedpoints"] number of points
		## settings["pulsedlimit"] limit for current in voltage mode or for voltage in current mode
		## settings["pulsednplc"] integration time in nplc units
		## settings["pulseddelay"] stabilization time before the measurement
		## settings["pulsepause"] pase between the pulses
		# settings for drain
		## settings["drainstart"] start point
		## settings["drainend"] end point
		## settings["drainpoints"] number of points should be not zero. If equals to 1 only the start point is used
		## settings["drainlimit"] limit for current in voltage mode or for voltage in current mode
		## settings["drainnplc"] integration time in nplc units
		## settings["draindelay"] stabilization time before the measurement
		## settings["drainhighc"] HighC mode for drain: may be True or False  


"""


class Keithley2612BGUI:
    """GUI for Keithley2612B"""

    non_public_methods = []  # add function names here, if they should not be exported as public to another plugins

    ####################################  threads

    ################################### internal functions

    ########Slots

    ########Signals

    ########Functions
    def __init__(self):
        # Load the settings based on the name of this file.
        self.path = os.path.dirname(__file__) + os.path.sep
        self.settingsWidget = uic.loadUi(self.path + "Keithley2612B_settingsWidget.ui")

        # Initialize Keithley module
        ##IRtodo#### move Keithley address to GUI
        self.smu = Keithley2612B()
        self.settings = {}

    ########Functions
    ###############GUI setting up

    def _initGUI(
        self,
        plugin_info,
    ) -> None:
        if plugin_info["sourcehighc"] == "True":
            self.settingsWidget.checkBox_sourceHighC.setChecked(True)
        if plugin_info["drainhighc"] == "True":
            self.settingsWidget.checkBox_drainHighC.setChecked(True)
        self.settingsWidget.lineEditAddress.setText(plugin_info["address"])
        self.settingsWidget.lineEditETH.setText(plugin_info["eth_address"])
        self.settingsWidget.backendCombobox.setCurrentText(plugin_info["backend"])
        self.settingsWidget.lineEditPort.setText(plugin_info["port"])

    ########Functions
    ########plugins interraction
    def _get_public_methods(self) -> dict:
        """
        Returns a nested dictionary of public methods for the plugin
        """
        # if the plugin type matches the requested type, return the functions

        methods = {
            method: getattr(self, method)
            for method in dir(self)
            if callable(getattr(self, method))
            and not method.startswith("__")
            and not method.startswith("_")
            and method not in self.non_public_methods
        }
        return methods

    ########Functions to be used externally
    ###############get settings from GUI

    def parse_settings_widget(self) -> tuple[int, dict]:
        """Parses the settings widget for the Keithley. Extracts current values

        Returns [status, settings_dict]:
            status: 0 - no error, ~0 - error (add error code later on if needed)
            self.settings
        """

        # Determine a HighC mode for source: may be True or False
        self.settings["sourcehighc"] = self.settingsWidget.checkBox_sourceHighC.isChecked()

        # Determine a HighC mode for drain: may be True or False
        self.settings["drainhighc"] = self.settingsWidget.checkBox_drainHighC.isChecked()
        if "lineFrequency" not in self.settings:
            info = self.smu.getLineFrequency()
            self.settings["lineFrequency"] = info
        self._parse_settings_address()
        return (0, self.settings)

    def _parse_settings_address(self) -> None:
        """Updates the address, eth_address, backend and port in self.settings from the GUI"""
        self.settings["address"] = self.settingsWidget.lineEditAddress.text()
        self.settings["eth_address"] = self.settingsWidget.lineEditETH.text()
        self.settings["backend"] = self.settingsWidget.backendCombobox.currentText()
        self.settings["port"] = self.settingsWidget.lineEditPort.text()

    ###############GUI enable/disable
    def set_running(self, status: bool) -> None:
        """Sets the running state of the GUI elements.

        Args:
            status (bool): True if the plugin is running, False otherwise.
        """
        self.settingsWidget.groupBox_HWsettings.setEnabled(not status)
        self.settingsWidget.groupBox_channels.setEnabled(not status)

    ###############providing access to SMU functions
    def smu_channelNames(self) -> list[str]:
        """provides channel names for particular SMU
        this should make plugins more universal, but still need to be rechecked"""
        self._parse_settings_address()
        return self.smu.channel_names(self.settings["backend"])

    def smu_connect(self) -> tuple[int, dict]:
        """an interface for an externall calling function to connect to Keithley

        Returns [status, message]:
            0 - no error, ~0 - error (add error code later on if needed)
            message contains devices response to IDN query if devices is connected, or an error message otherwise

        """
        self._parse_settings_address()
        try:
            self.smu.keithley_connect(
                self.settings["address"], self.settings["eth_address"], self.settings["backend"], self.settings["port"]
            )
            return (0, {"Error message": self.smu.keithley_IDN()})
        except Exception as e:
            return (
                4,
                {
                    "Error message": "Hardware error in Keithley2612B plugin: can not connect to the device",
                    "Exception": e,
                },
            )

    def smu_disconnect(self) -> None:
        """an interface for an externall calling function to disconnect Keithley"""
        self.smu.keithley_disconnect()

    def smu_abort(self, channel) -> None:
        """An interface for an externall calling function to stop the sweep on Keithley
        (this function will NOT switch OFF the outputs)
        s: channel to get the last value (may be 'smua' or 'smub')
        """
        self.smu.abort_sweep(channel)

    def smu_outputON(self, source: Optional[str] = None, drain: Optional[str] = None) -> None:
        """An interface for an externall calling function to switch on the output

        source and drain are "smua" or "smub"
        """
        self.smu.channelsON(source, drain)

    def smu_outputOFF(self) -> None:
        """An interface for an externall calling function to switch off the output"""

        self.smu.channelsOFF()

    def smu_init(self, s: dict) -> int:
        """an interface for an externall calling function to initialize Keithley
        s: dictionary containing the settings for the sweep to initialize. It is different from the self. settings, as it contains data only for the current sweep

        Return the same as for keithley_init [status, message]:
                status: 0 - no error, ~0 - error
                message

        Args:
            s (dict): Configuration dictionary.

        Note: this function should be called only when the settings are checked, i.e. after parse_settings_widget
        """
        return self.smu.keithley_init(s)

    def smu_runSweep(self, s: dict) -> int:
        """an interface for an externall calling function to run sweep on Keithley
        s: dictionary containing the settings to run the sweep. It is different from the self. settings, as it contains data only for the current sweep

        Returns:
            0 - no error
            ~0 - error (add error code later on if needed)

        Args:
            s (dict): Configuration dictionary.

        Note: this function should be called only after the Keithley is initialized (i.e. after smu.keithley_init(s))
        """
        return self.smu.keithley_run_sweep(s)

    def smu_getLastBufferValue(self, channel, readings=None) -> list:
        """an interface for an externall calling function to get last buffer value from Keithley
        s: channel to get the last value (may be 'smua' or 'smub')

        Returns:
            list [i, v, number of point in the buffer]
        """
        return self.smu.get_last_buffer_value(channel, readings)

    def smu_bufferRead(self, channel):
        """an interface for an externall calling function to get the content of a channel buffer from Keithley
        s: channel to get the last value (may be 'smua' or 'smub')

        Returns:
            np.ndarray (current, voltage)
        """
        return self.smu.read_buffers(channel)

    def smu_getIV(self, channel) -> tuple[int, list[float]]:
        """gets IV data

        Returns:
            list [i, v]
        """
        return (0, self.smu.getIV(channel))

    def smu_setOutput(self, channel, outputType, value):
        #        """sets smu output but does not switch it ON
        # channel = "smua" or "smub"
        # outputType = "i" or "v"
        # value = float
        #        """
        self.smu.setOutput(channel, outputType, value)
        return [0, "OK"]

    def smu_setup_resmes(self, channel):
        """Sets up resistance measurement

        Args:
            channel (str): The channel to measure ('smua' or 'smub').

        Returns:
            tuple: (status, resistance value) where status is 0 for success, non-zero for error.
        """
        success, err_text = self.smu.resistance_measurement_setup(channel)
        if success:
            return (0, {"Error message": "Keithley setup resistance measurement"})
        else:
            return (4, {"Error message": f"HW issue in keithley resistance setup: {err_text}"})

    def smu_resmes(self, channel):
        """Measures resistance on the specified channel.

        Args:
            channel (str): The channel to measure ('smua' or 'smub').

        Returns:
            tuple: (status, resistance value) where status is 0 for success, non-zero for error.
        """
        resistance = self.smu.resistance_measurement(channel)
        return (0, resistance)

    def smu_set_digio(self, channel, value):
        """Sets digital output on the specified channel.

        Args:
            channel (str): The channel to set ('smua' or 'smub').
            value (int): The value to set (0 or 1).

        Returns:
            tuple: (status, message) where status is 0 for success, non-zero for error.
        """
        self.smu.set_digio(channel, value)
        return (0, {"Error message": "Digital output set successfully"})
