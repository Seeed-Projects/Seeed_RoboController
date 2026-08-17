#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
舵机快速校准工具 - 快速失能并校准中位
Servo Quick Calibration - Quick disable and calibrate middle value

用法 / Usage:
    python servo_quick_calibration.py          # 交互式选择端口 / Interactive port selection
    python servo_quick_calibration.py <port>   # 指定端口 / Specify port
    python servo_quick_calibration.py --list   # 列出可用端口 / List available ports
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

# === 配置常量 ===
BAUD_RATE = 1000000
SMS_STS_TORQUE_ENABLE = 40
TORQUE_OFF = 0
SMS_STS_CALIBRATE_MIDDLE = 128  # 校准命令：将当前位置设为2048


def scan_servos(servo_handler) -> list:
    """扫描端口上的所有舵机"""
    found = []
    for servo_id in range(1, 21):
        model_number, result, error = servo_handler.ping(servo_id)
        if result == COMM_SUCCESS:
            found.append(servo_id)
    return found


def quick_calibration(port_name: str) -> bool:
    """
    快速校准 - 失能舵机并校准中位（将当前位置设为2048）

    流程：
    1. 失能所有舵机
    2. 将当前物理位置校准为中位(2048)

    Args:
        port_name: 串口名称

    Returns:
        bool: 校准是否成功
    """
    print(f"\n{'='*50}")
    print(tr("⚡ 舵机快速校准工具 / Servo Quick Calibration"))
    print(f"{'='*50}")
    print(tr("端口 / Port: {}").format(port_name))
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

        # 扫描舵机
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
        # Step 1: 失能所有舵机
        print(tr("⏹️ Step 1: 失能舵机 / Disabling servos..."))
        print("-" * 50)
        disabled_count = 0
        failed_disable = []

        for servo_id in found_servos:
            result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, TORQUE_OFF)
            if result == COMM_SUCCESS:
                disabled_count += 1
            else:
                failed_disable.append(servo_id)
            time.sleep(0.05)

        print(tr("✅ {}/{} 个舵机已失能 / {}/{} servos disabled").format(disabled_count, len(found_servos), disabled_count, len(found_servos)))
        if failed_disable:
            print(tr("   失败 / Failed: {}").format(failed_disable))
        print()

        time.sleep(1)  # 等待舵机稳定

        # Step 2: 校准中位
        print(tr("🔧 Step 2: 校准中位（当前位置→2048）/ Calibrating middle (current→2048)"))
        print("-" * 50)
        print(tr("💡 确保舵机已手动调整到期望的中位位置\n   Make sure servos are manually adjusted to desired center position"))
        print("-" * 50)

        calibrated_count = 0
        failed_calibrate = []

        for servo_id in found_servos:
            print(f"  ID{servo_id}...", end=" ")

            # 解锁 EEPROM
            result, error = servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                print(tr("❌ EEPROM解锁失败 / Unlock failed"))
                failed_calibrate.append(servo_id)
                continue
            time.sleep(0.05)

            # 发送校准命令（写128到地址40）
            result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_CALIBRATE_MIDDLE)
            if result != COMM_SUCCESS:
                print(tr("❌ 校准失败 / Calibration failed"))
                servo_handler.LockEprom(servo_id)
                failed_calibrate.append(servo_id)
                continue
            time.sleep(0.05)

            # 重新锁定 EEPROM
            servo_handler.LockEprom(servo_id)

            calibrated_count += 1
            print(tr("✅ 成功 / Success"))

        print()
        print("=" * 50)

        if calibrated_count == len(found_servos):
            print(tr("✅ 全部成功! / All Success! {}/{} 个舵机已校准").format(calibrated_count, len(found_servos)))
            print(f"   {calibrated_count}/{len(found_servos)} servos calibrated")
        else:
            print(tr("⚠️ 部分成功 / Partial: {}/{} 个舵机已校准").format(calibrated_count, len(found_servos)))
            if failed_calibrate:
                print(tr("   失败的舵机 / Failed servos: {}").format(failed_calibrate))

        print("=" * 50)
        print()
        print(tr("✅ 快速校准完成 / Quick calibration complete!"))
        print("=" * 50)

        return calibrated_count > 0

    except Exception as e:
        print(tr("\n❌ 校准异常 / Calibration error: {}").format(e))
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
        port_name = select_port_interactive(tr("选择校准串口 / Select port to calibrate"))
        if not port_name:
            print(tr("❌ 未选择端口 / No port selected"))
            sys.exit(1)

    # 执行快速校准
    success = quick_calibration(port_name)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
