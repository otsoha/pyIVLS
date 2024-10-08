"""Module for the MPC-325 abstraction layer


"""

import struct  # Handling binary
import time  # for device-spesified wait-times
from typing import Final  # for constants
import serial  # Accessing sutter device through serial port
import numpy as np  # for better typing
import os

from PyQt6 import uic
from PyQt6 import QtWidgets
from PyQt6.QtCore import QObject
import pyIVLS_constants as const


class Mpc325:
    """Handles communication with the Sutter MPC-325 micromanipulator system.
    Methods are named after the commands in the manual.
    """

    # constants from the manual. These the the same for the whole class
    # move speeds in micrometers per second
    _MOVE_SPEEDS: Final = {
        15: 1300,
        14: 1218.75,
        13: 1137.5,
        12: 1056.25,
        11: 975,
        10: 893.75,
        9: 812.5,
        8: 731.25,
        7: 650,
        6: 568.75,
        5: 487.5,
        4: 406.25,
        3: 325,
        2: 243.75,
        1: 162.5,
        0: 81.25,
    }
    _BAUDRATE: Final = 128000
    _TIMEOUT = 30  # seconds
    _DATABITS: Final = serial.EIGHTBITS
    _STOPBITS: Final = serial.STOPBITS_ONE
    _PARITY: Final = serial.PARITY_NONE
    _S2MCONV: Final = np.float64(0.0625)
    _M2SCONV: Final = np.float64(16.0)
    _MINIMUM_MS: Final = 0
    _MAXIMUM_M: Final = 25000
    _MAXIMUM_S: Final = 400000  # Manual says 266667, this is the actual maximum.

    def __init__(self):
        # vars for a single instance
        self.port = const.SUTTER_DEFAULT_PORT
        self.ser = serial.Serial()  # init a closed port
        # Initialize settings:
        self.quick_move = False
        self.speed = 1

        # Load the settings based on the name of this file.
        self.path = os.path.dirname(__file__) + os.path.sep
        filename = (
            os.path.splitext(os.path.basename(__file__))[0] + "_settingsWidget.ui"
        )
        self.settingsWidget = uic.loadUi(self.path + filename)

        # initialize labels that might be modified:
        self.port_label = self.settingsWidget.findChild(
            QtWidgets.QLabel, "connectionLabel"
        )
        self.status_label = self.settingsWidget.findChild(
            QtWidgets.QLabel, "statusLabel"
        )

    # Close the connection when python garbage collection gets around to it.
    def __del__(self):
        if self.ser.is_open:
            self.ser.close()

    # FIXME: add a check that tests if the port is already open
    def open(self):
        # Open port
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self._BAUDRATE,
                stopbits=self._STOPBITS,
                parity=self._PARITY,
                timeout=self._TIMEOUT,
                bytesize=self._DATABITS,
            )
            print(
                f"Port {self.port} is open: {self.ser.is_open}. Flushing I/O to initialize micromanipulators."
            )
            self._flush()
            return True
        except serial.SerialException as e:
            return False

    def close(self):
        if self.ser.is_open:
            self.ser.close()
            print(f"Port {self.port} is closed: {self.ser.is_open}")

    def _validate_and_unpack(self, format_str, output):
        """Takes in a struct of bytes, validates end marker and unpacks the data.
        Handles possible errors for the whole code.

        Args:
            format (str): format string for struct
            output (): bytes recieved from serial port

        Returns:
           Tuple : unpacked data based on format, without the end marker. If end marker is invalid, returns [-1, -1, -1, -1, -1, -1].
        """
        unpacked_data = struct.unpack(format_str, output)
        # Check last byte for simple validation.
        if unpacked_data[-1] != 0x0D:
            print(
                f"Invalid end marker sent from device. Expected 0x0D, got {unpacked_data[-1]}. Flushing buffers."
            )
            self._flush()
            return [-1, -1, -1, -1, -1, -1]  # Return error code
        else:
            return unpacked_data[:-1]

    def _flush(self):
        """Flushes i/o buffers. Also applies a wait time between commands. Every method should call this before sending a command."""
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(
            0.002
        )  # Hardcoded wait time (2 ms) between commands from the manual.
        # FIXME: made it 20 ms for testing

    def get_connected_devices_status(self):
        """Get the status of connected micromanipulators

        Returns:
            tuple: first element is how many devices connected, second element is a list representing
            the status of connected devices
        """
        self._flush()
        self.ser.write(bytes([85]))  # Send command to the device (ASCII: U)
        output = self.ser.read(6)

        unpacked_data = self._validate_and_unpack("6B", output)
        num_devices = unpacked_data[0]  # Number of devices connected
        device_statuses = unpacked_data[1:5]  # Status of each device (0 or 1)

        return (num_devices, device_statuses)

    def get_active_device(self):
        """Returns the current active device.

        Returns:
            int: active device number
        """
        self._flush()
        self.ser.write(bytes([75]))  # Send command to the device (ASCII: K)
        output = self.ser.read(4)
        unpacked = self._validate_and_unpack("4B", output)
        return unpacked[0]

    def change_active_device(self, dev_num: int):
        """Change active device

        Args:
            devNum (int): Device number to be activated (1-4 on this system)

        Returns:
            bool: Change successful
        """
        self._flush()
        command = struct.pack("<2B", 73, dev_num)
        self.ser.write(command)  # Send command to the device (ASCII: I )

        output = self.ser.read(2)
        unpacked = self._validate_and_unpack("2B", output)
        if unpacked[0] == 69:  # If error
            return False
        return True

    def get_current_position(self):
        """Get current position in microns.

        Returns:
            tuple: (x,y,z)
        """
        self._flush()
        self.ser.write(bytes([67]))  # Send command (ASCII: C)
        output = self.ser.read(14)
        unpacked = self._validate_and_unpack("=BIIIB", output)

        return (self._s2m(unpacked[1]), self._s2m(unpacked[2]), self._s2m(unpacked[3]))

    def calibrate(self):
        """Calibrate the device. Does the same thing as the calibrate button on the back of the control unit.
        (moves to 0,0,0)
        """
        if self.ser.is_open:
            self._flush()
            self.ser.write(bytes([78]))  # Send command (ASCII: N)
            output = self.ser.read(1)
            self._validate_and_unpack("B", output)

    def quick_move_to(self, x: np.float64, y: np.float64, z: np.float64):
        """Quickmove orthogonally at full speed.

        Args:
            x (np.float64): x in microns
            y (np.float64): y in microns
            z (np.float64): z in microns
        """
        self._flush()
        # Pack first part of command
        command1 = struct.pack("<B", 77)
        # check bounds for coordinates and convert to microsteps. Makes really *really* sure that the values are good.
        x_s = self._handrail_step(self._m2s(self._handrail_micron(x)))
        y_s = self._handrail_step(self._m2s(self._handrail_micron(y)))
        z_s = self._handrail_step(self._m2s(self._handrail_micron(z)))
        wait_time = self._calculate_wait_time(
            15, self._s2m(x_s), self._s2m(y_s), self._s2m(z_s)
        )
        print(
            f"Moving to: ({self._s2m(x_s)}, {self._s2m(y_s)}, {self._s2m(z_s)}) in microns.\npredicted move time: {wait_time} seconds."
        )

        command2 = struct.pack(
            "<3I", x_s, y_s, z_s
        )  # < to enforce little endianness. Just in case someone tries to run this on an IBM S/360
        command3 = struct.pack("<B", 13)

        self.ser.write(command1)
        self.ser.write(command2)
        self.ser.write(command3)

        time.sleep(wait_time)  # wait for the move to finish
        output = self.ser.read(1)
        self._validate_and_unpack("B", output)

    def slow_move_to(self, x: np.float64, y: np.float64, z: np.float64, speed=None):
        """Slower move in straight lines. Speed is set as a class variable. (Or given as an argument)

        Args:
            speed (int): speed in range 0-15. Enforced in the code.
            x (np.float64): x in microns
            y (np.float64): y in microns
            z (np.float64): z in microns

        """
        if speed is None:
            speed = self.speed
        self._flush()
        # Enforce speed limits
        speed = max(0, min(speed, 15))

        # Pack first part of command
        command1 = struct.pack("<2B", 83, speed)
        # check bounds for coordinates and convert to microsteps. Makes really *really* sure that the values are good.
        x_s = self._handrail_step(self._m2s(self._handrail_micron(x)))
        y_s = self._handrail_step(self._m2s(self._handrail_micron(y)))
        z_s = self._handrail_step(self._m2s(self._handrail_micron(z)))
        wait_time = self._calculate_wait_time(
            speed, self._s2m(x_s), self._s2m(y_s), self._s2m(z_s)
        )

        print(
            f"Moving to: ({self._s2m(x_s)}, {self._s2m(y_s)}, {self._s2m(z_s)}) in microns.\npredicted move time: {wait_time} seconds."
        )

        command2 = struct.pack(
            "<3I", x_s, y_s, z_s
        )  # < to enforce little endianness. Just in case someone tries to run this on an IBM S/360

        self.ser.write(command1)
        time.sleep(0.03)  # wait period specified in the manual (30 ms)
        self.ser.write(command2)
        time.sleep(wait_time)  # wait for the move to finish
        output = self.ser.read(1)
        self._validate_and_unpack("B", output)

    def stop(self):
        """Stop the current movement"""
        self._flush()
        self.ser.write(bytes([3]))  # Send command (ASCII: <ETX>)
        output = self.ser.read(1)
        self._validate_and_unpack("B", output)

    def move(self, x, y, z):
        """Move to a position. If quick_move is set to True, the movement will be at full speed.

        Args:
            x (np.float64): x in microns
            y (np.float64): y in microns
            z (np.float64): z in microns
        """
        if self.quick_move:
            return self.quick_move_to(x, y, z)
        else:
            return self.slow_move_to(x, y, z)

    def parse_settings_widget(self):
        """Parses the settings widget and sets the values in the class."""

        quick_move = self.settingsWidget.findChild(QtWidgets.QCheckBox, "quickBox")
        if quick_move.isChecked():
            self.quick_move = True

        speed = self.settingsWidget.findChild(QtWidgets.QSlider, "speedSlider")
        self.speed = speed.value()

        source = self.settingsWidget.findChild(QtWidgets.QLineEdit, "sourceInput")
        self._port = source.text()

    ## Button functionality:

    def connect_button(self):
        self.parse_settings_widget()
        if self.open():
            self.port_label.setText(f"Connected to {self._port}")
        else:
            self.port_label.setText(f"Failed to connect to {self._port}")

    def status_button(self):
        if self.ser.is_open:
            num_devices, device_statuses = self.get_connected_devices_status()
            self.status_label.setText(
                f"Connected devices: {num_devices}\nStatus: {device_statuses}"
            )
        else:
            self.status_label.setText("Not connected")

    def save_button(self):
        self.parse_settings_widget()
        self.status_label.setText("Settings saved.")

    # Handrails for microns/microsteps. Realistically would be enough just to check the microsteps, but CATCH ME LETTING A MISTAKE BREAK THESE
    def _handrail_micron(self, microns) -> np.uint32:
        return max(self._MINIMUM_MS, min(microns, self._MAXIMUM_M))

    def _handrail_step(self, steps) -> np.uint32:
        return max(self._MINIMUM_MS, min(steps, self._MAXIMUM_S))

    # Function to convert microns to microsteps.
    def _m2s(self, microns: np.float64) -> np.uint32:
        return np.uint32(microns * self._M2SCONV)

    # Function to convert microsteps to microns.
    def _s2m(self, steps: np.uint32) -> np.float64:
        return np.float64(steps * self._S2MCONV)

    def _calculate_wait_time(self, speed, x, y, z):
        """Approximates time of travel. NOTE: make sure to pass microns, not microsteps to this

        Args:
            speed (int): speed
            x (_type_): x target in microns
            y (_type_): y target in microns
            z (_type_): z target in microns

        Returns:
            _type_: move speed in seconds
        """
        curr_pos = self.get_current_position()
        x_diff = abs(curr_pos[0] - x)
        y_diff = abs(curr_pos[1] - y)
        z_diff = abs(curr_pos[2] - z)

        total_diff = x_diff + y_diff + z_diff

        time = total_diff / self._MOVE_SPEEDS[speed]
        return time
