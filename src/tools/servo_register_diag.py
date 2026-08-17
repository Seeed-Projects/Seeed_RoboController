#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
舵机寄存器诊断工具
用于检查 current / moving 等寄存器是否真实可读、数值是否变化
"""

import sys
import time
import argparse

sys.path.append('.')
sys.path.append('./scservo_sdk')

from scservo_sdk.port_handler import PortHandler
from scservo_sdk.sms_sts import sms_sts
from scservo_sdk.scservo_def import COMM_SUCCESS

try:
    from src.port_utils import get_default_port, get_available_ports
    PORT_UTILS_AVAILABLE = True
except ImportError:
    PORT_UTILS_AVAILABLE = False

try:
    from src.i18n import tr
except ImportError:
    def tr(text):
        return text


BAUD_RATE = 1000000


def list_ports():
    """列出可用串口"""
    if PORT_UTILS_AVAILABLE:
        ports = get_available_ports()
        print(tr("可用串口:"))
        for p in ports:
            print(f"  {p}")
    else:
        print(tr("无法列出串口，请手动指定"))


def connect(port_name):
    """连接串口"""
    ph = PortHandler(port_name)
    if not ph.openPort():
        print(tr("无法打开串口: {}").format(port_name))
        return None
    if not ph.setBaudRate(BAUD_RATE):
        print(tr("无法设置波特率: {}").format(BAUD_RATE))
        ph.closePort()
        return None
    return sms_sts(ph), ph


def read_all(servo_handler, servo_id):
    """读取所有相关寄存器的原始值和结果"""
    results = {}

    pos, result, error = servo_handler.ReadPos(servo_id)
    results['pos'] = {'value': pos, 'result': result, 'error': error}

    speed, result, error = servo_handler.ReadSpeed(servo_id)
    results['speed'] = {'value': speed, 'result': result, 'error': error}

    load, result, error = servo_handler.ReadLoad(servo_id)
    results['load'] = {'value': load, 'result': result, 'error': error}

    voltage, result, error = servo_handler.ReadVoltage(servo_id)
    results['voltage'] = {'value': voltage, 'result': result, 'error': error}

    temperature, result, error = servo_handler.ReadTemperature(servo_id)
    results['temperature'] = {'value': temperature, 'result': result, 'error': error}

    current, result, error = servo_handler.ReadCurrent(servo_id)
    results['current'] = {'value': current, 'result': result, 'error': error}

    moving, result, error = servo_handler.ReadMoving(servo_id)
    results['moving'] = {'value': moving, 'result': result, 'error': error}

    model, result, error = servo_handler.ReadModelNumber(servo_id)
    results['model'] = {'value': model, 'result': result, 'error': error}

    return results


def print_results(servo_id, results):
    """打印读取结果"""
    line = f"ID{servo_id}: "
    parts = []
    for key in ['pos', 'speed', 'load', 'voltage', 'temperature', 'current', 'moving', 'model']:
        item = results[key]
        val = item['value']
        res = item['result']
        err = item['error']
        if res != COMM_SUCCESS:
            parts.append(f"{key}=ERR({res},{err})")
        elif key == 'voltage':
            parts.append(f"{key}={val/10.0:.1f}V")
        elif key == 'moving':
            parts.append(f"{key}={'Yes' if val else 'No'}")
        else:
            parts.append(f"{key}={val}")
    print(line + " | ".join(parts))


def main():
    parser = argparse.ArgumentParser(description=tr("舵机寄存器诊断工具"))
    parser.add_argument("port", nargs="?", help=tr("串口路径，如 /dev/ttyUSB0"))
    parser.add_argument("--id", type=int, default=1, help=tr("要测试的舵机ID，默认1"))
    parser.add_argument("--list", action="store_true", help=tr("列出可用串口"))
    parser.add_argument("--move", action="store_true", help=tr("自动移动舵机以观察 moving/current 变化"))
    parser.add_argument("--interval", type=float, default=0.05, help=tr("读取间隔(秒)，默认0.05"))
    args = parser.parse_args()

    if args.list:
        list_ports()
        return

    port = args.port
    if not port:
        if PORT_UTILS_AVAILABLE:
            port = get_default_port(0)
        if not port:
            port = input(tr("请输入串口路径: ")).strip()

    print(tr("连接串口: {}").format(port))
    servo_handler, ph = connect(port)
    if servo_handler is None:
        return

    servo_id = args.id
    print(tr("诊断舵机 ID: {}").format(servo_id))
    print(tr("读取间隔: {}s").format(args.interval))
    print(tr("按 Ctrl+C 停止\n"))

    try:
        if args.move:
            # 开启力矩
            print(tr("开启力矩..."))
            servo_handler.write1ByteTxRx(servo_id, 40, 1)
            targets = [1500, 2600, 2048]
            target_idx = 0
            last_move_time = time.time()

        count = 0
        while True:
            results = read_all(servo_handler, servo_id)
            print_results(servo_id, results)
            count += 1

            if args.move and count % 30 == 0:
                target = targets[target_idx % len(targets)]
                print(tr("\n>>> 发送移动命令到位置: {}\n").format(target))
                servo_handler.WritePosEx(servo_id, target, 500, 50)
                target_idx += 1

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print(tr("\n停止诊断"))
    finally:
        if args.move:
            print(tr("关闭力矩..."))
            servo_handler.write1ByteTxRx(servo_id, 40, 0)
        ph.closePort()


if __name__ == "__main__":
    main()
