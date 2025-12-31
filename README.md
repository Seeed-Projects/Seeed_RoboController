# FTServo 工厂校准工具 (FTServo Factory Calibration Tool)

这是一个完整的FTServo舵机工厂校准工具包，包含双串口校准GUI界面和所有必要的脚本。支持 Windows、macOS 和 Linux。

**主要特性：自动检测可用串口，跨平台支持**

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
- `port_utils.py` - 跨平台串口检测工具模块
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

### 自动检测模式（推荐）

所有脚本支持自动检测可用串口，无需手动指定：

```bash
# 主GUI工具 - 自动检测前两个可用串口
python factory_calibration_tool.py

# 扫描舵机ID - 自动检测第一个可用串口
python scan_id.py

# 中位校准 - 自动检测并提示选择串口
python servo_middle_calibration.py

# 遥控操作 - 自动检测前两个可用串口
python servo_remote_control.py
```

### 手动指定串口

**Windows:**
```bash
python factory_calibration_tool.py --port1 COM1 --port2 COM2
```

**macOS / Linux:**
```bash
# 使用自动检测到的设备
python factory_calibration_tool.py --port1 /dev/cu.usbserial-xxx --port2 /dev/cu.usbserial-yyy

# 或使用标准设备名（如果有映射）
python factory_calibration_tool.py --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1
```

## 串口配置 (Serial Port Configuration)

### 自动检测优先级

工具使用 `port_utils.py` 自动检测串口，按以下优先级排序：

| 平台 | 最高优先级 | 次优先级 |
|------|-----------|----------|
| **macOS** | `/dev/cu.usbserial-*` | `/dev/cu.usbmodem-*` |
| **macOS** | `/dev/cu.usbserial-*` | `/dev/tty.usbserial-*` |
| **Linux** | `/dev/ttyUSB*` | `/dev/ttyACM*` |
| **Windows** | COM1, COM2... | （按编号排序） |

> **注意**: macOS 上优先使用 `cu.*` 设备而非 `tty.*`，因为 `cu` 设备是非阻塞的，更适合通信应用。

### 查找可用串口

**macOS:**
```bash
# 列出所有串口设备
ls /dev/tty.* /dev/cu.*

# 使用 Python 脚本检测
python -c "from port_utils import list_ports_for_user; print(list_ports_for_user())"
```

**Linux:**
```bash
# 列出 USB 串口设备
ls -l /dev/ttyUSB* /dev/ttyACM*

# 或使用 dmesg 查看最近插入的设备
dmesg | grep tty
```

**Windows:**
```bash
# 在设备管理器中查看 "端口 (COM 和 LPT)"
# 或使用 Python
python -c "from port_utils import list_ports_for_user; print(list_ports_for_user())"
```

### macOS 串口设备说明

| 设备类型 | 路径格式 | 说明 |
|----------|----------|------|
| 呼出设备（推荐） | `/dev/cu.usbserial-*` | 非阻塞，适合通信 |
| 呼入设备 | `/dev/tty.usbserial-*` | 可能阻塞，不推荐 |
| USB Modem | `/dev/cu.usbmodem-*` | Arduino 风格设备 |
| 蓝牙串口 | `/dev/cu.Bluetooth*` | 蓝牙虚拟串口 |

## 功能特性 (Features)

- 自动检测可用串口（跨平台）
- macOS 上优先使用 `cu.*` 非阻塞设备
- 双串口同时校准支持
- 动态串口选择和切换
- 中位校准、中位测试、失能电机功能
- 舵机角度限制设置
- 水平布局UI，美观节省空间
- 连接稳定性和智能重试机制

## 系统要求 (Requirements)

- Python 3.7+
- PySide6（GUI界面）
- pyserial（串口通信）

## 注意事项 (Notes)

- 首次使用前请运行 `python setup.py` 检查环境
- 确保舵机正确连接到串口
- 校准过程中请勿移动舵机
- macOS 用户可能需要安装 USB 驱动程序：
  - **CH340 芯片**: [下载地址](http://www.wch.cn/download/CH341SER_MAC_ZIP.html)
  - **CP2102 芯片**: [下载地址](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)
  - **FTDI 芯片**: 通常 macOS 自带驱动

## 许可证 (License)

本项目遵循 MIT 许可证。