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

| 特性 | 说明 |
|------|------|
| 自动端口检测 | 智能识别 USB 串口，自动过滤虚拟设备 |
| 跨平台支持 | Windows / Ubuntu / macOS 全平台兼容 |
| 交互式选择 | 友好的命令行交互，轻松选择串口 |
| 双端口同步 | 支持主从双端口同步遥控控制 |
| GUI 工具 | Qt 图形界面，直观易用 |
| 自动扫描 | 自动检测 ID 1-20 范围内所有舵机 |
| LeRobot 校准 | 生成 LeRobot 格式的 JSON 校准文件 |
| 校准文件中位运行 | 根据校准文件将机械臂移动到中位 |

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

## 使用文档（可选）

### 命令行工具 / CLI Tools

| 脚本名称 | 功能描述 | Windows | Ubuntu | macOS |
|----------|----------|:-------:|:------:|:-----:|
| [src/tools/scan_id.py](src/tools/scan_id.py) | 扫描检测舵机 ID | ✅ | ✅ | ✅ |
| [src/tools/lerobot_calibrate.py](src/tools/lerobot_calibrate.py) | LeRobot 风格整臂校准 | ✅ | ✅ | ✅ |
| [src/tools/run_calibration_middle.py](src/tools/run_calibration_middle.py) | 根据校准文件运行到中位 | ✅ | ✅ | ✅ |
| [src/tools/servo_center_test.py](src/tools/servo_center_test.py) | 中位测试验证 | ✅ | ✅ | ✅ |
| [src/tools/servo_disable.py](src/tools/servo_disable.py) | 失能舵机力矩 | ✅ | ✅ | ✅ |
| [src/tools/servo_middle_calibration.py](src/tools/servo_middle_calibration.py) | 中位校准 | ✅ | ✅ | ✅ |
| [src/tools/servo_quick_calibration.py](src/tools/servo_quick_calibration.py) | 快速失能+校准 | ✅ | ✅ | ✅ |
| [src/tools/servo_remote_control.py](src/tools/servo_remote_control.py) | 双端口同步遥控 | ✅ | ✅ | ✅ |
| [src/tools/change_single_servo_id.py](src/tools/change_single_servo_id.py) | 修改单个舵机 ID | ✅ | ✅ | ✅ |

### GUI 工具 / GUI Tools

| 脚本名称 | 功能描述 | Windows | Ubuntu | macOS |
|----------|----------|:-------:|:------:|:-----:|
| [src/gui/factory_calibration_tool.py](src/gui/factory_calibration_tool.py) | 双端口 GUI 工厂校准工具 | ✅ | ✅ | ✅ |
| [src/gui/calibration_wizard.py](src/gui/calibration_wizard.py) | LeRobot 校准向导（GUI） | ✅ | ✅ | ✅ |
| [src/gui/servo_angle_limit_set.py](src/gui/servo_angle_limit_set.py) | 角度限制设置 GUI | ✅ | ✅ | ✅ |

---

## 详细用法

### src/tools/scan_id.py

###  查看可用串口

```bash
python -m src.tools.scan_id --list
```

###  连接舵机并扫描

```bash
python -m src.tools.scan_id
```

扫描串口上的所有舵机，自动检测 ID 1-20。

```bash
# 交互式选择端口
python -m src.tools.scan_id

# 指定端口扫描
python -m src.tools.scan_id /dev/ttyUSB0

# 列出可用端口
python -m src.tools.scan_id --list
```

---

### src/tools/lerobot_calibrate.py

LeRobot 风格交互式机械臂校准，生成 JSON 校准文件。

```bash
# 交互式选择端口和保存路径
python -m src.tools.lerobot_calibrate

# 指定端口
python -m src.tools.lerobot_calibrate /dev/ttyUSB0

# 标定领导臂
python -m src.tools.lerobot_calibrate --arm-type leader

# 列出可用串口
python -m src.tools.lerobot_calibrate --list
```

校准文件默认保存到：
- 从动臂：`~/.cache/huggingface/lerobot/calibration/robots/so_follower/`
- 领导臂：`~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/`

---

### src/tools/run_calibration_middle.py

根据 LeRobot 校准文件将舵机移动到中位。

