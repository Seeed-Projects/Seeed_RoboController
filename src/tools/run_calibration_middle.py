#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
根据 LeRobot 校准文件运行舵机到中位
Run servos to middle position based on LeRobot calibration file

用法 / Usage:
    python run_calibration_middle.py <calibration_file> <port> [--mode zero|range]
    
示例 / Examples:
    python run_calibration_middle.py ~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/my_awesome_leader_arm.json /dev/ttyACM0
    python run_calibration_middle.py ~/.cache/huggingface/lerobot/calibration/robots/so_follower/my_awesome_follower_arm.json /dev/ttyUSB0 --mode range
"""

import sys
import os
import time
import argparse
import io
from pathlib import Path

# 解决 Windows 下 stdout 被重定向到管道时使用 GBK 编码导致 emoji 输出报错
if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# 引入 SDK
sys.path.append('../..')
sys.path.append('../../scservo_sdk')

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError as e:
    print(f"❌ 错误: 无法导入 SCServo SDK: {e}")
    sys.exit(1)

# 引入端口工具
try:
    from src.port_utils import select_port_interactive, list_ports_for_user
except ImportError:
    print("❌ 错误: 未找到 port_utils")
    sys.exit(1)

# 引入校准文件管理器
try:
    from src.calibration_manager import CalibrationManager, JOINT_NAME_MAP
except ImportError:
    print("❌ 错误: 未找到 calibration_manager")
    sys.exit(1)


BAUD_RATE = 1000000
SMS_STS_TORQUE_ENABLE = 40
TORQUE_ON = 1
SERVO_SPEED = 1000
SERVO_ACCEL = 50


def load_calibration(calibration_path: str) -> dict:
    """加载校准文件"""
    manager = CalibrationManager()
    data = manager.load_calibration_file(calibration_path)
    if data is None:
        print(f"❌ 无法读取校准文件: {calibration_path}")
        sys.exit(1)
    return data


def compute_middle_positions(data: dict, mode: str = "zero") -> dict:
    """
    根据校准文件计算每个关节的中位值

    Args:
        data: 校准数据
        mode: "zero" 使用 homing_offset, "range" 使用 range 中点

    Returns:
        {joint_name: target_position}
    """
    middle_positions = {}
    for joint_name, joint_data in data.items():
        if mode == "zero":
            target = joint_data.get("homing_offset", 2048)
        elif mode == "range":
            range_min = joint_data.get("range_min", 0)
            range_max = joint_data.get("range_max", 4095)
            target = (range_min + range_max) // 2
        else:
            raise ValueError(f"未知模式: {mode}, 请选择 'zero' 或 'range'")

        # 确保在有效范围内
        target = max(0, min(4095, target))
        middle_positions[joint_name] = target

    return middle_positions


def scan_servos(servo_handler) -> list:
    """扫描端口上的所有舵机"""
    found = []
    for servo_id in range(1, 21):
        model_number, result, error = servo_handler.ping(servo_id)
        if result == COMM_SUCCESS:
            found.append(servo_id)
    return found


def run_to_middle(port_name: str, calibration_path: str, mode: str = "zero") -> bool:
    """
    根据校准文件将舵机移动到中位

    Args:
        port_name: 串口名称
        calibration_path: 校准文件路径
        mode: 中位计算模式

    Returns:
        是否成功
    """
    print(f"\n{'='*60}")
    print(f"🎯 校准文件中位运行工具 / Calibration Middle Position Runner")
    print(f"{'='*60}")
    print(f"校准文件 / Calibration: {calibration_path}")
    print(f"串口 / Port: {port_name}")
    print(f"中位模式 / Mode: {'校准零点 (homing_offset)' if mode == 'zero' else '范围中点 (range midpoint)'}")
    print(f"{'='*60}\n")

    # 加载校准文件
    data = load_calibration(calibration_path)
    middle_positions = compute_middle_positions(data, mode)

    print("📋 校准文件关节信息 / Joint info from calibration:")
    print("-" * 60)
    for joint_name, joint_data in data.items():
        display_name = JOINT_NAME_MAP.get(joint_name, joint_name)
        servo_id = joint_data.get("id", "N/A")
        homing_offset = joint_data.get("homing_offset", "N/A")
        range_min = joint_data.get("range_min", "N/A")
        range_max = joint_data.get("range_max", "N/A")
        target = middle_positions[joint_name]
        print(f"  {display_name}")
        print(f"    ID: {servo_id}, Homing Offset: {homing_offset}, Range: [{range_min}, {range_max}]")
        print(f"    → 目标中位 / Target: {target}")
    print("-" * 60)

    # 初始化串口
    try:
        port_handler = PortHandler(port_name)
        if not port_handler.openPort():
            print(f"❌ 无法打开串口 / Cannot open port: {port_name}")
            return False
        if not port_handler.setBaudRate(BAUD_RATE):
            print(f"❌ 无法设置波特率 / Cannot set baud rate")
            port_handler.closePort()
            return False

        servo_handler = sms_sts(port_handler)
        print(f"✅ 串口已连接 / Port connected: {port_name}\n")

    except Exception as e:
        print(f"❌ 串口初始化失败 / Port init failed: {e}")
        return False

    # 扫描舵机
    print("📡 扫描舵机 / Scanning servos...")
    found_servos = scan_servos(servo_handler)
    if not found_servos:
        print("❌ 未发现舵机 / No servos found")
        port_handler.closePort()
        return False
    print(f"✅ 发现舵机 / Found servos: {found_servos}\n")

    # 检查校准文件中的舵机是否都在线
    missing_ids = []
    for joint_name, joint_data in data.items():
        servo_id = joint_data.get("id")
        if servo_id not in found_servos:
            missing_ids.append((joint_name, servo_id))

    if missing_ids:
        print("⚠️ 以下校准文件中的舵机未在线 / Following servos from calibration not found:")
        for joint_name, servo_id in missing_ids:
            print(f"  {joint_name}: ID {servo_id}")
        print()

    try:
        # 启动力矩
        print("⚡ 启动力矩 / Enabling torque...")
        enabled_count = 0
        for joint_name, joint_data in data.items():
            servo_id = joint_data.get("id")
            if servo_id in found_servos:
                result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, TORQUE_ON)
                if result == COMM_SUCCESS:
                    enabled_count += 1
                time.sleep(0.05)
        print(f"✅ {enabled_count} 个舵机力矩已启动 / {enabled_count} servos enabled\n")
        time.sleep(0.5)

        # 移动到中位
        print("🎯 移动到中位 / Moving to middle positions...")
        print("-" * 60)
        moved_count = 0
        for joint_name, joint_data in data.items():
            servo_id = joint_data.get("id")
            target = middle_positions[joint_name]
            if servo_id in found_servos:
                result, error = servo_handler.WritePosEx(servo_id, target, SERVO_SPEED, SERVO_ACCEL)
                display_name = JOINT_NAME_MAP.get(joint_name, joint_name)
                if result == COMM_SUCCESS:
                    print(f"  ✅ ID{servo_id} ({display_name}) → {target}")
                    moved_count += 1
                else:
                    print(f"  ❌ ID{servo_id} ({display_name}) → 发送失败")
                time.sleep(0.05)
        print("-" * 60)
        print(f"✅ {moved_count} 个舵机已发送中位命令 / {moved_count} servos commanded\n")

        print("⏳ 等待2秒稳定... / Waiting 2 seconds to stabilize...")
        time.sleep(2)

        # 读取最终位置
        print("\n📍 最终位置 / Final positions:")
        print("-" * 60)
        for joint_name, joint_data in data.items():
            servo_id = joint_data.get("id")
            target = middle_positions[joint_name]
            if servo_id in found_servos:
                position, result, error = servo_handler.ReadPos(servo_id)
                display_name = JOINT_NAME_MAP.get(joint_name, joint_name)
                if result == COMM_SUCCESS:
                    diff = position - target
                    print(f"  ID{servo_id} ({display_name}): 当前 {position:4d} | 目标 {target:4d} | 偏差 {diff:+4d}")
                else:
                    print(f"  ID{servo_id} ({display_name}): 读取失败")
                time.sleep(0.05)
        print("-" * 60)

        print("\n✅ 中位运行完成 / Middle position running complete!")
        print("   按 Ctrl+C 退出 / Press Ctrl+C to exit")

        # 保持力矩开启
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n⏹️ 用户中断 / User interrupted")
        return True
    except Exception as e:
        print(f"\n❌ 运行异常 / Runtime error: {e}")
        return False
    finally:
        try:
            port_handler.closePort()
        except:
            pass


def main():
    parser = argparse.ArgumentParser(
        description='根据 LeRobot 校准文件运行舵机到中位',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
中位模式说明 / Mode explanation:
  zero  : 使用 homing_offset 作为中位（LeRobot 的零点）
  range : 使用 (range_min + range_max) / 2 作为中位（物理范围中点）
        """
    )
    parser.add_argument('calibration_file', help='LeRobot 校准文件路径')
    parser.add_argument('port', nargs='?', help='串口名称，不指定则交互式选择')
    parser.add_argument('--mode', choices=['zero', 'range'], default='zero',
                       help='中位计算模式（默认: zero）')
    parser.add_argument('--list', action='store_true', help='列出可用串口')

    args = parser.parse_args()

    if args.list:
        print("=== 可用串口 / Available Serial Ports ===")
        print(list_ports_for_user())
        return

    calibration_path = args.calibration_file
    if not os.path.exists(calibration_path):
        print(f"❌ 校准文件不存在 / Calibration file not found: {calibration_path}")
        sys.exit(1)

    if args.port:
        port_name = args.port
        print(f"🔌 使用指定端口 / Using specified port: {port_name}")
    else:
        port_name = select_port_interactive("选择要运行中位的串口 / Select port")
        if not port_name:
            print("❌ 未选择端口 / No port selected")
            sys.exit(1)

    success = run_to_middle(port_name, calibration_path, args.mode)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
