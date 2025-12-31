#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
舵机扫描工具 - 扫描指定端口上的所有舵机
Servo ID Scanner - Scan all servos on specified port
"""

import sys
import os

# 引入 SDK
sys.path.append('.')
sys.path.append('./scservo_sdk')

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError:
    print("❌ 错误: 未找到 scservo_sdk。请确保 scservo_sdk 文件夹在当前目录下。")
    sys.exit(1)

# 引入端口工具
try:
    from port_utils import select_port_interactive, get_default_port
except ImportError:
    print("❌ 错误: 未找到 port_utils。请确保 port_utils.py 在当前目录下。")
    sys.exit(1)

# === 配置 ===
BAUDRATE = 1000000
MAX_ID = 20  # 扫描范围 1 - 20


def main():
    print(f"=== 舵机扫描工具 (范围 1-{MAX_ID}) ===")

    # 1. 获取端口 - 支持命令行参数或交互式选择
    if len(sys.argv) > 1:
        port_name = sys.argv[1]
        print(f"🔌 使用命令行指定端口: {port_name}")
    else:
        # 交互式选择端口
        port_name = select_port_interactive("选择要扫描的串口 / Select port to scan")
        if not port_name:
            print("❌ 未选择端口，退出 / No port selected, exit")
            sys.exit(1)

    if not port_name:
        print("❌ 未找到可用串口！请检查连接。")
        sys.exit(1)

    # 2. 初始化连接
    try:
        port_handler = PortHandler(port_name)
        packet_handler = sms_sts(port_handler)

        if not port_handler.openPort():
            print("❌ 无法打开串口")
            sys.exit(1)
        if not port_handler.setBaudRate(BAUDRATE):
            print("❌ 无法设置波特率")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 初始化异常: {e}")
        sys.exit(1)

    # 3. 开始扫描
    print("\n🚀 开始扫描...")
    found_count = 0
    
    print("-" * 40)
    print(f"{'ID':<5} | {'型号 (Model)':<15} | {'状态'}")
    print("-" * 40)

    for servo_id in range(1, MAX_ID + 1):
        # 发送 Ping 指令
        model_number, result, error = packet_handler.ping(servo_id)
        
        if result == COMM_SUCCESS:
            print(f"{servo_id:<5} | {model_number:<15} | ✅ 在线")
            found_count += 1
        else:
            # 如果你想看扫描过程，取消下面这行的注释
            # print(f"{servo_id:<5} | {'-':<15} | .") 
            pass

    print("-" * 40)
    print(f"\n📊 扫描结束，共发现 {found_count} 个舵机。")
    
    port_handler.closePort()

if __name__ == "__main__":
    main()