```bash
# 交互式选择端口
python -m src.tools.run_calibration_middle ~/.cache/huggingface/lerobot/calibration/robots/so_follower/my_awesome_follower_arm.json

# 指定端口
python -m src.tools.run_calibration_middle ~/.cache/huggingface/lerobot/calibration/robots/so_follower/my_awesome_follower_arm.json /dev/ttyUSB0

# 使用范围中点而非 homing_offset
python -m src.tools.run_calibration_middle my_awesome_follower_arm.json /dev/ttyUSB0 --mode range
```

---

### src/gui/factory_calibration_tool.py

双串口 GUI 工厂校准工具，支持完整的舵机校准流程。

```bash
# 交互式选择端口
python -m src.gui.factory_calibration_tool

# 手动指定端口
python -m src.gui.factory_calibration_tool --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1
```

**功能：**
- 双端口独立控制
- 中位校准与测试
- 实时位置读取
- 力矩开关控制
- 修改舵机 ID

---

### src/gui/calibration_wizard.py

LeRobot 校准向导对话框，图形化引导整臂校准。

```bash
python -m src.gui.calibration_wizard
```

---

### src/tools/servo_center_test.py

测试舵机中位校准结果，移动到位置 2048 验证。

```bash
python -m src.tools.servo_center_test
python -m src.tools.servo_center_test /dev/ttyUSB0
```

---

### src/tools/servo_disable.py

关闭舵机力矩，使其可以手动旋转。

```bash
python -m src.tools.servo_disable
python -m src.tools.servo_disable /dev/ttyUSB0
```

---

### src/tools/servo_middle_calibration.py

舵机中位校准，将当前位置设为中位值 2048。

```bash
python -m src.tools.servo_middle_calibration
python -m src.tools.servo_middle_calibration /dev/ttyUSB0
```

---

### src/tools/servo_quick_calibration.py

快速失能并校准中位，一键完成。

```bash
python -m src.tools.servo_quick_calibration
python -m src.tools.servo_quick_calibration /dev/ttyUSB0
```

---

### src/tools/servo_remote_control.py

双端口同步遥控系统，从主控端口读取角度，同步控制从控端口。

```bash
# 交互式选择双端口
python -m src.tools.servo_remote_control

# 指定端口
python -m src.tools.servo_remote_control --read-port /dev/ttyUSB0 --control-port /dev/ttyUSB1
```

---

### src/gui/servo_angle_limit_set.py

GUI 工具，设置舵机角度限制范围。

```bash
python -m src.gui.servo_angle_limit_set
```

---

### src/tools/change_single_servo_id.py

修改单个舵机的 ID 地址。

```bash
python -m src.tools.change_single_servo_id
```

---

## 串口配置

### 自动端口检测

所有脚本使用 `src/port_utils.py` 进行智能端口检测：

```
优先级排序：
┌─────────────────────────────────────────────────────────┐
│ macOS: cu.usbserial → cu.usbmodem → cu.* → tty.*      │
│ Linux: ttyUSB → ttyACM → others                        │
│ Windows: COM1 → COM2 → ... (按编号)                    │
└─────────────────────────────────────────────────────────┘

自动过滤：
┌─────────────────────────────────────────────────────────┐
│ ❌ DEBUG      (调试端口)                                 │
│ ❌ BLUETOOTH  (蓝牙设备)                                 │
│ ❌ RFCOMM     (蓝牙 RFCOMM)                              │
│ ❌ INCOMING   (传入连接)                                 │
│ ❌ ttyS*      (Linux 虚拟串口)                           │
└─────────────────────────────────────────────────────────┘
```

### 平台特定说明

#### macOS

| 设备类型 | 路径格式 | 推荐 |
|----------|----------|:----:|
| USB Serial | `/dev/cu.usbserial-*` | ✅ |
| USB Modem | `/dev/cu.usbmodem-*` | ✅ |
| TTY 设备 | `/dev/tty.usbserial-*` | ❌ |

查看可用端口：
```bash
ls /dev/cu.* /dev/tty.*
python -m src.tools.scan_id --list
```

#### Ubuntu/Linux

```bash
# 查看可用端口
ls -l /dev/ttyUSB* /dev/ttyACM*

# 查看插入设备
dmesg | grep tty
```

