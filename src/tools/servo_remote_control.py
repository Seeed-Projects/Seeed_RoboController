#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
舵机同步遥控系统 - 双端口实时同步控制
Servo Sync Remote Control - Dual port real-time sync control

功能 / Feature:
  从主控端口读取舵机角度 → 同步控制从控端口的同ID舵机
  Read angles from master port → Sync control to slave port same ID servos

用法 / Usage:
    python servo_remote_control.py                          # 交互式选择端口 / Interactive port selection
    python servo_remote_control.py --list                    # 列出可用端口 / List available ports
    python servo_remote_control.py --read-port <port> \
                                     --control-port <port>  # 指定端口 / Specify ports

性能 / Performance:
  - 10ms 更新间隔 (100Hz) 实现最小延迟
  - 10ms update interval for MINIMAL LAG
"""

import sys
import os
import time
import argparse
from typing import Optional

# 引入 SDK
sys.path.append('../..')
sys.path.append('../../scservo_sdk')

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError as e:
    print(f"❌ 错误: 无法导入 SCServo SDK: {e}")
    print("   Error: Cannot import SCServo SDK")
    sys.exit(1)

# 引入端口工具
try:
    from src.port_utils import select_port_interactive, get_available_ports, list_ports_for_user
except ImportError:
    print("❌ 错误: 未找到 port_utils")
    print("   Error: port_utils not found")
    sys.exit(1)

# === 配置常量 ===
BAUD_RATE = 1000000
UPDATE_INTERVAL = 0.01  # 10ms = 100Hz
DISPLAY_INTERVAL = 2.0   # 每2秒显示一次状态
SMS_STS_TORQUE_ENABLE = 40
TORQUE_ON = 1
SERVO_SPEED = 3000  # 超快速度
SERVO_ACCEL = 100   # 加速度


class SyncRemoteControl:
    """同步遥控系统 - 双端口舵机实时同步"""

    def __init__(self, read_port: str, control_port: str):
        self.read_port = read_port      # 主控端口（只读角度）
        self.control_port = control_port  # 从控端口（控制舵机）
        self.running = False

        # 端口处理器
        self.read_handler = None
        self.control_handler = None
        self.read_servo = None
        self.control_servo = None

    def connect(self) -> bool:
        """连接两个串口"""
        print(f"\n{'='*55}")
        print(f"🎮 舵机同步遥控系统 / Servo Sync Remote Control")
        print(f"{'='*55}")
        print(f"主控端口 / Master Port (只读/Read):  {self.read_port}")
        print(f"从控端口 / Slave Port (控制/Control): {self.control_port}")
        print(f"{'='*55}\n")

        # 连接主控端口（只读）
        print(f"📡 连接主控端口 / Connecting master port...")
        try:
            self.read_handler = PortHandler(self.read_port)
            if not self.read_handler.openPort():
                print(f"❌ 无法打开 / Cannot open {self.read_port}")
                return False
            if not self.read_handler.setBaudRate(BAUD_RATE):
                print(f"❌ 无法设置波特率 / Cannot set baud rate")
                self.read_handler.closePort()
                return False
            self.read_servo = sms_sts(self.read_handler)
            print(f"✅ 主控端口已连接 / Master port connected\n")
        except Exception as e:
            print(f"❌ 主控端口异常 / Master port error: {e}")
            return False

        # 连接从控端口（控制）
        print(f"📡 连接从控端口 / Connecting control port...")
        try:
            self.control_handler = PortHandler(self.control_port)
            if not self.control_handler.openPort():
                print(f"❌ 无法打开 / Cannot open {self.control_port}")
                self.read_handler.closePort()
                return False
            if not self.control_handler.setBaudRate(BAUD_RATE):
                print(f"❌ 无法设置波特率 / Cannot set baud rate")
                self.control_handler.closePort()
                self.read_handler.closePort()
                return False
            self.control_servo = sms_sts(self.control_handler)
            print(f"✅ 从控端口已连接 / Control port connected\n")
        except Exception as e:
            print(f"❌ 从控端口异常 / Control port error: {e}")
            self.read_handler.closePort()
            return False

        return True

    def scan_servos(self) -> tuple:
        """扫描两个端口上的舵机"""
        print("📡 扫描舵机 / Scanning servos...\n")
        master_found = []
        slave_found = []

        # 扫描主控端口
        for servo_id in range(1, 21):
            model_number, result, error = self.read_servo.ping(servo_id)
            if result == COMM_SUCCESS:
                master_found.append(servo_id)
                print(f"  📖 主控 / Master: ID{servo_id} (型号/Model: {model_number})")

        # 扫描从控端口
        for servo_id in range(1, 21):
            model_number, result, error = self.control_servo.ping(servo_id)
            if result == COMM_SUCCESS:
                slave_found.append(servo_id)
                print(f"  🎮 从控 / Slave:  ID{servo_id} (型号/Model: {model_number})")

        print()
        print(f"📊 扫描结果 / Scan Results:")
        print(f"   主控端口 / Master: {master_found}")
        print(f"   从控端口 / Slave:  {slave_found}")

        return master_found, slave_found

    def enable_control_torque(self, servo_ids: list) -> int:
        """启动力矩"""
        print(f"\n⚡ 启动力矩 / Enabling torque...")
        enabled_count = 0

        for servo_id in servo_ids:
            result, error = self.control_servo.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, TORQUE_ON)
            if result == COMM_SUCCESS:
                enabled_count += 1
            time.sleep(0.05)

        print(f"✅ {enabled_count}/{len(servo_ids)} 个舵机力矩已启动 / {enabled_count}/{len(servo_ids)} servos enabled\n")
        return enabled_count

    def run_sync_control(self, servo_ids: list):
        """运行同步控制循环"""
        print("=" * 50)
        print("🚀 启动同步控制 / Starting sync control")
        print("=" * 50)
        print(f"⏱️ 更新间隔 / Update interval: {UPDATE_INTERVAL*1000:.0f}ms ({1/UPDATE_INTERVAL:.0f}Hz)")
        print(f"📊 显示频率 / Display freq: 每{DISPLAY_INTERVAL}秒")
        print(f"⏹️ 按 Ctrl+C 停止 / Press Ctrl+C to stop")
        print("=" * 50)
        print(f"📖 主控端口 / Master: {self.read_port} (只读角度)")
        print(f"🎮 从控端口 / Slave:  {self.control_port} (控制舵机)")
        print("=" * 50)
        print()

        self.running = True
        loop_count = 0
        last_display_time = time.time()

        try:
            while self.running:
                loop_count += 1
                sync_count = 0
                start_time = time.time()

                # 快速读取并同步所有舵机
                for servo_id in servo_ids:
                    # 读取主控舵机角度
                    position, result, error = self.read_servo.ReadPos(servo_id)

                    if result == COMM_SUCCESS:
                        # 同步到从控舵机
                        result, error = self.control_servo.WritePosEx(
                            servo_id, position, SERVO_SPEED, SERVO_ACCEL
                        )
                        if result == COMM_SUCCESS:
                            sync_count += 1

                # 定期显示状态
                current_time = time.time()
                if current_time - last_display_time >= DISPLAY_INTERVAL:
                    fps = loop_count / DISPLAY_INTERVAL
                    print(f"📊 [{time.strftime('%H:%M:%S')}] 同步频率/Sync: {fps:.1f} Hz | "
                          f"活跃舵机/Active: {sync_count} 个/servos")
                    last_display_time = current_time
                    loop_count = 0

                # 精确的延迟控制
                processing_time = time.time() - start_time
                sleep_time = max(0.001, UPDATE_INTERVAL - processing_time)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n\n⏹️ 用户停止 / User stopped")

    def disconnect(self):
        """断开连接"""
        print("\n" + "=" * 50)
        print("🔌 断开连接 / Disconnecting...")
        print("=" * 50)

        try:
            if self.read_handler:
                self.read_handler.closePort()
                print(f"✅ 主控端口已断开 / Master disconnected")
        except:
            pass

        try:
            if self.control_handler:
                self.control_handler.closePort()
                print(f"✅ 从控端口已断开 / Slave disconnected")
        except:
            pass


def main():
    """主函数"""
    # 解析参数
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        print("=== 可用串口 / Available Serial Ports ===")
        print(list_ports_for_user())
        return

    # 获取可用端口
    ports = get_available_ports()
    if len(ports) < 2:
        print("❌ 错误: 需要至少2个串口设备 / Error: Need at least 2 serial ports")
        print(f"   当前可用 / Current available: {len(ports)} 个")
        print("\n可用端口列表 / Available ports:")
        print(list_ports_for_user())
        sys.exit(1)

    # 默认使用前两个端口
    default_read = ports[0].device
    default_control = ports[1].device

    # 命令行参数解析
    parser = argparse.ArgumentParser(
        description='舵机同步遥控系统 / Servo Sync Remote Control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例 / Examples:
  python servo_remote_control.py                    # 交互式选择 / Interactive
  python servo_remote_control.py --list              # 列出端口 / List ports
  python servo_remote_control.py --read-port /dev/cu.usbmodem1 \\
                                     --control-port /dev/cu.usbmodem2
        """
    )
    parser.add_argument('--read-port', default=default_read,
                       help=f'主控端口/读取角度 (默认: {default_read})')
    parser.add_argument('--control-port', default=default_control,
                       help=f'从控端口/控制舵机 (默认: {default_control})')

    # 如果没有提供参数，交互式选择
    if len(sys.argv) == 1:
        print(f"\n{'='*55}")
        print(f"🎮 舵机同步遥控系统 / Servo Sync Remote Control")
        print(f"{'='*55}")
        print()
        print(f"检测到 {len(ports)} 个可用串口 / Detected {len(ports)} available serial ports")
        print()
        print(list_ports_for_user())
        print()

        # 选择主控端口
        read_port = select_port_interactive("选择主控端口 (读取角度) / Select master port (read)")
        if not read_port:
            print("❌ 未选择端口 / No port selected")
            sys.exit(1)

        # 选择从控端口
        control_port = select_port_interactive("选择从控端口 (控制舵机) / Select control port (write)")
        if not control_port:
            print("❌ 未选择端口 / No port selected")
            sys.exit(1)
    else:
        args = parser.parse_args()
        read_port = args.read_port
        control_port = args.control_port

    # 创建控制器并运行
    controller = SyncRemoteControl(read_port, control_port)

    try:
        if not controller.connect():
            sys.exit(1)

        master_found, slave_found = controller.scan_servos()

        if not master_found:
            print(f"\n❌ 主控端口未发现舵机 / No servos on master port")
            sys.exit(1)

        # 取交集，只同步两个端口都存在的舵机
        sync_servos = list(set(master_found) & set(slave_found))

        if not sync_servos:
            print(f"\n❌ 两个端口没有相同ID的舵机 / No matching servo IDs on both ports")
            print(f"   主控端口 / Master: {master_found}")
            print(f"   从控端口 / Slave:  {slave_found}")
            sys.exit(1)

        print(f"\n✅ 将同步 {len(sync_servos)} 个舵机 / Will sync {len(sync_servos)} servos: {sync_servos}")
        print()

        controller.enable_control_torque(sync_servos)
        controller.run_sync_control(sync_servos)

    except Exception as e:
        print(f"\n❌ 运行异常 / Runtime error: {e}")
    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()
