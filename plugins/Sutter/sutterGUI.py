from functools import wraps
import os

from PyQt6 import QtWidgets, uic
from PyQt6.QtCore import QObject
from Sutter import Mpc325
from plugin_components import (
    LoggingHelper,
    ConnectionIndicatorStyle,
    public,
    get_public_methods,
    CloseLockSignalProvider,
)
import copy
from components.threadStopped import ThreadStopped
import threading

"""
From readme:
0 = no error, 
1 = Value error, 
2 = Any error reported by dependent plugin, 
3 = missing functions or plugins, 
4 = harware error 
plugins return errors in form of list [number, {"Error message":"Error text", "Exception":f"e"}]
e.g. [1, {"Error message":"Value error in sweep plugin: SMU limit prescaler field should be numeric"}] 
error text will be shown in the dialog message in the interaction plugin, 
so the error text should contain the plugin name,
e.g. return [1, {"Error message":"Value error in Keithley plugin: 
drain nplc field should be numeric"}]

"Error message" : message to display in info box
"Missing functions" : list of missing functions from other plugins
"Exception" : exception from called function

"""


def handle_sutter_exceptions(func):
    """Decorator to handle Sutter-specific exceptions while letting ThreadStopped pass through"""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except ThreadStopped:
            # Re-raise ThreadStopped without catching it
            raise
        except InterruptedError as e:
            # Handle move interruption as a successful stop operation
            return [0, {"Error message": f"Sutter move interrupted: {str(e)}"}]
        except ValueError as e:
            return [1, {"Error message": f"Value error in Sutter plugin: {str(e)}", "Exception": str(e)}]
        except Exception as e:
            return [4, {"Error message": f"Sutter HW error: {str(e)}", "Exception": str(e)}]

    return wrapper


