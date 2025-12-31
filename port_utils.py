#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
跨平台串口工具模块
Cross-platform serial port utilities
"""

import platform
import os


def get_available_ports():
    """
    获取所有可用的串口设备
    Get all available serial port devices

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
                if "/dev/cu." in device:
                    if "USB" in device or "ACM" in device:
                        return 1  # cu.usb* / cu.acm* - 最高优先级
                    return 2
                if "/dev/tty." in device:
                    return 3  # tty.* 设备（阻塞，优先级较低）
                return 4

            # Linux: USB 设备优先
            elif system == "Linux":
                if "ttyUSB" in device or "ttyACM" in device:
                    return 1
                return 2

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


if __name__ == "__main__":
    # 测试代码
    print("Platform Info:")
    for key, value in get_platform_info().items():
        print(f"  {key}: {value}")

    print("\n" + list_ports_for_user())

    print("\nDefault port (index=0):", get_default_port(0))
    print("Default port (index=1):", get_default_port(1))
