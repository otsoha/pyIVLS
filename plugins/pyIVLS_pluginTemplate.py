#!/usr/bin/python3.8

"""
This is a template for a plugin in pyIVLS

This file only implements the hooks for pyIVLS.
The proper implementation should be placed in a directory with the same name (for this template it is "pluginTemplate") next to this file.
The main reason to put implementation in a different calss is to allow to reuse it in other applications.

The standard implementation may (but not must) include
- GUI a Qt widget implementation
- GUI functionality (e.g. pluginTemplateGUI.py) - code that interracts with Qt GUI elements from widgets
- plugin core implementation - a set of functions that may be used outside of GUI
"""

import pluggy
from pluginTemplate.pluginTemplateGUI import pluginTemplateGUI


class pyIVLS_pluginTemplate_plugin:
    """Hooks for pluginTemplate plugin
    Not all hooks must be implemented
    If hook is not needed it should be deleted
    """

    hookimpl = pluggy.HookimplMarker("pyIVLS")

    def __init__(self):
        self.plugin_name = "pluginTemplate"
        self.plugin_function = (
            "pluginFunction"  # e.g. smu, camera, micromanipulator, etc.
        )
        self.pluginClass = pluginTemplateGUI()
        super().__init__()

    @hookimpl
    def get_setup_interface(self, plugin_data) -> dict:
        """Returns GUI plugin for the docking area (settings/buttons). This function is called from pyIVLS_container
        Args:
            plugin_data (dict): plugin dict from pyIVLS_container. Used for example to get the initial settings.
        Returns:
            dict: name, widget
        """
        ##IRtodo#### add check if (error) show message and return error
        self.pluginClass._initGUI(plugin_data[self.plugin_name]["settings"])
        return {self.plugin_name: self.pluginClass.settingsWidget}

    @hookimpl
    def get_MDI_interface(self, args=None) -> dict:
        """Returns MDI window (visualisation). This function is called from pyIVLS_container

        Returns:
            dict: name, widget
        """
        return {self.plugin_name: self.pluginClass.MDIWidget}

    @hookimpl
    def get_functions(self, args=None):
        """Returns a dictionary of publicly accessible functions. This function is called from pyIVLS_container

        Args:
            args (dict): function

        Returns:
            dict: functions
        """
        if args is None or args.get("function") == self.plugin_function:
            return {self.plugin_name: self.pluginClass._get_public_methods()}

    @hookimpl
    def get_log(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.plugin_function:
            return {self.plugin_name: self.camera_control._getLogSignal()}

    @hookimpl
    def get_info(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.plugin_function:
            return {self.plugin_name: self.pluginClass._getInfoSignal()}

    @hookimpl
    def get_closeLock(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.plugin_function:
            return {self.plugin_name: self.pluginClass._getCloseLockSignal()}
