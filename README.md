# FTServo 工厂校准工具 (FTServo Factory Calibration Tool)

这是一个完整的FTServo舵机工厂校准工具包，包含双串口校准GUI界面和所有必要的脚本。支持 Windows、macOS 和 Linux。

## 文件说明 (File Description)

- `factory_calibration_tool.py` - 主GUI应用程序，支持双串口舵机校准
- `servo_angle_limit_set.py` - 舵机角度限制设置GUI工具
- `servo_middle_calibration.py` - 舵机中位值校准脚本
- `servo_quick_calibration.py` - 快速校准脚本
- `servo_center_test.py` - 舵机中心测试脚本
- `servo_disable.py` - 舵机失能脚本
- `servo_remote_control.py` - 遥控操作脚本
- `scan_id.py` - 舵机ID扫描工具
- `change_single_servo_id.py` - 修改单个舵机ID工具
- `scservo_sdk/` - SCServo SDK文件夹，包含舵机通信库
- `setup.py` - 自动化安装和检查脚本
- `requirements.txt` - Python依赖清单

## 安装 (Installation)

### 方法一：使用 requirements.txt（推荐）

```bash
pip install -r requirements.txt
```

### 方法二：手动安装

```bash
pip install PySide6 pyserial
```

### 方法三：运行安装脚本

```bash
python setup.py
```

## 使用方法 (Usage)

### 运行主GUI程序

```bash
python factory_calibration_tool.py
```

### 指定串口运行

**Windows:**
```bash
python factory_calibration_tool.py --port1 COM1 --port2 COM2
```

**macOS / Linux:**
```bash
python factory_calibration_tool.py --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1
```

### 其他工具

**扫描舵机ID:**
```bash
python scan_id.py [port]
```

**舵机中位校准:**
```bash
python servo_middle_calibration.py [port]
```

**遥控操作:**
```bash
# Windows
python servo_remote_control.py --read-port COM7 --control-port COM8

# macOS / Linux
python servo_remote_control.py --read-port /dev/ttyUSB0 --control-port /dev/ttyUSB1
```

## 串口配置 (Serial Port Configuration)

### 默认串口

| 平台 | 默认串口1 | 默认串口2 |
|------|-----------|-----------|
| Windows | COM1 | COM2 |
| macOS | /dev/ttyUSB0 | /dev/ttyUSB1 |
| Linux | /dev/ttyUSB0 | /dev/ttyUSB1 |

### macOS 串口设备查找

在 macOS 上，USB转串口设备通常显示为：
- `/dev/tty.usbserial-*` - 常见的USB转串口
- `/dev/cu.usbserial-*` - 呼出设备（推荐使用）
- `/dev/tty.usbmodem-*` - Arduino风格调制解调器
- `/dev/cu.usbmodem-*` - 呼出设备

查找可用串口：
```bash
# 列出所有串口设备
ls /dev/tty.* /dev/cu.*

# 或使用 Python
python -c "import serial.tools.list_ports; print([p.device for p in serial.tools.list_ports.comports()])"
```

## 功能特性 (Features)

- 双串口同时校准支持
- 动态串口选择
- 中位校准、中位测试、失能电机功能
- 舵机角度限制设置
- 水平布局UI，美观节省空间
- 连接稳定性和智能重试机制
- 跨平台支持（Windows / macOS / Linux）

## 系统要求 (Requirements)

- Python 3.7+
- PySide6（GUI界面）
- pyserial（串口通信）

## 注意事项 (Notes)

- 确保舵机正确连接到指定串口
- 校准过程中请勿移动舵机
- 建议在校准前先进行中位测试
- macOS 用户可能需要安装 USB 驱动程序（如 CH340/CP2102）

## 许可证 (License)

本项目遵循 MIT 许可证。