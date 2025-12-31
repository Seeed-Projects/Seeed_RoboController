#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Factory Calibration Tool Setup Script
检查并安装必要的依赖
"""

import subprocess
import sys
import os

def install_package(package):
    """安装Python包"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"[OK] {package} installed successfully")
        return True
    except subprocess.CalledProcessError:
        print(f"[ERROR] Failed to install {package}")
        return False

def check_import(module_name, package_name=None):
    """检查模块是否可导入"""
    try:
        __import__(module_name)
        print(f"[OK] {module_name} is available")
        return True
    except ImportError:
        print(f"[ERROR] {module_name} is not available")
        if package_name:
            print(f"       Installing {package_name}...")
            return install_package(package_name)
        return False

def main():
    print("=== Factory Calibration Tool Setup ===")
    print("Checking dependencies...\n")

    # 检查必要的Python包
    dependencies = [
        ("PySide6", "PySide6"),
        ("serial", "pyserial"),
    ]

    all_ok = True
    for module, package in dependencies:
        if not check_import(module, package):
            all_ok = False

    # 检查文件完整性
    print("\nChecking file integrity...")
    required_files = [
        "factory_calibration_tool.py",
        "servo_middle_calibration.py",
        "servo_quick_calibration.py",
        "servo_center_test.py",
        "servo_disable.py",
        "servo_remote_control.py",
        "scservo_sdk/port_handler.py",
        "scservo_sdk/sms_sts.py",
        "scservo_sdk/scservo_def.py",
    ]

    for file in required_files:
        if os.path.exists(file):
            print(f"[OK] {file}")
        else:
            print(f"[ERROR] {file} is missing")
            all_ok = False

    if all_ok:
        print("\n=== Setup Complete! ===")
        print("You can now run the calibration tool:")
        print("  python factory_calibration_tool.py")
        print("\nThe tool will auto-detect available serial ports.")
        print("Or manually specify ports:")
        import platform
        if platform.system() == "Windows":
            print("  python factory_calibration_tool.py --port1 COM1 --port2 COM2")
        else:
            # macOS/Linux: Show actual detected ports if available
            try:
                from port_utils import get_available_ports, list_ports_for_user
                ports = get_available_ports()
                if len(ports) >= 2:
                    print(f"  python factory_calibration_tool.py --port1 {ports[0].device} --port2 {ports[1].device}")
                elif len(ports) == 1:
                    print(f"  python factory_calibration_tool.py --port1 {ports[0].device}")
                    print("  (Note: Only one port detected, connect another adapter)")
                else:
                    print("  python factory_calibration_tool.py --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1")
                    print("  (No ports detected, please connect USB-to-Serial adapter)")
            except ImportError:
                print("  python factory_calibration_tool.py --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1")
    else:
        print("\n=== Setup Failed ===")
        print("Please fix the issues above before running the tool.")
        sys.exit(1)

if __name__ == "__main__":
    main()