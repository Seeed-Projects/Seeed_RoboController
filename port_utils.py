#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
跨平台串口工具模块
Cross-platform serial port utilities
"""

import platform
import os


def get_available_ports(include_virtual=False):
    """
    获取所有可用的串口设备
    Get all available serial port devices

    Args:
        include_virtual: 是否包含虚拟设备（如 debug-console），默认 False
                         Whether to include virtual devices (e.g. debug-console), default False

    Returns:
        list: 可用串口设备列表，按优先级排序
              List of available serial ports, sorted by priority
    """
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())

        # 按平台优先级排序
        system = platform.system()

        def port_priority(port):
            """计算端口优先级"""
            device = port.device
            description = port.description.upper()

            # macOS: 优先使用 cu.* 设备（非阻塞）
            if system == "Darwin":
                # 过滤掉虚拟/调试设备
                if not include_virtual:
                    exclude_keywords = ["DEBUG", "BLUETOOTH", "RFCOMM", "INCOMING"]
                    device_upper = device.upper()
                    if any(kw in device_upper for kw in exclude_keywords):
                        return 999

                if "/dev/cu." in device:
                    if "USB" in device.upper() or "ACM" in device.upper():
                        return 1  # cu.usb* / cu.acm* - 最高优先级
                    if "MODEM" in device.upper():
                        return 1  # cu.usbmodem* 优先级
                    return 2
                if "/dev/tty." in device:
                    if "USB" in device.upper() or "ACM" in device.upper():
                        return 3
                    return 4  # tty.* 设备（阻塞，优先级较低）
                return 5

            # Linux: USB 设备优先
            elif system == "Linux":
                if "ttyUSB" in device or "ttyACM" in device:
                    return 1
                if "ttyS" in device:
                    return 2
                return 3

            # Windows: COM 端口按编号排序
            else:
                try:
                    com_num = int(device.replace("COM", ""))
                    return com_num
                except ValueError:
                    return 999

            return 999

        # 过滤有效端口并排序
        valid_ports = [p for p in ports if p.device != 'n/a']
        valid_ports.sort(key=port_priority)

        # 如果不是包含虚拟设备，则过滤掉优先级为 999 的端口
        if not include_virtual:
            valid_ports = [p for p in valid_ports if port_priority(p) < 999]

        return valid_ports

    except ImportError:
        print("Warning: pyserial not installed, cannot list ports")
        return []
    except Exception as e:
        print(f"Warning: Error listing ports: {e}")
        return []


def get_default_port(index=0):
    """
    获取默认串口设备
    Get default serial port device

    Args:
        index: 端口索引，默认为0（第一个可用端口）
              Port index, default is 0 (first available port)

    Returns:
        str: 端口设备路径，如果没有可用端口则返回None
             Port device path, or None if no ports available
    """
    ports = get_available_ports()
    if ports and index < len(ports):
        return ports[index].device
    return None


def list_ports_for_user():
    """
    以用户友好的格式列出可用端口
    List available ports in user-friendly format

    Returns:
        str: 格式化的端口列表字符串
             Formatted port list string
    """
    ports = get_available_ports()
    if not ports:
        return "No serial ports found"

    lines = ["Available serial ports:"]
    for i, port in enumerate(ports):
        lines.append(f"  {i}: {port.device}")
        if port.description:
            lines.append(f"     Description: {port.description}")
        if port.manufacturer:
            lines.append(f"     Manufacturer: {port.manufacturer}")
        if port.vid and port.pid:
            lines.append(f"     USB ID: {port.vid:04x}:{port.pid:04x}")

    return "\n".join(lines)


def find_port_by_description(keyword):
    """
    根据描述关键词查找端口
    Find port by description keyword

    Args:
        keyword: 描述关键词（不区分大小写）
                 Description keyword (case-insensitive)

    Returns:
        str: 匹配的端口设备路径，如果没找到则返回None
             Matched port device path, or None if not found
    """
    ports = get_available_ports()
    keyword_upper = keyword.upper()

    for port in ports:
        if keyword_upper in port.description.upper():
            return port.device
        if keyword_upper in port.device.upper():
            return port.device

    return None


def get_platform_info():
    """
    获取平台信息，用于调试
    Get platform information for debugging

    Returns:
        dict: 平台信息字典
             Platform information dictionary
    """
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor()
    }


def select_port_interactive(prompt="请选择串口 / Select serial port"):
    """
    交互式选择串口
    Interactive port selection

    Args:
        prompt: 提示信息
                Prompt message

    Returns:
        str: 用户选择的串口设备路径，如果没有选择则返回None
             User-selected port device path, or None if no selection
    """
    ports = get_available_ports()

    if not ports:
        print("❌ 未发现可用串口 / No serial ports found")
        print("   请检查 USB 转串口适配器是否已连接")
        print("   Please ensure USB-to-Serial adapter is connected")
        return None

    if len(ports) == 1:
        # 只有一个端口，自动返回
        port = ports[0]
        print(f"🔌 自动选择唯一端口 / Auto-select only port: {port.device}")
        if port.description:
            print(f"   描述 / Description: {port.description}")
        return port.device

    # 多个端口，让用户选择
    print(f"\n{'='*50}")
    print(f"发现 {len(ports)} 个可用串口 / Found {len(ports)} available serial port(s):")
    print(f"{'='*50}")

    for i, port in enumerate(ports):
        print(f"\n  [{i}] {port.device}")
        if port.description:
            print(f"      描述 / Description: {port.description}")
        if port.manufacturer:
            print(f"      制造商 / Manufacturer: {port.manufacturer}")
        if port.vid and port.pid:
            print(f"      USB ID: {port.vid:04x}:{port.pid:04x}")

    print(f"\n{'='*50}")

    while True:
        try:
            user_input = input(f"\n{prompt} [0-{len(ports)-1}] (直接回车选择第一个 / Enter for first): ").strip()

            if not user_input:
                selection = 0
            else:
                selection = int(user_input)

            if 0 <= selection < len(ports):
                selected = ports[selection]
                print(f"✅ 已选择 / Selected: {selected.device}")
                return selected.device
            else:
                print(f"❌ 无效选择，请输入 0-{len(ports)-1} 之间的数字")
                print(f"   Invalid selection, please enter 0-{len(ports)-1}")

        except ValueError:
            print(f"❌ 无效输入，请输入数字")
            print(f"   Invalid input, please enter a number")
        except (EOFError, KeyboardInterrupt):
            print(f"\n❌ 用户取消 / User cancelled")
            return None


if __name__ == "__main__":
    # 测试代码
    print("Platform Info:")
    for key, value in get_platform_info().items():
        print(f"  {key}: {value}")

    print("\n" + list_ports_for_user())

    print("\nDefault port (index=0):", get_default_port(0))
    print("Default port (index=1):", get_default_port(1))

    # 测试交互式选择
    print("\n" + "="*50)
    print("测试交互式端口选择 / Testing interactive port selection")
    print("="*50)
    selected = select_port_interactive()
    if selected:
        print(f"\n最终选择 / Final selection: {selected}")
