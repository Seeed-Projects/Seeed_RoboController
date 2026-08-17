#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
import os

try:
    from src.i18n import tr
except ImportError:
    def tr(text):
        return text

# 确保能找到 scservo_sdk
sys.path.append('../..')
sys.path.append('../../scservo_sdk')

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError:
    print(tr("❌ 错误: 未找到 scservo_sdk 包。请确保将 scservo_sdk 文件夹放在当前目录下。"))
    sys.exit(1)

# 配置参数
BAUDRATE = 1000000  # 默认波特率
ID_ADDR = 5         # 舵机内存中 ID 的地址

def get_available_ports():
    """获取串口列表"""
    import serial.tools.list_ports
    return [port.device for port in serial.tools.list_ports.comports()]

def scan_one_servo(packet_handler):
    """扫描总线上的一只舵机"""
    print(tr("正在扫描舵机 (ID 1-254)..."))
    for servo_id in range(1, 255):
        # 使用 ping 指令检测
        model_number, result, error = packet_handler.ping(servo_id)
        if result == COMM_SUCCESS:
            print(tr("✅ 发现舵机! ID: {}, 型号: {}").format(servo_id, model_number))
            return servo_id
    return None

def change_id(packet_handler, old_id, new_id):
    """核心逻辑：修改ID"""
    print(tr("\n--- 开始修改 ID: {} -> {} ---").format(old_id, new_id))

    # 1. 解锁 EEPROM
    print(tr("1. 正在解锁 EEPROM..."))
    result, error = packet_handler.unLockEprom(old_id)
    if result != COMM_SUCCESS:
        print(tr("❌ 解锁失败: {}").format(packet_handler.getTxRxResult(result, error)))
        return False

    # 2. 写入新 ID (地址 5)
    print(tr("2. 写入新 ID {} 到内存地址 {}...").format(new_id, ID_ADDR))
    result, error = packet_handler.write1ByteTxRx(old_id, ID_ADDR, new_id)
    if result != COMM_SUCCESS:
        print(tr("❌ 写入 ID 失败: {}").format(packet_handler.getTxRxResult(result, error)))
        return False
    
    time.sleep(0.1) # 稍作等待

    # 3. 验证新 ID
    print(tr("3. 验证新 ID {}...").format(new_id))
    model, result, error = packet_handler.ping(new_id)
    if result != COMM_SUCCESS:
        print(tr("❌ 验证失败: 无法 Ping 通新 ID {}").format(new_id))
        return False

    # 4. 重新锁定 EEPROM (使用新 ID 进行锁定操作)
    print(tr("4. 重新锁定 EEPROM..."))
    result, error = packet_handler.LockEprom(new_id)
    if result != COMM_SUCCESS:
        print(tr("⚠️ 警告: 锁定失败，但 ID 可能已修改。错误: {}").format(packet_handler.getTxRxResult(result, error)))
    else:
        print(tr("✅ EEPROM 已锁定。"))

    return True

def main():
    print(tr("=== 串行总线舵机 ID 修改工具 ==="))

    # 1. 选择串口
    ports = get_available_ports()
    if not ports:
        print(tr("❌ 未检测到串口！"))
        return

    print(tr("\n可用串口:"))
    for i, p in enumerate(ports):
        print(f" [{i}] {p}")

    try:
        idx = int(input(tr("\n请输入串口序号 (0/1/...): ")))
        port_name = ports[idx]
    except:
        print(tr("❌ 输入无效，默认使用第一个串口。"))
        port_name = ports[0]

    # 2. 初始化连接
    port_handler = PortHandler(port_name)
    packet_handler = sms_sts(port_handler)

    if not port_handler.openPort():
        print(tr("❌ 无法打开串口！"))
        return
    if not port_handler.setBaudRate(BAUDRATE):
        print(tr("❌ 无法设置波特率！"))
        return

    print(tr("已连接到 {} @ {}bps").format(port_name, BAUDRATE))
    print(tr("⚠️ 注意：请确保总线上只连接了 **一个** 需要修改的舵机，以免ID冲突！"))
    input(tr("按回车键开始扫描..."))

    # 3. 扫描当前 ID
    current_id = scan_one_servo(packet_handler)
    if current_id is None:
        print(tr("❌ 未扫描到任何舵机，请检查连接或电源。"))
        port_handler.closePort()
        return

    # 4. 获取新 ID
    try:
        new_id_str = input(tr("\n检测到当前 ID 为 [{}]，请输入新 ID (1-253): ").format(current_id))
        new_id = int(new_id_str)
        if new_id < 1 or new_id > 253:
            print(tr("❌ ID 必须在 1-253 之间"))
            return
        if new_id == current_id:
            print(tr("⚠️ 新 ID 与旧 ID 相同，无需修改。"))
            return
    except ValueError:
        print(tr("❌ 输入无效"))
        return

    # 5. 执行修改
    if change_id(packet_handler, current_id, new_id):
        print(tr("\n🎉 成功！舵机 ID 已从 {} 修改为 {}").format(current_id, new_id))
    else:
        print(tr("\n❌ 修改失败。"))

    port_handler.closePort()

if __name__ == "__main__":
    main()