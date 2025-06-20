#!/usr/bin/python3.8
import pluggy
import configparser
import os

from VenusUSB2GUI import VenusUSB2GUI

"""
This hook implementation file should only contain the necessary hooks for the plugin.
See pyIVLS_hookspec.py for the possible hooks. If the plugin does not need a hook, it does
not need to be implemented.
"""


class pyIVLS_VenusUSB2_plugin:
    """Hooks for VenusUSB2 camera plugin"""

    hookimpl = pluggy.HookimplMarker("pyIVLS")

    def __init__(self):
        """
        Initialize the plugin and set up properties.
        """

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
        self.type = config.get("plugin", "type",)
        self.function = config.get("plugin", "function", fallback="")
        self._class = config.get("plugin", "class", fallback="")
        self.dependencies = config.get("plugin", "dependencies", fallback="").split(",")
        self.version = config.get("plugin", "version", fallback="")
        self.metadata = {
            "name": self.name,
            "type": self.type,
            "function": self.function,
            "version": "placeholder",
            "dependencies": self.dependencies
        }
        
        self.camera_control = VenusUSB2GUI()

    @hookimpl
    def get_setup_interface(self, plugin_data: dict) -> dict:
        """Returns GUI
        Args:
            plugin_data (dict): plugin data read from .ini to read initial settings.

        Returns:
            dict: name, widget
        """
        self.camera_control._initGUI(plugin_data[self.name]["settings"])
        return {self.metadata["name"]: self.camera_control.settingsWidget}

    @hookimpl
    def get_MDI_interface(self, args=None) -> dict:
        """Returns MDI window for camera preview

        Returns:
            dict: name, widget
        """
        return {self.metadata["name"]: self.camera_control.previewWidget}

    @hookimpl
    def get_functions(self, args=None):
        """Returns a dictionary of publicly accessible functions.

        Args:
            args (dict): function

        Returns:
            dict: functions
        """
        if args is None or args.get("function") == self.metadata["function"]:
            return {self.metadata["name"]: self.camera_control._get_public_methods(self.function)}

    @hookimpl
    def get_log(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.metadata["function"]:
            return {self.metadata["name"]: self.camera_control._getLogSignal()}

    @hookimpl
    def get_info(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.metadata["function"]:
            return {self.metadata["name"]: self.camera_control._getInfoSignal()}

    @hookimpl
    def get_closeLock(self, args=None):
        """provides the signal for logging to main app

        :return: dict that includes the log signal
        """

        if args is None or args.get("function") == self.metadata["function"]:
            return {self.metadata["name"]: self.camera_control._getCloseLockSignal()}
        
    @hookimpl
    def get_plugin(self, args=None):
        """Returns the plugin as a reference to itself.
        NOTE: when writing implmentations of this, the plugin should contain its own metadata, such as name, type, version, etc.

        Args:
            args (_type_, optional): can be used to specify which plugin is needed based on
            type, function, etc. 

        Returns:
            tuple[object, metadata]: reference to the plugin itself along with its properties such as name, type, version, etc.
        """
        if args is None or args.get("function") == self.metadata["function"]:
            return [self.camera_control, self.metadata]
        
    @hookimpl
    def get_plugin_settings(self, args=None):
        """See pyIVLS_hookspec.py for details.
        """
        if args is None or args.get("function") == self.metadata["function"]:
            status, settings = self.camera_control._parse_settings_preview()
            return (self.metadata["name"], status, settings)
