"""
Using composition instead of multiple inheritance,
mostly because this is similar to the existing implementations.
The added benefit is that classes don't need to inherit from QObject,
since that is handled by the logger that actually uses QObject functionality.

Core ideas:
- plugin functionality implemented in a low level class that works by itself. The low level should not use the components in this file.
    - low level class should raise exceptions on errors? The errors are caught by the plugin GUI class.
- plugin GUI functionality implemented in a separate class that uses the low level class. The plugin GUI class can use these components.
    - GUIs should not raise exceptions(?), but return PyIVLSReturn objects. This allows for handling inter-plugin errors in a standardized way.
- plugins currently don't inherit from any base class nor from QObject. I would prefer to keep it that way and offload all qt-related functionality to components.
This also helps in keeping the GUI implementation relatively clean.
- Most of the common functionality should be moved to a component, since:
    1. Reduce repetitive code, make it easier to maintain with a single point of change (not rewriting all plugins on all changes)
    2. Make it easier to implement new plugins, since the common functionality is already implemented
    3. Way way way easier to test the components than all plugins by themselves.
-IDEA: if the plugin returns something, it should not also log. so no returns like this:
    self.logger.log_info("Something happened")
    return PyIVLSReturn.success({"what happened": "something"})
since this would lead to double logging.

This file includes:
- ConnectionIndicatorStyle: Enum for connection indicator styles
- CloseLockSignalProvider: Component to provide closelock signal functionality without QObject inheritance
- public: Decorator to mark a function as public in the plugin system. Also checks that the return type is annotated correctly.
- PyIVLSReturnCode: Enum for standard return codes for pyIVLS plugins.

- PyIVLSReturn: Class providing a standardized way to handle returns across all plugin GUIs while maintaining full backward compatibility with the existing [status, data] tuple pattern.
this is still w.i.p, but in my opinion this could simplify the codebase. Some legacy plugins return [status, data] lists instead of tuples, so some standardization will be needed in any case.
I think it would be the most intuitive to use a class for this, since the current format is not very intuitive. e.g:
status, data = plugin.try_something()
if status:
    logger.log(data["error message"])
else:
    good_value = data
when unpacking, the data could be anything and contain any keys. lots of room for error.

- is_success: Function to check if a return value indicates success, works with both new and legacy formats.
- get_error_message: Function to extract error message from return value, works with both new and legacy formats.
- FileManager: Class for handling file operations for plugins, including creating headers for CSV files and spectrometer files.
- GuiMapper: Class for getting/setting values from the GUI
- DependencyManager: Class to handle dependencies between plugins, including checking for missing dependencies and handling dependency-related GUI changes
- LoggingHelper: Class for logging messages with different severity levels
- SMUHelper: I don't know what this is yet.


"""

import sys
import traceback
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox, QWidget
from dataclasses import dataclass

class ConnectionIndicatorStyle(Enum):
    """Enum for connection indicator styles."""

    GREEN_CONNECTED = "border-radius: 10px; background-color: rgb(38, 162, 105); min-height: 20px; min-width: 20px;"
    RED_DISCONNECTED = "border-radius: 10px; background-color: rgb(165, 29, 45); min-height: 20px; min-width: 20px;"


class CloseLockSignalProvider(QObject):
    """Component to provide closelock signal functionality without QObject inheritance."""

    closeLock = pyqtSignal(bool)

    def __init__(self):
        super().__init__()

    def emit_close_lock(self, locked: bool):
        """Emit the close lock signal."""
        self.closeLock.emit(locked)


def public(func):
    """Decorator to mark a function as public in the plugin system. Also checks that the return type is annotated correctly.
    HOX: this does not enforce anything but that the annotation is correct. The user can still return anything, but any IDE or linter should at least warn the developer about it.
    """
    # currently enforcement of the return type is not active.
    """
    expected_type = PyIVLSReturn
    sig = inspect.signature(func)

    assert sig.return_annotation == expected_type, f"Function '{func.__name__}' must have return type annotation {expected_type}, but got {sig.return_annotation}"
    """
    func._is_public = True
    return func


def get_public_methods(obj) -> Dict:
    """
    Get a dict of public methods in an object instance that are marked with the @public decorator.

    Args:
        obj: Object instance to inspect

    Returns:
        Dict of method names to their callable objects
    """
    return {
        name: getattr(obj, name)
        for name in dir(obj)
        if callable(getattr(obj, name, None)) and getattr(getattr(obj, name, None), "_is_public", False)
    }


class PyIVLSReturnCode(Enum):
    """Standard return codes for pyIVLS plugins."""

    SUCCESS = 0
    VALUE_ERROR = 1
    DEPENDENCY_ERROR = 2
    MISSING_DEPENDENCY = 3
    HARDWARE_ERROR = 4
    THREAD_STOPPED = 5
    # add more if needed, also add a factory method for each new code

