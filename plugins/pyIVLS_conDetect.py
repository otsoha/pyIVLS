#!/usr/bin/python3.8
import pluggy

from conDetectGUI import conDetectGUI


class pyIVLS_conDetect_plugin:
    """Hooks for conDetect plugin
    The plugin is intended to be used for checking
    if there is connection between 2 needles on the same pad in remote sense (4-wire) measurement"""

    hookimpl = pluggy.HookimplMarker("pyIVLS")

    def __init__(self):
        self.plugin_name = "conDetect"
        self.plugin_function = "contacting"
        self.GUI = conDetectGUI()
        super().__init__()

    @hookimpl
    def get_setup_interface(self, plugin_data) -> dict:
        """Returns GUI

        Returns:
            dict: name, widget
        """
        self.GUI._initGUI(plugin_data[self.plugin_name]["settings"])
        return {self.plugin_name: self.GUI.settingsWidget}

    @hookimpl
    def get_functions(self, args=None):
        """Returns a dictionary of publicly accessible functions.

        Args:
            args (dict): function

        Returns:
            dict: functions
        """
        if args is None or args.get("function") == plugin_function:
            return {self.plugin_name: self.GUI._get_public_methods()}

    @hookimpl
    def get_log(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.plugin_function:
            return {self.plugin_name: self.GUI._getLogSignal()}

    @hookimpl
    def get_info(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.plugin_function:
            return {self.plugin_name: self.GUI._getInfoSignal()}

    @hookimpl
    def get_closeLock(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.plugin_function:
            return {self.plugin_name: self.GUI._getCloseLockSignal()}
