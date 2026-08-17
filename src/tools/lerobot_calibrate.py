#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LeRobot 风格的交互式机械臂校准工具
参考 Seeed Studio SO-10x 校准流程：
  1. 将每个关节移动到范围中位，记录 homing_offset
  2. 将每个关节（除 wrist_roll）在整个范围内移动，记录 range_min / range_max
  3. 生成 LeRobot 格式的 JSON 校准文件

用法 / Usage:
    python -m src.tools.lerobot_calibrate                 # 交互式选择端口和保存路径
    python -m src.tools.lerobot_calibrate /dev/ttyACM0    # 指定端口
"""

import sys
import os
import time
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

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
    sys.exit(1)

try:
    from src.port_utils import select_port_interactive, list_ports_for_user
    from src.calibration_manager import CalibrationManager, JOINT_NAME_MAP
except ImportError:
    print(tr("❌ 错误: 无法导入项目工具模块"))
    sys.exit(1)


BAUD_RATE = 1000000
SMS_STS_TORQUE_ENABLE = 40
TORQUE_ON = 1
TORQUE_OFF = 0

# ID -> 关节名映射（SO-10x 标准配置）
ID_TO_JOINT = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
}

# 连续旋转关节（不记录范围，固定 [0, 4095]）
CONTINUOUS_JOINTS = {"wrist_roll"}


def scan_servos(servo_handler) -> List[int]:
    """扫描端口上的所有舵机"""
    found = []
    for servo_id in range(1, 21):
        model_number, result, error = servo_handler.ping(servo_id)
        if result == COMM_SUCCESS:
            found.append(servo_id)
    return found


def read_position(servo_handler, servo_id: int) -> Optional[int]:
    """读取单个舵机当前位置"""
    position, result, error = servo_handler.ReadPos(servo_id)
    if result == COMM_SUCCESS:
        return position
    return None


def enable_torque(servo_handler, servo_ids: List[int], enable: bool = True) -> None:
    """批量使能/失能舵机力矩"""
    value = TORQUE_ON if enable else TORQUE_OFF
    for servo_id in servo_ids:
        servo_handler.write1ByteTxRx(servo_id, SMS_STS_TORQUE_ENABLE, value)
        time.sleep(0.02)


def calibrate_joint(servo_handler, servo_id: int, joint_name: str) -> Dict:
    """
    校准单个关节

    流程：
      1. 失能力矩，让用户把关节摆到范围中位，按回车记录 homing_offset
      2. 如果是非连续旋转关节，让用户缓慢移动关节过整个范围，记录 min/max
      3. 连续旋转关节直接设为 [0, 4095]
    """
    display_name = JOINT_NAME_MAP.get(joint_name, joint_name)
    print(f"\n{'='*60}")
    print(tr("🔧 校准关节 / Calibrating joint: ID{} - {}").format(servo_id, display_name))
    print(f"{'='*60}")

    # 失能力矩
    enable_torque(servo_handler, [servo_id], enable=False)
    print(tr("⏹️ 力矩已关闭，请手动移动该关节\n   Torque disabled, please move this joint manually\n"))

    # 步骤 1：记录中位 / homing_offset
    input(tr("请将 {} 移动到其运动范围的中间位置，然后按回车...\nMove {} to the MIDDLE of its range and press ENTER...").format(display_name, joint_name))

    homing_offset = read_position(servo_handler, servo_id)
    if homing_offset is None:
        print(tr("❌ 无法读取 ID{} 位置，使用默认值 2048").format(servo_id))
        homing_offset = 2048
    else:
        print(tr("✅ 中位已记录 / Homing offset recorded: {}\n").format(homing_offset))

    # 步骤 2：记录运动范围
    if joint_name in CONTINUOUS_JOINTS:
        range_min = 0
        range_max = 4095
        print(tr("🔄 {} 为连续旋转关节，范围固定为 [0, 4095]\n").format(display_name))
    else:
        input(tr("请缓慢将 {} 在其完整运动范围内来回移动，然后按回车停止记录...\nSlowly move {} through its FULL RANGE of motion, then press ENTER...").format(display_name, joint_name))

        print(tr("📡 正在记录范围 / Recording range..."))
        range_min = 4095
        range_max = 0
        record_count = 0

        # 记录 2 秒或直到用户再次按键？这里改为固定记录 2 秒
        start_time = time.time()
        while time.time() - start_time < 2.0:
            pos = read_position(servo_handler, servo_id)
            if pos is not None:
                if pos < range_min:
                    range_min = pos
                if pos > range_max:
                    range_max = pos
                record_count += 1
            time.sleep(0.02)

        if record_count == 0:
            print(tr("⚠️ 未记录到有效位置，使用默认范围 [0, 4095]"))
            range_min = 0
            range_max = 4095
        else:
            print(tr("✅ 范围已记录 / Range recorded: [{}, {}]\n").format(range_min, range_max))

    # 失能力矩，让用户可以调整下一个关节
    enable_torque(servo_handler, [servo_id], enable=False)

    return {
        "id": servo_id,
        "drive_mode": 0,
        "homing_offset": homing_offset,
        "range_min": range_min,
        "range_max": range_max,
    }


def calibrate_arm(port_name: str, save_path: str, arm_type: str = "follower") -> bool:
    """
    校准整条机械臂并保存校准文件

    Args:
        port_name: 串口名称
        save_path: 校准文件保存路径
        arm_type: "follower" 或 "leader"，仅用于日志提示
    """
    print(f"\n{'='*70}")
    print(tr("🦾 LeRobot 风格机械臂校准 / LeRobot-style Arm Calibration"))
    print(f"{'='*70}")
    print(tr("串口 / Port: {}").format(port_name))
    print(tr("臂类型 / Arm type: {}").format(arm_type))
    print(tr("保存路径 / Save path: {}").format(save_path))
    print(f"{'='*70}\n")

    # 初始化串口
    try:
        port_handler = PortHandler(port_name)
        if not port_handler.openPort():
            print(tr("❌ 无法打开串口 / Cannot open port: {}").format(port_name))
            return False
        if not port_handler.setBaudRate(BAUD_RATE):
            print(tr("❌ 无法设置波特率 / Cannot set baud rate"))
            port_handler.closePort()
            return False

        servo_handler = sms_sts(port_handler)
        print(tr("✅ 串口已连接 / Port connected\n"))

    except Exception as e:
        print(tr("❌ 串口初始化失败 / Port init failed: {}").format(e))
        return False

    # 扫描舵机
    print(tr("📡 扫描舵机 / Scanning servos..."))
    found_servos = scan_servos(servo_handler)
    if not found_servos:
        print(tr("❌ 未发现舵机 / No servos found"))
        port_handler.closePort()
        return False
    print(tr("✅ 发现舵机 / Found servos: {}\n").format(found_servos))

    # 过滤出已知的 1-6 号关节
    calib_servos = [sid for sid in found_servos if sid in ID_TO_JOINT]
    if not calib_servos:
        print(tr("❌ 未发现 SO-10x 标准关节舵机（ID 1-6）"))
        port_handler.closePort()
        return False

    print(tr("将校准以下舵机 / Will calibrate: {}\n").format(calib_servos))

    # 先全部失能，方便手动调整
    enable_torque(servo_handler, calib_servos, enable=False)
    print(tr("💡 所有待校准舵机已失能，可以手动移动\n"))

    # 逐个校准
    calibration_data = {}
    for servo_id in sorted(calib_servos):
        joint_name = ID_TO_JOINT[servo_id]
        joint_calib = calibrate_joint(servo_handler, servo_id, joint_name)
        calibration_data[joint_name] = joint_calib

    # 保存校准文件
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(calibration_data, f, indent=4, ensure_ascii=False)
        print(tr("\n✅ 校准文件已保存 / Calibration saved to: {}\n").format(save_path))
    except Exception as e:
        print(tr("\n❌ 保存校准文件失败 / Failed to save calibration: {}\n").format(e))
        port_handler.closePort()
        return False

    # 测试：移动到中位
    print(tr("🎯 校准完成，是否移动到中位验证？"))
    try:
        confirm = input(tr("按 'y' 回车移动到中位验证，其他键跳过: ")).strip().lower()
        if confirm == 'y':
            print(tr("\n⚡ 启动力矩..."))
            enable_torque(servo_handler, calib_servos, enable=True)
            time.sleep(0.5)

            print(tr("🎯 移动到中位..."))
            for servo_id in sorted(calib_servos):
                joint_name = ID_TO_JOINT[servo_id]
                target = calibration_data[joint_name]["homing_offset"]
                servo_handler.WritePosEx(servo_id, target, 1000, 50)
                time.sleep(0.05)

            print(tr("⏳ 等待 3 秒稳定..."))
            time.sleep(3)

            print(tr("\n📍 最终位置 / Final positions:"))
            print("-" * 60)
            for servo_id in sorted(calib_servos):
                joint_name = ID_TO_JOINT[servo_id]
                target = calibration_data[joint_name]["homing_offset"]
                pos = read_position(servo_handler, servo_id)
                if pos is not None:
                    diff = pos - target
                    print(tr("  ID{} ({}): 当前 {:4d} | 目标 {:4d} | 偏差 {:+4d}").format(servo_id, JOINT_NAME_MAP.get(joint_name, joint_name), pos, target, diff))
            print("-" * 60)
    except (EOFError, KeyboardInterrupt):
        pass

    port_handler.closePort()
    print(tr("\n✅ 校准流程结束 / Calibration complete!"))
    return True


def main():
    parser = argparse.ArgumentParser(
        description=tr('LeRobot 风格机械臂校准工具'),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=tr("""