#unused
@dataclass
class KeithleySettings:
    source: str
    drain: str
    type: str
    sourcesense: bool
    drainsense: bool
    single_ch: bool
    pulse: bool
    pulsepause: float
    sourcenplc: float
    drainnplc: float
    delay: bool
    delayduration: float
    draindelay: bool
    draindelayduration: float
    steps: int
    start: float
    end: float
    limit: float
    sourcehighc: bool
    drainhighc: bool
    repeat: int
    drainvoltage: float
    drainlimit: float

    def _check_types(self):
        if not isinstance(self.source, str):
            raise TypeError("Source must be a string")
        if not isinstance(self.drain, str):
            raise TypeError("Drain must be a string")
        if not isinstance(self.type, str):
            raise TypeError("Type must be a string")
        if not isinstance(self.sourcesense, bool):
            raise TypeError("Source sense must be a boolean")
        if not isinstance(self.drainsense, bool):
            raise TypeError("Drain sense must be a boolean")
        if not isinstance(self.single_ch, bool):
            raise TypeError("Single channel must be a boolean")
        if not isinstance(self.pulse, bool):
            raise TypeError("Pulse must be a boolean")
        if not isinstance(self.pulsepause, (int, float)):
            raise TypeError("Pulse pause must be a number")
        if not isinstance(self.sourcenplc, (int, float)):
            raise TypeError("Source NPLC must be a number")
        if not isinstance(self.drainnplc, (int, float)):
            raise TypeError("Drain NPLC must be a number")
        if not isinstance(self.delay, bool):
            raise TypeError("Delay must be a boolean")
        if not isinstance(self.delayduration, (int, float)):
            raise TypeError("Delay duration must be a number")
        if not isinstance(self.draindelay, bool):
            raise TypeError("Drain delay must be a boolean")
        if not isinstance(self.draindelayduration, (int, float)):
            raise TypeError("Drain delay duration must be a number")
        if not isinstance(self.steps, int):
            raise TypeError("Steps must be an integer")
        if not isinstance(self.start, (int, float)):
            raise TypeError("Start value must be a number")
        if not isinstance(self.end, (int, float)):
            raise TypeError("End value must be a number")
        if not isinstance(self.limit, (int, float)):
            raise TypeError("Limit must be a number")
        if not isinstance(self.sourcehighc, bool):
            raise TypeError("Source high C must be a boolean")
        if not isinstance(self.drainhighc, bool):
            raise TypeError("Drain high C must be a boolean")
        if not isinstance(self.repeat, int):
            raise TypeError("Repeat count must be an integer")
        if not isinstance(self.drainvoltage, float):
            raise TypeError("Drain voltage must be a number")
        if not isinstance(self.drainlimit, float):
            raise TypeError("Drain limit must be a number")

    def validate(self):
        self._check_types()
        if self.source not in ["smua", "smub"]:
            raise ValueError("Source must be 'smua' or 'smub'")
        if self.drain not in ["smua", "smub"]:
            raise ValueError("Drain must be 'smua' or 'smub'")
        if self.type not in ["i", "v"]:
            raise ValueError("Type must be 'i' or 'v'")
        if self.steps <= 0:
            raise ValueError("Steps must be a positive integer")
        if self.limit <= 0:
            raise ValueError("Limit must be a positive number")
        if self.sourcenplc <= 0:
            raise ValueError("Source NPLC must be a positive number")
        if self.drainnplc <= 0:
            raise ValueError("Drain NPLC must be a positive number")
        if self.delay and self.delayduration < 0:
            raise ValueError("Delay duration must be non-negative")
        if self.draindelay and self.draindelayduration < 0:
            raise ValueError("Drain delay duration must be non-negative")
        if self.repeat <= 0:
            raise ValueError("Repeat count must be a positive integer")
        if self.pulse and self.pulsepause < 0:
            raise ValueError("Pulse pause duration must be non-negative")
        if self.single_ch and self.drain != "voltage":
            raise ValueError("In single channel mode, drain must be set to 'voltage'")
        
    def __post_init__(self):
        self.validate()