#### Windows

```cmd
# 在设备管理器中查看 "端口 (COM 和 LPT)"
# 或使用 Python
python -m src.tools.scan_id --list
```

---

## 常见问题

### Q: macOS 上检测到 `/dev/cu.debug-console` 而不是 USB 设备？

**A:** 这通常发生在没有物理 USB 设备连接时。新版本已自动过滤此类虚拟设备。确保 USB 舵机已正确连接。

### Q: 提示 "Need at least 2 serial ports"？

**A:** 双端口工具需要两个 USB 设备。检查：
```bash
python -m src.tools.scan_id --list
```

### Q: 舵机校准后移动幅度很大？

**A:** 说明校准前舵机不在正确中位。重新运行：
```bash
python -m src.tools.servo_middle_calibration
```
在校准前手动将舵机调整到期望的中位位置。

### Q: macOS 上无法访问串口？

**A:** 可能需要安装 USB 转串口驱动：

| 芯片型号 | 驱动下载 |
|----------|----------|
| CH340 | [下载](http://www.wch.cn/download/CH341SER_MAC_ZIP.html) |
| CP2102 | [下载](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers) |
| FTDI | 通常自带驱动 |

### Q: Linux 上提示权限拒绝？

**A:** 将用户添加到 dialout 组：
```bash
sudo usermod -a -G dialout $USER
# 重新登录后生效，或执行 newgrp dialout
```

### Q: 运行 GUI 时报错缺少 Qt 平台插件？

**A:** Linux 上可能需要安装系统图形库：
```bash
sudo apt install -y libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-xfixes0 libopengl0 libegl1
```

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 🐍 Python | 3.8 或更高版本 |
| 🖼️ PySide6 | >= 6.0 |
| 🔌 pyserial | >= 3.5 |

---

## 项目结构

```
Seeed_RoboController/
├── src/
│   ├── __init__.py                # 包标记
│   ├── port_utils.py              # 串口工具模块
│   ├── calibration_manager.py     # LeRobot 校准文件管理
│   ├── tools/                     # 命令行工具
│   │   ├── __init__.py
│   │   ├── scan_id.py             # 舵机 ID 扫描
│   │   ├── lerobot_calibrate.py   # LeRobot 风格校准
│   │   ├── run_calibration_middle.py  # 校准文件中位运行
│   │   ├── servo_center_test.py   # 中位测试
│   │   ├── servo_disable.py       # 舵机失能
│   │   ├── servo_middle_calibration.py  # 中位校准
│   │   ├── servo_quick_calibration.py   # 快速校准
│   │   ├── servo_remote_control.py      # 双端口遥控
│   │   └── change_single_servo_id.py    # 修改舵机 ID
│   └── gui/                       # GUI 工具
│       ├── __init__.py
│       ├── factory_calibration_tool.py  # GUI 双端口工厂校准工具
│       ├── calibration_wizard.py        # LeRobot 校准向导
│       └── servo_angle_limit_set.py     # 角度限制设置 GUI
│
├── scservo_sdk/                   # SCServo SDK
├── setup.py                       # 环境检查脚本
├── requirements.txt               # 依赖清单
└── README.md                      # 项目文档
```

> **运行方式**: 所有工具使用 `python -m src.<tools|gui>.<脚本名>` 运行

---

## 更新日志

### v2.2

- 📁 重构项目结构，所有代码移至 `src/` 目录
- 🤖 新增 LeRobot 风格校准工具
- 🧙 新增 LeRobot 校准向导 GUI
- 📄 新增校准文件中位运行工具
- 🧹 删除根目录重复的旧包装脚本
- 📦 统一使用 Python 模块方式运行工具 (`python -m src.<tools|gui>.*`)

### v2.0

- 智能端口选择，自动过滤虚拟设备
- 交互式端口选择
- 自动扫描 ID 1-20 范围内舵机
- 修正中位值为 2048
- 全平台兼容性增强
- 双语界面（中文/English）

---

## 许可证

本项目采用 MIT 许可证开源。

---

<div align="center">

**如有问题，请提交 Issue**

Built with ❤️ for the SoARM 10X community

Powered by Seeed Studio

</div>
