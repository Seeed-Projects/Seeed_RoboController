#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
舵机中位校准工具 - 将当前舵机位置校准为中位(2048)
Servo Middle Calibration - Set current servo position as center (2048)

用法 / Usage:
    python servo_middle_calibration.py          # 交互式选择端口 / Interactive port selection
    python servo_middle_calibration.py <port>   # 指定端口 / Specify port
    python servo_middle_calibration.py --list   # 列出可用端口 / List available ports
"""

import sys
import os
import time
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
MIDDLE_POSITION = 2048  # 正确的中位值
SMS_STS_TORQUE_ENABLE = 40  # 力矩开关地址（也是校准命令地址）
SMS_STS_TORQUE_ON = 1
SMS_STS_TORQUE_OFF = 0
SMS_STS_CALIBRATE_MIDDLE = 128  # 校准命令：将当前位置设为2048


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


def disable_servos(servo_handler, servo_list: list) -> int:
    """失能所有舵机"""
    disabled_count = 0
    for servo_id in servo_list:
        result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_TORQUE_OFF)
        if result == COMM_SUCCESS:
            disabled_count += 1
        time.sleep(0.05)
    return disabled_count


def read_positions(servo_handler, servo_list: list) -> dict:
    """读取所有舵机位置"""
    positions = {}
    for servo_id in servo_list:
        position, result, error = servo_handler.ReadPos(servo_id)
        if result == COMM_SUCCESS:
            positions[servo_id] = position
        time.sleep(0.05)
    return positions


def calibrate_middle_offset(servo_handler, servo_id: int) -> bool:
    """
    校准单个舵机的中位偏移 - 将当前位置设为2048

    流程：
    1. 解锁 EEPROM
    2. 发送校准命令（写128到地址40）
    3. 重新锁定 EEPROM
    """
    try:
        # 1. 解锁 EEPROM
        result, error = servo_handler.unLockEprom(servo_id)
        if result != COMM_SUCCESS:
            print(f"    ❌ EEPROM解锁失败: {error}")
            return False
        time.sleep(0.1)

        # 2. 发送校准命令（写128到地址40）
        result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_CALIBRATE_MIDDLE)
        if result != COMM_SUCCESS:
            print(f"    ❌ 校准命令失败: {error}")
            servo_handler.LockEprom(servo_id)
            return False
        time.sleep(0.1)

        # 3. 重新锁定 EEPROM
        result, error = servo_handler.LockEprom(servo_id)
        if result != COMM_SUCCESS:
            print(f"    ⚠️ EEPROM重新锁定失败: {error}")

        return True

    except Exception as e:
        print(f"    ❌ 校准异常: {e}")
        return False


def center_servo(servo_handler, servo_id: int) -> bool:
    """将单个舵机移动到中位"""
    try:
        # 吺动力矩
        result, error = servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_TORQUE_ON)
        if result != COMM_SUCCESS:
            return False
        time.sleep(0.05)

        # 移动到中位
        result, error = servo_handler.WritePosEx(servo_id, MIDDLE_POSITION, 1000, 50)
        return result == COMM_SUCCESS

    except Exception:
        return False


def interactive_calibration(port_name: str) -> bool:
    """
    交互式中位校准 - 逐步引导用户完成校准
    """
    print(f"\n{'='*55}")
    print(f"🔧 舵机中位校准工具 / Servo Middle Calibration Tool")
    print(f"{'='*55}")
    print(f"端口 / Port: {port_name}")
    print(f"{'='*55}\n")

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
        print("📡 Step 1: 扫描舵机 / Scanning servos...")
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
        # Step 2: 失能舵机
        print("⏹️ Step 2: 失能舵机（可手动旋转）/ Disable servos (free to rotate)")
        try:
            confirm = input("是否失能舵机？(y/n): ").strip().lower()
            if confirm in ['y', 'yes']:
                count = disable_servos(servo_handler, found_servos)
                print(f"✅ {count}/{len(found_servos)} 个舵机已失能 / {count}/{len(found_servos)} servos disabled\n")
                time.sleep(1)
            else:
                print("⏭️ 跳过失能 / Skipped\n")
        except (EOFError, KeyboardInterrupt):
            print("⏭️ 跳过失能 / Skipped\n")

        # Step 3: 读取当前位置
        print("📍 Step 3: 读取当前位置 / Reading current positions...")
        print("-" * 50)
        positions_before = read_positions(servo_handler, found_servos)
        for servo_id in found_servos:
            if servo_id in positions_before:
                pos = positions_before[servo_id]
                deg = position_to_degrees(pos)
                print(f"  ID{servo_id}: {pos:4d} ({deg:6.1f}°)")
        print()

        # Step 4: 提示用户手动调整位置
        print("=" * 50)
        print("📋 Step 4: 手动调整舵机位置")
        print("   Manually adjust servos to desired center position")
        print("=" * 50)
        try:
            input("调整完成后按回车继续 / Press Enter when ready...\n")
        except (EOFError, KeyboardInterrupt):
            print("⏭️ 用户取消 / User cancelled")
            return False

        # Step 5: 校准中位
        print("🔧 Step 5: 校准中位（将当前位置设为2048）/ Calibrate middle (set current as 2048)")
        print("-" * 50)

        try:
            confirm = input("确认校准？(y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("⏭️ 取消校准 / Calibration cancelled")
                return False
        except (EOFError, KeyboardInterrupt):
            print("⏭️ 取消校准 / Calibration cancelled")
            return False

        print("正在校准... / Calibrating...")
        success_count = 0
        for servo_id in found_servos:
            print(f"  ID{servo_id}...", end=" ")
            if calibrate_middle_offset(servo_handler, servo_id):
                success_count += 1
                print("✅ 成功 / Success")
            else:
                print("❌ 失败 / Failed")
            time.sleep(0.1)

        print(f"\n✅ {success_count}/{len(found_servos)} 个舵机校准完成 / {success_count}/{len(found_servos)} servos calibrated\n")
        time.sleep(2)

        # Step 6: 移动到中位测试
        print("🎯 Step 6: 移动到中位测试 / Move to center for testing")
        print("-" * 50)

        try:
            confirm = input("是否移动舵机到中位测试？(y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("⏭️ 跳过测试 / Skipped testing")
            else:
                print("正在移动... / Moving...")
                moved_count = 0
                for servo_id in found_servos:
                    if center_servo(servo_handler, servo_id):
                        moved_count += 1
                    time.sleep(0.1)

                print(f"✅ {moved_count}/{len(found_servos)} 个舵机已移动到中位 / {moved_count}/{len(found_servos)} servos moved to center")
                print("\n⏳ 等待3秒... / Waiting 3 seconds...")
                time.sleep(3)

                # 读取最终位置
                print("\n📍 最终位置 / Final positions:")
                print("-" * 50)
                positions_after = read_positions(servo_handler, found_servos)
                for servo_id in found_servos:
                    if servo_id in positions_before and servo_id in positions_after:
                        movement = positions_after[servo_id] - positions_before[servo_id]
                        movement_deg = position_to_degrees(movement)
                        final_deg = position_to_degrees(positions_after[servo_id])
                        print(f"  ID{servo_id}: {positions_after[servo_id]:4d} ({final_deg:6.1f}°) [位移/movement: {movement:+4d} ({movement_deg:+5.1f}°)]")

        except (EOFError, KeyboardInterrupt):
            print("⏭️ 跳过测试 / Skipped testing")

        # 完成
        print()
        print("=" * 50)
        print("✅ 校准流程完成 / Calibration process complete!")
        print("=" * 50)
        print("💡 如果舵机保持原位（位移很小），说明校准成功")
        print("   If servos stayed near original position, calibration is successful")
        print("=" * 50)

        return True

    except Exception as e:
        print(f"\n❌ 校准异常 / Calibration error: {e}")
        return False
    finally:
        try:
            port_handler.closePort()
        except:
            pass


def auto_calibration(port_name: str) -> bool:
    """
    自动中位校准 - 快速模式
    """
    print(f"\n{'='*55}")
    print(f"🔧 舵机中位校准工具（自动模式）/ Servo Middle Calibration (Auto)")
    print(f"{'='*55}")
    print(f"端口 / Port: {port_name}")
    print(f"{'='*55}\n")

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

        # 扫描舵机
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
        # 失能舵机
        print("⏹️ 失能舵机 / Disabling servos...")
        disable_servos(servo_handler, found_servos)
        time.sleep(1)

        # 提示手动调整
        print("\n" + "=" * 50)
        print("!!! 手动步骤 / MANUAL STEP !!!")
        print(f"请手动将所有舵机 ({found_servos}) 调整到期望的中位位置")
        print(f"Manually move all servos to desired center position")
        input("调整完成后按回车 / Press Enter when ready...\n")
        print("=" * 50)

        # 读取当前位置
        print("📍 读取当前位置 / Reading current positions...")
        positions_before = read_positions(servo_handler, found_servos)
        for servo_id in found_servos:
            if servo_id in positions_before:
                pos = positions_before[servo_id]
                deg = position_to_degrees(pos)
                print(f"  ID{servo_id}: {pos:4d} ({deg:6.1f}°)")
        print()

        # 校准
        print("🔧 校准中位 / Calibrating middle...")
        success_count = 0
        for servo_id in found_servos:
            print(f"  ID{servo_id}...", end=" ")
            if calibrate_middle_offset(servo_handler, servo_id):
                success_count += 1
                print("✅")
            else:
                print("❌")
            time.sleep(0.1)

        print(f"\n✅ {success_count}/{len(found_servos)} 个舵机校准完成\n")
        time.sleep(2)

        # 移动到中位测试
        print("🎯 移动到中位测试 / Move to center for testing...")
        for servo_id in found_servos:
            center_servo(servo_handler, servo_id)
            time.sleep(0.1)

        print("⏳ 等待3秒... / Waiting 3 seconds...")
        time.sleep(3)

        # 读取最终位置
        print("\n📍 最终位置 / Final positions:")
        positions_after = read_positions(servo_handler, found_servos)
        for servo_id in found_servos:
            if servo_id in positions_before and servo_id in positions_after:
                movement = positions_after[servo_id] - positions_before[servo_id]
                movement_deg = position_to_degrees(movement)
                final_deg = position_to_degrees(positions_after[servo_id])
                print(f"  ID{servo_id}: {positions_after[servo_id]:4d} ({final_deg:6.1f}°) [位移/movement: {movement:+4d} ({movement_deg:+5.1f}°)]")

        print()
        print("=" * 50)
        print("✅ 校准完成 / Calibration complete!")
        print("=" * 50)

        return True

    except Exception as e:
        print(f"\n❌ 校准异常 / Calibration error: {e}")
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
        port_name = select_port_interactive("选择校准串口 / Select port to calibrate")
        if not port_name:
            print("❌ 未选择端口 / No port selected")
            sys.exit(1)

    # 选择模式
    print("\n" + "=" * 50)
    print("选择模式 / Select Mode:")
    print("=" * 50)
    print("1. 交互式模式 / Interactive mode (逐步引导)")
    print("2. 自动模式 / Auto mode (快速执行)")
    print("=" * 50)

    try:
        mode = input("选择模式 (1/2) / Select mode (1/2): ").strip()
    except (EOFError, KeyboardInterrupt):
        mode = "2"

    # 执行校准
    if mode == "1":
        success = interactive_calibration(port_name)
    else:
        success = auto_calibration(port_name)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