class PyIVLSReturn:
    """
    This class provides a standardized way to handle returns across all plugin (GUIs, since the ll-implementation should be stand-alone) while
    maintaining full backward compatibility with the existing [status, data] tuple pattern.
    TODO:
    - add a field for the exception that was raised instead of just the exception as a str. Might help future debugging.
    (To be fair, this would just be reinventing the exception wheel again. )
    """

    def __init__(self, code: PyIVLSReturnCode, data: Dict[str, Any]):
        """
        Initialize return object. Use class methods for construction instead.

        Args:
            code: PyIVLSReturnCode enum value
            data: Dictionary containing return data or error information
        """
        self._code = code
        self._data = data.copy() if data else {}

    @property
    def code(self) -> PyIVLSReturnCode:
        """Get the return code enum."""
        return self._code

    @property
    def status_code(self) -> int:
        """Get the numeric status code"""
        return self._code.value

    @property
    def data(self) -> Dict[str, Any]:
        """Get the return data dictionary."""
        return self._data.copy()

    @property
    def is_success(self) -> bool:
        """Check if the operation was successful."""
        return self._code == PyIVLSReturnCode.SUCCESS

    @property
    def is_error(self) -> bool:
        """Check if the operation failed."""
        return not self.is_success

    @property
    def error_message(self) -> str:
        """Get error message if present, empty string otherwise."""
        return self._data.get("Error message", "")

    def to_tuple(self) -> Tuple[int, Dict[str, Any]]:
        """Convert to legacy tuple format"""
        return (self._code.value, self._data.copy())

    def get_data_value(self, key: str, default: Any = None) -> Any:
        """Safely get a value from the data dictionary."""
        return self._data.get(key, default)

    def has_data_key(self, key: str) -> bool:
        """Check if a specific key exists in the data."""
        return key in self._data

    # Factory methods for creating returns
    @classmethod
    def success(cls, data: Optional[Dict[str, Any]] = None) -> "PyIVLSReturn":
        """
        Create a successful return.

        Args:
            data: Optional dictionary containing return data

        Returns:
            PyIVLSReturn object indicating success

        """
        return cls(PyIVLSReturnCode.SUCCESS, data or {})

    @classmethod
    def value_error(cls, message: str, plugin_name: str, **extra_data) -> "PyIVLSReturn":
        """
        Create a value error return with standardized formatting.

        Args:
            message: Error description
            plugin_name: Name of the plugin reporting the error
            **extra_data: Additional data to include in return

        Returns:
            PyIVLSReturn object indicating value error

        """
        error_msg = f"Value error in {plugin_name}: {message}"
        data = {"Error message": error_msg}
        data.update(extra_data)
        return cls(PyIVLSReturnCode.VALUE_ERROR, data)

    @classmethod
    def dependency_error(cls, error_data: Dict[str, Any]) -> "PyIVLSReturn":
        """
        Forward an error from a dependency plugin.

        Args:
            error_data: Error dictionary from dependency plugin

        Returns:
            PyIVLSReturn object indicating dependency error

        """
        return cls(PyIVLSReturnCode.DEPENDENCY_ERROR, error_data)

    @classmethod
    def missing_dependency(
        cls, message: str, missing_functions: Optional[List[str]] = None, **extra_data
    ) -> "PyIVLSReturn":
        """
        Create a missing dependency return.

        Args:
            message: Error description
            missing_functions: Optional list of missing function names
            **extra_data: Additional data to include in return

        Returns:
            PyIVLSReturn object indicating missing dependency

        """
        data = {"Error message": message}
        if missing_functions:
            data["Missing functions"] = missing_functions
        data.update(extra_data)
        return cls(PyIVLSReturnCode.MISSING_DEPENDENCY, data)

    @classmethod
    def hardware_error(cls, message: str, plugin_name: str, **extra_data) -> "PyIVLSReturn":
        """
        Create a hardware error return with standardized formatting.

        Args:
            message: Error description
            plugin_name: Name of the plugin reporting the error
            **extra_data: Additional data to include in return

        Returns:
            PyIVLSReturn object indicating hardware error

        """
        error_msg = f"Hardware error in {plugin_name}: {message}"
        data = {"Error message": error_msg}
        data.update(extra_data)
        return cls(PyIVLSReturnCode.HARDWARE_ERROR, data)

    @classmethod
    def custom_error(cls, code: PyIVLSReturnCode, message: str, plugin_name: str = "", **extra_data) -> "PyIVLSReturn":
        """
        Create a custom error with any return code and additional data.

        Args:
            code: PyIVLSReturnCode enum value
            message: Error description
            plugin_name: Optional plugin name to include in message
            **extra_data: Additional data to include in return

        Returns:
            PyIVLSReturn object with custom error
        """
        if plugin_name:
            formatted_message = f"{plugin_name}: {message}"
        else:
            formatted_message = message

        data = {"Error message": formatted_message}
        data.update(extra_data)
        return cls(code, data)

    @classmethod
    def from_tuple(cls, tup: Tuple[int, Dict[str, Any]]) -> "PyIVLSReturn":
        """
        Create PyIVLSReturn from legacy tuple format.

        Args:
            tup: Legacy tuple in format (status_code, data_dict)

        Returns:
            PyIVLSReturn object

        Examples:
            legacy_return = (1, {"Error message": "Some error"})
            result = PyIVLSReturn.from_tuple(legacy_return)
        """
        status_code, data = tup
        code = PyIVLSReturnCode(status_code)
        return cls(code, data)

    # Operator overloading for convenience
    def __bool__(self) -> bool:
        """Allow truthiness checking: if result: ..."""
        return self.is_success

    def __iter__(self):
        """Allow tuple unpacking: status, data = result"""
        return iter((self._code.value, self._data.copy()))

    def __str__(self) -> str:
        """Human-readable string representation."""
        if self.is_success:
            return f"Success: {self._data}"
        else:
            return f"Error ({self._code.name}): {self.error_message}"

    def __getitem__(self, key):
        """Allow dict-like access for backward compatibility: info['Error message']"""
        return self._data[key]


# Utility functions for working with returns
def is_success(return_value: Union[PyIVLSReturn, Tuple[int, Dict[str, Any]]]) -> bool:
    """
    Check if a return value indicates success, works with both new and legacy formats.

    Args:
        return_value: Either PyIVLSReturn object or legacy tuple

    Returns:
        bool: True if successful

    Examples:
        if is_success(plugin_result):
            process_data(...)
    """
    if isinstance(return_value, PyIVLSReturn):
        return return_value.is_success
    elif isinstance(return_value, tuple) and len(return_value) == 2:
        return return_value[0] == 0
    return False


def get_error_message(return_value: Union[PyIVLSReturn, Tuple[int, Dict[str, Any]]]) -> str:
    """
    Extract error message from return value, works with both new and legacy formats.

    Args:
        return_value: Either PyIVLSReturn object or legacy tuple

    Returns:
        str: Error message or empty string if no error

    Examples:
        if not is_success(result):
            logger.error(get_error_message(result))
    """
    if isinstance(return_value, PyIVLSReturn):
        return return_value.error_message
    elif isinstance(return_value, tuple) and len(return_value) == 2:
        return return_value[1].get("Error message", "")
    return ""


