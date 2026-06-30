#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Seeed_RoboController 环境检查脚本
运行: python setup.py
"""

import os
import sys
import platform
import subprocess


def install_package(package):
    """安装 Python 包"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"[OK] {package} 安装成功")
        return True
    except subprocess.CalledProcessError:
        print(f"[ERROR] {package} 安装失败")
        return False


def check_import(module_name, package_name=None, install=False):
    """检查模块是否可导入"""
    try:
        __import__(module_name)
        print(f"[OK] {module_name} 可导入")
        return True
    except ImportError:
        print(f"[ERROR] {module_name} 无法导入")
        if install and package_name:
            print(f"       正在安装 {package_name}...")
            return install_package(package_name)
        return False


def check_python_version():
    """检查 Python 版本"""
    version = sys.version_info
    print(f"[INFO] Python 版本: {version.major}.{version.minor}.{version.micro}")
    if version < (3, 8):
        print("[ERROR] 需要 Python >= 3.8")
        return False
    print("[OK] Python 版本符合要求")
    return True


def check_files():
    """检查关键文件是否存在"""
    print("\n检查项目文件完整性...")
    required_files = [
        "requirements.txt",
        "src/port_utils.py",
        "src/calibration_manager.py",
        "src/tools/scan_id.py",
        "src/tools/lerobot_calibrate.py",
        "src/tools/run_calibration_middle.py",
        "src/gui/factory_calibration_tool.py",
        "src/gui/calibration_wizard.py",
        "scservo_sdk/port_handler.py",
        "scservo_sdk/sms_sts.py",
        "scservo_sdk/scservo_def.py",
    ]

    all_ok = True
    for f in required_files:
        if os.path.exists(f):
            print(f"[OK] {f}")
        else:
            print(f"[ERROR] 缺失: {f}")
            all_ok = False
    return all_ok


def main():
    print("=" * 50)
    print("Seeed_RoboController 环境检查")
    print("=" * 50)
    print(f"平台: {platform.system()} {platform.release()}")
    print(f"机器: {platform.machine()}")
    print("")

    all_ok = True

    if not check_python_version():
        all_ok = False

    # 检查依赖
    print("\n检查 Python 依赖...")
    dependencies = [
        ("PySide6", "PySide6"),
        ("serial", "pyserial"),
    ]
    for module, package in dependencies:
        if not check_import(module, package):
            all_ok = False

    # 检查项目模块
    print("\n检查项目模块...")
    project_modules = [
        "src.port_utils",
        "src.calibration_manager",
    ]
    for module in project_modules:
        if not check_import(module):
            all_ok = False

    # 检查 SDK
    print("\n检查 SCServo SDK...")
    sdk_modules = [
        "scservo_sdk.port_handler",
        "scservo_sdk.sms_sts",
        "scservo_sdk.scservo_def",
    ]
    for module in sdk_modules:
        if not check_import(module):
            all_ok = False

    # 检查文件
    if not check_files():
        all_ok = False

    print("")
    if all_ok:
        print("=" * 50)
        print("[OK] 环境检查通过，可以运行项目")
        print("=" * 50)
        print("\n常用命令:")
        print("  python -m src.tools.scan_id --list")
        print("  python -m src.tools.scan_id")
        print("  python -m src.gui.factory_calibration_tool")
        print("  python -m src.tools.lerobot_calibrate")
        print("  python -m src.tools.run_calibration_middle")
        return 0
    else:
        print("=" * 50)
        print("[ERROR] 环境检查未通过，请修复上述问题")
        print("=" * 50)
        print("\n可尝试手动安装:")
        print("  python3 -m venv .venv")
        print("  source .venv/bin/activate")
        print("  pip install -r requirements.txt")
        return 1


if __name__ == "__main__":
    sys.exit(main())
