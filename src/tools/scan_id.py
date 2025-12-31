#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
舵机扫描工具 - 扫描指定端口上的所有舵机
Servo ID Scanner - Scan all servos on specified port

用法 / Usage:
    python scan_id.py                    # 交互式选择端口 / Interactive port selection
    python scan_id.py <port>             # 指定端口 / Specify port
    python scan_id.py --list             # 列出可用端口 / List available ports
"""

import sys
import os

# 引入 SDK
sys.path.append('../..')
sys.path.append('../../scservo_sdk')

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError:
    print("❌ 错误: 未找到 scservo_sdk。请确保 scservo_sdk 文件夹在当前目录下。")
    print("   Error: scservo_sdk not found. Make sure scservo_sdk folder is in current directory.")
    sys.exit(1)

# 引入端口工具
try:
    from src.port_utils import select_port_interactive, list_ports_for_user
except ImportError:
    print("❌ 错误: 未找到 port_utils。请确保 port_utils.py 在当前目录下。")
    print("   Error: port_utils not found. Make sure port_utils.py is in current directory.")
    sys.exit(1)

# === 配置常量 ===
BAUDRATE = 1000000
MAX_ID = 20  # 扫描范围 1 - 20


def scan_servos(port_name: str) -> list:
    """
    扫描端口上的所有舵机

    Args:
        port_name: 串口名称

    Returns:
        list: 发现的舵机 ID 列表
    """
    print(f"\n{'='*50}")
    print(f"📡 舵机扫描工具 / Servo ID Scanner")
    print(f"{'='*50}")
    print(f"端口 / Port: {port_name}")
    print(f"扫描范围 / Scan Range: ID 1 - {MAX_ID}")
    print(f"{'='*50}\n")

    # 初始化连接
    try:
        port_handler = PortHandler(port_name)
        packet_handler = sms_sts(port_handler)

        if not port_handler.openPort():
            print(f"❌ 无法打开串口 / Cannot open port: {port_name}")
            return []
        if not port_handler.setBaudRate(BAUDRATE):
            print(f"❌ 无法设置波特率 / Cannot set baud rate")
            port_handler.closePort()
            return []
    except Exception as e:
        print(f"❌ 初始化异常 / Init error: {e}")
        return []

    # 开始扫描
    print("🔍 扫描中 / Scanning...\n")
    print("-" * 50)
    print(f"{'ID':<5} | {'型号 (Model)':<15} | {'状态'}")
    print("-" * 50)

    found = []
    for servo_id in range(1, MAX_ID + 1):
        model_number, result, error = packet_handler.ping(servo_id)

        if result == COMM_SUCCESS:
            print(f"{servo_id:<5} | {model_number:<15} | ✅ 在线 / Online")
            found.append(servo_id)
        else:
            # 显示未找到的舵机（可选，注释掉以减少输出）
            # print(f"{servo_id:<5} | {'-':<15} | ❌ 未找到 / Not found")
            pass

    print("-" * 50)
    print(f"\n📊 扫描结束 / Scan Complete")
    print(f"   发现 {len(found)} 个舵机 / Found {len(found)} servo(s): {found}")
    print(f"{'='*50}\n")

    port_handler.closePort()
    return found


def main():
    """主函数"""
    # 处理 --list 参数
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        print("=== 可用串口 / Available Serial Ports ===")
        print(list_ports_for_user())
        return

    # 获取端口 - 支持命令行参数或交互式选择
    if len(sys.argv) > 1:
        port_name = sys.argv[1]
        print(f"🔌 使用指定端口 / Using specified port: {port_name}")
    else:
        # 交互式选择端口
        port_name = select_port_interactive("选择要扫描的串口 / Select port to scan")
        if not port_name:
            print("❌ 未选择端口，退出 / No port selected, exit")
            sys.exit(1)

    # 执行扫描
    found = scan_servos(port_name)
    sys.exit(0 if found else 1)


if __name__ == "__main__":
    main()