class FileManager:
    """Handles file operations for plugins."""

    @staticmethod
    def create_file_header(settings: Dict[str, Any], smu_settings: Dict[str, Any]) -> str:
        """
        creates a header for the csv file in the old measuremnt system style

        input	smu_settings dictionary for Keithley2612GUI.py class (see Keithley2612BGUI.py)
            settings dictionary for the sweep plugin

        str containing the header

        """

        ## header may not be optimal, this is because it should repeat the structure of the headers produced by the old measurement station
        comment = "#####################"
        if settings["samplename"] == "":
            comment = f"{comment}\n#\n# measurement of {{noname}}\n#\n#"
        else:
            comment = f"{comment}\n#\n# measurement of {settings['samplename']}\n#\n#"
        comment = f"{comment}date {datetime.now().strftime('%d-%b-%Y, %H:%M:%S')}\n#"
        comment = f"{comment}Keithley source {settings['channel']}\n#"
        comment = f"{comment}Source in {settings['inject']} injection mode\n#"
        if settings["inject"] == "voltage":
            stepunit = "V"
            limitunit = "A"
        else:
            stepunit = "A"
            limitunit = "V"
        comment = f"{comment}\n#\n#"
        comment = f"{comment}Set value for time check {settings['sourcevalue']} {stepunit}\n#"
        comment = f"{comment}\n#"
        comment = f"{comment}Limit for step {settings['sourcelimit']} {limitunit}\n#"
        if settings["sourcedelaymode"] == "auto":
            comment = f"{comment}Measurement acquisition period is done in AUTO mode\n#"
        else:
            comment = f"{comment}Measurement stabilization period is {settings['sourcedelay'] / 1000} ms\n#"
        comment = f"{comment}NPLC value {settings['sourcenplc'] * 1000 / smu_settings['lineFrequency']} ms (for detected line frequency {smu_settings['lineFrequency']} Hz is {settings['sourcenplc']})\n#"
        comment = f"{comment}\n#\n#"
        comment = f"{comment}Continuous operation of the source with step time settings['timestep'] \n#\n#\n#"

        if not settings["singlechannel"]:
            comment = f"{comment}Drain in {settings['draininject']} injection mode\n#"
            if settings["draininject"] == "voltage":
                stepunit = "V"
                limitunit = "A"
            else:
                stepunit = "A"
                limitunit = "V"
            comment = f"{comment}Set value for drain {settings['drainvalue']} {stepunit}\n#"
            comment = f"{comment}Limit for drain {settings['drainlimit']} {limitunit}\n#"
            if settings["draindelaymode"] == "auto":
                comment = f"{comment}Measurement acquisition period for drain is done in AUTO mode\n#"
            else:
                comment = (
                    f"{comment}Measurement stabilization period for drain is {settings['draindelay'] / 1000} ms\n#"
                )
            comment = f"{comment}NPLC value {settings['drainnplc'] * 1000 / smu_settings['lineFrequency']} ms (for detected line frequency {smu_settings['lineFrequency']} Hz is {settings['drainnplc']})\n#"
        else:
            comment = f"{comment}\n#\n#\n#\n#\n#"

        comment = f"{comment}\n#"
        comment = f"{comment}Comment: {settings['comment']}\n#"
        comment = f"{comment}\n#"

        comment = f"{comment}\n#\n#\n#"

        if smu_settings["sourcehighc"]:
            comment = f"{comment}Source in high capacitance mode"
        else:
            comment = f"{comment}Source not in HighC mode (normal operation)"
        if not settings["singlechannel"]:
            if smu_settings["drainhighc"]:
                comment = f"{comment}. Drain in high capacitance mode\n#"
            else:
                comment = f"{comment}. Drain not in HighC mode (normal operation)\n#"
        else:
            comment = f"{comment}\n#"

        comment = f"{comment}\n#\n#\n#\n#\n#\n#\n#\n#\n#"

        if settings["stoptimer"]:
            comment = f"{comment}Timer set for {settings['stopafter']} minutes\n#"
        else:
            comment = f"{comment}\n#"

        if settings["sourcesensemode"] == "2 wire":
            comment = f"{comment}Sourse in 2 point measurement mode\n#"
        elif settings["sourcesensemode"] == "4 wire":
            comment = f"{comment}Sourse in 4 point measurement mode\n#"
        if not (settings["singlechannel"]):
            if settings["drainsensemode"] == "2 wire":
                comment = f"{comment}Drain in 2 point measurement mode\n"
            elif settings["drainsensemode"] == "4 wire":
                comment = f"{comment}Drain in 4 point measurement mode\n"
        else:
            comment = f"{comment}\n"

        if settings["singlechannel"]:
            comment = f"{comment}stime, IS, VS"
        else:
            comment = f"{comment}stime, IS, VS, ID, VD"

        return comment

    @staticmethod
    def create_spectrometer_header(varDict: Optional[Dict[str, Any]] = None, separator: str = ";") -> str:
        """
        Creates a header for spectrometer files following Thorlabs software structure.

        Args:
            varDict: Dictionary containing spectrometer metadata
                    - 'average': int, averaging count
                    - 'integrationtime': float, integration time in seconds
                    - 'triggermode': int, external trigger = 1 / internal = 0
                    - 'name': str, sample name
                    - 'comment': str, comment
                    - 'timestamp': float, optional timestamp
            separator: Field separator character

        Returns:
            str: Formatted header string
        """
        if varDict is None:
            varDict = {}

        comment = "Thorlabs FTS operated by pyIVSL\n"
        comment = f"{comment}#[SpectrumHeader]\n"
        comment = f"{comment}Date{separator}{datetime.now().strftime('%Y%m%d')}\n"
        comment = f"{comment}Time{separator}{datetime.now().strftime('%H%M%S%f')[:-4]}\n"
        comment = f"{comment}GMTTime{separator}{datetime.utcnow().strftime('%H%M%S%f')[:-4]}\n"
        comment = f"{comment}XAxisUnit{separator}nm_air\n"
        comment = f"{comment}YAxisUnit{separator}intensity\n"

        if "average" in varDict:
            comment = f"{comment}Average{separator}{varDict['average']}\n"
        else:
            comment = f"{comment}Average{separator}0\n"

        comment = f"{comment}RollingAverage{separator}0\n"
        comment = f"{comment}SpectrumSmooth{separator}0\n"
        comment = f"{comment}SSmoothParam1{separator}0\n"
        comment = f"{comment}SSmoothParam2{separator}0\n"
        comment = f"{comment}SSmoothParam3{separator}0\n"
        comment = f"{comment}SSmoothParam4{separator}0\n"
        comment = f"{comment}IntegrationTime{separator}{varDict.get('integrationtime', 0)}\n"
        comment = f"{comment}TriggerMode{separator}{varDict.get('triggermode', 0)}\n"
        comment = f"{comment}InterferometerSerial{separator}M00903839\n"
        comment = f"{comment}Source\n"
        comment = f"{comment}AirMeasureOpt{separator}0\n"
        comment = f"{comment}WnrMin{separator}0\n"
        comment = f"{comment}WnrMax{separator}0\n"
        comment = f"{comment}Length{separator}3648\n"
        comment = f"{comment}Resolution{separator}0\n"
        comment = f"{comment}ADC{separator}0\n"
        comment = f"{comment}Instrument{separator}0\n"
        comment = f"{comment}Model{separator}CCS175\n"
        comment = f"{comment}Type{separator}emission\n"
        comment = f"{comment}AirTemp{separator}0\n"
        comment = f"{comment}AirPressure{separator}0\n"
        comment = f"{comment}AirRelHum{separator}0\n"

        if "name" in varDict:
            comment = f"{comment}Name{separator}{varDict['name']}\n"
        else:
            comment = f"{comment}Name{separator}\n"

        if "comment" in varDict:
            comment = f'{comment}Comment{separator}"{varDict["comment"]}"\n'
        else:
            comment = f'{comment}Comment{separator} ""\n'

        # Add timestamp if provided
        if "timestamp" in varDict:
            comment = f"{comment}Timestamp{separator}{varDict['timestamp']}\n"

        comment = f"{comment}#[Data]\n"
        return comment

    @staticmethod
    def get_address() -> str:
        """Returns the address of the SMU device."""
        return "Not implemented"


