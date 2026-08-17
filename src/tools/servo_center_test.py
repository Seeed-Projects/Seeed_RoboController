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
sys.path.append('../..')
sys.path.append('../../scservo_sdk')

try:
    from src.i18n import tr
except ImportError:
    def tr(text):
        return text

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError as e:
    print(tr("❌ 错误: 无法导入 SCServo SDK: {}").format(e))
    print("   Error: Cannot import SCServo SDK")
    sys.exit(1)

# 引入端口工具
try:
    from src.port_utils import select_port_interactive, get_available_ports, list_ports_for_user
except ImportError:
    print(tr("❌ 错误: 未找到 port_utils"))
    print("   Error: port_utils not found")
    sys.exit(1)

# 引入中位校准工具中的状态读取辅助函数
try:
    from src.tools.servo_middle_calibration import (
        read_all_servo_info,
        print_servo_info_table,
        check_servo_health,
    )
except ImportError as e:
    print(tr("❌ 错误: 无法导入状态读取函数: {}").format(e))
    print("   Error: Cannot import status reader functions")
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
    print(tr("🎯 舵机中位测试 / Servo Center Test"))
    print(f"{'='*50}")
    print(tr("端口 / Port: {}").format(port_name))
    print(tr("目标位置 / Target: {}").format(target_position))
    print(f"{'='*50}\n")

    # 初始化端口
    try:
        port_handler = PortHandler(port_name)
        if not port_handler.openPort():
            print(tr("❌ 无法打开串口 / Cannot open {}").format(port_name))
            return False
        if not port_handler.setBaudRate(BAUD_RATE):
            print(tr("❌ 无法设置波特率 / Cannot set baud rate"))
            port_handler.closePort()
            return False

        servo_handler = sms_sts(port_handler)

        # Step 1: 扫描舵机
        print(tr("📡 扫描舵机 / Scanning servos..."))
        found_servos = scan_servos(servo_handler)

        if not found_servos:
            print(tr("❌ 未发现舵机 / No servos found"))
            port_handler.closePort()
            return False

        print(tr("✅ 发现 {} 个舵机 / Found {} servo(s): {}\n").format(len(found_servos), len(found_servos), found_servos))

    except Exception as e:
        print(tr("❌ 初始化异常 / Init error: {}").format(e))
        return False

    try:
        # Step 2: 读取当前位置与状态
        print(tr("📍 读取当前位置与状态 / Reading current positions and status..."))
        info_before = read_all_servo_info(servo_handler, found_servos)
        print_servo_info_table(info_before, tr("测试前状态 / Status Before Test"))
        check_servo_health(info_before)
        positions_before = {info["id"]: info["position"] for info in info_before if info["position"] is not None}

        # Step 3: 启动力矩
        print(tr("⚡ 启动力矩 / Enabling torque..."))
        enabled_count = 0

        for servo_id in found_servos:
            result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, TORQUE_ON)
            if result == COMM_SUCCESS:
                enabled_count += 1
            time.sleep(0.05)

        print(tr("✅ {}/{} 个舵机力矩已启动 / {}/{} servos enabled").format(enabled_count, len(found_servos), enabled_count, len(found_servos)))
        time.sleep(1)  # 等待力矩稳定

        # Step 4: 移动到中位
        print(tr("\n🎯 移动到中位 ({}) / Moving to center...").format(target_position))
        moved_count = 0

        for servo_id in found_servos:
            result, error = servo_handler.WritePosEx(servo_id, target_position, 1000, 50)
            if result == COMM_SUCCESS:
                moved_count += 1
            time.sleep(0.05)

        print(tr("✅ {}/{} 个舵机已发送命令 / {}/{} servos commanded").format(moved_count, len(found_servos), moved_count, len(found_servos)))
        print(tr("\n⏳ 等待3秒... / Waiting 3 seconds..."))
        time.sleep(3)

        # Step 5: 读取最终位置与状态
        print(tr("\n📍 读取最终位置与状态 / Reading final positions and status..."))
        info_after = read_all_servo_info(servo_handler, found_servos)
        print_servo_info_table(info_after, tr("最终状态 / Final Status"))
        check_servo_health(info_after)

        # 打印位移摘要
        print(tr("\n📏 位移摘要 / Movement Summary:"))
        print("-" * 60)
        for info in info_after:
            servo_id = info["id"]
            if servo_id in positions_before and info["position"] is not None:
                movement = info["position"] - positions_before[servo_id]
                movement_degrees = position_to_degrees(movement)
                final_degrees = position_to_degrees(info["position"])
                print(f"  ID{servo_id}: {info['position']:4d} ({final_degrees:6.1f}°) [{tr('位移/movement')}: {movement:+4d} ({movement_degrees:+5.1f}°)]")
        print("-" * 60)

        print()
        print("=" * 50)
        print(tr("✅ 测试完成 / Test complete!"))
        print("=" * 50)
        print(tr("💡 如果舵机保持在原位附近，说明校准成功\n   If servos stayed near original positions, calibration is working correctly"))
        print()
        print(tr("💡 如果舵机移动了很大幅度，说明需要重新校准\n   If servos moved significantly, recalibration is needed"))
        print("=" * 50)

        # 力矩在舵机侧保持开启（串口关闭后依然有效），无需占用串口等待。
        # 注意: 之前这里用 while True 无限挂起进程，导致 Windows 上串口被独占，
        # 后续“失能电机”等操作无法打开串口 (PermissionError)，GUI 扫描线程也无法恢复。
        print(tr("\n⚡ 力矩保持开启（舵机侧）/ Torque stays enabled on servos\n   观察 5 秒后自动退出 / Auto-exit after 5s of observation..."))
        time.sleep(5)
        print(tr("👋 测试进程退出，释放串口 / Exiting, port released"))
        return True

    except KeyboardInterrupt:
        print(tr("\n\n⏹️ 用户中断 / User interrupted"))
        return True
    except Exception as e:
        print(tr("\n❌ 测试异常 / Test error: {}").format(e))
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
            print(tr("=== 可用串口 / Available Serial Ports ==="))
            print(list_ports_for_user())
            return
        else:
            port_name = sys.argv[1]
            print(tr("🔌 使用指定端口 / Using specified port: {}").format(port_name))
    else:
        # 交互式选择端口
        port_name = select_port_interactive(tr("选择要测试的串口 / Select port to test"))
        if not port_name:
            print(tr("❌ 未选择端口 / No port selected"))
            sys.exit(1)

    # 执行测试
    success = quick_center_test(port_name)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()