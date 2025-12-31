#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Ultra Fast Remote Control Script - 10ms update interval
Read servo angles from one port -> Sync control to another port same ID servos
Ultra responsive version for minimal lag
"""

import sys
import os
import time
import argparse

# 添加SCServo SDK路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(project_root, 'scservo_sdk'))

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError as e:
    print(f"Error: Cannot import SCServo SDK: {e}")
    print("Please ensure scservo_sdk directory exists with necessary files")
    sys.exit(1)

# 引入端口工具
try:
    from port_utils import get_default_port, list_ports_for_user
except ImportError:
    print("Warning: port_utils not found, using fallback port detection")


class UltraFastRemoteControl:
    def __init__(self, read_port=None, control_port=None):
        # Auto-detect default ports using port_utils
        if read_port is None:
            read_port = get_default_port(0)  # First available port
        if control_port is None:
            control_port = get_default_port(1)  # Second available port
        self.master_port = read_port    # 纯读取角度
        self.slave_port = control_port  # 控制舵机
        self.baud_rate = 1000000
        self.servo_ids = [1, 2, 3, 4, 5, 6]  # 舵机ID范围
        self.running = False

        # 端口和处理器
        self.master_handler = None
        self.master_servo = None
        self.slave_handler = None
        self.slave_servo = None

    def connect_ports(self):
        """连接两个串口"""
        print("=" * 50)
        print("ULTRA FAST Remote Control System")
        print("=" * 50)

        # Connect COM7 (Master - Read Only)
        print(f"Connecting to {self.master_port} (read angles only)...")
        try:
            self.master_handler = PortHandler(self.master_port)
            if not self.master_handler.openPort():
                print(f"X Cannot open {self.master_port}")
                return False

            if not self.master_handler.setBaudRate(self.baud_rate):
                print(f"X Cannot set baud rate for {self.master_port}")
                self.master_handler.closePort()
                return False

            self.master_servo = sms_sts(self.master_handler)
            print(f"+ {self.master_port} connected successfully")
        except Exception as e:
            print(f"X {self.master_port} connection error: {e}")
            return False

        # Connect COM8 (Slave)
        print(f"Connecting to {self.slave_port} (control servos)...")
        try:
            self.slave_handler = PortHandler(self.slave_port)
            if not self.slave_handler.openPort():
                print(f"X Cannot open {self.slave_port}")
                self.master_handler.closePort()
                return False

            if not self.slave_handler.setBaudRate(self.baud_rate):
                print(f"X Cannot set baud rate for {self.slave_port}")
                self.slave_handler.closePort()
                self.master_handler.closePort()
                return False

            self.slave_servo = sms_sts(self.slave_handler)
            print(f"+ {self.slave_port} connected successfully")
        except Exception as e:
            print(f"X {self.slave_port} connection error: {e}")
            self.master_handler.closePort()
            return False

        return True

    def scan_servos(self):
        """Scan servos"""
        print("\nScanning servos...")
        master_found = []
        slave_found = []

        # Scan master port servos
        for servo_id in self.servo_ids:
            try:
                model_number, result, error = self.master_servo.ping(servo_id)
                if result == COMM_SUCCESS:
                    master_found.append(servo_id)
                    print(f"  {self.master_port}: Found servo ID:{servo_id} Model:{model_number}")
            except:
                continue

        # Scan slave port servos
        for servo_id in self.servo_ids:
            try:
                model_number, result, error = self.slave_servo.ping(servo_id)
                if result == COMM_SUCCESS:
                    slave_found.append(servo_id)
                    print(f"  {self.slave_port}: Found servo ID:{servo_id} Model:{model_number}")
            except:
                continue

        print(f"\nScan Results:")
        print(f"  {self.master_port} found servos: {master_found}")
        print(f"  {self.slave_port} found servos: {slave_found}")

        return master_found, slave_found

    def read_servo_angle(self, servo_id):
        """Read single servo angle"""
        try:
            position, result, error = self.master_servo.ReadPos(servo_id)
            if result == COMM_SUCCESS:
                return position
        except:
            pass
        return None

    def write_servo_angle(self, servo_id, angle):
        """Write single servo angle - Ultra fast settings"""
        try:
            result, error = self.slave_servo.WritePosEx(servo_id, angle, 3000, 100)  # speed 3000, acceleration 100 (ultra fast)
            return result == COMM_SUCCESS
        except:
            return False

    def set_slave_torque_on(self):
        """设置从控端口所有舵机有力矩"""
        print(f"\nSetting all servos on {self.slave_port} to FULL torque (ready for control)...")
        for servo_id in self.servo_ids:
            try:
                # 先ping检测舵机是否存在
                model_number, result, error = self.slave_servo.ping(servo_id)
                if result == COMM_SUCCESS:
                    torque_value = 1
                    result, error = self.slave_servo.write1ByteTxRx(servo_id, 40, torque_value)  # SMS_STS_TORQUE_ENABLE = 40
                    if result == COMM_SUCCESS:
                        print(f"  + ID{servo_id}: Torque ON (ready for control)")
                    else:
                        print(f"  X ID{servo_id}: Failed to set torque ON")
            except:
                continue

    def run_ultra_fast_control(self):
        """Run ultra fast remote control"""
        print("\nStarting ULTRA FAST remote control...")
        print("Press Ctrl+C to stop")
        print("Ultra Performance Mode: 10ms update interval (100Hz) for MINIMAL LAG")
        print("-" * 50)

        # 只设置COM8力矩状态，COM7只读不操作
        self.set_slave_torque_on()
        print(f"\nNOTE: {self.master_port} is READ ONLY - no operations performed")
        print(f"NOTE: {self.slave_port} is WRITE MODE - ready for control")

        self.running = True
        loop_count = 0
        last_display_time = time.time()
        display_interval = 2.0  # 每2秒显示一次状态，减少日志开销

        try:
            while self.running:
                loop_count += 1
                sync_count = 0
                start_time = time.time()

                # 快速读取和同步所有舵机
                for servo_id in self.servo_ids:
                    # Read COM7 servo angle
                    angle = self.read_servo_angle(servo_id)

                    if angle is not None:
                        # Sync to COM8 servo - 立即执行
                        success = self.write_servo_angle(servo_id, angle)
                        if success:
                            sync_count += 1

                # 只在指定间隔显示状态，最小化日志开销
                current_time = time.time()
                if current_time - last_display_time >= display_interval:
                    fps = loop_count / display_interval
                    print(f"[{time.strftime('%H:%M:%S')}] Ultra Fast Sync: {fps:.1f} Hz | Active: {sync_count} servos")
                    last_display_time = current_time
                    loop_count = 0  # 重置计数器

                # 超快响应：10ms更新间隔 (100Hz)
                # 动态调整：如果处理时间过长，减少延迟
                processing_time = time.time() - start_time
                sleep_time = max(0.001, 0.01 - processing_time)  # 最小1ms，确保稳定运行
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n\nUser stopped control")
        except Exception as e:
            print(f"\nControl error: {e}")

    def disconnect_ports(self):
        """Disconnect ports"""
        print("\nDisconnecting...")
        try:
            if self.master_handler:
                self.master_handler.closePort()
                print(f"+ {self.master_port} disconnected")
        except:
            pass

        try:
            if self.slave_handler:
                self.slave_handler.closePort()
                print(f"+ {self.slave_port} disconnected")
        except:
            pass

    def run(self):
        """Run complete process"""
        try:
            # Connect ports
            if not self.connect_ports():
                return

            # Scan servos
            master_found, slave_found = self.scan_servos()

            if not master_found:
                print(f"\nX No servos found on {self.master_port}, exiting")
                return

            if not slave_found:
                print(f"\n! No servos found on {self.slave_port}, but continuing")

            print(f"\n+ Ultra Fast System ready, starting remote control...")
            print(f"   Master port: {self.master_port} ({len(master_found)} servos)")
            print(f"   Slave port: {self.slave_port} ({len(slave_found)} servos)")
            print(f"   Response Rate: UP TO 100Hz for minimal lag")

            # Start ultra fast remote control
            self.run_ultra_fast_control()

        except Exception as e:
            print(f"X Runtime error: {e}")
        finally:
            # Disconnect
            self.disconnect_ports()


def main():
    """Main function"""
    # 解析命令行参数
    default_read = get_default_port(0) or "/dev/ttyUSB0"
    default_control = get_default_port(1) or "/dev/ttyUSB1"

    parser = argparse.ArgumentParser(description='Ultra Fast Remote Control System')
    parser.add_argument('--read-port', default=default_read, help=f'Port for reading servo angles (default: {default_read})')
    parser.add_argument('--control-port', default=default_control, help=f'Port for controlling servos (default: {default_control})')

    args = parser.parse_args()

    print("ULTRA FAST Remote Control System v1.0")
    print(f"Function: Read servo angles from {args.read_port} -> Sync control to {args.control_port}")
    print("Performance: 10ms update interval for MINIMAL LAG")
    print("Author: Assistant")
    print()

    remote_control = UltraFastRemoteControl(
        read_port=args.read_port,
        control_port=args.control_port
    )
    remote_control.run()


if __name__ == "__main__":
    main()