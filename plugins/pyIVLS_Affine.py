#!/usr/bin/python3.8
import pluggy
from PyQt6 import QtWidgets

from plugins.CoordConverter.affine import Affine


class pyIVLS_Affine_plugin:
    """Hooks for affine conversion plugin"""

    hookimpl = pluggy.HookimplMarker("pyIVLS")

    def __init__(self):
        self.affine = Affine()

    @hookimpl
    def get_setup_interface(self, pm) -> dict:
        """Sets up the buttons for affine conversion plugin

        Returns:
            dict: name, widget
        """

        mask_button = self.affine.settingsWidget.findChild(
            QtWidgets.QPushButton, "maskButton"
        )

        find_button = self.affine.settingsWidget.findChild(
            QtWidgets.QPushButton, "findButton"
        )

        save_button = self.affine.settingsWidget.findChild(
            QtWidgets.QPushButton, "saveButton"
        )
        mask_gds_button = self.affine.settingsWidget.findChild(
            QtWidgets.QPushButton, "maskGdsButton"
        )
        check_mask_button = self.affine.settingsWidget.findChild(
            QtWidgets.QPushButton, "checkMaskButton"
        )

        # FIXME: a button to reset the affine? might not be necessary.
        # Connect widget buttons to functions
        mask_button.clicked.connect(self.affine.mask_button)
        find_button.clicked.connect(self.affine.find_button)
        save_button.clicked.connect(self.affine.save_button)
        mask_gds_button.clicked.connect(self.affine.mask_gds_button)
        check_mask_button.clicked.connect(self.affine.check_mask_button)
        if self.affine.A is None:
            self.affine.affine_label.setText(
                "Affine matrix not found. Please click 'Find Affine'."
            )

        # FIXME: Should this be saved do a .ini file?
        self.affine.mask_label.setText("Set mask image.")

        if self.affine.camera_functions is None:
            self.affine.camera_functions = pm.hook.get_functions(
                args={"function": "camera"}
            )

        return {"Affine": self.affine.settingsWidget}

    @hookimpl
    def get_functions(self, args):
        if args.get("function") == "coordinate conversion":
            return {"affine_coords": self.affine.coords}
