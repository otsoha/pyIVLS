#!/usr/bin/python3.8


import pluggy
import configparser
from verifyContactGui import verifyContactGUI
import os


class pyIVLS_verifyContact_plugin:
    hookimpl = pluggy.HookimplMarker("pyIVLS")

    def __init__(self):
        # iterate current directory to find the .ini file
        path = os.path.dirname(__file__)
        for file in os.listdir(path):
            if file.endswith(".ini"):
                path = os.path.join(path, file)
                break
        config = configparser.ConfigParser()
        # no need to close resource, since configparser handles it internally
        # https://stackoverflow.com/questions/990867/closing-file-opened-by-configparser
        config.read(path)

        self.name = config.get("plugin", "name")
        self.type = config.get("plugin", "type")
        self.function = config.get("plugin", "function")
        self._class = config.get("plugin", "class")
        self.dependencies = config.get("plugin", "dependencies").split(",")
        self.pluginClass = verifyContactGUI()

    @hookimpl
    def get_setup_interface(self, plugin_data) -> dict:
        """Returns GUI plugin for the docking area (settings/buttons). This function is called from pyIVLS_container
        Args:
            plugin_data (dict): plugin dict from pyIVLS_container. Used for example to get the initial settings.
        Returns:
            dict: name, widget
        """
        settings = plugin_data.get(self.name, {})
        return {self.name: self.pluginClass.setup(settings)}

    @hookimpl
    def get_log(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.function:
            return {self.name: self.pluginClass._getLogSignal()}

    @hookimpl
    def get_info(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.function:
            return {self.name: self.pluginClass._getInfoSignal()}

    @hookimpl
    def get_functions(self, args=None):
        """returns a dict of publicly accessible functions.

        :return: dict containing the functions
        """
        if args is None or args.get("function") == self.function:
            return {self.name: self.pluginClass._get_public_methods()}
    
    @hookimpl
    def set_function(self, function_dict):
        """provides a list of available public functions from other plugins as a nested dict

        Returns:
        """
        pruned = {function_dict_key: function_dict[function_dict_key] for function_dict_key in self.dependencies if function_dict_key in function_dict}
        self.pluginClass.dm.set_function_dict(pruned)
        result = self.pluginClass._getPublicFunctions(pruned)
        return result
    
    @hookimpl
    def get_plugin_settings(self, args=None):
        """Reads the current settings from the settingswidget, returns a dict. Returns (name, status, settings_dict)"""
        if args is None or args.get("function") == self.function:
            status, settings = self.pluginClass.parse_settings_widget()
            return (self.name, status, settings)