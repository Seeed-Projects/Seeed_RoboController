<div align="center">

# Seeed Studio SoARM 系列校准工具

# Seeed Studio SoARM Series Calibration Tool

**专为 Seeed Studio SoARM 10X 系列机械臂设计的 FTServo 舵机工厂校准与 LeRobot 校准工具包**

*A complete FTServo servo factory calibration and LeRobot-style calibration toolkit designed for Seeed Studio SoARM 10X series robotic arms*

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Ubuntu%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![License](https://img.shields.io/badge/license-MIT-orange)

[功能特性](#-功能特性)  [快速开始](#-快速开始)  [使用文档](#-使用文档)  [故障排除](#-故障排除)

</div>

---

## 功能特性


| 特性             | 说明                                |
| ---------------- | ----------------------------------- |
| 自动端口检测     | 智能识别 USB 串口，自动过滤虚拟设备 |
| 跨平台支持       | Windows / Ubuntu / macOS 全平台兼容 |
| 交互式选择       | 友好的命令行交互，轻松选择串口      |
| 双端口同步       | 支持主从双端口同步遥控控制          |
| GUI 工具         | Qt 图形界面，直观易用               |
| 自动扫描         | 自动检测 ID 1-20 范围内所有舵机     |
| LeRobot 校准     | 生成 LeRobot 格式的 JSON 校准文件   |
| 校准文件中位运行 | 根据校准文件将机械臂移动到中位      |

---

## 快速开始

### 1 环境要求

- Python >= 3.8
- PySide6 >= 6.0
- pyserial >= 3.5

### 2 安装依赖

推荐安装在lerobot虚拟环境中，如需单独创立建议创立新的虚拟环境，避免污染系统 Python。

```bash
# 安装依赖
pip install -r requirements.txt
```

### 3 检查环境

```bash
python setup.py
```

### 4 开始使用

```bash
# 交互式选择端口
python -m src.gui.factory_calibration_tool

# 手动指定端口（如若端口被占用）
python -m src.gui.factory_calibration_tool --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1
```

---