保存路径说明:
  默认保存到 ~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/
  或 ~/.cache/huggingface/lerobot/calibration/robots/so_follower/
  具体取决于你选择的臂类型。

标准操作流程:
  1. 失能所有舵机
  2. 将每个关节摆到中位，记录 homing_offset
  3. 将每个关节（除 wrist_roll）在范围内移动，记录 min/max
  4. 保存 JSON 校准文件
        """)
    )
    parser.add_argument('port', nargs='?', help=tr('串口名称，不指定则交互式选择'))
    parser.add_argument('--arm-type', choices=['follower', 'leader'], default='follower',
                       help=tr('臂类型（默认: follower）'))
    parser.add_argument('--id', default=None, help=tr('校准文件 ID 名称（默认自动生成）'))
    parser.add_argument('--output', default=None, help=tr('自定义输出文件路径'))
    parser.add_argument('--list', action='store_true', help=tr('列出可用串口'))

    args = parser.parse_args()

    if args.list:
        print(tr("=== 可用串口 / Available Serial Ports ==="))
        print(list_ports_for_user())
        return

    # 端口选择
    if args.port:
        port_name = args.port
        print(tr("🔌 使用指定端口 / Using specified port: {}").format(port_name))
    else:
        port_name = select_port_interactive(tr("选择要校准的串口 / Select port to calibrate"))
        if not port_name:
            print(tr("❌ 未选择端口 / No port selected"))
            sys.exit(1)

    # 确定保存路径
    if args.output:
        save_path = args.output
    else:
        manager = CalibrationManager()
        if args.arm_type == 'leader':
            base_dir = manager.teleoperators_dir / "so_leader"
        else:
            base_dir = manager.robots_dir / "so_follower"

        if args.id:
            file_id = args.id
        else:
            default_name = "my_awesome_leader_arm" if args.arm_type == 'leader' else "my_awesome_follower_arm"
            try:
                file_id = input(tr("请输入校准文件 ID（直接回车使用 {}）: ").format(default_name)).strip()
            except (EOFError, KeyboardInterrupt):
                file_id = ""
            if not file_id:
                file_id = default_name

        save_path = str(base_dir / f"{file_id}.json")

    # 执行校准
    success = calibrate_arm(port_name, save_path, args.arm_type)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    import argparse
    main()