class GuiMapper(QObject):
    """Enhanced GUI field mapper with dynamic type detection and bidirectional conversion."""

    update_gui = pyqtSignal(dict, dict, dict)

    def __init__(self, widget, plugin_name):
        super().__init__()
        self.widget: QWidget = widget
        self.plugin_name: str = plugin_name
        self.update_gui.connect(self.set_values)

    def get_values(
        self, field_mapping: Dict[str, str], validation_rules: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> PyIVLSReturn:
        """Extract values from GUI widgets with dynamic type detection.

        Args:
            field_mapping: Dict mapping setting names to widget attribute names
                          {"setting_name": "widget_attribute_name"}
            validation_rules: Optional validation rules for each setting
                            {"setting_name": {"required": True, "validator": lambda x: x > 0}}

        Returns:
            PyIVLSReturn: Success with data dict or error with message
        """
        result = {}
        validation_rules = validation_rules or {}

        for setting_name, widget_name in field_mapping.items():
            try:
                # Get the widget
                widget_obj = getattr(self.widget, widget_name)

                # Dynamically determine type and extract value
                value = self._extract_value_dynamic(widget_obj)
                # Apply validation if specified
                if setting_name in validation_rules:
                    validation_result = self._validate_value_dynamic(
                        setting_name, value, validation_rules[setting_name]
                    )
                    if validation_result.is_error:
                        return validation_result
                    value = validation_result.get_data_value("validated_value", value)

                result[setting_name] = value

            except AttributeError:
                return PyIVLSReturn.value_error(
                    f"Widget '{widget_name}' not found for {setting_name}", self.plugin_name
                )
            except Exception as e:
                return PyIVLSReturn.value_error(f"Error processing {setting_name}: {str(e)}", self.plugin_name)

        return PyIVLSReturn.success(result)

    def schedule_gui_update(self, settings, field_mapping, validation_rules):
        """Schedule a GUI update. Callable from other threads to update the GUI safely?

        Args:
            settings (dict): The settings to apply.
            field_mapping (dict): The mapping of fields to update.
            validation_rules (dict): The validation rules to apply.
        """
        self.update_gui.emit(settings, field_mapping, validation_rules)

    @pyqtSlot(dict, dict, dict)
    def set_values(self, settings: dict, field_mapping: dict, validation_rules: dict) -> PyIVLSReturn:
        """Set GUI widget values from settings dictionary with dynamic type detection and conversion.

        Args:
            settings: Settings dictionary with values to set
            field_mapping: Dict mapping setting names to widget attribute names
            validation_rules: Optional rules for converting stored values to display format
                {"setting_name": {"display_converter": lambda x: ...}}
        """
        validation_rules = validation_rules
        for setting_name, widget_name in field_mapping.items():
            try:
                widget_obj = getattr(self.widget, widget_name)
                value = settings[setting_name]
                # Apply display conversion if specified
                if setting_name in validation_rules and "display_converter" in validation_rules[setting_name]:
                    try:
                        value = validation_rules[setting_name]["display_converter"](value)
                    except Exception as e:
                        return PyIVLSReturn.value_error(
                            f"Display conversion failed for {setting_name}: {str(e)}", self.plugin_name
                        )

                # Dynamically set value based on widget type
                self._set_value_dynamic(widget_obj, value)

            except AttributeError:
                return PyIVLSReturn.value_error(
                    f"Widget '{widget_name}' not found for {setting_name}", self.plugin_name
                )
            except Exception as e:
                return PyIVLSReturn.value_error(f"Error processing {setting_name}: {str(e)}", self.plugin_name)
        return PyIVLSReturn.success()

    def _extract_value_dynamic(self, widget_obj) -> Any:
        """Dynamically extract value based on widget type.
        QLineEdit: Tries to convert to int, fallback on str
        QCheckBox: Returns bool
        QComboBox: Returns current text as str
        QSpinBox: Returns int value

        """
        if isinstance(widget_obj, QLineEdit):
            text = widget_obj.text().strip()
            # Try to convert to number if possible, but preserve original text for validation
            if text == "":
                return ""  # Return empty string for empty fields
            try:
                return float(text)
            except ValueError:
                # Return as text - validation will handle type conversion if needed
                return text
        elif isinstance(widget_obj, QCheckBox):
            return widget_obj.isChecked()
        elif isinstance(widget_obj, QComboBox):
            return widget_obj.currentText()
        elif isinstance(widget_obj, QSpinBox):
            return widget_obj.value()  # Already int
        elif isinstance(widget_obj, QDoubleSpinBox):
            return widget_obj.value()  # Already float
        else:
            # For unknown widget types, try to get a value attribute or text
            if hasattr(widget_obj, "value"):
                return widget_obj.value()
            elif hasattr(widget_obj, "text"):
                return widget_obj.text()
            else:
                raise ValueError(f"Unsupported widget type: {type(widget_obj)}")

    def _set_value_dynamic(self, widget_obj, value: Any) -> None:
        """Dynamically set value based on widget type."""
        if isinstance(widget_obj, QLineEdit):
            widget_obj.setText(str(value))
        elif isinstance(widget_obj, QCheckBox):
            # Handle various boolean representations
            if isinstance(value, bool):
                widget_obj.setChecked(value)
            elif isinstance(value, str):
                widget_obj.setChecked(value.lower() in ["true", "1", "yes", "on"])
            else:
                widget_obj.setChecked(bool(value))
        elif isinstance(widget_obj, QComboBox):
            text_value = str(value)
            # Try to find exact match first
            index = widget_obj.findText(text_value)
            if index >= 0:
                widget_obj.setCurrentIndex(index)
            else:
                # If no exact match, set text anyway (might add new item depending on combo box settings)
                widget_obj.setCurrentText(text_value)
        elif isinstance(widget_obj, QSpinBox):
            widget_obj.setValue(int(float(value)))  # Convert to int, handling float strings
        elif isinstance(widget_obj, QDoubleSpinBox):
            widget_obj.setValue(float(value))
        else:
            # For unknown widget types, try common patterns
            if hasattr(widget_obj, "setValue"):
                widget_obj.setValue(value)
            elif hasattr(widget_obj, "setText"):
                widget_obj.setText(str(value))
            else:
                raise ValueError(f"Unsupported widget type for setting value: {type(widget_obj)}")

    def _validate_value_dynamic(self, setting_name: str, value: Any, validation_config: Dict[str, Any]) -> PyIVLSReturn:
        """Validate a value using dynamic validation rules."""

        # Apply conversion function if specified
        if "converter" in validation_config:
            try:
                value = validation_config["converter"](value)
            except Exception as e:
                return PyIVLSReturn.value_error(f"conversion failed for {setting_name}: {str(e)}", self.plugin_name)

        # Apply custom validator function
        if "validator" in validation_config:
            validator_func = validation_config["validator"]
            try:
                if not validator_func(value):
                    error_msg = validation_config.get("error_message", f"{setting_name} failed validation")
                    return PyIVLSReturn.value_error(error_msg, self.plugin_name)
            except Exception as e:
                return PyIVLSReturn.value_error(f"validation failed for {setting_name}: {str(e)}", self.plugin_name)

        return PyIVLSReturn.success({"validated_value": value})


class DataOrder(Enum):
    """Enum for data ordering."""

    V = 1
    I = 0  # noqa: E741


class PluginException(Exception):
    """Base exception for plugin errors."""

    pass


class DependencyManager:
    """Enhanced dependency manager that handles multiple dependency types and validation."""

    def __init__(self, plugin_name: str, dependencies: Dict[str, list], widget, mapping: Dict[str, str]):
        """
        Initialize dependency manager.

        Args:
            plugin_name: Name of the plugin using this manager
            dependencies: Dict mapping dependency types to required function lists
                         e.g., {"smu": ["connect", "init"], "spectro": ["measure"]}
            widget: Optional widget containing comboboxes for dependency selection
            mapping: Dict mapping dependency type to combobox widget name
        """
        self.plugin_name = plugin_name
        self.dependencies = dependencies
        self.widget = widget
        self._function_dict = {}
        self.missing_functions = []
        self.dependency_settings = {}
        self.combobox_mapping = mapping
        self.last_selected = {}

    @property
    def function_dict(self) -> Dict[str, Any]:
        """Get the current function dictionary."""
        return self._function_dict

    @function_dict.setter
    def function_dict(self, value: Dict[str, Any]) -> None:
        """Set the function dictionary and automatically update GUI comboboxes."""
        self._function_dict = value
        # Automatically update comboboxes when function dict is set
        self.update_comboboxes()

    def set_function_dict(self, function_dict: Dict[str, Any]) -> None:
        """Set the available function dictionary from plugin system."""
        self.function_dict = function_dict

    def setup(self, settings: Dict[str, Any]) -> PyIVLSReturn:
        """Setup the dependency manager with initial settings if needed."""
        self.last_selected = settings.copy()
        self.update_comboboxes()
        return PyIVLSReturn.success()

    def validate_dependencies(self) -> Tuple[bool, list]:
        """
        Validate that all required dependencies are available.

        Returns:
            Tuple[bool, list]: (is_valid, missing_functions_list)
        """
        self.missing_functions = []

        for dependency_type, required_functions in self.dependencies.items():
            if dependency_type not in self._function_dict:
                self.missing_functions.extend([f"{dependency_type}.{func}" for func in required_functions])
                continue

            available_plugins = self._function_dict[dependency_type]

            # Check if any plugin provides all required functions
            has_valid_plugin = False
            for plugin_name, plugin_functions in available_plugins.items():
                if all(func in plugin_functions for func in required_functions):
                    has_valid_plugin = True
                    break

            if not has_valid_plugin:
                missing_for_type = []
                for func in required_functions:
                    if not any(func in plugin_funcs for plugin_funcs in available_plugins.values()):
                        missing_for_type.append(f"{dependency_type}.{func}")
                self.missing_functions.extend(missing_for_type)

        return len(self.missing_functions) == 0, self.missing_functions

    def update_comboboxes(self) -> None:
        """Update all dependency comboboxes with available plugins."""
        for dependency_type, combobox_name in self.combobox_mapping.items():
            if dependency_type in self._function_dict:
                combobox = getattr(self.widget, combobox_name)
                combobox.clear()
                available_plugins = list(self._function_dict[dependency_type].keys())
                combobox.addItems(available_plugins)
                # Try to restore previous selection if it's still available
                if dependency_type in self.last_selected:
                    last_selection = self.last_selected[dependency_type]
                    if last_selection in available_plugins:
                        combobox.setCurrentText(last_selection)

    def get_selected_dependencies(self) -> Dict[str, str]:
        """
        Get currently selected dependencies from comboboxes.

        Returns:
            Dict mapping dependency type to selected plugin name
        """
        selected = {}
        if not self.widget:
            return selected

        for dependency_type, combobox_name in self.combobox_mapping.items():
            try:
                combobox = getattr(self.widget, combobox_name)
                selected[dependency_type] = combobox.currentText()
            except AttributeError:
                continue

        return selected

    def validate_selection(self, dependency_type: str, plugin_name: str) -> Tuple[bool, str]:
        """
        Validate that a selected plugin provides all required functions.

        Args:
            dependency_type: Type of dependency (e.g., "smu")
            plugin_name: Name of selected plugin

        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        if dependency_type not in self.dependencies:
            return False, f"Unknown dependency type: {dependency_type}"

        if dependency_type not in self._function_dict:
            return False, f"No {dependency_type} plugins available"

        if plugin_name not in self._function_dict[dependency_type]:
            return False, f"{dependency_type} plugin '{plugin_name}' not found"

        plugin_functions = self._function_dict[dependency_type][plugin_name]
        required_functions = self.dependencies[dependency_type]

        missing_functions = [func for func in required_functions if func not in plugin_functions]

        if missing_functions:
            return False, f"{dependency_type} plugin '{plugin_name}' missing functions: {', '.join(missing_functions)}"

        return True, ""

    def get_function_dict_for_dependencies(self) -> Dict[str, Any]:
        """
        Get a filtered function dictionary containing only the dependencies needed by this plugin.

        Returns:
            Dict containing only the dependency types this plugin needs
        """
        filtered_dict = {}
        for dependency_type in self.dependencies.keys():
            if dependency_type in self._function_dict:
                filtered_dict[dependency_type] = self._function_dict[dependency_type]
        return filtered_dict

    def validate_and_extract_dependency_settings(self, target_settings_dict: Dict[str, Any]) -> PyIVLSReturn:
        """
        Validates all dependency selections and extracts their settings.

        This method:
        1. Checks if function_dict is available
        2. Gets selected dependencies from comboboxes
        3. Validates each dependency selection
        4. Calls parse_settings_widget for each valid dependency
        5. Updates target_settings_dict with dependency names and settings

        Args:
            target_settings_dict: Dictionary to update with dependency information

        Returns:
            PyIVLSReturn: Success with dependency settings or error with message
        """
        if not self._function_dict:
            return PyIVLSReturn.missing_dependency(
                f"Missing functions in {self.plugin_name} plugin. Check log", self.missing_functions
            )

        # Get selected dependencies from GUI
        selected_deps = self.get_selected_dependencies()
        dependency_settings = {}

        # Validate and extract settings for each dependency type
        for dependency_type in self.dependencies.keys():
            if dependency_type not in selected_deps or not selected_deps[dependency_type]:
                return PyIVLSReturn.missing_dependency(f"No {dependency_type} plugin selected")

            selected_plugin = selected_deps[dependency_type]

            # Validate selection
            is_valid, error_msg = self.validate_selection(dependency_type, selected_plugin)
            if not is_valid:
                return PyIVLSReturn.missing_dependency(f"{dependency_type} validation failed: {error_msg}")

            # Update target settings with selected plugin name
            target_settings_dict[dependency_type] = selected_plugin

            # Extract settings from the dependency plugin
            try:
                status, state = self._function_dict[dependency_type][selected_plugin]["parse_settings_widget"]()
                if status:
                    return PyIVLSReturn.dependency_error({"Error message": state})
                else:
                    settings = state

                # Store settings with a standardized key
                settings_key = f"{dependency_type}_settings"
                dependency_settings[settings_key] = settings

            except KeyError as e:
                return PyIVLSReturn.missing_dependency(
                    f"Required function 'parse_settings_widget' not found in {dependency_type} plugin '{selected_plugin}': {str(e)}"
                )
            except Exception as e:
                return PyIVLSReturn.missing_dependency(
                    f"Error calling parse_settings_widget for {dependency_type} plugin '{selected_plugin}': {str(e)}"
                )
        return PyIVLSReturn.success(dependency_settings)


class LoggingHelper(QObject):
    """Helper class for standard logging functionality. pass "self" to the helper on plugin init
    Logging levels:
    DEBUG: Detailed information, typically only of interest to a developer trying to diagnose a problem.
    INFO: Confirmation that things are working as expected.
    WARN: An indication that something unexpected happened, or indicative of some problem in the near future (e.g., 'disk space low'). The software is still working as expected.
    ERROR: Due to a more serious problem, the software has not been able to perform some function.
    """

    logger_signal = pyqtSignal(str)
    info_popup_signal = pyqtSignal(str)

    def __init__(self, plugin_instance):
        self.plugin_name = plugin_instance.__class__.__name__
        super().__init__()

    def log_info(self, message: str) -> None:
        """Log informational messages with INFO flag
        INFO: Confirmation that things are working as expected.
        """
        log = f"{self.plugin_name} : INFO : {message}"
        self.logger_signal.emit(log)

    def log_debug(self, message: str) -> None:
        """Log debug messages with DEBUG flag
        DEBUG: Detailed information, typically only of interest to a developer trying to diagnose a problem.
        """

        log = f"{self.plugin_name} : DEBUG : {message}"
        self.logger_signal.emit(log)

    def log_warn(self, message: str) -> None:
        """Log warning messages with WARN flag
        WARN: An indication that something unexpected happened, or indicative of some problem in the near future (e.g., 'disk space low'). The software is still working as expected.
        """
        log = f"{self.plugin_name} : WARN : {message}"
        self.logger_signal.emit(log)

    def log_error(self, message: str, include_trace: bool = True) -> None:
        """Log error messages with ERROR flag.
        ERROR: Due to a more serious problem, the software has not been able to perform some function.
        """
        log = f"{self.plugin_name} : ERROR : {message}"

        if include_trace:
            # Get current exception traceback (if inside except block)
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_type is not None:
                trace = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                log += f"\n{trace}"
            else:
                # Outside of exception block — include current stack
                stack = "".join(traceback.format_stack()[:-1])  # remove the current function call
                log += f"\nStack trace:\n{stack}"

        self.logger_signal.emit(log)

    def info_popup(self, message: str) -> None:
        """show info popup, if provided"""
        message = f"{self.plugin_name}: {message}"
        self.info_popup_signal.emit(message)


class SMUHelper:
    """FORMAT OF SMU SETTINGS:
    # s["source"] source channel: may take values [smua, smub]
    # s["drain"] dain channel: may take values [smub, smua]
    # s["type"] source inject current or voltage: may take values [i ,v]
    # s["sourcesense"] source sence mode: may take values [True - 4 wire, False - 2 wire]
    # s["drainsense"] drain sence mode: may take values [True - 4 wire, False - 2 wire]

    # s["single_ch"] single channel mode: may be True or False

    # s["pulse"] set pulsed mode: may be True - pulsed, False - continuous
    # s["pulsepause"] pause between pulses in sweep

    # s['sourcenplc'] integration time in nplc units
    # s["drainnplc"] integration time in nplc units

    # s["delay"] stabilization time mode for source: may take values [True - Auto, False - manual]
    # s["delayduration"] stabilization time duration if manual

    # s["draindelay"] stabilization time mode for drain: may take values [True - Auto, False - manual]
    # s["draindelayduration"] stabilization time duration if manual

    # s["steps"] number of points in sweep
    # s["start"] start point of sweep
    # s["end"] end point of sweep
    # s["limit"] limit for the voltage if is in current injection mode, limit for the current if in voltage injection mode

    # s["sourcehighc"] high capacitance mode for source
    # s["drainhighc"] high capacitance mode for drain

    # s["repeat"] repeat count

    # settings for drain
    ## s["drainvoltage"] voltage on drain
    ## s["drainlimit"] limit for current in voltage mode or for voltage in current mode
    """

    def __init__(self, plugin_name: str):
        """Initialize the SMU helper with the plugin name."""
        self.plugin_name = plugin_name

    def smu_init(self, plugin_settings_dict, smu_settings, smu_functions) -> PyIVLSReturn:
        """Initialize the SMU with the provided settings."""
        s = {}
        s["pulse"] = False
        s["source"] = plugin_settings_dict[
            "channel"
        ]  # may take values depending on the channel names in smu, e.g. for Keithley 2612B [smua, smub]
        s["drain"] = plugin_settings_dict["drainchannel"]
        s["type"] = (
            "v" if plugin_settings_dict["inject"] == "voltage" else "i"
        )  # source inject current or voltage: may take values [i ,v]
        s["single_ch"] = plugin_settings_dict["singlechannel"]  # single channel mode: may be True or False

        s["sourcenplc"] = plugin_settings_dict["sourcenplc"]  # drain NPLC (may not be used in single channel mode)
        s["delay"] = (
            True if plugin_settings_dict["sourcedelaymode"] == "auto" else False
        )  # stabilization time mode for source: may take values [True - Auto, False - manual]
        s["delayduration"] = plugin_settings_dict[
            "sourcedelay"
        ]  # stabilization time duration if manual (may not be used in single channel mode)
        s["limit"] = plugin_settings_dict[
            "sourcelimit"
        ]  # limit for current in voltage mode or for voltage in current mode (may not be used in single channel mode)
        s["sourcehighc"] = smu_settings["sourcehighc"]

        s["drainnplc"] = plugin_settings_dict["drainnplc"]  # drain NPLC (may not be used in single channel mode)
        s["draindelay"] = (
            True if plugin_settings_dict["draindelaymode"] == "auto" else False
        )  # stabilization time mode for source: may take values [True - Auto, False - manual]
        s["draindelayduration"] = plugin_settings_dict[
            "draindelay"
        ]  # stabilization time duration if manual (may not be used in single channel mode)
        s["drainlimit"] = plugin_settings_dict[
            "drainlimit"
        ]  # limit for current in voltage mode or for voltage in current mode (may not be used in single channel mode)
        s["drainhighc"] = smu_settings["drainhighc"]

        if plugin_settings_dict["sourcesensemode"] == "4 wire":
            s["sourcesense"] = True  # source sence mode: may take values [True - 4 wire, False - 2 wire]
        else:
            s["sourcesense"] = False  # source sence mode: may take values [True - 4 wire, False - 2 wire]
        if plugin_settings_dict["drainsensemode"] == "4 wire":
            s["drainsense"] = True  # source sence mode: may take values [True - 4 wire, False - 2 wire]
        else:
            s["drainsense"] = False  # source sence mode: may take values [True - 4 wire, False - 2 wire]

        # Call SMU initialization function
        try:
            init_result = smu_functions["smu_init"](s)
            if init_result:  # Non-zero return indicates error
                return PyIVLSReturn.hardware_error("error in SMU plugin can not initialize", self.plugin_name)
        except Exception as e:
            return PyIVLSReturn.hardware_error(f"SMU initialization failed: {str(e)}", self.plugin_name)

        return PyIVLSReturn.success({"smu_config": s})


class GuiPluginBase:
    """TODO"""

    @property
    def settings(self):
        return self._settings

    @settings.setter
    def settings(self, value: Dict[str, Any]):
        """Settings setter. Could be a useful tool to validate settings before applying, or automatically updating GUI elements."""
        if not isinstance(value, dict):
            raise ValueError("Settings must be a dictionary")
        self._settings = value

    def __init__(self):
        self._settings = {}
