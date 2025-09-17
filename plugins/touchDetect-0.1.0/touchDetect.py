#

# detects 20 ohms -> slow down, don't move too far from there
#
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class ManipulatorInfo:
    mm_number: int
    smu_channel: str
    condet_channel: str
    threshold: int
    stride: int
    sample_width: float
    function: str
    last_z: Optional[int] = None
    spectrometer_height: Optional[int] = None

    def __post_init__(self):
        """Generates new field (self.function) after __init__ is called"""
        if self.smu_channel == "spectrometer" or self.condet_channel == "spectrometer":
            self.function: str = "spectrometer"
        elif self.smu_channel == "none" or self.condet_channel == "none":
            self.function: str = "unconfigured"
        elif self.smu_channel == "" or self.condet_channel == "":
            self.function: str = "unconfigured"
        else:
            self.function: str = "normal"

        # convert all to proper types
        self.mm_number = int(self.mm_number)
        self.smu_channel = str(self.smu_channel)
        self.condet_channel = str(self.condet_channel)
        self.threshold = int(self.threshold)
        self.stride = int(self.stride)
        self.sample_width = float(self.sample_width)
        self.last_z = int(self.last_z) if self.last_z is not None else None
        self.spectrometer_height = int(self.spectrometer_height) if self.spectrometer_height is not None else None

    def with_new_settings(self, **kwargs) -> "ManipulatorInfo":
        """
        Creates a new ManipulatorInfo instance with updated settings.
        This ensures __post_init__ is called to recalculate derived fields.

        Args:
            **kwargs: Fields to update (e.g., threshold=100, stride=5)

        Returns:
            ManipulatorInfo: New instance with updated settings
        """
        # Get current values as a dict
        current_values = self.to_dict()

        # Update with provided kwargs
        current_values.update(kwargs)
        return ManipulatorInfo(**current_values)

    def to_dict(self) -> dict:
        """Converts the ManipulatorInfo instance to a dictionary."""
        return {
            "mm_number": self.mm_number,
            "smu_channel": self.smu_channel,
            "condet_channel": self.condet_channel,
            "threshold": self.threshold,
            "stride": self.stride,
            "sample_width": self.sample_width,
            "function": self.function,
            "last_z": self.last_z,
            "spectrometer_height": self.spectrometer_height,
        }

    def to_named_dict(self) -> dict:
        """Returns a dictionary with named keys for each field. Useful for saving to ini for instance."""
        return {
            f"{self.mm_number}_smu": self.smu_channel,
            f"{self.mm_number}_con": self.condet_channel,
            f"{self.mm_number}_res": self.threshold,
            f"{self.mm_number}_last_z": self.last_z,
            "stride": self.stride,
            "sample_width": self.sample_width,
            "spectrometer_height": self.spectrometer_height,
        }

    def validate(self) -> list[str]:
        """Returns a list of validation errors, if any."""
        errors = []
        if self.threshold <= 0:
            errors.append("Invalid threshold")
        if self.stride <= 0:
            errors.append("Invalid stride")
        if self.sample_width <= 0:
            errors.append("Invalid sample width")
        if self.function == "spectrometer" and self.spectrometer_height is None:
            errors.append("Spectrometer height is not set")
        if self.function == "normal" and self.last_z is None:
            errors.append("Last known position is not set for normal function")
        return errors

    def is_configured(self) -> bool:
        """Returns True if the manipulator is configured, False otherwise."""
        return self.function != "unconfigured"

    def needs_z_pos(self) -> bool:
        """Returns True if the manipulator needs a Z position to be set, False otherwise."""
        return self.function == "normal"  # and self.last_z is None
        # Commented second part of statement out because if it is set, then resetting the z-position is not possible
        # since the manipulators are filtered out


