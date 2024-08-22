# File: pyIVLS_constants.py definitions for the constants used in pyIVLS

### main config name
configFileName = "pyIVLS.ini"

### dictionary for plugin data

"""
plugin_num = 0
plugin_name = 1
plugin_type = 2
plugin_function = 3
plugin_address = 4
"""

### Keithley constants
KEITHLEY_VISA = "TCPIP::192.168.1.5::INSTR"
LINE_FREQ = 50  # Hz

### Sutter constants
SUTTER_DEFAULT_PORT = (
    "/dev/serial/by-id/usb-Sutter_Sutter_Instrument_ROE-200_SI9NGJEQ-if00-port0"
)

### Thorspec constants
THORSPEC_PID = 0x1551
THORSPEC_VID = 0x1000

### Plugin constants
HOOKS = ["get_setup_interface", "get_functions"]
