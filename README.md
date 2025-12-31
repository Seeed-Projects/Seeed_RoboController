<div align="center">

# FTServo 工厂校准工具
# FTServo Factory Calibration Tool

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Ubuntu%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.7+-green)
![License](https://img.shields.io/badge/license-MIT-orange)

**一套完整的 FTServo 舵机工厂校准工具包**

*A complete FTServo servo factory calibration toolkit*

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

---

## 快速开始

### 1 安装依赖

```bash
pip install -r requirements.txt
```

或手动安装：

```bash
pip install PySide6 pyserial
```

### 2 查看可用串口

```bash
python -m src.tools.scan_id --list
```

### 3 连接舵机并扫描

```bash
python -m src.tools.scan_id
```

---

## 脚本工具对照表

| 脚本名称 | 功能描述 | Windows | Ubuntu | macOS |
|----------|----------|:-------:|:------:|:-----:|
| [src/gui/factory_calibration_tool.py](src/gui/factory_calibration_tool.py) | 双端口 GUI 校准工具 | ✅ | ✅ | ✅ |
| [src/tools/scan_id.py](src/tools/scan_id.py) | 扫描检测舵机 ID | ✅ | ✅ | ✅ |
| [src/tools/servo_center_test.py](src/tools/servo_center_test.py) | 中位测试验证 | ✅ | ✅ | ✅ |
| [src/tools/servo_disable.py](src/tools/servo_disable.py) | 失能舵机力矩 | ✅ | ✅ | ✅ |
| [src/tools/servo_middle_calibration.py](src/tools/servo_middle_calibration.py) | 中位校准 | ✅ | ✅ | ✅ |
| [src/tools/servo_quick_calibration.py](src/tools/servo_quick_calibration.py) | 快速失能+校准 | ✅ | ✅ | ✅ |
| [src/tools/servo_remote_control.py](src/tools/servo_remote_control.py) | 双端口同步遥控 | ✅ | ✅ | ✅ |
| [src/gui/servo_angle_limit_set.py](src/gui/servo_angle_limit_set.py) | 角度限制设置 GUI | ✅ | ✅ | ✅ |
| [src/tools/change_single_servo_id.py](src/tools/change_single_servo_id.py) | 修改单个舵机 ID | ✅ | ✅ | ✅ |

---

## 使用文档

### src/gui/factory_calibration_tool.py

双串口 GUI 校准工具，支持完整的舵机校准流程。

```bash
# 交互式选择端口
python -m src.gui.factory_calibration_tool

# 手动指定端口
python -m src.gui.factory_calibration_tool --port1 /dev/cu.usbserial-xxx --port2 /dev/cu.usbserial-yyy
```

**功能：**
- 双端口独立控制
- 中位校准与测试
- 实时位置读取
- 力矩开关控制

---

### src/tools/scan_id.py

扫描串口上的所有舵机，自动检测 ID 1-20。

```bash
# 交互式选择端口
python -m src.tools.scan_id

# 指定端口扫描
python -m src.tools.scan_id /dev/cu.usbserial-xxx

# 列出可用端口
python -m src.tools.scan_id --list
```

**输出示例：**
```
==================================================
 舵机扫描工具 / Servo ID Scanner
==================================================
端口 / Port: /dev/cu.usbmodem58FA1023621
扫描范围 / Scan Range: ID 1 - 20
==================================================

 扫描中 / Scanning...
--------------------------------------------------
ID    | 型号 (Model)     | 状态
--------------------------------------------------
1     | 3310             | ✅ 在线 / Online
2     | 3310             | ✅ 在线 / Online
3     | 3310             | ✅ 在线 / Online
--------------------------------------------------

📊 扫描结束 / Scan Complete
   发现 3 个舵机 / Found 3 servo(s): [1, 2, 3]
==================================================
```

---

### src/tools/servo_center_test.py

测试舵机中位校准结果，移动到位置 2048 验证。

```bash
# 交互式选择端口
python -m src.tools.servo_center_test

# 指定端口测试
python -m src.tools.servo_center_test /dev/cu.usbserial-xxx
```

**测试流程：**
1. 扫描舵机
2. 读取当前位置
3. 启动力矩
4. 移动到中位 (2048)
5. 显示位移结果

**判断标准：**
- ✅ 校准成功：舵机保持原位（位移很小）
- ❌ 需要重新校准：舵机移动幅度较大

---

### src/tools/servo_disable.py

关闭舵机力矩，使其可以手动旋转。

```bash
# 交互式选择端口
python -m src.tools.servo_disable

# 指定端口失能
python -m src.tools.servo_disable /dev/cu.usbserial-xxx
```

**使用场景：**
- 手动调整舵机位置
- 校准前准备
- 维护和检修

---

### src/tools/servo_middle_calibration.py

舵机中位校准，将当前位置设为中位值 (2048)。

```bash
# 交互式选择端口（可选择模式）
python -m src.tools.servo_middle_calibration

# 指定端口校准
python -m src.tools.servo_middle_calibration /dev/cu.usbserial-xxx
```

**两种模式：**

| 模式 | 说明 |
|------|------|
| 🤝 交互式 | 逐步引导，每个步骤需确认 |
| 🚀 自动 | 快速执行，自动完成校准 |

**校准流程：**
1. 扫描舵机
2. 失能舵机（可选）
3. 手动调整到期望中位
4. 发送校准命令
5. 移动测试验证

---

### src/tools/servo_quick_calibration.py

快速失能并校准中位，一键完成。

```bash
# 交互式选择端口
python -m src.tools.servo_quick_calibration

# 指定端口
python -m src.tools.servo_quick_calibration /dev/cu.usbserial-xxx
```

**快捷流程：**
1. 自动失能所有舵机
2. 等待手动调整
3. 一键校准中位

---

### src/tools/servo_remote_control.py

双端口同步遥控系统，从主控端口读取角度，同步控制从控端口。

```bash
# 交互式选择双端口
python -m src.tools.servo_remote_control

# 指定端口
python -m src.tools.servo_remote_control --read-port /dev/cu.usbserial-xxx --control-port /dev/cu.usbserial-yyy
```

**控制参数：**
- 更新间隔：10ms (100Hz)
- 舵机速度：3000
- 加速度：100

**使用场景：**
- 主从同步控制
- 镜像运动复制
- 双机器人协作

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
python -c "from src.port_utils import list_ports_for_user; print(list_ports_for_user())"
```

#### Ubuntu/Linux

```bash
# 查看可用端口
ls -l /dev/ttyUSB* /dev/ttyACM*

# 查看插入设备
dmesg | grep tty
```

#### Windows

```bash
# 在设备管理器中查看 "端口 (COM 和 LPT)"
# 或使用 Python
python -c "from src.port_utils import list_ports_for_user; print(list_ports_for_user())"
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
# 重新登录后生效
```

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 🐍 Python | 3.7 或更高版本 |
| 🖼️ PySide6 | >= 6.0 |
| 🔌 pyserial | >= 3.5 |

---

## 项目结构

```
Seeed_RoboController/
├── src/
│   ├── port_utils.py              # 串口工具模块
│   ├── tools/                     # 命令行工具
│   │   ├── scan_id.py             # 舵机 ID 扫描
│   │   ├── servo_center_test.py   # 中位测试
│   │   ├── servo_disable.py       # 舵机失能
│   │   ├── servo_middle_calibration.py  # 中位校准
│   │   ├── servo_quick_calibration.py   # 快速校准
│   │   ├── servo_remote_control.py      # 双端口遥控
│   │   └── change_single_servo_id.py    # 修改舵机 ID
│   └── gui/                       # GUI 工具
│       ├── factory_calibration_tool.py  # GUI 双端口校准工具
│       └── servo_angle_limit_set.py    # 角度限制设置 GUI
│
├── scservo_sdk/                   # SCServo SDK
├── setup.py                       # 安装检查脚本
├── requirements.txt               # 依赖清单
└── README.md                      # 项目文档
```

> **运行方式**: 所有工具使用 `python -m src.<tools|gui>.<脚本名>` 运行

---

## 更新日志

### v2.1 (最新)

- 📁 重构项目结构，所有代码移至 `src/` 目录
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

Made with for FTServo Community

</div>
