"""
Comprehensive tests for Keithley2612B class using mock backend.

This module tests the Keithley2612B class to ensure correct commands are sent
to the instrument based on different configuration parameters, with special
attention to conditional commands that depend on specific settings.
"""

import pytest
import sys
import os

# Add the plugins directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "Keithley2612B"))

try:
    from Keithley2612B import Keithley2612B
except ImportError as e:
    pytest.skip(f"Cannot import Keithley2612B: {e}", allow_module_level=True)

STANDARD_SETTINGS = {
    "source": "mocka",
    "drain": "mockb",
    "type": "v",
    "sourcesense": False,
    "drainsense": False,
    "single_ch": True,
    "pulse": False,
    "pulsepause": 0.1,
    "sourcenplc": 20,
    "drainnplc": 20,
    "delay": True,
    "delayduration": 1,
    "draindelay": True,
    "draindelayduration": 1,
    "steps": 10,
    "start": 0.0,
    "end": 1.0,
    "limit": 0.5,
    "sourcehighc": False,
    "drainhighc": False,
    "repeat": 1,
    "drainvoltage": 0.0,
    "drainlimit": 0.1,
}


class TestKeithley2612B:
    """Test the Keithley2612B class with mock backend."""

    def setup_method(self):
        """Set up test fixtures."""
        self.keithley = Keithley2612B()
        self.commands_sent = []

        # Mock the safewrite method to capture commands
        def mock_safewrite(command):
            self.commands_sent.append(command)

        self.keithley.safewrite = mock_safewrite

        def mock_safequery(command):
            if "linefreq" in command:
                return "50"
            elif "nvbuffer" in command and ".n" in command:
                return "10"
            elif "printbuffer" in command:
                return "0.001,0.002,0.003"
            else:
                return "OK"

        self.keithley.safequery = mock_safequery

    def test_keithley_connect_mock_backend(self):
        """Test connection to mock backend."""
        self.keithley.keithley_connect("mock_address", "192.168.1.1", "MOCK", "502")

        assert self.keithley.backend == "MOCK"
        assert self.keithley.mock_con is True
        assert self.keithley.address == "mock_address"

    def test_keithley_init_basic_commands(self):
        """Test that basic initialization commands are always sent."""
        # Connect first
        self.keithley.keithley_connect("", "", "MOCK", "")

        # Basic settings
        settings = STANDARD_SETTINGS

        self.keithley.keithley_init(settings)

        # Check basic initialization commands
        assert "reset()" in self.commands_sent
        assert "beeper.enable=0" in self.commands_sent
        assert "display.screen = display.SMUA_SMUB" in self.commands_sent
        assert "format.data = format.ASCII" in self.commands_sent
        assert "format.asciiprecision = 14" in self.commands_sent
        assert f"{settings['source']}.reset()" in self.commands_sent

    def test_source_sense_mode_remote(self):
        """Test that SENSE_REMOTE is set when sourcesense is True."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["sourcesense"] = True  # This should trigger SENSE_REMOTE

        self.keithley.keithley_init(settings)
        # Check that SENSE_REMOTE command is sent
        assert "mocka.sense = mocka.SENSE_REMOTE" in self.commands_sent
        # Check that SENSE_LOCAL is NOT sent
        assert "mocka.sense = mocka.SENSE_LOCAL" not in self.commands_sent

    def test_source_sense_mode_local(self):
        """Test that SENSE_LOCAL is set when sourcesense is False."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["sourcesense"] = False  # This should trigger SENSE_Local

        self.keithley.keithley_init(settings)

        # Check that SENSE_LOCAL command is sent
        assert "mocka.sense = mocka.SENSE_LOCAL" in self.commands_sent
        # Check that SENSE_REMOTE is NOT sent
        assert "mocka.sense = mocka.SENSE_REMOTE" not in self.commands_sent

    def test_drain_sense_mode_dual_channel(self):
        """Test drain sense mode settings in dual channel mode."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["single_ch"] = False  # Dual channel mode
        settings["drainsense"] = True  # This should trigger SENSE_REMOTE for drain

        self.keithley.keithley_init(settings)

        # Check drain sense commands
        assert "mockb.sense = mockb.SENSE_REMOTE" in self.commands_sent
        assert "mockb.sense = mockb.SENSE_LOCAL" not in self.commands_sent
        # Also check source sense
        assert "mocka.sense = mocka.SENSE_LOCAL" in self.commands_sent

    def test_high_capacitance_mode_source(self):
        """Test that source high capacitance mode is set correctly."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["sourcehighc"] = True  # High capacitance mode enabled
        self.keithley.keithley_init(settings)

        # Check that high capacitance mode is enabled
        assert "mocka.source.highc = mocka.ENABLE" in self.commands_sent

    def test_high_capacitance_mode_disabled(self):
        """Test that high capacitance mode is not set when disabled."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["sourcehighc"] = False  # High capacitance mode disabled
        self.keithley.keithley_init(settings)

        # Check that high capacitance mode is enabled
        assert "mocka.source.highc = mocka.ENABLE" not in self.commands_sent

    def test_delay_mode_auto(self):
        """Test automatic delay mode settings."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["delay"] = True  # Auto delay mode

        self.keithley.keithley_init(settings)

        # Check auto delay commands
        assert "mocka.measure.delay = mocka.DELAY_AUTO" in self.commands_sent
        assert "mocka.measure.delayfactor = 28.0" in self.commands_sent  # Continuous mode factor

    def test_delay_mode_auto_pulsed(self):
        """Test automatic delay mode with pulsed operation."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["delay"] = True  # Auto delay mode
        settings["pulse"] = True  # Pulsed mode

        self.keithley.keithley_init(settings)

        # Check auto delay commands for pulsed mode
        assert "mocka.measure.delay = mocka.DELAY_AUTO" in self.commands_sent
        assert "mocka.measure.delayfactor = 1.0" in self.commands_sent  # Pulsed mode factor

    def test_delay_mode_manual(self):
        """Test manual delay mode settings."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["delay"] = False  # Manual delay mode
        settings["delayduration"] = 0.5  # Specific delay duration
        self.keithley.keithley_init(settings)

        # Check manual delay command
        assert "mocka.measure.delay = 0.5" in self.commands_sent
        # Check that auto delay is NOT set
        assert "mocka.measure.delay = mocka.DELAY_AUTO" not in self.commands_sent

    def test_current_injection_mode_low_current(self):
        """Test current injection mode with low current (< 1.5A)."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["type"] = "i"  # Current injection
        settings["start"] = 0.0
        settings["end"] = 1.0  # < 1.5A
        settings["limit"] = 5.0  # Voltage limit
        self.keithley.keithley_init(settings)

        # Check current injection specific commands
        assert "mocka.trigger.source.limitv = 5.0" in self.commands_sent
        assert "mocka.source.limitv = 5.0" in self.commands_sent
        assert "mocka.measure.filter.count = 4" in self.commands_sent
        assert "mocka.measure.filter.enable = mocka.FILTER_ON" in self.commands_sent
        assert "mocka.measure.autorangei = mocka.AUTORANGE_ON" in self.commands_sent
        assert "mocka.measure.autorangev = mocka.AUTORANGE_ON" in self.commands_sent
        assert "display.mocka.measure.func = display.MEASURE_DCVOLTS" in self.commands_sent

    def test_current_injection_mode_high_current(self):
        """Test current injection mode with high current (> 1.5A)."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["type"] = "i"  # Current injection
        settings["start"] = 0.0
        settings["end"] = 5.0  # > 1.5A
        settings["limit"] = 5.0  # Voltage limit
        self.keithley.keithley_init(settings)

        # Check high current specific commands
        assert "mocka.measure.filter.enable = mocka.FILTER_OFF" in self.commands_sent
        assert "mocka.source.autorangei = mocka.AUTORANGE_OFF" in self.commands_sent
        assert "mocka.source.autorangev = mocka.AUTORANGE_OFF" in self.commands_sent
        assert "mocka.source.delay = 100e-6" in self.commands_sent
        assert "mocka.measure.autozero = mocka.AUTOZERO_OFF" in self.commands_sent
        assert "mocka.source.rangei = 10" in self.commands_sent
        assert "mocka.source.leveli = 0" in self.commands_sent
        assert "mocka.source.limitv = 6" in self.commands_sent
        assert "mocka.trigger.source.limiti = 10" in self.commands_sent
        assert "display.mocka.measure.func = display.MEASURE_DCVOLTS" in self.commands_sent

    def test_voltage_injection_mode_low_current_limit(self):
        """Test voltage injection mode with low current limit (< 1.5A)."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["type"] = "v"  # Voltage injection
        settings["limit"] = 1.0  # current limit < 1.5A
        self.keithley.keithley_init(settings)

        # Check voltage injection with low current limit
        assert "mocka.trigger.source.limiti = 1.0" in self.commands_sent
        assert "mocka.source.limiti = 1.0" in self.commands_sent
        assert "display.mocka.measure.func = display.MEASURE_DCAMPS" in self.commands_sent

    def test_voltage_injection_mode_high_current_limit(self):
        """Test voltage injection mode with high current limit (> 1.5A)."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["type"] = "v"  # Voltage injection
        settings["limit"] = 2.0  # current limit > 1.5A
        self.keithley.keithley_init(settings)

        # Check voltage injection with high current limit
        assert "mocka.measure.filter.enable = mocka.FILTER_OFF" in self.commands_sent
        assert "mocka.source.autorangei = mocka.AUTORANGE_OFF" in self.commands_sent
        assert "mocka.source.autorangev = mocka.AUTORANGE_OFF" in self.commands_sent
        assert "mocka.measure.rangei = 10" in self.commands_sent
        assert "mocka.source.delay = 100e-6" in self.commands_sent
        assert "mocka.measure.autozero = mocka.AUTOZERO_OFF" in self.commands_sent
        assert "mocka.source.rangev = 6" in self.commands_sent
        assert "mocka.source.levelv = 0" in self.commands_sent
        assert "mocka.source.limiti = 2.0" in self.commands_sent
        assert "mocka.trigger.source.limiti = 2.0" in self.commands_sent
        assert "display.mocka.measure.func = display.MEASURE_DCAMPS" in self.commands_sent

    def test_dual_channel_configuration(self):
        """Test dual channel configuration with drain settings."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["single_ch"] = False  # Dual channel mode
        settings["drainsense"] = True  # Drain sense remote
        settings["drainnplc"] = 0.02
        settings["drainhighc"] = True  # Drain high capacitance
        settings["draindelay"] = False  # Manual delay
        settings["draindelayduration"] = 0.3  # Specific drain delay
        self.keithley.keithley_init(settings)

        # Check drain channel initialization
        assert "mockb.reset()" in self.commands_sent
        assert "mockb.sense = mockb.SENSE_REMOTE" in self.commands_sent
        assert "mockb.measure.nplc = 0.02" in self.commands_sent
        assert "mockb.source.highc = mockb.ENABLE" in self.commands_sent
        assert "mockb.source.settling = mockb.SETTLE_FAST_RANGE" in self.commands_sent
        assert "display.mockb.measure.func = display.MEASURE_DCAMPS" in self.commands_sent

        # Check drain delay settings (manual mode)
        assert "mockb.measure.delay = 0.3" in self.commands_sent
        assert "mockb.measure.delay = mockb.DELAY_AUTO" not in self.commands_sent

    def test_drain_auto_delay_continuous(self):
        """Test drain auto delay in continuous mode."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["single_ch"] = False  # Dual channel mode
        settings["drainsense"] = True  # Drain sense remote
        settings["drainnplc"] = 0.02
        settings["drainhighc"] = True  # Drain high capacitance
        settings["draindelay"] = True  # Auto Delay
        settings["pulse"] = False  # Continuous mode
        self.keithley.keithley_init(settings)

        # Check drain auto delay settings for continuous mode
        assert "mockb.measure.delay = mockb.DELAY_AUTO" in self.commands_sent
        assert "mockb.measure.delayfactor = 28.0" in self.commands_sent

    def test_drain_auto_delay_pulsed(self):
        """Test drain auto delay in pulsed mode."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["single_ch"] = False  # Dual channel mode
        settings["drainsense"] = True  # Drain sense remote
        settings["drainnplc"] = 0.02
        settings["pulse"] = True  # Pulsed mode
        settings["drainhighc"] = True  # Drain high capacitance
        settings["draindelay"] = True  # Auto Delay
        self.keithley.keithley_init(settings)

        # Check drain auto delay settings for pulsed mode
        assert "mockb.measure.delay = mockb.DELAY_AUTO" in self.commands_sent
        assert "mockb.measure.delayfactor = 1.0" in self.commands_sent

    def test_nplc_settings(self):
        """Test that NPLC settings are correctly applied."""
        self.keithley.keithley_connect("", "", "MOCK", "")

        settings = STANDARD_SETTINGS
        settings["single_ch"] = False  # Dual channel mode
        settings["sourcenplc"] = 0.05
        settings["drainnplc"] = 0.1
        self.keithley.keithley_init(settings)

        # Check NPLC settings
        assert "mocka.measure.nplc = 0.05" in self.commands_sent
        assert "mockb.measure.nplc = 0.1" in self.commands_sent


    def test_set_output_commands(self):
        """Test setOutput commands."""
        self.keithley.keithley_connect("mock", "192.168.1.1", "MOCK", "502")

        # Test voltage output
        self.keithley.setOutput("mocka", "v", 2.5)
        assert "mocka.source.levelv = 2.5" in self.commands_sent

        # Test current output
        self.commands_sent.clear()
        self.keithley.setOutput("mockb", "i", 0.001)
        assert "mockb.source.leveli = 0.001" in self.commands_sent

    def test_abort_sweep(self):
        """Test abort sweep command."""
        self.keithley.keithley_connect("mock", "192.168.1.1", "MOCK", "502")

        self.keithley.abort_sweep("mocka")
        assert "mocka.abort()" in self.commands_sent

    def test_channel_names_mock_backend(self):
        """Test channel names for mock backend."""
        result = self.keithley.channel_names("MOCK")
        assert result == ["mockA", "mockB"]

    def test_single_channel_mode(self):
        """Test that drain settings are not applied in single channel mode."""
        self.keithley.keithley_connect("mock", "192.168.1.1", "MOCK", "502")

        settings = {
            "source": "mocka",
            "drain": "mockb",  # This should be ignored
            "sourcesense": False,
            "drainsense": True,  # This should be ignored
            "single_ch": True,  # Single channel mode
            "type": "v",
            "sourcenplc": 0.01,
            "drainnplc": 0.01,  # This should be ignored
            "delay": True,
            "draindelay": True,  # This should be ignored
            "start": 0.0,
            "end": 1.0,
            "limit": 0.5,
            "sourcehighc": False,
            "drainhighc": True,  # This should be ignored
            "pulse": False,
        }

        self.keithley.keithley_init(settings)

        # Check that source commands are present
        assert "mocka.reset()" in self.commands_sent
        assert "mocka.sense = mocka.SENSE_LOCAL" in self.commands_sent

        # Check that drain commands are NOT present
        assert "mockb.reset()" not in self.commands_sent
        assert "mockb.sense = mockb.SENSE_REMOTE" not in self.commands_sent
        assert "mockb.measure.nplc = 0.01" not in self.commands_sent
        assert "mockb.source.highc = mockb.ENABLE" not in self.commands_sent

