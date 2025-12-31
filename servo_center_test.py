#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
舵机中位测试 - 启动舵机并移动到中位(2048)来测试校准结果
Servo Center Test - Enable servos and move to center(2048) to test calibration

用法 / Usage:
    python servo_center_test.py              # 交互式选择端口 / Interactive port selection
    python servo_center_test.py <port>       # 指定端口 / Specify port
    python servo_center_test.py --list       # 列出可用端口 / List available ports
"""

import sys
import os
import time
from typing import Optional

# 引入 SDK
sys.path.append('.')
sys.path.append('./scservo_sdk')

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
    from port_utils import select_port_interactive, get_available_ports, list_ports_for_user
except ImportError:
    print("❌ 错误: 未找到 port_utils")
    print("   Error: port_utils not found")
    sys.exit(1)

# === 配置常量 ===
BAUD_RATE = 1000000
MIDDLE_POSITION = 2048  # 正确的中位值
SERVO_ID_RANGE = [1, 2, 3, 4, 5, 6]
SMS_STS_TORQUE_ENABLE = 40
TORQUE_ON = 1


def position_to_degrees(position: int) -> float:
    """将位置值转换为角度"""
    return position * 360.0 / 4096.0


def scan_servos(servo_handler) -> list:
    """扫描端口上的所有舵机"""
    found = []
    for servo_id in range(1, 21):
        model_number, result, error = servo_handler.ping(servo_id)
        if result == COMM_SUCCESS:
            found.append(servo_id)
    return found


def quick_center_test(port_name: str, target_position: int = MIDDLE_POSITION) -> bool:
    """
    快速中位测试 - 启动舵机并移动到中位

    Args:
        port_name: 串口名称
        target_position: 目标位置，默认2048（中位）

    Returns:
        bool: 测试是否成功
    """
    print(f"\n{'='*50}")
    print(f"🎯 舵机中位测试 / Servo Center Test")
    print(f"{'='*50}")
    print(f"端口 / Port: {port_name}")
    print(f"目标位置 / Target: {target_position}")
    print(f"{'='*50}\n")

    # 初始化端口
    try:
        port_handler = PortHandler(port_name)
        if not port_handler.openPort():
            print(f"❌ 无法打开串口 / Cannot open {port_name}")
            return False
        if not port_handler.setBaudRate(BAUD_RATE):
            print(f"❌ 无法设置波特率 / Cannot set baud rate")
            port_handler.closePort()
            return False

        servo_handler = sms_sts(port_handler)

        # Step 1: 扫描舵机
        print("📡 扫描舵机 / Scanning servos...")
        found_servos = scan_servos(servo_handler)

        if not found_servos:
            print("❌ 未发现舵机 / No servos found")
            port_handler.closePort()
            return False

        print(f"✅ 发现 {len(found_servos)} 个舵机 / Found {len(found_servos)} servo(s): {found_servos}\n")

    except Exception as e:
        print(f"❌ 初始化异常 / Init error: {e}")
        return False

    try:
        # Step 2: 读取当前位置
        print("📍 读取当前位置 / Reading current positions...")
        print("-" * 50)
        positions_before = {}

        for servo_id in found_servos:
            position, result, error = servo_handler.ReadPos(servo_id)
            if result == COMM_SUCCESS:
                positions_before[servo_id] = position
                degrees = position_to_degrees(position)
                print(f"  ID{servo_id}: {position:4d} ({degrees:6.1f}°)")
            time.sleep(0.05)

        print()

        # Step 3: 启动力矩
        print("⚡ 启动力矩 / Enabling torque...")
        enabled_count = 0

        for servo_id in found_servos:
            result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, TORQUE_ON)
            if result == COMM_SUCCESS:
                enabled_count += 1
            time.sleep(0.05)

        print(f"✅ {enabled_count}/{len(found_servos)} 个舵机力矩已启动 / {enabled_count}/{len(found_servos)} servos enabled")
        time.sleep(1)  # 等待力矩稳定

        # Step 4: 移动到中位
        print(f"\n🎯 移动到中位 ({target_position}) / Moving to center...")
        moved_count = 0

        for servo_id in found_servos:
            result, error = servo_handler.WritePosEx(servo_id, target_position, 1000, 50)
            if result == COMM_SUCCESS:
                moved_count += 1
            time.sleep(0.05)

        print(f"✅ {moved_count}/{len(found_servos)} 个舵机已发送命令 / {moved_count}/{len(found_servos)} servos commanded")
        print("\n⏳ 等待3秒... / Waiting 3 seconds...")
        time.sleep(3)

        # Step 5: 读取最终位置
        print("\n📍 读取最终位置 / Reading final positions...")
        print("-" * 50)

        for servo_id in found_servos:
            final_position, result, error = servo_handler.ReadPos(servo_id)
            if result == COMM_SUCCESS and servo_id in positions_before:
                movement = final_position - positions_before[servo_id]
                movement_degrees = position_to_degrees(movement)
                final_degrees = position_to_degrees(final_position)
                print(f"  ID{servo_id}: {final_position:4d} ({final_degrees:6.1f}°) [位移/movement: {movement:+4d} ({movement_degrees:+5.1f}°)]")
            time.sleep(0.05)

        print()
        print("=" * 50)
        print("✅ 测试完成 / Test complete!")
        print("=" * 50)
        print("💡 如果舵机保持在原位附近，说明校准成功")
        print("   If servos stayed near original positions, calibration is working correctly")
        print()
        print("💡 如果舵机移动了很大幅度，说明需要重新校准")
        print("   If servos moved significantly, recalibration is needed")
        print("=" * 50)

        # 力矩保持开启以便观察
        print("\n⚡ 力矩保持开启 / Torque stays enabled for observation")
        print("   按 Ctrl+C 退出 / Press Ctrl+C to exit")

        # 等待用户中断
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n⏹️ 用户中断 / User interrupted")
        return True
    except Exception as e:
        print(f"\n❌ 测试异常 / Test error: {e}")
        return False
    finally:
        try:
            port_handler.closePort()
        except:
            pass


def main():
    """主函数"""
    # 解析参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            print("=== 可用串口 / Available Serial Ports ===")
            print(list_ports_for_user())
            return
        else:
            port_name = sys.argv[1]
            print(f"🔌 使用指定端口 / Using specified port: {port_name}")
    else:
        # 交互式选择端口
        port_name = select_port_interactive("选择要测试的串口 / Select port to test")
        if not port_name:
            print("❌ 未选择端口 / No port selected")
            sys.exit(1)

    # 执行测试
    success = quick_center_test(port_name)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()