class touchDetect:
    MAX_CORRECTION_ATTEMPTS = 10  # maximum attempts to correct non-contacting manipulators
    MONITORING_DURATION = 2  # seconds, to monitor stability after initial contact
    APPROACH_MARGIN = 200  # microns, margin before last known position

    def __init__(self, log=None):
        # Store logging functions from GUI if provided
        self.log = log
        # Store last known Z positions for each manipulator
        self.last_z_positions = {}

    def _log(self, message):
        if self.log:
            self.log(message)

    def monitor_manual_contact_detection(
        self,
        mm: dict,
        smu: dict,
        con: dict,
        manipulator_infos: list[ManipulatorInfo],
        progress_callback=None,
        error_callback=None,
        stop_requested_callback=None,
    ) -> tuple[int, dict]:
        """
        Monitors for manual contact detection and saves Z positions to an internal dictionary.

        Args:
            mm: Micromanipulator methods dict
            smu: SMU methods dict
            con: Contact detection methods dict
            manipulator_infos: List of ManipulatorInfo objects to monitor
            progress_callback: Function to call with progress messages
            error_callback: Function to call with error messages
            stop_requested_callback: Function that returns True if stop is requested

        Returns:
            tuple[int, dict]: (status, result_dict)
        """
        try:
            self._log("Starting manual contact detection monitoring")

            # Connect to devices
            status, state = con["deviceConnect"]()
            if status != 0:
                if error_callback:
                    error_callback(f"Contact detection connection failed: {state}")
                return (status, {"Error message": f"Contact detection failed: {state}"})

            status_smu, state_smu = smu["smu_connect"]()
            if status_smu != 0:
                if error_callback:
                    error_callback(f"SMU connection failed: {state_smu}")
                return (status_smu, {"Error message": f"SMU failed: {state_smu}"})

            status_mm, state_mm = mm["mm_open"]()
            if status_mm != 0:
                if error_callback:
                    error_callback(f"Micromanipulator connection failed: {state_mm}")
                return (status_mm, {"Error message": f"MM failed: {state_mm}"})

            if progress_callback:
                progress_callback("All devices connected successfully")

            # Filter to only configured manipulators
            print(f"Manis inside low level {manipulator_infos}")
            configured_manipulators = [info for info in manipulator_infos if info.is_configured()]

            if not configured_manipulators:
                error_msg = "No configured manipulators found"
                if error_callback:
                    error_callback(error_msg)
                return (1, {"Error message": error_msg})

            # Process each configured manipulator
            for info in configured_manipulators:
                if stop_requested_callback and stop_requested_callback():
                    break

                self._log(f"Starting monitoring for manipulator {info.mm_number}")
                if progress_callback:
                    progress_callback(
                        f"Starting monitoring for manipulator {info.mm_number} (SMU: {info.smu_channel}, Con: {info.condet_channel}, Threshold: {info.threshold})"
                    )

                # Set up measurement for this manipulator
                status, state = self._manipulator_measurement_setup(mm, smu, con, info)
                if status != 0:
                    if error_callback:
                        error_callback(f"Failed to setup manipulator {info.mm_number}: {state}")
                    continue

                if progress_callback:
                    progress_callback(
                        f"MANUAL CONTROL: Move manipulator {info.mm_number} manually until contact is detected"
                    )
                    progress_callback(f"Monitoring resistance on {info.smu_channel} with threshold {info.threshold}...")

                # Monitor loop for this manipulator
                contact_detected = False
                last_resistance_log = None

                while not contact_detected and not (stop_requested_callback and stop_requested_callback()):
                    try:
                        contacting, r = self._contacting(smu, info)
                        if r < 0:
                            raise Exception("Keithley HW exception")

                        # Log resistance updates less frequently to avoid spam
                        if last_resistance_log is None or abs(r - last_resistance_log) > info.threshold * 0.1:
                            if progress_callback:
                                progress_callback(
                                    f"Manipulator {info.mm_number} resistance: {r:.1f} Ω (threshold: {info.threshold} Ω)"
                                )
                            last_resistance_log = r

                        if contacting:
                            # Contact detected! Save the z-position to both ManipulatorInfo and low-level storage
                            position_data = mm["mm_current_position"]()
                            x, y, z_position = position_data
                            info.last_z = int(z_position)
                            # Store in low-level dictionary for move_to_contact to use
                            self.last_z_positions[info.mm_number] = int(z_position)
                            self._log(f"Contact detected for manipulator {info.mm_number} at Z={z_position}")
                            if progress_callback:
                                progress_callback(
                                    f"Contact detected for manipulator {info.mm_number} at Z={z_position}"
                                )
                            contact_detected = True

                        time.sleep(0.1)

                    except Exception as e:
                        if error_callback:
                            error_callback(f"Exception during monitoring for manipulator {info.mm_number}: {str(e)}")
                        break

                # Clean up for this manipulator
                self._channels_off_single_manipulator(con, smu)

            if not (stop_requested_callback and stop_requested_callback()):
                saved_positions = {
                    info.mm_number: info.last_z for info in configured_manipulators if info.last_z is not None
                }
                if progress_callback:
                    progress_callback("Monitoring completed for all configured manipulators")
                    progress_callback(f"Saved positions: {saved_positions}")
                return (0, {"Error message": "Monitoring completed successfully", "saved_positions": saved_positions})
            else:
                if progress_callback:
                    progress_callback("Monitoring stopped by user")
                return (0, {"Error message": "Monitoring stopped by user"})

        except Exception as e:
            error_msg = f"Exception during monitoring: {str(e)}"
            self._log(error_msg)
            if error_callback:
                error_callback(error_msg)
            return (2, {"Error message": error_msg, "Exception": str(e)})

        finally:
            # Clean up
            try:
                self._channels_off(con, smu)
                if progress_callback:
                    progress_callback("Disconnected from all devices")
            except Exception:
                pass  # Ignore cleanup errors

    def _setup_and_move_to_contact(self, mm: dict, smu: dict, con: dict, info: ManipulatorInfo) -> tuple[int, dict]:
        """Helper method to setup measurement and move to contact for a single manipulator."""
        try:
            # Set up for resistance measurement
            status, state = self._manipulator_measurement_setup(mm, smu, con, info)
            if status != 0:
                return status, {"Error message": f"Failed to set up measurement: {state}"}

            # move to last known position
            status, state = self._move_manipulator_to_last_contact(mm, info)
            if status != 0:
                return status, {"Error message": f"Failed to move to last contact position: {state}"}

            # compute the maximum move distance for the initial move
            effective_max_distance = self.APPROACH_MARGIN + info.sample_width

            # move down until contact is detected
            status, result = self._move_until_contact(mm, smu, info, effective_max_distance)
            return status, result

        except Exception as e:
            return 1, {"Error message": f"Exception in setup and move: {str(e)}"}

    def move_to_contact(self, mm: dict, con: dict, smu: dict, manipulator_info: list[ManipulatorInfo]):
        """Moves the specified micromanipulators to contact with the sample.

        Implements iterative contact verification:
        1. Move all manipulators to initial contact
        2. Check which manipulators are still in contact
        3. Move non-contacting manipulators further toward sample
        4. Monitor all contacts for stability before confirming success

        Args:
            mm (dict): micromanipulator methods dict
            con (dict): contact detection switcher methods dict
            smu (dict): smu methods dict
            manipulator_info (list[ManipulatorInfo]): list of ManipulatorInfo objects
        Returns:
            tuple: (status_code, result_dict)
        """
        try:
            self._log("Starting move_to_contact operation")

            # connect devices
            status, state = con["deviceConnect"]()
            status_smu, state_smu = smu["smu_connect"]()
            status_mm, state_mm = mm["mm_open"]()

            assert status == 0, f"Contact detection connection failed: {state}"
            assert status_smu == 0, f"SMU connection failed: {state_smu}"
            assert status_mm == 0, f"Micromanipulator connection failed: {state_mm}"
            # remove manipulators from the list with no configuration
            manipulator_info = [info for info in manipulator_info if info.is_configured()]

            # Populate last_z positions from stored data and validate
            for info in manipulator_info:
                if info.mm_number in self.last_z_positions:
                    info.last_z = self.last_z_positions[info.mm_number]
                    self._log(f"Loaded stored z position for manipulator {info.mm_number}: {info.last_z}")
                elif info.function == "normal":
                    # Normal manipulators require a stored z position
                    error_msg = f"Manipulator {info.mm_number} requires a stored z position from previous monitoring. Run manual monitoring first."
                    self._log(error_msg)
                    return (1, {"Error message": error_msg})

            # remove manipulators with invalid configurations:
            validated = []
            for info in manipulator_info:
                errors = info.validate()
                if errors:
                    self._log(f"Manipulator {info.mm_number} has validation errors: {errors}")
                else:
                    validated.append(info)
            manipulator_info = validated
            self._log(f"Filtered manipulators to {len(manipulator_info)} valid configurations")

            # PHASE 1: Move all manipulators to initial contact
            self._log("PHASE 1: Moving all manipulators to initial contact")

            for info in manipulator_info:
                self._log(
                    f"Processing manipulator {info.mm_number} with threshold {info.threshold}, stride {info.stride}, max distance {info.sample_width}"
                )
                status, result = self._setup_and_move_to_contact(mm, smu, con, info)
                assert status == 0, f"Failed to move manipulator {info.mm_number} to contact: {result}"

            # PHASE 2: Iterative contact verification and correction
            self._log("PHASE 2: Starting iterative contact verification")

            correction_attempt = 0
            while correction_attempt < self.MAX_CORRECTION_ATTEMPTS:
                correction_attempt += 1
                self._log(f"Contact verification attempt {correction_attempt}/{self.MAX_CORRECTION_ATTEMPTS}")

                # Check which manipulators are currently contacting
                uncontacting = self._get_uncontacting(smu, con, mm, manipulator_info)

                if not uncontacting:
                    self._log("All configured manipulators are contacting")
                    break

                self._log(
                    f"Found {len(uncontacting)} non-contacting manipulators: {[m.mm_number for m in uncontacting]}"
                )

                # Move non-contacting manipulators further toward sample
                for info in uncontacting:
                    self._log(f"Correcting contact for manipulator {info.mm_number}")

                    status, state = self._manipulator_measurement_setup(mm, smu, con, info)
                    assert status == 0, f"Failed to set up measurement for manipulator {info.mm_number}: {state}"

                    correction_max_distance = info.stride * 8  # Limited correction distance

                    # move until contact is detected using the method that does not use the last known position
                    status, result = self._move_until_contact(mm, smu, info, correction_max_distance)
                    if status == 0:
                        self._log(f"Manipulator {info.mm_number} corrected successfully, starting monitoring")
                        # After moving, monitor stability for a few seconds
                        stable = self._monitor_contact_stability(smu, info, duration_seconds=self.MONITORING_DURATION)
                        if stable:
                            self._log(f"Manipulator {info.mm_number} contact is stable after correction")
                    else:
                        self._log(f"Failed to correct contact for manipulator {info.mm_number}: {result}")

            # ADD LOGIC TO MOVE THE SPECTEROMETER DOWN
            self._log("Move to contact operation completed successfully - all contacts verified and stable")
            return (0, {"Error message": "OK"})

        except Exception as e:
            error_msg = f"Exception in move_to_contact: {str(e)}"
            self._log(error_msg)
            return (2, {"Error message": "exception in move_to_contact", "exception": str(e)})
        finally:
            self._channels_off(con, smu)

    def _monitor_contact_stability(self, smu: dict, info: ManipulatorInfo, duration_seconds: int) -> bool:
        """
        Monitors contact stability for a specified duration after initial contact detection.

        Args:
            smu: SMU method dictionary
            channel: SMU channel to measure
            threshold: resistance threshold for contact detection
            duration_seconds: how long to monitor for stability

        Returns:
            bool: True if contact remained stable for the entire duration, False otherwise
        """

        self._log(f"Monitoring contact stability for {duration_seconds} seconds...")
        start_time = time.time()
        measurements = []

        while time.time() - start_time < duration_seconds:
            contacting, r = self._contacting(smu, info)

            measurements.append(contacting)

            if not contacting:
                self._log(f"Contact lost during stability monitoring after {time.time() - start_time:.1f} seconds")
                return False

            # Small delay between measurements
            time.sleep(0.1)

        self._log(f"Contact remained stable for {duration_seconds} seconds ({len(measurements)} measurements)")
        return True

    def _calculate_adaptive_stride(self, base_stride: int, latest_resistance: float) -> int:
        """Calculate adaptive stride"""
        adaptive_stride = base_stride  # Default to base stride
        if latest_resistance < 20:
            adaptive_stride = max(1, base_stride // 4)  # must be close to contact, move slowly
        time.sleep(0.05)  # Small delay to slow everything down
        return adaptive_stride

    def _contacting(self, smu: dict, info: ManipulatorInfo):
        """Check resistance between manipulator probes

        Args:
            smu (object): smu
            info (ManipulatorInfo): manipulator information
        Returns:
            tuple of (0, bool) when successful, (code, status) with errors
        """
        status, r = smu["smu_resmes"](info.smu_channel)
        assert status == 0, f"Failed to measure resistance on channel {info.smu_channel}: {r}"

        self._log(f"Measured resistance: {r} Ω, threshold: {info.threshold} Ω")
        # assert correct types
        assert isinstance(r, (int, float)), f"Invalid resistance type: {type(r)}"
        assert isinstance(info.threshold, (int, float)), f"Invalid threshold type: {type(info.threshold)}"

        if r < info.threshold:
            self._log(f"Contact detected! Resistance {r} below threshold {info.threshold}")
            return True, r
        return False, r

    def _get_uncontacting(self, smu: dict, con: dict, mm: dict, mi: list[ManipulatorInfo]) -> list[ManipulatorInfo]:
        """Check contact status for all manipulators and return a list of booleans.

        Args:
            smu: SMU method dict
            con: contact detection method dict
            manipulator_info: list of ManipulatorInfo objects

        Returns:
            list[ManipulatorInfo]:
        """
        contact_status = []

        for info in mi:
            status, state = self._manipulator_measurement_setup(mm, smu, con, info)
            assert status == 0, f"Failed to set up measurement for manipulator {info.mm_number}: {state}"

            try:
                contacting = self._monitor_contact_stability(smu, info, duration_seconds=self.MONITORING_DURATION)
                if not contacting:
                    self._log(f"Manipulator {info.mm_number} not contacting (above threshold)")
                    contact_status.append(info)
                else:
                    self._log(f"Manipulator {info.mm_number} is contacting")

            except Exception as e:
                self._log(f"Error checking contact for manipulator {info.mm_number}: {str(e)}")
                contact_status.append(info)

        return contact_status

    def _move_until_contact(
        self, mm: dict, smu: dict, manipulator_info: ManipulatorInfo, max_distance_to_move: float
    ) -> tuple[int, dict]:
        """Move the manipulator until contact is detected or the maximum distance is exceeded.

        Args:
            mm (dict): Micromanipulator methods dict
            smu (dict): SMU methods dict
            manipulator_info (ManipulatorInfo): Manipulator information
            max_distance_to_move (float): Maximum distance to move the manipulator

        Returns:
            tuple[int, dict]: Status code and additional information
        """
        total_distance = 0
        # Move until initial contact is detected
        contacting, r = self._contacting(smu, manipulator_info)
        while not contacting:
            if total_distance > max_distance_to_move:
                error_msg = f"Maximum distance {max_distance_to_move} exceeded for manipulator {manipulator_info.mm_number} (moved {total_distance})"
                return (3, {"Error message": error_msg})

            # Calculate adaptive stride based on proximity to last known position
            current_stride = self._calculate_adaptive_stride(manipulator_info.stride, r)

            status, state = mm["mm_zmove"](current_stride)
            assert status == 0, f"Z-move failed: {state}"
            self._log(
                f"Moving manipulator {manipulator_info.mm_number} down by {current_stride} microns (total moved: {total_distance + current_stride})"
            )

            total_distance += current_stride
            contacting, r = self._contacting(smu, manipulator_info)
        # Initial contact detected! Return success
        return (0, {"Error message": "OK"})

    def _move_manipulator_to_last_contact(self, mm: dict, manipulator_info: ManipulatorInfo) -> tuple[int, dict]:
        """Does no error checking, just assumes that the ManipulatorInfo is already validated in public functions. Moves the manipulator to the last known contact position + APPROACH_MARGIN.

        Args:
            mm (dict): Micromanipulator methods dict
            manipulator_info (ManipulatorInfo): Manipulator information

        Returns:
            tuple[int, dict]: Status code and additional information
        """

        last_position = manipulator_info.last_z
        last_position = last_position - self.APPROACH_MARGIN  # Move down to approach margin
        self._log(f"Moving manipulator {manipulator_info.mm_number} to last contact position {last_position}")
        status, result = mm["mm_move"](z=last_position)
        if status != 0:
            return (status, result)
        return (
            0,
            {"Error message": "OK"},
        )

    def _manipulator_measurement_setup(self, mm: dict, smu: dict, con: dict, mi: ManipulatorInfo) -> tuple[int, dict]:
        """Set up SMU for resistance measurement on a specific manipulator channel."""
        try:
            # setup smu for resistance measurement
            smu_status, smu_state = smu["smu_setup_resmes"](mi.smu_channel)
            assert smu_status == 0, f"Failed to setup SMU for manipulator {mi.mm_number}: {smu_state}"

            # set active manipulator
            mm_status, mm_state = mm["mm_change_active_device"](mi.mm_number)
            assert mm_status == 0, f"Failed to change active device for manipulator {mi.mm_number}: {mm_state}"

            # setup contact detection channel
            con["deviceLoCheck"](False)
            con["deviceHiCheck"](False)
            if mi.condet_channel == "Hi":
                con["deviceHiCheck"](True)
            elif mi.condet_channel == "Lo":
                con["deviceLoCheck"](True)
            else:
                raise ValueError(f"Invalid contact detection channel {mi.condet_channel}")

            return (0, {"Error message": f"SMU setup successful for manipulator {mi.mm_number}"})
        except Exception as e:
            return (1, {"Error message": f"Error setting up SMU for manipulator {mi.mm_number}: {str(e)}"})

    def _channels_off(self, con: dict, smu: dict):
        """Cleanup function to reset contact detection and SMU state."""
        try:
            con["deviceLoCheck"](False)
            con["deviceHiCheck"](False)
            smu["smu_outputOFF"]()
            smu["smu_disconnect"]()
            con["deviceDisconnect"]()
            self._log("Cleanup completed successfully")

        except Exception as e:
            self._log(f"Error during cleanup: {str(e)}")

    def _channels_off_single_manipulator(self, con: dict, smu: dict):
        """Cleanup function for a single manipulator without disconnecting devices."""
        try:
            con["deviceLoCheck"](False)
            con["deviceHiCheck"](False)
            smu["smu_outputOFF"]()
        except Exception as e:
            self._log(f"Error during single manipulator cleanup: {str(e)}")

    def verify_contact(self, mm: dict, smu: dict, con: dict, infos: list[ManipulatorInfo]) -> tuple[int, dict]:
        """Verifies contact for all manipulators."""
        self._log("Starting verify_contact operation")
        status_smu, state_smu = smu["smu_connect"]()
        status_con, state_con = con["deviceConnect"]()
        status_mm, state_mm = mm["mm_open"]()
        if any(s != 0 for s in [status_smu, status_con, status_mm]):
            return (2, {"Error message": "Verify contact failed to set up hardware"})
        stables = []
        for info in infos:
            stable = self._verify_contact_single(smu, con, mm, info)
            stables.append(stable)

        self._channels_off(con, smu)
        self._log("Verify contact operation completed successfully")
        for i, stable in enumerate(stables):
            if not stable:
                return (0, {"Error message": f"Manipulator {infos[i].mm_number} not in contact"})
        return (0, {"Error message": "Verify contact operation completed successfully"})

    def _verify_contact_single(self, smu: dict, con: dict, mm: dict, info: ManipulatorInfo) -> bool:
        """Verifies contact for a single manipulator."""
        self._log(f"Starting verify_contact for manipulator {info.mm_number}")

        status, state = self._manipulator_measurement_setup(mm, smu, con, info)
        if status != 0:
            return (status, state)

        stable = self._monitor_contact_stability(smu, info, self.MONITORING_DURATION)

        return stable
