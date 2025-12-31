#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Middle Value Calibration Script - STS Servo Middle Value Calibration Tool
Functions:
1. Connect port
2. Scan all servos
3. Disable all servos
4. Read current angles of all servos
5. Calibrate middle values (Set current position as 2048)
6. Center all servos (Move to 2048)
"""

import sys
import os
import time

# --- SDK Import Logic ---
# Add SCServo SDK path for standalone factory directory
sys.path.append('.')
sys.path.append('./scservo_sdk')

try:
    # Direct import from scservo_sdk - same as ez_tool.py
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
    print("SCServo SDK imported successfully")
except ImportError as e:
    print(f"Error: Cannot import SCServo SDK: {e}")
    print("Trying alternative import path...")

    try:
        # Alternative import path
        from port_handler import PortHandler
        from sms_sts import sms_sts
        from scservo_def import COMM_SUCCESS
        print("SCServo SDK imported successfully (alternative path)")
    except ImportError as e2:
        print(f"Error: Cannot import SCServo SDK (alternative): {e2}")

        # If import fails, define necessary constants
        COMM_SUCCESS = 0
        print("Using fallback mode with COMM_SUCCESS =", COMM_SUCCESS)

        # Create mock classes for testing
        class PortHandler:
            def __init__(self, port_name):
                self.port_name = port_name
            def openPort(self):
                return False
            def setBaudRate(self, rate):
                return False
            def closePort(self):
                pass

        class sms_sts:
            def __init__(self, handler):
                self.handler = handler
            def ping(self, servo_id):
                return 0, -1, 0
            def ReadPos(self, servo_id):
                return 0, -1, 0
            def write1ByteTxRx(self, servo_id, address, value):
                return -1, 0
            def unLockEprom(self, servo_id):
                return -1, 0
            def LockEprom(self, servo_id):
                return -1, 0
            def WritePosEx(self, servo_id, position, speed, acc):
                return -1, 0
# --- End SDK Import Logic ---

# 引入端口工具
try:
    from port_utils import get_default_port, list_ports_for_user
except ImportError:
    print("Warning: port_utils not found, using fallback port detection")
    def get_default_port(index=0):
        return None


# Define register addresses from documentation
SMS_STS_TORQUE_ENABLE = 40        # Address for Torque switch AND calibration
SMS_STS_TORQUE_ENABLE_VALUE = 1   # Value to enable torque
SMS_STS_TORQUE_DISABLE_VALUE = 0  # Value to disable torque
SMS_STS_CALIBRATE_MIDDLE_VALUE = 128 # **SPECIAL COMMAND: Set current pos as 2048**
SMS_STS_MIDDLE_POSITION = 2048    # **The correct middle position (center)**


class MiddleValueCalibrator:
    """STS Servo Middle Value Calibrator - Single Port Version"""

    def __init__(self, port_name: str = None):
        # Auto-detect default port using port_utils
        if port_name is None:
            port_name = get_default_port(0)
        # Port configuration - single port only
        self.port_name = port_name
        self.port_handler = None
        self.servo_handler = None

        self.baud_rate = 1000000
        self.servo_ids = [1, 2, 3, 4, 5, 6]  # Supported servo ID range

    def log(self, message: str):
        """Add log"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    def connect_port(self) -> bool:
        """Connect single port"""
        self.log(f"Connecting to {self.port_name}")

        try:
            self.port_handler = PortHandler(self.port_name)
            if not self.port_handler.openPort():
                self.log(f"X Cannot open {self.port_name}")
                return False
            if not self.port_handler.setBaudRate(self.baud_rate):
                self.log(f"X Cannot set baud rate for {self.port_name}")
                self.port_handler.closePort()
                return False
            self.servo_handler = sms_sts(self.port_handler)
            self.log(f"+ {self.port_name} connected successfully")
            return True
        except Exception as e:
            self.log(f"X {self.port_name} connection error: {e}")
            return False

    def disconnect_port(self):
        """Disconnect port"""
        self.log(f"Disconnecting {self.port_name}")
        try:
            if self.port_handler:
                self.port_handler.closePort()
                self.log(f"+ {self.port_name} disconnected")
        except:
            pass

    def scan_servos(self) -> list:
        """Scan all servos on single port with delay"""
        self.log(f"Scanning servos on {self.port_name} with delay...")
        found_servos = []

        for servo_id in self.servo_ids:
            try:
                self.log(f"  Scanning ID:{servo_id}...")
                model_number, result, error = self.servo_handler.ping(servo_id)
                if result == COMM_SUCCESS:
                    found_servos.append(servo_id)
                    self.log(f"  + {self.port_name}: Found servo ID:{servo_id} Model:{model_number}")
                else:
                    self.log(f"  - ID:{servo_id}: No response")
            except Exception as e:
                self.log(f"  X ID:{servo_id}: Error {e}")
                continue

            # Small delay between scans to avoid interference
            time.sleep(0.1)

        self.log(f"{self.port_name} scan complete - Found {len(found_servos)} servos: {found_servos}")
        return found_servos

    def disable_all_servos(self, servo_list: list) -> int:
        """Disable all servos on the port (set torque to 0)"""
        success_count = 0
        self.log(f"Disabling all {self.port_name} servos (torque OFF): {servo_list}")

        for servo_id in servo_list:
            try:
                self.log(f"  Disabling ID{servo_id}...")
                # Write 0 to Addr 40
                result, error = self.servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_TORQUE_DISABLE_VALUE)
                if result == COMM_SUCCESS:
                    success_count += 1
                    self.log(f"  + ID{servo_id}: Torque OFF (free to rotate)")
                else:
                    self.log(f"  X ID{servo_id}: Failed to set torque OFF (result: {result}, error: {error})")
            except Exception as e:
                self.log(f"  X ID{servo_id}: Exception during torque OFF: {e}")

            # Small delay between servos
            time.sleep(0.05)

        self.log(f"{self.port_name} torque disable complete: {success_count}/{len(servo_list)} servos")
        return success_count

    def read_servo_positions(self, servo_list: list) -> dict:
        """Read current angles of all servos on the port"""
        positions = {}
        self.log(f"Reading current angles of all {self.port_name} servos...")

        for servo_id in servo_list:
            try:
                self.log(f"  Reading ID{servo_id}...")
                position, result, error = self.servo_handler.ReadPos(servo_id)
                if result == COMM_SUCCESS:
                    positions[servo_id] = position
                    degrees = position * 360.0 / 4095.0
                    self.log(f"  + ID{servo_id}: {position:4d} ({degrees:6.1f}°)")
                else:
                    self.log(f"  X ID{servo_id}: Read failed (result: {result}, error: {error})")
            except Exception as e:
                self.log(f"  X ID{servo_id}: Read exception: {e}")

            # Small delay between reads
            time.sleep(0.05)

        self.log(f"{self.port_name} angle reading complete: {len(positions)}/{len(servo_list)} servos")
        return positions

    def write_middle_offset(self, servo_id: int) -> bool:
        """
        *** CORRECTED IMPLEMENTATION ***
        Write current angle as servo middle offset (2048)
        using the built-in servo command (Write 128 to Addr 40)
        """
        try:
            self.log(f"Calibrating {self.port_name} ID{servo_id} - Setting current position as NEW CENTER (2048)")

            # 1. Unlock EEPROM (Address 55) - crucial for saving the offset
            # The SDK's unLockEprom() handles writing 0 to Addr 55
            result, error = self.servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                self.log(f"  X EEPROM unlock failed: {error}")
                return False
            self.log("  + EEPROM unlocked (Addr 55=0)")
            time.sleep(0.1) # Wait for unlock

            # 2. Send the "Calibrate Current Position to 2048" command
            # This is: Write 128 to Address 40 (SMS_STS_TORQUE_ENABLE)
            result, error = self.servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_CALIBRATE_MIDDLE_VALUE)
            
            if result != COMM_SUCCESS:
                self.log(f"  X Calibration command (128 to Addr 40) failed: {error}")
                # Try to re-lock EPROM even if write fails
                self.servo_handler.LockEprom(servo_id)
                return False

            self.log("  + Calibration command sent. Servo now considers this position as 2048.")
            time.sleep(0.1) # Wait for EPROM write

            # 3. Re-lock EEPROM (Address 55)
            # The SDK's LockEprom() handles writing 1 to Addr 55
            result, error = self.servo_handler.LockEprom(servo_id)
            if result != COMM_SUCCESS:
                self.log(f"  ! EEPROM re-lock failed: {error}")
            else:
                self.log(f"  + EEPROM re-locked (Addr 55=1)")

            self.log(f"  + ID{servo_id}: Middle value calibration complete")
            return True

        except Exception as e:
            self.log(f"  X ID{servo_id}: Calibration exception: {e}")
            return False

    def calibrate_middle_values(self, servo_list: list) -> int:
        """
        *** MODIFIED ***
        Calibrate middle values for all servos on the port with interactive confirmation
        (No longer needs the positions dictionary)
        """
        self.log(f"Ready to calibrate {self.port_name} servo middle values...")

        # Display offset values for user confirmation
        print("\n" + "=" * 50)
        print("SETTING CURRENT POSITIONS AS NEW CENTER (2048):")
        print("=" * 50)
        print("This will write the *current* physical position of each servo")
        print("as its new '2048' center point.")
        print("Servos to be calibrated:")
        for servo_id in sorted(servo_list):
            print(f"  ID{servo_id}")
        print("=" * 50)

        # Ask user for confirmation
        try:
            confirm = input("\nWrite these offset values to EEPROM? (y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.log(f"User cancelled offset calibration for {self.port_name}")
                return 0
        except (EOFError, KeyboardInterrupt):
            self.log(f"User cancelled offset calibration for {self.port_name}")
            return 0

        self.log(f"User confirmed - Starting {self.port_name} servo middle value calibration...")

        success_count = 0
        # Iterate over the list of servos, not the old positions dictionary
        for servo_id in sorted(servo_list):
            if self.write_middle_offset(servo_id):
                success_count += 1

        self.log(f"{self.port_name} middle value calibration complete - Success: {success_count}/{len(servo_list)}")
        return success_count

    def center_servo(self, servo_id: int) -> bool:
        """Center single servo to middle position (2048) with torque enabled"""
        try:
            self.log(f"  Centering ID{servo_id}...")

            # Enable servo torque first
            result, error = self.servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_TORQUE_ENABLE_VALUE)
            if result != COMM_SUCCESS:
                self.log(f"    X ID{servo_id}: Failed to enable torque (result: {result}, error: {error})")
                return False

            self.log(f"    + ID{servo_id}: Torque enabled")

            # Small delay
            time.sleep(0.05)

            # Send center command (2048) - **CORRECTED FROM 2047**
            result, error = self.servo_handler.WritePosEx(servo_id, SMS_STS_MIDDLE_POSITION, 1000, 50)
            if result == COMM_SUCCESS:
                self.log(f"  + {self.port_name} ID{servo_id}: Center command sent ({SMS_STS_MIDDLE_POSITION})")
                return True
            else:
                self.log(f"    X ID{servo_id}: Center command failed (result: {result}, error: {error})")
        except Exception as e:
            self.log(f"    X ID{servo_id}: Centering exception: {e}")

        return False

    def center_all_servos(self, servo_list: list) -> int:
        """Center all servos on the port with torque enabled and interactive confirmation"""
        # Ask user for confirmation before centering
        print("\n" + "=" * 50)
        print("CENTERING SERVOS:")
        print("=" * 50)
        print(f"Will center the following {self.port_name} servos:")
        for servo_id in sorted(servo_list):
            print(f"  ID{servo_id}: Enable torque and move to center ({SMS_STS_MIDDLE_POSITION})")
        print("=" * 50)
        print(f"WARNING: Servos will move to center position ({SMS_STS_MIDDLE_POSITION})!")
        print("This is the test: If calibration worked, servos should NOT move.")
        print("=" * 50)

        try:
            confirm = input("\nCenter all servos now? (y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.log(f"User cancelled centering for {self.port_name}")
                return 0
        except (EOFError, KeyboardInterrupt):
            self.log(f"User cancelled centering for {self.port_name}")
            return 0

        self.log(f"User confirmed - Starting {self.port_name} all servos centering with torque enabled...")

        success_count = 0
        for servo_id in sorted(servo_list):
            if self.center_servo(servo_id):
                success_count += 1

            # Small delay between servos
            time.sleep(0.1)

        self.log(f"{self.port_name} centering complete: {success_count}/{len(servo_list)} servos")
        return success_count

    def run_interactive_calibration(self):
        """Run interactive middle value calibration process with step-by-step control"""
        print("=" * 60)
        print(f"Interactive Middle Value Calibration Tool - {self.port_name}")
        print("=" * 60)
        print("Step-by-step control - Each step requires confirmation")
        print("=" * 60)

        # 1. Connect port
        try:
            confirm = input(f"\nStep 1: Connect to {self.port_name}? (y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.log("User cancelled connection")
                return False
        except (EOFError, KeyboardInterrupt):
            self.log("User cancelled connection")
            return False

        if not self.connect_port():
            self.log("Connection failed, process terminated")
            return False

        # 2. Scan servos on port
        try:
            confirm = input(f"\nStep 2: Scan for servos on {self.port_name}? (y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.log("User cancelled scanning")
                self.disconnect_port()
                return False
        except (EOFError, KeyboardInterrupt):
            self.log("User cancelled scanning")
            self.disconnect_port()
            return False

        found_servos = self.scan_servos()
        if not found_servos:
            self.log("No servos found, process terminated")
            self.disconnect_port()
            return False

        # 3. Disable all servos on the port
        try:
            confirm = input(f"\nStep 3: Disable torque on {len(found_servos)} servos (free to rotate)? (y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.log("User skipped torque disable")
            else:
                self.disable_all_servos(found_servos)
                time.sleep(1)
        except (EOFError, KeyboardInterrupt):
            self.log("User skipped torque disable")

        # 4. Read current angles of all servos on the port
        # (This is just for user info, not strictly required for new calibration)
        try:
            confirm = input(f"\nStep 4: Read current angles of {len(found_servos)} servos? (y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.log("User skipped angle reading")
            else:
                self.read_servo_positions(found_servos)
        except (EOFError, KeyboardInterrupt):
            self.log("User skipped angle reading")

        # 5. Calibrate middle values for all servos on the port
        # *** MODIFIED ***
        calibrate_success = 0
        try:
            confirm = input(f"\nStep 5: Proceed with offset calibration? (y/n): ").strip().lower()
            if confirm in ['y', 'yes']:
                # Call the modified function with the LIST of servos
                calibrate_success = self.calibrate_middle_values(found_servos)
                time.sleep(2)
            else:
                self.log("User skipped offset calibration")
        except (EOFError, KeyboardInterrupt):
            self.log("User skipped offset calibration")

        # 6. Center all servos on the port
        center_count = 0
        try:
            confirm = input(f"\nStep 6: Center {len(found_servos)} servos (will move!)? (y/n): ").strip().lower()
            if confirm in ['y', 'yes']:
                center_count = self.center_all_servos(found_servos)
            else:
                self.log("User skipped centering")
        except (EOFError, KeyboardInterrupt):
            self.log("User skipped centering")

        # Completion message
        self.log("\n" + "=" * 60)
        self.log("Interactive calibration process finished!")
        self.log(f"{self.port_name}: Found {len(found_servos)} servos, Calibrated {calibrate_success}, Centered {center_count}")
        self.log("Please observe if servos are correctly centered (i.e., did not move in Step 6)")
        self.log("=" * 60)

        return True

    def run_full_calibration(self):
        """Run complete middle value calibration process (non-interactive)"""
        print("=" * 60)
        print(f"Auto Middle Value Calibration Tool - {self.port_name}")
        print("=" * 60)
        print("Automatic execution - No interactive prompts")
        print("=" * 60)

        # 1. Connect port
        if not self.connect_port():
            self.log("Connection failed, process terminated")
            return False

        # 2. Scan servos on port
        found_servos = self.scan_servos()
        if not found_servos:
            self.log("No servos found, process terminated")
            self.disconnect_port()
            return False

        # 3. Disable all servos on the port
        self.log(f"\nStep 3: Disable all {self.port_name} servos")
        self.disable_all_servos(found_servos)
        time.sleep(1)
        
        print("\n" + "=" * 50)
        print("!!! MANUAL STEP !!!")
        print(f"Please manually move all servos ({found_servos}) to their desired center positions.")
        input("Press Enter when ready to calibrate...")
        print("=" * 50)


        # 4. Read current angles (Optional, for logging)
        self.log(f"\nStep 4: Read current angles of all {self.port_name} servos (for info)")
        self.read_servo_positions(found_servos)

        # 5. Calibrate middle values
        # *** MODIFIED ***
        self.log(f"\nStep 5: Calibrate middle values for all {self.port_name} servos")
        calibrate_success = 0
        if found_servos:
             # Call the modified function with the LIST of servos
            calibrate_success = self.calibrate_middle_values(found_servos)
        else:
            self.log(f"{self.port_name} no servos, skipping calibration")

        # Wait for calibration completion
        time.sleep(2)

        # 6. Center all servos on the port
        self.log(f"\nStep 6: Center all {self.port_name} servos (Test calibration)")
        center_count = 0
        if found_servos:
            center_count = self.center_all_servos(found_servos)
        else:
            self.log(f"{self.port_name} no servos, skipping centering")

        # Completion message
        self.log("\n" + "=" * 60)
        self.log("Auto calibration process finished!")
        self.log(f"{self.port_name}: Found {len(found_servos)} servos, Calibrated {calibrate_success}, Centered {center_count}")
        self.log("Please observe if servos are correctly centered (i.e., did not move in Step 6)")
        self.log("=" * 60)

        return True


def main():
    """Main function"""
    import sys

    # Auto-detect default port
    default_port = get_default_port(0)
    if not default_port:
        print("Error: No serial ports found!")
        print("Please connect a USB-to-Serial adapter and try again.")
        sys.exit(1)

    print("Middle Value Calibration Tool v2.1 (Corrected Logic)")
    print("Function: STS servo middle value calibration and centering")
    print(f"Method: Use built-in command (Write 128 to Addr 40) to set center as {SMS_STS_MIDDLE_POSITION}")
    print("Based: scservo_sdk SMS_STS protocol")
    print("=" * 50)
    print(f"\nAuto-detected port: {default_port}")
    print()

    # Get port from user input
    if len(sys.argv) > 1:
        port_name = sys.argv[1]
        print(f"Using port from command line: {port_name}")
    else:
        user_input = input(f"Press Enter to use {default_port}, or type a different port: ").strip()
        port_name = user_input if user_input else default_port
        print(f"Using port: {port_name}")

    # Ask user for mode selection
    print("\n" + "=" * 50)
    print("SELECT MODE:")
    print("=" * 50)
    print("1. Interactive mode - Step by step with confirmation")
    print("2. Auto mode - Asks for confirmation before each major step")
    print("=" * 50)

    try:
        mode_choice = input("Select mode (1=Interactive, 2=Auto): ").strip()
        if mode_choice == "1":
            interactive_mode = True
            print("Selected: Interactive mode")
        else:
            interactive_mode = False
            print("Selected: Auto mode (default)")
    except (EOFError, KeyboardInterrupt):
        interactive_mode = False
        print("Using: Auto mode (default)")

    print("=" * 50)

    calibrator = MiddleValueCalibrator(port_name)

    try:
        if interactive_mode:
            # Run interactive calibration process
            success = calibrator.run_interactive_calibration()
        else:
            # Run "automatic" calibration process
            # Note: This modified auto-mode still has user confirmation prompts
            # inside calibrate_middle_values() and center_all_servos()
            # It also has a manual 'Press Enter' step
            success = calibrator.run_full_calibration()

        if success:
            input("\nProcess finished. Press Enter to exit...")
        else:
            input("\nProcess failed or cancelled. Press Enter to exit...")

    except KeyboardInterrupt:
        print("\nUser interrupted")
    except Exception as e:
        print(f"Runtime exception: {e}")
        input("Press Enter to exit...")
    finally:
        calibrator.disconnect_port()


if __name__ == "__main__":
    main()