class SutterGUI(QObject):
    """
    GUI implementation of the sutter microman plugin for pyIVLS.

    public API:

    - mm_open
    - mm_change_active_device
    - mm_devices
    - mm_move
    - mm_move_relative
    - mm_zmove
    - mm_stop
    - mm_up_max
    - mm_current_position



    hooks:
    - get_setup_interface
    - get_functions
    - get_log
    - get_info
    - get_closeLock



    revision 0.1
    2025.05.22
    otsoha
    """

    GREEN_STYLE = ConnectionIndicatorStyle.GREEN_CONNECTED.value
    RED_STYLE = ConnectionIndicatorStyle.RED_DISCONNECTED.value

    # FIXME: kinda stupid to import the names here
    def __init__(self, name, function):
        super().__init__()
        self.hal = Mpc325()
        self.plugin_name = name
        self.plugin_function = function
        self.logger = LoggingHelper(self)
        self.cl = CloseLockSignalProvider()
        self.settings = {}

    def setup(self, settings):
        """
        Setup the sutter GUI by loading ui and initializing the hal. Connect buttons to functions.
        """
        path = os.path.dirname(__file__) + os.path.sep
        self.settingsWidget = uic.loadUi(path + "Sutter_settingsWidget.ui")

        # Store settings internally in .ini format
        self.settings = copy.deepcopy(settings)

        # connect buttons to functions
        self.settingsWidget.connectButton.clicked.connect(self._connect_button)
        self.settingsWidget.statusButton.clicked.connect(self._status_button)
        self.settingsWidget.stopButton.clicked.connect(self._stop_button)
        self.settingsWidget.calibrateButton.clicked.connect(self._calibrate_button)
        self.settingsWidget.quickBox.toggled.connect(self._quickmove_changed)
        self.settingsWidget.speedComboBox.currentIndexChanged.connect(self.speed_changed)
        self.settingsWidget.devnumCombo.currentIndexChanged.connect(self._devnum_changed)

        # save input fields. Explicit typing here just so I get type hints in vscode
        self.quickmove_input: QtWidgets.QCheckBox = self.settingsWidget.quickBox
        self.source_input: QtWidgets.QLineEdit = self.settingsWidget.sourceInput
        self.speed_input: QtWidgets.QComboBox = self.settingsWidget.speedComboBox
        self.devnum_combo: QtWidgets.QComboBox = self.settingsWidget.devnumCombo

        # fill combobox
        speeds = self.hal._MOVE_SPEEDS
        for speed_key, speed_value in speeds.items():
            self.speed_input.addItem(f"{speed_key}: {int(speed_value)} microns/s")

        # Apply settings to GUI from internal settings
        self._apply_settings_to_gui()

        self._gui_change_device_connected(self.hal.is_connected())

        return self.settingsWidget

    # GUI interactions
    def _apply_settings_to_gui(self):
        """Apply internal settings to GUI controls."""
        try:
            # Handle quickmove setting - can be boolean or string
            quickmove = self.settings.get("quickmove", False)
            if isinstance(quickmove, str):
                self.quickmove_input.setChecked(quickmove.lower() == "true")
            else:
                self.quickmove_input.setChecked(bool(quickmove))

            # Set address
            address = self.settings.get("address", "")
            self.source_input.setText(address)

            # Set speed text
            speed_text = self.settings.get("speed_text", "")
            if speed_text:
                self.speed_input.setCurrentText(speed_text)

            # Update HAL internal state based on current settings
            self._update_hal_from_settings()

        except Exception as e:
            self.logger.log_warn(f"Error applying settings to GUI: {str(e)}")

    def _update_hal_from_settings(self):
        """Update HAL internal state from current settings."""
        try:
            # Parse quickmove
            quickmove = self.settings["quickmove"]
            if isinstance(quickmove, str):
                quickmove = quickmove.lower() == "true"
            else:
                quickmove = bool(quickmove)

            # Get speed
            speed = self.settings["speed"]
            # Get address
            address = self.settings["address"]
            self.hal.update_internal_state(quickmove, speed, address)

        except Exception as e:
            self.logger.log_warn(f"Error updating HAL from settings: {str(e)}")

    @public
    def parse_settings_widget(self) -> tuple[int, dict]:
        """Parses the settings widget and returns settings in .ini file format."""
        try:
            quick_move = bool(self.quickmove_input.isChecked())
            speed_text = self.speed_input.currentText()
            speed = int(speed_text.split(":")[0])
            address = self.source_input.text()

            # Return settings in .ini format (same as sutter.ini)
            settings = {"address": address, "speed": speed, "quickmove": quick_move, "speed_text": speed_text}

            # Update internal settings
            self.settings.update(settings)

            # Update HAL internal state
            self.hal.update_internal_state(quick_move, speed, address)

            return [0, settings]
        except Exception as e:
            return [1, {"Error message": f"SutterGUI: {str(e)}"}]

    def _gui_change_device_connected(self, connected: bool):
        if connected:
            self.settingsWidget.connectionIndicator.setStyleSheet(self.GREEN_STYLE)

        else:
            self.settingsWidget.connectionIndicator.setStyleSheet(self.RED_STYLE)

        self.source_input.setEnabled(not connected)
        self.settingsWidget.connectButton.setText("Disconnect" if connected else "Connect")
        self.settingsWidget.basicBox.setEnabled(connected)
        self.settingsWidget.saveBox.setEnabled(connected)
        if connected:
            dev_count, dev_statuses = self.hal.get_connected_devices_status()
            self.devnum_combo.clear()
            for i in range(dev_count):
                dev_status = dev_statuses[i]
                if dev_status == 1:
                    self.devnum_combo.addItem(f"{i + 1}")

            current_dev = self.hal.get_active_device()
            self.devnum_combo.setCurrentIndex(current_dev - 1)
        else:
            self.devnum_combo.clear()
        self.cl.emit_close_lock(connected)

    # The following methods handle GUI events, but also update the internal state of the plugin.
    # kind of non-standard.
    def _quickmove_changed(self, checked: bool):
        """Called when the quickmove checkbox is changed,
        sets visibility of the speed combobox."""
        if checked:
            self.settingsWidget.speedComboBox.setEnabled(False)
        else:
            self.settingsWidget.speedComboBox.setEnabled(True)

        # Update internal settings
        self.settings["quickmove"] = checked
        self.hal.update_internal_state(checked, None, None)

    def _devnum_changed(self):
        """Called when the device number combobox is changed, sets the device number in the hal."""
        curr_text = self.devnum_combo.currentText()
        if curr_text == "":
            return
        dev_num = int(curr_text)
        self.hal.change_active_device(dev_num)

    def speed_changed(self):
        """Called when the speed combobox is changed, sets the speed in the hal."""
        speed_text = self.speed_input.currentText()
        speed = int(speed_text.split(":")[0]) if ":" in speed_text else 13

        # Update internal settings
        self.settings["speed"] = speed
        self.settings["speed_text"] = speed_text

        self.hal.update_internal_state(None, speed, None)

    ## Button functionality:

    def _connect_button(self):
        """Called when the connect button is pressed. Opens the device and sets the connection indicator color."""
        try:
            if self.hal.is_connected():
                self.hal.close()
            else:
                address = self.source_input.text()
                # Update settings with current address
                self.settings["address"] = address
                self.hal.open(address)

        except Exception as e:
            self.logger.info_popup(f"Sutter connection error: {str(e)}")

        finally:
            if self.hal.is_connected():
                self._gui_change_device_connected(True)
                # self._move_worker.start()  # Removed move worker from public API

            else:
                self._gui_change_device_connected(False)

    def _status_button(self):
        def _move_sequence():
            pos = self.hal.get_current_position()
            print(f"Current position in status button: x={pos[0]}, y={pos[1]}, z={pos[2]}")
            status, state = self.mm_move(x=0, y=0, z=0)
            print(f"status: {status}, state: {state} for zeroing move")

            status, state = self.mm_move_relative(x_change=1000, y_change=1000, z_change=1000)
            print(f"status: {status}, state: {state} for positive relative move")
            status, state = self.mm_move_relative(x_change=-1000, y_change=-1000, z_change=-1000)
            print(f"status: {status}, state: {state} for negative relative move")
            status, state = self.mm_zmove(z_change=1000, absolute=True)
            print(f"status: {status}, state: {state} for absolute z move down")
            status, state = self.mm_zmove(z_change=0, absolute=True)
            print(f"status: {status}, state: {state} for absolute z move up")
            status, state = self.mm_zmove(z_change=1000, absolute=False)
            print(f"status: {status}, state: {state} for relative z move down")
            status, state = self.mm_up_max()
            print(f"status: {status}, state: {state} for move to max z")

        def _quickmove_slowmove_check():
            pos = self.hal.get_current_position()
            print(f"Current position in quickmove/slowmove check: x={pos[0]}, y={pos[1]}, z={pos[2]}")
            initial = self.hal.quick_move
            self.hal.quick_move = True
            self.mm_move(x=pos[0] + 200, y=pos[1] + 200, z=pos[2] + 200)
            self.mm_move(x=pos[0], y=pos[1], z=pos[2])
            self.hal.quick_move = False
            self.mm_move(x=pos[0] + 200, y=pos[1] + 200, z=pos[2] + 200)
            self.mm_move(x=pos[0], y=pos[1], z=pos[2])
            self.hal.quick_move = initial

        def check_working_slow_moves_single_axis():
            import time
            import numpy as np

            # Running this shows that speeds up to 12 work when using spesified wait time between command1 and 2. When using wait time * 4 modes up to 13 work.
            for i in range(10, 16):
                n = 1000
                pos = self.hal.get_current_position()
                move_times = []
                initial = self.hal.quick_move
                self.hal.quick_move = False
                initial_speed = self.hal.speed
                self.hal.speed = i
                # move n microns, track time:
                start_time = time.perf_counter()
                self.mm_move(x=pos[0] + n)
                end_time = time.perf_counter()
                move_times.append(end_time - start_time)
                """
                start_time = time.perf_counter()
                self.mm_move(x=pos[0])
                end_time = time.perf_counter()
                move_times.append(end_time - start_time)
                """
                print(f"moved with speed {i}: {np.mean(move_times)} seconds")
                self.hal.quick_move = initial
                self.hal.speed = initial_speed
            
        def check_fast_moves():
            import time
            import numpy as np
            # Running this shows that speeds up to 12 work when using spesified wait time between command1 and 2. When using wait time * 4 modes up to 13 work.
            for i in range(12,16):
                n = 1000
                pos = self.hal.get_current_position()
                move_times = []
                initial = self.hal.quick_move
                self.hal.quick_move = False
                initial_speed = self.hal.speed
                self.hal.speed = i
                # move n microns, track time:
                start_time = time.perf_counter()
                self.mm_move(x=pos[0] + n)
                end_time = time.perf_counter()
                move_times.append(end_time - start_time)
                """
                start_time = time.perf_counter()
                self.mm_move(x=pos[0])
                end_time = time.perf_counter()
                move_times.append(end_time - start_time)
                """
                print(f"moved with speed {i}: {np.mean(move_times)} seconds")
                self.hal.quick_move = initial
                self.hal.speed = initial_speed   

        def check_working_slow_moves_multi_axis():
            import time
            import numpy as np

            # Running this shows that speeds up to 13 work.
            for i in range(16):
                pos = self.hal.get_current_position()
                move_times = []
                initial = self.hal.quick_move
                self.hal.quick_move = False
                initial_speed = self.hal.speed
                self.hal.speed = i
                # move n microns, track time:
                n = 200
                start_time = time.perf_counter()
                self.mm_move(x=pos[0] + n, y=pos[1] + n, z=pos[2] + n)
                end_time = time.perf_counter()
                move_times.append(end_time - start_time)
                start_time = time.perf_counter()
                self.mm_move(x=pos[0], y=pos[1], z=pos[2])
                end_time = time.perf_counter()
                move_times.append(end_time - start_time)
                print(f"moved with speed {i}: {np.mean(move_times)} seconds")
                self.hal.quick_move = initial
                self.hal.speed = initial_speed

        # run move sequence in a thread
        move_thread = threading.Thread(target=check_fast_moves)
        move_thread.start()

    def _stop_button(self):
        """Called when the stop button is pressed. Stops any ongoing movement."""
        try:
            status, result = self.mm_stop()
            if status == 0:
                self.logger.info_popup("Sutter movement stopped successfully")
            else:
                self.logger.info_popup(f"Stop command failed: {result.get('Error message', 'Unknown error')}")
        except Exception as e:
            self.logger.info_popup(f"Error stopping Sutter: {str(e)}")

    def _calibrate_button(self):
        self.mm_calibrate()

    ## hook functionality

    def _get_public_methods(self):
        """
        Returns a a list of public methods of the class.
        """
        return get_public_methods(self)

    ## API
    @public
    def setSettings(self, settings: dict) -> None:
        """Sets the plugin settings from the sequence builder in .ini format."""
        self.settings = copy.deepcopy(settings)
        # Update HAL internal state based on new settings
        self._update_hal_from_settings()

    @public
    def set_gui_from_settings(self) -> tuple[int, dict]:
        """Updates the GUI controls based on the internal settings."""
        try:
            self._apply_settings_to_gui()
            return (0, {"Error message": "GUI updated from settings"})
        except Exception as e:
            error_msg = f"Error updating GUI from settings: {str(e)}"
            self.logger.log_warn(error_msg)
            return (1, {"Error message": error_msg, "Exception": str(e)})

    @public
    @handle_sutter_exceptions
    def mm_open(self) -> tuple:
        """Open the device.

        Returns:
            status: tuple of (status, error message)
        """
        if self.hal.is_connected():
            return (0, {"Error message": "Sutter already connected"})
        address = self.settings.get("address", "")
        if not address:
            address = self.source_input.text()
            self.settings["address"] = address

        self.hal.open(address)
        # Update settings from GUI after successful connection
        status, parsed_settings = self.parse_settings_widget()
        if status == 0:
            self.settings.update(parsed_settings)
        self._gui_change_device_connected(self.hal.is_connected())
        return (0, {"Error message": "Sutter connected"})

    @public
    @handle_sutter_exceptions
    def mm_change_active_device(self, dev_num: int):
        """Micromanipulator active device change.

        Args:
            *args: device number (1-4)

        Returns:
            Status: tuple of (status, error message)

        """
        # commented out since this will be called from a separate thread
        # self.devnum_combo.setCurrentIndex(dev_num - 1)
        if self.hal.change_active_device(dev_num):
            return [0, {"Error message": "Sutter device changed to " + str(dev_num)}]
        return [4, {"Error message": "Sutter device change error"}]

    @public
    @handle_sutter_exceptions
    def mm_move(self, x=None, y=None, z=None):
        """Micromanipulator move.

        Args:
            x, y, z: Target coordinates. If None, the current position for that axis is maintained.
        """
        # Perform direct move
        self.hal.move(x, y, z)

        return [0, {"Error message": "Sutter moved"}]

    @public
    @handle_sutter_exceptions
    def mm_move_relative(self, x_change=0, y_change=0, z_change=0):
        """Micromanipulator move relative to the current position.

        Args:
            *args: x_change, y_change, z_change
        """
        (x, y, z) = self.hal.get_current_position()
        self.mm_move(x + x_change, y + y_change, z + z_change)
        return [0, {"Error message": "Sutter moved"}]

    @public
    @handle_sutter_exceptions
    def mm_calibrate(self, all=False):
        if not all:
            # move first in the z axis to the minimum position
            self.mm_move(z=self.hal._MINIMUM_MS)
            # finally calibrate the device
            _ = self.hal.calibrate()
            return [0, {"Error message": "Sutter calibrated"}]
        if all:
            raise NotImplementedError("Sutter calibration for all devices is not implemented yet.")

    @public
    @handle_sutter_exceptions
    def mm_stop(self) -> tuple:
        """Micromanipulator stop."""
        try:
            self.hal.stop()
            return (0, {"Error message": "Sutter stopped"})
        except Exception as e:
            return (4, {"Error message": f"Sutter stop error: {str(e)}", "Exception": str(e)})

    @public
    @handle_sutter_exceptions
    def mm_zmove(self, z_change, absolute=False) -> tuple:
        """Moves the micromanipulator in the z axis. If the move is out of bounds, it will return False.

        Args:
            z_change (float): change in z axis in micron (or absolute z position if absolute=True)
            absolute (bool): If True, z_change is treated as absolute z position

        Returns:
            status
        """
        (x, y, z) = self.hal.get_current_position()

        if absolute:
            # For absolute positioning, z_change is the target z position
            target_z = z_change
            if target_z > self.hal._MAXIMUM_M or target_z < self.hal._MINIMUM_MS:
                return (1, {"Error message": "Sutter move out of bounds"})
            self.mm_move(x, y, target_z)
            return (0, {"Error message": "Sutter moved"})
        else:
            # For relative positioning, z_change is the offset
            target_z = z + z_change
            if target_z > self.hal._MAXIMUM_M or target_z < self.hal._MINIMUM_MS:
                return (1, {"Error message": "Sutter move out of bounds"})
            self.mm_move(x, y, target_z)
            return (0, {"Error message": "Sutter moved"})

    @public
    @handle_sutter_exceptions
    def mm_get_active_device(self) -> tuple:
        """Returns the currently active device."""
        return (0, self.hal.get_active_device())

    @public
    @handle_sutter_exceptions
    def mm_up_max(self) -> tuple:
        """Moves to z = 0"""
        x, y, z = self.hal.get_current_position()
        if z == 0:
            return (0, {"Error message": "Sutter already at max"})
        self.mm_move(x, y, 0)
        return (0, {"Error message": "Sutter moved up to max"})

    @public
    @handle_sutter_exceptions
    def mm_current_position(self, manipulator_name=None):
        """Returns the current position of the micromanipulator.

        Returns:
            tuple: (x, y, z) position in microns
        """
        if manipulator_name is not None:
            old_device = self.hal.get_active_device()
            success = self.hal.change_active_device(manipulator_name)
            if not success:
                return (4, {"Error message": f"Failed to change to device {manipulator_name}"})
            pos = self.hal.get_current_position()
            self.hal.change_active_device(old_device)  # Restore previous device
        else:
            pos = self.hal.get_current_position()
        return pos

    @public
    @handle_sutter_exceptions
    def mm_devices(self):
        """Returns the number of connected devices and their statuses.

        Returns:
            tuple: (number of devices, list of device statuses)
        """
        code, status = self.mm_open()  # Ensure the device is open before fetching statuses
        if code != 0:
            return [code, status]  # Return error if opening failed
        dev_count, dev_statuses = self.hal.get_connected_devices_status()
        return [0, (dev_count, dev_statuses)]

    @public
    @handle_sutter_exceptions
    def mm_get_positions(self):
        """Returns the current positions of all manipulators.

        Returns:
            tuple: (status, positions_dict)
            dict: {device_number: (x, y, z)}
        """
        connected_devices = self.hal.get_connected_devices_status()[1]
        for i, status in enumerate(connected_devices):
            if status == 1:
                success = self.hal.change_active_device(i + 1)
                if not success:
                    return 4, {"Error message": f"Failed to change to device {i + 1}"}
                else:
                    pos = self.hal.get_current_position()
                    if pos is None:
                        return 4, {"Error message": f"Failed to get position for device {i + 1}"}
                    return 0, {i + 1: pos}

    @public
    @handle_sutter_exceptions
    def mm_get_num_manipulators(self):
        """
        Get the total number of manipulators available.

        Returns:
            int: Number of manipulators
        """
        dev_count, _ = self.hal.get_connected_devices_status()
        return dev_count

    @public
    @handle_sutter_exceptions
    def mm_slow_move(self, x=None, y=None, z=None):
        """Micromanipulator slow move (for testing stop functionality).

        Args:
            x, y, z: Target coordinates. If None, the current position for that axis is maintained.
        """
        if x is None and y is None and z is None:
            return [1, {"Error message": "Sutter slow move requires at least one coordinate"}]
        if x is None:
            x = self.hal.get_current_position()[0]
        if y is None:
            y = self.hal.get_current_position()[1]
        if z is None:
            z = self.hal.get_current_position()[2]
        self.hal.slow_move_to(x, y, z, 7)
        return [0, {"Error message": "Sutter moved"}]
