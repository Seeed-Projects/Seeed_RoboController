#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EZ Tool - Simplified dual-serial-port factory servo calibration tool
Based on the original tool, with just one added mid-point calibration button
"""

import sys
import time
import threading
import subprocess
import os
from typing import List
from queue import Queue

# 添加必要的路径
sys.path.append('.')
sys.path.append('./scservo_sdk')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QGridLayout, QGroupBox,
    QMessageBox, QFrame, QStatusBar, QSplitter, QComboBox,
    QInputDialog, QSpinBox, QDialog, QFormLayout, QDialogButtonBox,
    QTabWidget, QSlider, QScrollArea
)
from PySide6.QtCore import QTimer, Signal, QObject, Qt
from PySide6.QtGui import QFont, QPalette, QColor, QTextCursor

from scservo_sdk.port_handler import PortHandler
from scservo_sdk.sms_sts import sms_sts
from scservo_sdk.scservo_def import COMM_SUCCESS
from scservo_sdk.protocol_packet_handler import (
    ERRBIT_VOLTAGE,
    ERRBIT_OVERHEAT,
    ERRBIT_OVERELE,
    ERRBIT_OVERLOAD,
)

# 引入主题工具，强制浅色主题以避免 Windows 深色模式下文字看不见
try:
    from src.gui.theme_utils import setup_light_theme
    THEME_UTILS_AVAILABLE = True
except ImportError:
    THEME_UTILS_AVAILABLE = False
    print("Warning: theme_utils not found, UI may be unreadable in dark mode")

# 引入端口工具
try:
    from src.port_utils import get_default_port, get_available_ports
    PORT_UTILS_AVAILABLE = True
except ImportError:
    PORT_UTILS_AVAILABLE = False
    print("Warning: port_utils not found, using fallback port detection")

# 引入电压/温度阈值判断
try:
    from src.tools.servo_middle_calibration import (
        get_voltage_range,
        SAFE_TEMPERATURE_MAX,
    )
except ImportError:
    # 备用定义，避免导入失败时 UI 无法启动
    def get_voltage_range(voltage):
        if voltage is None:
            return (4.5, 13.5)
        return (4.5, 5.5) if voltage < 7.0 else (10.5, 13.5)
    SAFE_TEMPERATURE_MAX = 60.0


# 飞特舵机型号映射表（model number -> 型号名称）
# 注：部分型号号为 Seeed / SO-ARM100 定制版本，与飞特官方型号对应
SERVO_MODEL_NAME_MAP = {
    777: "STS3215",
    521: "STS3032",
    3215: "STS3215",
    3250: "STS3250",
    3032: "STS3032",
    3046: "STS3046",
    20: "STS20",
    15: "SCS15",
    25: "SCS25",
    45: "SCS45",
    115: "SCS115",
    215: "SCS215",
    2332: "SCS2332",
    40: "SCS40",
    9: "SCS009",
    6560: "SCS6560",
    30: "SM30",
    60: "SM60",
    150: "SM150",
    260: "SM260",
}


def get_servo_model_name(model_number):
    """Get the servo model name from its model number; returns the raw number string if unknown"""
    if model_number is None:
        return "--"
    name = SERVO_MODEL_NAME_MAP.get(model_number)
    if name:
        return f"{name} (#{model_number})"
    return f"#{model_number}"


# SMS/STS 舵机常用寄存器地址
SMS_STS_MIN_ANGLE_LIMIT_L = 9   # 最小角度限制低字节
SMS_STS_MAX_ANGLE_LIMIT_L = 11  # 最大角度限制低字节
SMS_STS_TORQUE_ENABLE = 40      # 力矩开关/中位校准命令地址
SMS_STS_CALIBRATE_MIDDLE = 128  # 中位校准命令值（将当前位置设为 2048）


class RemoteControlWorker(QObject):
    """Remote-control operation background worker thread"""
    status_updated = Signal(str)  # 状态更新信号
    log_message = Signal(str)   # 日志消息信号
    control_started = Signal()  # 遥控启动信号
    control_stopped = Signal()  # 遥控停止信号

    def __init__(self, read_port=None, control_port=None):
        super().__init__()
        self.remote_process = None
        self.running = False
        self.project_root = os.path.abspath(os.path.dirname(__file__))
        self.read_port = read_port
        self.control_port = control_port

    def start_remote_control(self):
        """Start remote-control operation"""
        if self.running:
            return False, "Remote-control operation already running"

        try:
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk
            command = [sys.executable, '-m', 'src.tools.servo_remote_control']
            if self.read_port:
                command.extend(['--read-port', self.read_port])
            if self.control_port:
                command.extend(['--control-port', self.control_port])

            # 启动子进程运行遥控脚本
            self.remote_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                cwd=self.project_root
            )

            self.running = True
            self.log_message.emit("🚀 Remote-control operation started (10ms update interval)")
            self.control_started.emit()

            # 启动监控线程
            threading.Thread(target=self._monitor_process, daemon=True).start()

            return True, "Remote-control operation started successfully"

        except Exception as e:
            return False, f"Failed to start remote-control operation: {e}"

    def stop_remote_control(self):
        """Stop remote-control operation"""
        if not self.running:
            return False, "Remote-control operation not running"

        try:
            if self.remote_process:
                self.remote_process.terminate()
                # 等待进程正常退出
                try:
                    self.remote_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # 如果5秒内没有退出，强制杀死
                    self.remote_process.kill()
                    self.remote_process.wait()

            self.running = False
            self.remote_process = None
            self.log_message.emit("⏹️ Remote-control operation stopped")
            self.control_stopped.emit()
            return True, "Remote-control operation stopped successfully"

        except Exception as e:
            return False, f"Failed to stop remote-control operation: {e}"

    def _monitor_process(self):
        """Monitor remote-control process output"""
        if not self.remote_process:
            return

        try:
            while self.running and self.remote_process.poll() is None:
                line = self.remote_process.stdout.readline()
                if line:
                    line = line.strip()
                    if line:
                        self.log_message.emit(f"Remote: {line}")
                time.sleep(0.1)

            # 进程结束
            if self.remote_process.poll() is not None:
                self.running = False
                self.remote_process = None
                self.log_message.emit("🔚 Remote-control process ended")
                self.control_stopped.emit()

        except Exception as e:
            self.log_message.emit(f"Exception monitoring remote-control process: {e}")
            self.running = False
            self.control_stopped.emit()


class IDChangeDialog(QDialog):
    """Change servo ID dialog - lets the user set a custom source ID and target ID"""

    def __init__(self, current_servos, default_old_id=None, default_new_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Servo ID")
        self.setMinimumWidth(280)
        self.setStyleSheet("""
            QDialog { background-color: #f8f9fa; color: #212529; }
            QLabel { color: #212529; font-size: 12px; }
            QComboBox {
                background-color: #ffffff; color: #212529; border: 1px solid #ced4da;
                padding: 4px; border-radius: 4px;
            }
            QSpinBox {
                background-color: #ffffff; color: #212529; border: 1px solid #ced4da;
                padding: 4px; border-radius: 4px;
            }
            QDialogButtonBox QPushButton {
                background-color: #007bff; color: white; padding: 5px 15px;
                border-radius: 4px; font-weight: bold;
            }
            QDialogButtonBox QPushButton:hover { background-color: #0056b3; }
        """)

        layout = QFormLayout(self)

        # 源ID（下拉选择当前在线的舵机）
        self.old_id_combo = QComboBox()
        for servo_id in sorted(current_servos):
            self.old_id_combo.addItem(f"Servo ID {servo_id}", servo_id)
        if default_old_id and default_old_id in current_servos:
            index = self.old_id_combo.findData(default_old_id)
            if index >= 0:
                self.old_id_combo.setCurrentIndex(index)
        layout.addRow("Source Servo ID:", self.old_id_combo)

        # 目标ID（数字输入）
        self.new_id_input = QSpinBox()
        self.new_id_input.setRange(1, 253)
        if default_new_id:
            self.new_id_input.setValue(default_new_id)
        else:
            self.new_id_input.setValue(1)
        layout.addRow("Change ID To:", self.new_id_input)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return self.old_id_combo.currentData(), self.new_id_input.value()


class ServoWorker(QObject):
    """Single-servo control worker thread"""
    status_updated = Signal(list, bool, str)  # 舵机列表, 连接状态, 端口标识
    id_changed = Signal(int, int, bool, str, str)  # old_id, new_id, success, message, 端口标识
    log_message = Signal(str, str)  # 日志消息, 端口标识
    positions_updated = Signal(object)  # {servo_id: position} 当前位置更新（object 类型避免 PySide6 dict 转换问题）
    servo_info_updated = Signal(object)  # {servo_id: info_dict} 完整状态更新
    register_read_result = Signal(int, int, int, int, str, str)  # servo_id, address, length, value, result, port_id
    system_command_result = Signal(str, bool, str, str)  # command_type, success, message, port_id

    def __init__(self, port_name: str, port_id: str):
        super().__init__()
        self.port_name = port_name
        self.port_id = port_id  # 端口标识 (left/right)
        self.port_handler = None
        self.servo_handler = None
        self.is_connected = False
        self.current_servos = []
        self.running = False
        self._scanner_thread = None  # 扫描线程引用，stop() 时等待其退出

        # 连接配置
        self.baud_rate = 1000000

        # ID修改队列
        self.id_change_queue = Queue()
        self.id_change_thread = None
        self.id_change_running = False

        # 系统命令队列（寄存器读写、波特率修改、恢复出厂设置）
        self.system_command_queue = Queue()
        self.system_command_thread = None
        self.system_command_running = False

        # 单舵机控制队列（力矩、位置）
        self.torque_queue = Queue()
        self.position_queue = Queue()
        self.command_event = threading.Event()  # 用于立即唤醒扫描线程处理命令

        # 扫描控制
        self.pause_scanning = False  # 是否暂停扫描
        self.rescan_requested = threading.Event()  # 手动重新扫描请求

    def request_rescan(self):
        """Request an immediate rescan"""
        self.rescan_requested.set()
        self.command_event.set()
        self.log_message.emit("🔄 Rescan request received", self.port_id)

    def connect_servo(self) -> bool:
        """Connect to the servo controller"""
        try:
            print(f"[DEBUG] {self.port_id}: Attempting to connect to {self.port_name}")
            self.log_message.emit(f"Connecting to servo controller: {self.port_name}", self.port_id)

            # 如果已有旧连接，先彻底关闭并释放（Windows 必须等句柄释放）
            if self.port_handler is not None:
                try:
                    self.port_handler.closePort()
                except Exception as e:
                    print(f"[DEBUG] {self.port_id}: exception closing old port: {e}")
                self.port_handler = None
                self.servo_handler = None
                if os.name == 'nt':
                    time.sleep(0.3)

            self.port_handler = PortHandler(self.port_name)

            if not self.port_handler.openPort():
                print(f"[DEBUG] {self.port_id}: Failed to open port {self.port_name}")
                self.log_message.emit(f"❌ Can't open serial port: {self.port_name}", self.port_id)
                return False

            if not self.port_handler.setBaudRate(self.baud_rate):
                print(f"[DEBUG] {self.port_id}: Failed to set baud rate {self.baud_rate}")
                self.log_message.emit(f"❌ Can't set baud rate: {self.baud_rate}", self.port_id)
                self.port_handler.closePort()
                return False

            self.servo_handler = sms_sts(self.port_handler)
            self.is_connected = True
            print(f"[DEBUG] {self.port_id}: Successfully connected to {self.port_name}")
            self.log_message.emit("✅ Servo controller connected successfully", self.port_id)
            return True

        except Exception as e:
            print(f"[DEBUG] {self.port_id}: Connection exception: {e}")
            self.log_message.emit(f"❌ Connection failed: {e}", self.port_id)
            return False

    def disconnect_servo(self):
        """Disconnect from the servo"""
        try:
            if self.port_handler:
                self.port_handler.closePort()
        except Exception as e:
            print(f"[DEBUG] {self.port_id}: exception disconnecting: {e}")
        finally:
            self.is_connected = False
            self.port_handler = None
            self.servo_handler = None
            self.log_message.emit("🔌 Servo controller disconnected", self.port_id)

    def ping_servo(self, servo_id: int) -> bool:
        """Detect whether the servo is present"""
        try:
            model_number, result, error = self.servo_handler.ping(servo_id)
            if result == COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: servo {servo_id} model: {model_number}")
                return True
            else:
                print(f"[DEBUG] {self.port_id}: Ping servo {servo_id} failed: result={result}, error={error}")
                return False
        except Exception as e:
            print(f"[DEBUG] {self.port_id}: Ping servo {servo_id} exception: {e}")
            return False

    def scan_servos(self) -> List[int]:
        """Scan all servos"""
        if not self.is_connected:
            return []

        # 热插拔检测：在 POSIX 系统上检查端口设备文件是否仍然存在
        if os.name != 'nt' and not os.path.exists(self.port_name):
            print(f"[DEBUG] {self.port_id}: port device disappeared: {self.port_name}")
            self.is_connected = False
            try:
                self.disconnect_servo()
            except Exception:
                pass
            return []

        found_servos = []
        for servo_id in range(1, 21):  # 扫描 ID 1-20，与命令行工具保持一致
            if self.ping_servo(servo_id):
                found_servos.append(servo_id)

        return found_servos

    def change_servo_id(self, old_id: int, new_id: int) -> (bool, str):
        """Change servo ID (queued version)"""
        # 将请求加入队列
        self.queue_id_change(old_id, new_id)
        return True, "ID change request added to queue"

    def queue_id_change(self, old_id: int, new_id: int):
        """Add an ID change request to the queue"""
        print(f"[DEBUG] {self.port_id}: ID change request queued: {old_id} -> {new_id}")
        self.log_message.emit(f"📝 ID change request queued: {old_id} -> {new_id}", self.port_id)
        self.id_change_queue.put((old_id, new_id, time.time()))

        # 启动ID修改线程（如果还没启动）
        if not self.id_change_running:
            self.start_id_change_processor()

    def start_id_change_processor(self):
        """Start the ID-change processing thread"""
        if not self.id_change_running:
            self.id_change_running = True
            self.id_change_thread = threading.Thread(target=self.process_id_changes, daemon=True)
            self.id_change_thread.start()
            print(f"[DEBUG] {self.port_id}: ID-change processing thread started")

    def process_id_changes(self):
        """Process the ID-change queue"""
        print(f"[DEBUG] {self.port_id}: starting to process ID-change queue")
        while self.id_change_running or not self.id_change_queue.empty():
            try:
                if not self.id_change_queue.empty():
                    old_id, new_id, request_time = self.id_change_queue.get(timeout=1)

                    # 暂停扫描，避免总线冲突
                    self.pause_scanning = True
                    print(f"[DEBUG] {self.port_id}: pausing scan, about to change ID: {old_id} -> {new_id}")
                    self.log_message.emit(f"⏸️ Pausing scan, changing ID: {old_id} -> {new_id}", self.port_id)

                    # 等待一下确保扫描完全停止
                    time.sleep(0.5)

                    # 执行ID修改
                    success, message = self.execute_id_change(old_id, new_id)

                    # 恢复扫描
                    self.pause_scanning = False
                    print(f"[DEBUG] {self.port_id}: resuming scan")
                    self.log_message.emit(f"▶️ Resuming scan", self.port_id)

                    # 发送结果
                    self.id_changed.emit(old_id, new_id, success, message, self.port_id)

                else:
                    time.sleep(0.1)  # 短暂休眠避免CPU占用

            except Exception as e:
                print(f"[DEBUG] {self.port_id}: exception processing ID change: {e}")
                self.log_message.emit(f"❌ Exception processing ID change: {e}", self.port_id)
                # 确保扫描被恢复
                self.pause_scanning = False

        print(f"[DEBUG] {self.port_id}: ID-change processing thread ended")
        self.id_change_running = False
        self.pause_scanning = False

    def execute_id_change(self, old_id: int, new_id: int) -> (bool, str):
        """Perform the actual ID-change operation"""
        try:
            if not self.is_connected:
                return False, "Servo controller not connected"

            self.log_message.emit(f"🔧 Performing SMS_STS ID change: {old_id} -> {new_id}", self.port_id)
            print(f"[DEBUG] {self.port_id}: performing ID change: {old_id} -> {new_id}")

            # 首先读取舵机信息（此时扫描已暂停，不会冲突）
            try:
                model_number, result, error = self.servo_handler.ping(old_id)
                if result == COMM_SUCCESS:
                    print(f"[DEBUG] {self.port_id}: SMS_STS servo model: {model_number}")
                    self.log_message.emit(f"📋 Servo model: {model_number}", self.port_id)
                else:
                    print(f"[DEBUG] {self.port_id}: can't read servo info: {error}")
                    return False, f"Can't read servo info: {error}"
            except Exception as e:
                return False, f"Exception reading servo info: {e}"

            # SMS_STS EEPROM解锁流程
            print(f"[DEBUG] {self.port_id}: SMS_STS unlocking EEPROM...")
            result, error = self.servo_handler.unLockEprom(old_id)
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: EEPROM unlock failed: result={result}, error={error}")
                return False, f"EEPROM unlock failed: {error}"

            print(f"[DEBUG] {self.port_id}: EEPROM unlocked successfully")
            time.sleep(0.1)

            # 修改ID (使用SMS_STS_ID地址)
            print(f"[DEBUG] {self.port_id}: writing new ID: {new_id}")
            result, error = self.servo_handler.write1ByteTxRx(old_id, 5, new_id)  # SMS_STS_ID = 5
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: ID write failed: result={result}, error={error}")
                return False, f"ID write failed: {error}"

            print(f"[DEBUG] {self.port_id}: ID written successfully")
            time.sleep(0.3)

            # 验证新ID（此时扫描仍暂停，ping不会冲突）
            print(f"[DEBUG] {self.port_id}: verifying new ID: {new_id}")
            if not self.ping_servo(new_id):
                print(f"[DEBUG] {self.port_id}: new ID verification failed")
                return False, f"Verification failed, can't ping new ID: {new_id}"

            print(f"[DEBUG] {self.port_id}: new ID verified successfully")

            # 重新锁定EEPROM
            print(f"[DEBUG] {self.port_id}: re-locking EEPROM...")
            result, error = self.servo_handler.LockEprom(new_id)
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: re-lock failed: {error}")
                self.log_message.emit(f"⚠️ Failed to re-lock EEPROM: {error}", self.port_id)
            else:
                print(f"[DEBUG] {self.port_id}: re-locked successfully")

            self.log_message.emit(f"✅ SMS_STS ID change successful: {old_id} -> {new_id}", self.port_id)
            print(f"[DEBUG] {self.port_id}: ID change complete: {old_id} -> {new_id}")
            return True, ""

        except Exception as e:
            error_msg = f"Exception changing ID: {e}"
            print(f"[DEBUG] {self.port_id}: exception changing ID: {e}")
            self.log_message.emit(f"❌ {error_msg}", self.port_id)
            return False, error_msg

    # ------------------------------------------------------------------
    # 系统命令队列：寄存器读写、波特率修改、恢复出厂设置
    # ------------------------------------------------------------------
    def queue_system_command(self, command: dict):
        """Add a system command to the queue"""
        print(f"[DEBUG] {self.port_id}: system command queued: {command}")
        self.system_command_queue.put(command)
        self.log_message.emit(f"📝 {command.get('desc', 'System command')} queued", self.port_id)
        if not self.system_command_running:
            self.start_system_command_processor()

    def start_system_command_processor(self):
        """Start the system-command processing thread"""
        if not self.system_command_running:
            self.system_command_running = True
            self.system_command_thread = threading.Thread(target=self.process_system_commands, daemon=True)
            self.system_command_thread.start()
            print(f"[DEBUG] {self.port_id}: system-command processing thread started")

    def process_system_commands(self):
        """Process the system-command queue"""
        print(f"[DEBUG] {self.port_id}: starting to process system-command queue")
        while self.system_command_running or not self.system_command_queue.empty():
            try:
                if not self.system_command_queue.empty():
                    command = self.system_command_queue.get(timeout=1)
                    cmd_type = command.get("type")

                    # 暂停扫描，避免总线冲突
                    self.pause_scanning = True
                    self.log_message.emit(f"⏸️ Pausing scan, running: {command.get('desc', cmd_type)}", self.port_id)
                    time.sleep(0.3)

                    success = False
                    message = "Unknown command"
                    extra = None

                    try:
                        if cmd_type == "register_read":
                            success, message, extra = self.execute_register_read(
                                command["servo_id"], command["address"], command["length"]
                            )
                        elif cmd_type == "register_write":
                            success, message = self.execute_register_write(
                                command["servo_id"], command["address"], command["length"], command["value"]
                            )
                        elif cmd_type == "baud_rate_change":
                            success, message = self.execute_baud_rate_change(
                                command["servo_id"], command["baud_rate"]
                            )
                        elif cmd_type == "factory_reset":
                            success, message = self.execute_factory_reset(command["servo_id"])
                        elif cmd_type == "set_middle":
                            success, message = self.execute_set_middle_calibration(command["servo_id"])
                        elif cmd_type == "clear_angle_limits":
                            success, message = self.execute_clear_angle_limits(command["servo_id"])
                    except Exception as e:
                        success = False
                        message = f"Execution exception: {e}"
                        print(f"[DEBUG] {self.port_id}: exception executing system command: {e}")

                    # 恢复扫描
                    self.pause_scanning = False
                    self.log_message.emit(f"▶️ Resuming scan", self.port_id)

                    # 发送结果
                    if cmd_type == "register_read" and extra is not None:
                        self.register_read_result.emit(
                            command["servo_id"], command["address"], command["length"],
                            extra, message, self.port_id
                        )
                    else:
                        self.system_command_result.emit(cmd_type, success, message, self.port_id)

                else:
                    time.sleep(0.1)

            except Exception as e:
                print(f"[DEBUG] {self.port_id}: exception processing system command: {e}")
                self.log_message.emit(f"❌ Exception processing system command: {e}", self.port_id)
                self.pause_scanning = False

        print(f"[DEBUG] {self.port_id}: system-command processing thread ended")
        self.system_command_running = False
        self.pause_scanning = False

    def execute_register_read(self, servo_id: int, address: int, length: int) -> (bool, str, int):
        """Perform a register read"""
        if not self.is_connected:
            return False, "Servo controller not connected", None

        self.log_message.emit(f"🔍 Reading ID{servo_id} register 0x{address:02X} ({length} bytes)", self.port_id)
        try:
            if length == 1:
                value, result, error = self.servo_handler.read1ByteTxRx(servo_id, address)
            elif length == 2:
                value, result, error = self.servo_handler.read2ByteTxRx(servo_id, address)
            elif length == 4:
                value, result, error = self.servo_handler.read4ByteTxRx(servo_id, address)
            else:
                return False, "Unsupported length (only 1/2/4 bytes supported)", None

            if result == COMM_SUCCESS:
                self.log_message.emit(f"✅ ID{servo_id} register 0x{address:02X} = {value} (0x{value:X})", self.port_id)
                return True, "Read successful", value
            else:
                return False, f"Read failed: result={result}, error={error}", None
        except Exception as e:
            return False, f"Read exception: {e}", None

    def execute_register_write(self, servo_id: int, address: int, length: int, value: int) -> (bool, str):
        """Perform a register write"""
        if not self.is_connected:
            return False, "Servo controller not connected"

        self.log_message.emit(f"✏️ Writing ID{servo_id} register 0x{address:02X} = {value} ({length} bytes)", self.port_id)
        try:
            if length == 1:
                result, error = self.servo_handler.write1ByteTxRx(servo_id, address, value)
            elif length == 2:
                result, error = self.servo_handler.write2ByteTxRx(servo_id, address, value)
            elif length == 4:
                result, error = self.servo_handler.write4ByteTxRx(servo_id, address, value)
            else:
                return False, "Unsupported length (only 1/2/4 bytes supported)"

            if result == COMM_SUCCESS:
                self.log_message.emit(f"✅ ID{servo_id} register 0x{address:02X} written successfully", self.port_id)
                return True, "Write successful"
            else:
                return False, f"Write failed: result={result}, error={error}"
        except Exception as e:
            return False, f"Write exception: {e}"

    def execute_baud_rate_change(self, servo_id: int, new_baud_rate: int) -> (bool, str):
        """Perform a baud rate change"""
        if not self.is_connected:
            return False, "Servo controller not connected"

        # 波特率值 -> 寄存器值映射
        baud_to_reg = {
            1000000: 0,
            500000: 1,
            250000: 2,
            128000: 3,
            115200: 4,
            76800: 5,
            57600: 6,
            38400: 7,
        }
        reg_to_baud = {v: k for k, v in baud_to_reg.items()}

        if new_baud_rate not in baud_to_reg:
            return False, f"Unsupported baud rate: {new_baud_rate}"

        reg_value = baud_to_reg[new_baud_rate]
        old_baud_rate = self.baud_rate

        self.log_message.emit(
            f"🔧 Changing ID{servo_id} baud rate: {old_baud_rate} -> {new_baud_rate}", self.port_id
        )

        try:
            # 解锁 EEPROM
            result, error = self.servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                return False, f"EEPROM unlock failed: {error}"

            # 写入新波特率（地址 6）
            result, error = self.servo_handler.write1ByteTxRx(servo_id, 6, reg_value)
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, f"Baud rate write failed: {error}"

            # 锁定 EEPROM
            self.servo_handler.LockEprom(servo_id)
            time.sleep(0.2)

            # 尝试切换到新波特率
            self.log_message.emit(f"🔄 Switching serial port to {new_baud_rate} bps...", self.port_id)
            self.port_handler.setBaudRate(new_baud_rate)
            self.baud_rate = new_baud_rate
            time.sleep(0.3)

            # 验证通信
            if self.ping_servo(servo_id):
                self.log_message.emit(f"✅ Baud rate changed successfully, now {new_baud_rate} bps", self.port_id)
                return True, f"Baud rate changed to {new_baud_rate} bps"
            else:
                # 切换失败，尝试恢复旧波特率
                self.log_message.emit(f"⚠️ New baud rate verification failed, trying to restore {old_baud_rate} bps", self.port_id)
                self.port_handler.setBaudRate(old_baud_rate)
                self.baud_rate = old_baud_rate
                time.sleep(0.3)
                if self.ping_servo(servo_id):
                    return False, f"New baud rate verification failed, restored to {old_baud_rate} bps"
                else:
                    return False, f"Critical: baud rate change failed and the old baud rate was also lost, please reconnect"

        except Exception as e:
            return False, f"Exception changing baud rate: {e}"

    def execute_factory_reset(self, servo_id: int) -> (bool, str):
        """Perform a factory reset"""
        if not self.is_connected:
            return False, "Servo controller not connected"

        self.log_message.emit(f"🔄 Restoring ID{servo_id} factory settings...", self.port_id)
        try:
            result, error = self.servo_handler.reSet(servo_id)
            if result == COMM_SUCCESS:
                self.log_message.emit(
                    f"✅ ID{servo_id} restored to factory settings (ID will revert to 1, baud rate to 1000000)",
                    self.port_id
                )
                return True, "Factory reset successful, please rescan (servo ID is now 1)"
            else:
                return False, f"Factory reset failed: result={result}, error={error}"
        except Exception as e:
            return False, f"Exception during factory reset: {e}"

    def execute_set_middle_calibration(self, servo_id: int) -> (bool, str):
        """Set the given servo's current position as its mid-point value (2048)"""
        if not self.is_connected:
            return False, "Servo controller not connected"
        if servo_id not in self.current_servos:
            return False, f"ID{servo_id} is offline, can't set mid-point"

        self.log_message.emit(f"🔧 Setting ID{servo_id} mid-point calibration...", self.port_id)
        try:
            # 解锁 EEPROM
            result, error = self.servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                return False, f"EEPROM unlock failed: {error}"
            time.sleep(0.1)

            # 发送中位校准命令：写 128 到地址 40
            result, error = self.servo_handler.write1ByteTxRx(
                servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_CALIBRATE_MIDDLE
            )
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, f"Mid-point calibration command failed: {error}"
            time.sleep(0.1)

            # 重新锁定 EEPROM
            result, error = self.servo_handler.LockEprom(servo_id)
            if result != COMM_SUCCESS:
                self.log_message.emit(f"⚠️ ID{servo_id} failed to re-lock EEPROM: {error}", self.port_id)

            return True, f"ID{servo_id} mid-point calibration successful (current position set to 2048)"
        except Exception as e:
            return False, f"Exception during mid-point calibration: {e}"

    def execute_clear_angle_limits(self, servo_id: int) -> (bool, str):
        """Clear the given servo's min/max angle limits (restore to 0~4095)"""
        if not self.is_connected:
            return False, "Servo controller not connected"
        if servo_id not in self.current_servos:
            return False, f"ID{servo_id} is offline, can't clear angle limits"

        self.log_message.emit(f"🧹 Clearing ID{servo_id} angle limits...", self.port_id)
        try:
            # 解锁 EEPROM
            result, error = self.servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                return False, f"EEPROM unlock failed: {error}"
            time.sleep(0.1)

            # 写入最小角度限制为 0
            result, error = self.servo_handler.write2ByteTxRx(
                servo_id, SMS_STS_MIN_ANGLE_LIMIT_L, 0
            )
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, f"Failed to clear min angle limit: {error}"
            time.sleep(0.05)

            # 写入最大角度限制为 4095
            result, error = self.servo_handler.write2ByteTxRx(
                servo_id, SMS_STS_MAX_ANGLE_LIMIT_L, 4095
            )
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, f"Failed to clear max angle limit: {error}"
            time.sleep(0.05)

            # 重新锁定 EEPROM
            result, error = self.servo_handler.LockEprom(servo_id)
            if result != COMM_SUCCESS:
                self.log_message.emit(f"⚠️ ID{servo_id} failed to re-lock EEPROM: {error}", self.port_id)

            return True, f"ID{servo_id} angle limits cleared (MIN=0, MAX=4095)"
        except Exception as e:
            return False, f"Exception clearing angle limits: {e}"

    def set_servo_torque(self, servo_id: int, enable: bool):
        """Set a single servo's torque (queued, executed serially by the scan thread)"""
        self.torque_queue.put((servo_id, enable))
        self.command_event.set()

    def set_servo_position(self, servo_id: int, position: int):
        """Set a single servo's target position (queued, executed serially by the scan thread)"""
        self.position_queue.put((servo_id, position))
        self.command_event.set()

    def _process_commands(self):
        """Process torque and position control commands"""
        if self.servo_handler is None or not self.is_connected:
            # 清空队列，避免积压
            while not self.torque_queue.empty():
                try:
                    self.torque_queue.get_nowait()
                except Exception:
                    break
            while not self.position_queue.empty():
                try:
                    self.position_queue.get_nowait()
                except Exception:
                    break
            return

        # 处理力矩命令
        while not self.torque_queue.empty():
            try:
                servo_id, enable = self.torque_queue.get_nowait()
                value = 1 if enable else 0
                result, error = self.servo_handler.write1ByteTxRx(servo_id, 40, value)
                if result == COMM_SUCCESS:
                    self.log_message.emit(
                        f"{'⚡' if enable else '⏹️'} ID{servo_id} torque {'On' if enable else 'Off'}", self.port_id
                    )
                else:
                    self.log_message.emit(f"❌ ID{servo_id} torque setting failed", self.port_id)
            except Exception as e:
                self.log_message.emit(f"❌ Torque command exception: {e}", self.port_id)

        # 处理位置命令
        while not self.position_queue.empty():
            try:
                servo_id, position = self.position_queue.get_nowait()
                # 确保力矩已开启
                self.servo_handler.write1ByteTxRx(servo_id, 40, 1)
                result, error = self.servo_handler.WritePosEx(servo_id, position, 1000, 50)
                if result == COMM_SUCCESS:
                    self.log_message.emit(f"🎯 ID{servo_id} -> {position}", self.port_id)
                else:
                    self.log_message.emit(f"❌ ID{servo_id} position write failed", self.port_id)
            except Exception as e:
                self.log_message.emit(f"❌ Position command exception: {e}", self.port_id)

    def _read_servo_info(self) -> dict:
        """Read full status info for all servos currently online"""
        info = {}
        if self.servo_handler is None or not self.is_connected:
            return info

        for servo_id in self.current_servos:
            servo_info = {
                "id": servo_id,
                "position": None,
                "speed": None,
                "load": None,
                "voltage": None,
                "temperature": None,
                "current": None,
                "moving": None,
                "model": None,
                "status": None,
                "errors": {},
            }
            try:
                pos, result, _ = self.servo_handler.ReadPos(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["position"] = pos

                speed, result, _ = self.servo_handler.ReadSpeed(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["speed"] = speed

                load, result, _ = self.servo_handler.ReadLoad(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["load"] = load

                voltage, result, _ = self.servo_handler.ReadVoltage(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["voltage"] = voltage / 10.0

                temperature, result, _ = self.servo_handler.ReadTemperature(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["temperature"] = temperature

                current, result, _ = self.servo_handler.ReadCurrent(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["current"] = current

                moving, result, _ = self.servo_handler.ReadMoving(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["moving"] = bool(moving)

                model, result, _ = self.servo_handler.ReadModelNumber(servo_id)
                if result == COMM_SUCCESS:
                    servo_info["model"] = model

                # 读取状态寄存器（地址 65）获取保护标志
                status, result, _ = self.servo_handler.read1ByteTxRx(servo_id, 65)
                if result == COMM_SUCCESS:
                    servo_info["status"] = status
                    servo_info["errors"] = self._parse_servo_status(status)

                info[servo_id] = servo_info
            except Exception:
                pass
        return info

    def _parse_servo_status(self, status: int) -> dict:
        """Parse the protection flags in the servo status register"""
        return {
            "overload": bool(status & ERRBIT_OVERLOAD),
            "over_current": bool(status & ERRBIT_OVERELE),
            "over_heat": bool(status & ERRBIT_OVERHEAT),
            "over_voltage": bool(status & ERRBIT_VOLTAGE),
        }

    def _read_positions(self) -> dict:
        """Read current position of online servos (legacy-signal compatible)"""
        positions = {}
        info = self._read_servo_info()
        for servo_id, servo_info in info.items():
            if servo_info["position"] is not None:
                positions[servo_id] = servo_info["position"]
        return positions

    def run_scanner(self):
        """Run the scan loop"""
        scan_count = 0
        self.running = True
        consecutive_failures = 0
        consecutive_empty_scans = 0
        max_failures = 3
        max_empty_scans = 5  # 连续空扫描阈值，超过则强制重新连接（处理热插拔）

        self.log_message.emit("🚀 Scan thread started", self.port_id)
        print(f"[DEBUG] {self.port_id}: Scanner thread started")

        # 首次连接
        if not self.is_connected:
            self.connect_servo()

        while self.running:
            try:
                scan_count += 1

                # 等待命令/重新扫描事件，最多1秒
                self.command_event.wait(timeout=1.0)
                self.command_event.clear()

                # 优先处理单舵机控制命令（与扫描同线程，安全无冲突）
                self._process_commands()

                # 如果未连接，尝试重新连接
                if not self.is_connected:
                    if consecutive_failures < max_failures:
                        self.log_message.emit(f"🔄 Trying to reconnect... (attempt {consecutive_failures + 1})", self.port_id)
                        time.sleep(2)  # 等待2秒再重试
                        # stop() 期间禁止重连，否则会重新打开串口导致端口泄漏
                        if not self.running:
                            break
                        if self.connect_servo():
                            consecutive_failures = 0  # 重置失败计数
                        else:
                            consecutive_failures += 1
                        continue
                    else:
                        # 失败次数过多，延长等待时间
                        self.log_message.emit(f"⚠️ Failed {max_failures} times in a row, retrying in 10s...", self.port_id)
                        time.sleep(10)
                        consecutive_failures = 0  # 重置计数
                        if not self.running:
                            break
                        continue

                # 检查是否暂停扫描（ID修改期间）
                if self.pause_scanning:
                    print(f"[DEBUG] {self.port_id}: scan paused (ID change in progress)")
                    time.sleep(0.5)  # 短暂休眠，减少CPU占用
                    continue

                # 检查是否有手动重新扫描请求
                is_rescan = self.rescan_requested.is_set()
                if is_rescan:
                    self.rescan_requested.clear()
                    self.log_message.emit("🔄 Running manual rescan...", self.port_id)

                # 扫描舵机
                new_servos = self.scan_servos()
                print(f"[DEBUG] {self.port_id}: Scan result: {new_servos}, current: {self.current_servos}")

                # 扫描成功，重置失败计数
                consecutive_failures = 0

                # 热插拔处理：连续多次扫描不到舵机，强制重新连接串口
                # 注意：这里用更新前的 current_servos 判断，避免刚清空后就重置计数
                had_servos_before = bool(self.current_servos)
                if not new_servos and had_servos_before:
                    consecutive_empty_scans += 1
                    if consecutive_empty_scans >= max_empty_scans:
                        self.log_message.emit(
                            f"⚠️ No servos found for {max_empty_scans} scans in a row, assuming the port disconnected, trying to reconnect...",
                            self.port_id
                        )
                        self.is_connected = False
                        try:
                            self.disconnect_servo()
                        except Exception:
                            pass
                        consecutive_empty_scans = 0
                        continue
                elif new_servos:
                    consecutive_empty_scans = 0

                # 如果舵机列表有变化
                if new_servos != self.current_servos:
                    old_servos = self.current_servos.copy() if self.current_servos else []
                    self.current_servos = new_servos

                    if new_servos:
                        if not old_servos:
                            self.log_message.emit(f"📡 Found servos: {new_servos}", self.port_id)
                        else:
                            added = set(new_servos) - set(old_servos)
                            removed = set(old_servos) - set(new_servos)
                            changes = []
                            if added:
                                changes.append(f"Added: {list(added)}")
                            if removed:
                                changes.append(f"Removed: {list(removed)}")
                            self.log_message.emit(f"📡 Servo change: {', '.join(changes)}", self.port_id)
                    else:
                        if old_servos:
                            self.log_message.emit("📡 All servos disconnected", self.port_id)

                    print(f"[DEBUG] {self.port_id}: Emitting status_updated: servos={new_servos}, connected={self.is_connected}")
                    self.status_updated.emit(self.current_servos, self.is_connected, self.port_id)

                # 读取并发送当前状态（包含位置、电压、温度等）
                servo_info = self._read_servo_info()
                if servo_info:
                    # 兼容旧信号
                    positions = {
                        sid: sinfo["position"]
                        for sid, sinfo in servo_info.items()
                        if sinfo["position"] is not None
                    }
                    if positions:
                        self.positions_updated.emit(positions)
                    # 新信号：完整状态
                    self.servo_info_updated.emit(servo_info)

                # 每30次扫描显示一次状态（减少日志频率）
                if scan_count % 30 == 0:
                    if self.current_servos:
                        self.log_message.emit(f"📊 Current servo IDs: {self.current_servos}", self.port_id)
                    else:
                        self.log_message.emit("📊 No servos currently", self.port_id)

            except Exception as e:
                consecutive_failures += 1
                self.log_message.emit(f"❌ Scan exception: {e} (failure count: {consecutive_failures})", self.port_id)
                # 连续异常达到阈值时，强制重新打开串口（处理底层 serial 异常未重置 is_connected 的情况）
                if consecutive_failures >= max_failures:
                    self.log_message.emit(
                        f"⚠️ Scan exception {max_failures} times in a row, forcing serial port reconnect...", self.port_id
                    )
                    self.is_connected = False
                    try:
                        self.disconnect_servo()
                    except Exception:
                        pass
                    consecutive_failures = 0
                # 不要立即断开连接，给下次重试机会
                time.sleep(1)

    def start(self):
        """Start the worker thread"""
        # 旧扫描线程尚未退出时不重复创建，避免两个线程并发操作同一串口
        if self._scanner_thread and self._scanner_thread.is_alive():
            self.running = True  # 让旧线程继续循环
            return
        self.running = True
        self._scanner_thread = threading.Thread(target=self.run_scanner, daemon=True)
        self._scanner_thread.start()

    def stop(self):
        """Stop the worker thread"""
        self.running = False
        self.id_change_running = False
        self.system_command_running = False

        # 先唤醒并等待扫描线程退出，再断开串口。
        # 否则线程可能在 stop 之后重连/扫描：重新打开串口造成占用
        # （Windows 上会导致后续子进程 PermissionError），或访问已删除对象。
        self.command_event.set()
        if self._scanner_thread and self._scanner_thread.is_alive():
            self._scanner_thread.join(timeout=3)
        if self._scanner_thread and not self._scanner_thread.is_alive():
            self._scanner_thread = None

        self.disconnect_servo()

        # 等待ID修改线程结束
        if self.id_change_thread and self.id_change_thread.is_alive():
            self.id_change_thread.join(timeout=2)

        # 等待系统命令线程结束
        if self.system_command_thread and self.system_command_thread.is_alive():
            self.system_command_thread.join(timeout=2)


class ServoPanel(QWidget):
    """Single-servo control panel"""

    DISABLED_PORT = "-- Disabled --"

    def __init__(self, port_name: str, port_id: str):
        super().__init__()
        self.port_name = port_name
        self.port_id = port_id
        self.worker = None
        self.init_ui()
        if port_name and port_name != self.DISABLED_PORT:
            self.worker = ServoWorker(port_name, port_id)
            self.init_connections()
            self.worker.start()
        else:
            self.title_label.setText(f"🏭 {self.DISABLED_PORT} - Servo Calibration")
            self.connection_status.setText("⚫ Disabled")

    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        self.title_label = QLabel(f"🏭 {self.port_name} - Servo Calibration")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50; margin: 5px;")
        layout.addWidget(self.title_label)

        # 状态面板
        self.create_status_panel(layout)

        # 舵机状态面板
        self.create_servo_panel(layout)

        # 标定面板
        self.create_calibration_panel(layout)

        # 单舵机控制面板（作为独立 widget，后续放到单独标签页中）
        self.servo_control_widget = self.create_servo_control_widget()

        # 日志面板
        self.create_log_panel(layout)

        # 设置整体样式
        self.setStyleSheet(f"""
            QWidget#{self.port_id} {{
                border: 2px solid #dee2e6;
                border-radius: 10px;
                padding: 10px;
                background-color: #ffffff;
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                margin-top: 5px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
            }}
            QPushButton {{
                background-color: #007bff;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #0056b3;
            }}
            QPushButton:pressed {{
                background-color: #004085;
            }}
            QPushButton:disabled {{
                background-color: #6c757d;
            }}
            QTextEdit {{
                background-color: #f8f9fa;
                color: #212529;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }}
            QLabel {{
                color: #495057;
            }}
        """)
        self.setObjectName(self.port_id)

    def create_status_panel(self, layout):
        """Create the status panel"""
        status_group = QGroupBox("📡 System Status")
        status_layout = QHBoxLayout()
        status_group.setLayout(status_layout)

        # 连接状态
        self.connection_status = QLabel("🔴 Not Connected")
        self.connection_status.setStyleSheet("font-size: 12px; font-weight: bold;")
        status_layout.addWidget(self.connection_status)

        status_layout.addStretch()

        # 当前舵机
        self.current_servos_label = QLabel("Current servos: scanning...")
        self.current_servos_label.setStyleSheet("font-size: 12px;")
        status_layout.addWidget(self.current_servos_label)

        status_layout.addSpacing(15)

        # 重新扫描按钮
        self.rescan_btn = QPushButton("🔄 Rescan")
        self.rescan_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                border: none;
                padding: 5px 12px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
            QPushButton:pressed {
                background-color: #117a8b;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.rescan_btn.setToolTip("Rescan servos immediately")
        self.rescan_btn.clicked.connect(self.request_rescan)
        status_layout.addWidget(self.rescan_btn)

        layout.addWidget(status_group)

    def create_servo_panel(self, layout):
        """Create the servo status panel"""
        servo_group = QGroupBox("📡 Servo Status")
        servo_layout = QVBoxLayout()
        servo_group.setLayout(servo_layout)

        # 左右并列布局
        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(10)

        # 左侧：发现的舵机
        found_layout = QVBoxLayout()
        found_label = QLabel("✅ Servos Found")
        found_label.setStyleSheet("font-weight: bold; color: #28a745; font-size: 12px;")
        found_layout.addWidget(found_label)

        self.servo_list_found = QTextEdit()
        self.servo_list_found.setReadOnly(True)
        self.servo_list_found.setMaximumHeight(150)
        self.servo_list_found.setPlainText("Scanning servos...")
        found_layout.addWidget(self.servo_list_found)

        lists_layout.addLayout(found_layout)

        # 右侧：未识别ID
        missing_layout = QVBoxLayout()
        missing_label = QLabel("⚠️ Unrecognized ID")
        missing_label.setStyleSheet("font-weight: bold; color: #dc3545; font-size: 12px;")
        missing_layout.addWidget(missing_label)

        self.servo_list_missing = QTextEdit()
        self.servo_list_missing.setReadOnly(True)
        self.servo_list_missing.setMaximumHeight(150)
        self.servo_list_missing.setPlainText("Scanning servos...")
        missing_layout.addWidget(self.servo_list_missing)

        lists_layout.addLayout(missing_layout)

        servo_layout.addLayout(lists_layout)
        layout.addWidget(servo_group)

    def create_calibration_panel(self, layout):
        """Create the calibration panel"""
        calibration_group = QGroupBox("🎯 ID Calibration")
        calibration_layout = QVBoxLayout()
        calibration_group.setLayout(calibration_layout)

        # 说明文字
        info_label = QLabel("📋 Click a target ID to change it\n⏸️ Scanning pauses automatically to ensure success")
        info_label.setStyleSheet("background-color: #e3f2fd; border: 1px solid #bbdefb; padding: 8px; border-radius: 4px; color: #1565c0; font-size: 11px;")
        calibration_layout.addWidget(info_label)

        # ID按钮网格
        self.id_buttons = []
        button_layout = QGridLayout()

        for i in range(6):
            row = i // 3
            col = i % 3

            btn = QPushButton(str(i + 1))
            btn.setMinimumHeight(60)
            btn.setMinimumWidth(80)
            btn.setStyleSheet("font-size: 24px;")
            btn.clicked.connect(lambda slot=i: self.change_servo_id(slot))
            btn.setEnabled(False)

            self.id_buttons.append(btn)
            button_layout.addWidget(btn, row, col)

        calibration_layout.addLayout(button_layout)
        layout.addWidget(calibration_group)

    def create_servo_control_widget(self):
        """Create the single-servo slider control panel; returns a reusable QWidget"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(5, 5, 5, 5)

        control_group = QGroupBox(f"🎚️ Single Servo Control - {self.port_name}")
        control_layout = QVBoxLayout()
        control_group.setLayout(control_layout)

        # 全局力矩按钮
        global_btn_layout = QHBoxLayout()

        self.enable_all_torque_btn = QPushButton("⚡ Enable All Torque")
        self.enable_all_torque_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #218838; }
            QPushButton:pressed { background-color: #1e7e34; }
        """)
        self.enable_all_torque_btn.clicked.connect(self.enable_all_torque)
        global_btn_layout.addWidget(self.enable_all_torque_btn)

        self.disable_all_torque_btn = QPushButton("⏹️ Disable All Torque")
        self.disable_all_torque_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #c82333; }
            QPushButton:pressed { background-color: #bd2130; }
        """)
        self.disable_all_torque_btn.clicked.connect(self.disable_all_torque)
        global_btn_layout.addWidget(self.disable_all_torque_btn)

        global_btn_layout.addStretch()
        control_layout.addLayout(global_btn_layout)

        # 每个舵机两行：
        # 第一行：ID | 当前位置 | 电压 | 温度 | 滑动条 | 目标位置 | 力矩开关
        # 第二行：速度 | 负载 | 电流 | 运行状态 | 型号
        self.servo_sliders = {}
        self.servo_pos_labels = {}
        self.servo_voltage_labels = {}
        self.servo_temp_labels = {}
        self.servo_target_labels = {}
        self.servo_torque_btns = {}
        self.servo_speed_labels = {}
        self.servo_load_labels = {}
        self.servo_current_labels = {}
        self.servo_moving_labels = {}
        self.servo_model_labels = {}
        self.servo_status_labels = {}
        self.servo_middle_btns = {}        # 中位校准按钮
        self.servo_clear_limit_btns = {}  # 清除角度限制按钮

        for servo_id in range(1, 7):
            servo_layout = QVBoxLayout()
            servo_layout.setSpacing(2)
            servo_layout.setContentsMargins(0, 0, 0, 0)

            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)

            id_label = QLabel(f"ID{servo_id}")
            id_label.setStyleSheet("font-weight: bold; font-size: 12px; min-width: 35px;")
            row_layout.addWidget(id_label)

            pos_label = QLabel("Pos: --")
            pos_label.setStyleSheet("font-size: 11px; min-width: 65px;")
            self.servo_pos_labels[servo_id] = pos_label
            row_layout.addWidget(pos_label)

            voltage_label = QLabel("V: --")
            voltage_label.setStyleSheet("font-size: 11px; min-width: 55px; color: #17a2b8;")
            self.servo_voltage_labels[servo_id] = voltage_label
            row_layout.addWidget(voltage_label)

            temp_label = QLabel("T: --")
            temp_label.setStyleSheet("font-size: 11px; min-width: 55px; color: #dc3545;")
            self.servo_temp_labels[servo_id] = temp_label
            row_layout.addWidget(temp_label)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 4095)
            slider.setValue(2048)
            slider.setEnabled(False)
            slider.setStyleSheet("""
                QSlider::groove:horizontal {
                    border: 1px solid #bbb;
                    height: 8px;
                    background: #e9ecef;
                    border-radius: 4px;
                }
                QSlider::handle:horizontal {
                    background: #007bff;
                    border: 1px solid #0056b3;
                    width: 18px;
                    margin: -5px 0;
                    border-radius: 4px;
                }
                QSlider::sub-page:horizontal {
                    background: #007bff;
                    border-radius: 4px;
                }
            """)
            slider.valueChanged.connect(lambda value, sid=servo_id: self.on_slider_value_changed(sid, value))
            slider.sliderReleased.connect(lambda sid=servo_id: self.on_slider_released(sid))
            self.servo_sliders[servo_id] = slider
            row_layout.addWidget(slider, stretch=1)

            target_label = QLabel("T: 2048")
            target_label.setStyleSheet("font-size: 11px; min-width: 55px;")
            self.servo_target_labels[servo_id] = target_label
            row_layout.addWidget(target_label)

            torque_btn = QPushButton("⚡ Torque")
            torque_btn.setCheckable(True)
            torque_btn.setChecked(False)
            torque_btn.setEnabled(False)
            torque_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6c757d;
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:checked {
                    background-color: #28a745;
                }
                QPushButton:hover {
                    background-color: #5a6268;
                }
                QPushButton:checked:hover {
                    background-color: #218838;
                }
            """)
            torque_btn.toggled.connect(lambda checked, sid=servo_id: self.on_torque_toggled(sid, checked))
            self.servo_torque_btns[servo_id] = torque_btn
            row_layout.addWidget(torque_btn)

            # 中位校准按钮（单独设置该舵机中位值）
            middle_btn = QPushButton("🎯 Mid-Pos")
            middle_btn.setEnabled(False)
            middle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #fd7e14;
                    color: white;
                    border: none;
                    padding: 5px 8px;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #e56b0a; }
                QPushButton:pressed { background-color: #c95d08; }
                QPushButton:disabled { background-color: #6c757d; }
            """)
            middle_btn.setToolTip("Set this servo's current position as its mid-point value (2048)")
            middle_btn.clicked.connect(lambda checked, sid=servo_id: self.on_set_middle_clicked(sid))
            self.servo_middle_btns[servo_id] = middle_btn
            row_layout.addWidget(middle_btn)

            # 清除角度限制按钮
            clear_limit_btn = QPushButton("🧹 Clear Limits")
            clear_limit_btn.setEnabled(False)
            clear_limit_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6f42c1;
                    color: white;
                    border: none;
                    padding: 5px 8px;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #5a32a3; }
                QPushButton:pressed { background-color: #4a2785; }
                QPushButton:disabled { background-color: #6c757d; }
            """)
            clear_limit_btn.setToolTip("Clear this servo's min/max angle limits (restore to 0~4095)")
            clear_limit_btn.clicked.connect(lambda checked, sid=servo_id: self.on_clear_limits_clicked(sid))
            self.servo_clear_limit_btns[servo_id] = clear_limit_btn
            row_layout.addWidget(clear_limit_btn)

            servo_layout.addLayout(row_layout)

            # 第二行：扩展状态信息
            info_layout = QHBoxLayout()
            info_layout.setSpacing(8)
            info_layout.setContentsMargins(43, 0, 0, 4)  # 左侧缩进与第一行 ID 列对齐

            speed_label = QLabel("Spd: --")
            speed_label.setStyleSheet("font-size: 10px; min-width: 75px; color: #6f42c1;")
            self.servo_speed_labels[servo_id] = speed_label
            info_layout.addWidget(speed_label)

            load_label = QLabel("Load: --")
            load_label.setStyleSheet("font-size: 10px; min-width: 75px; color: #fd7e14;")
            self.servo_load_labels[servo_id] = load_label
            info_layout.addWidget(load_label)

            current_label = QLabel("Cur: --")
            current_label.setStyleSheet("font-size: 10px; min-width: 70px; color: #20c997;")
            self.servo_current_labels[servo_id] = current_label
            info_layout.addWidget(current_label)

            moving_label = QLabel("Mov: --")
            moving_label.setStyleSheet("font-size: 10px; min-width: 70px; color: #0dcaf0;")
            self.servo_moving_labels[servo_id] = moving_label
            info_layout.addWidget(moving_label)

            model_label = QLabel("Model: --")
            model_label.setStyleSheet("font-size: 10px; min-width: 140px; color: #6c757d;")
            self.servo_model_labels[servo_id] = model_label
            info_layout.addWidget(model_label)

            status_label = QLabel("Status: --")
            status_label.setStyleSheet("font-size: 10px; min-width: 100px; color: #28a745; font-weight: bold;")
            self.servo_status_labels[servo_id] = status_label
            info_layout.addWidget(status_label)

            info_layout.addStretch()
            servo_layout.addLayout(info_layout)

            control_layout.addLayout(servo_layout)

        # 提示文字
        tip_label = QLabel(
            "💡 Drag the slider and release to move the servo to the target position. Unrecognized servos can't be controlled."
        )
        tip_label.setStyleSheet(
            "background-color: #fff3cd; border: 1px solid #ffeeba; padding: 6px; "
            "border-radius: 4px; color: #856404; font-size: 11px;"
        )
        tip_label.setWordWrap(True)
        control_layout.addWidget(tip_label)

        layout.addWidget(control_group)
        return container

    def create_log_panel(self, layout):
        """Create the log panel"""
        log_group = QGroupBox("📋 Operation Log")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setPlainText("System starting...")
        log_layout.addWidget(self.log_text)

        # 清空日志按钮
        clear_btn = QPushButton("Clear Log")
        clear_btn.setMaximumWidth(80)
        clear_btn.setStyleSheet("font-size: 11px;")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)

        layout.addWidget(log_group)

    def init_connections(self):
        """Initialize signal connections"""
        if self.worker is None:
            return
        self.worker.status_updated.connect(self.update_status)
        self.worker.id_changed.connect(self.on_id_changed)
        self.worker.log_message.connect(self.add_log)
        self.worker.positions_updated.connect(self.update_positions)
        self.worker.servo_info_updated.connect(self.update_servo_info)
        self.worker.system_command_result.connect(self.on_system_command_result)

        # 添加初始连接日志
        self.add_log("🔄 Signal connections established", self.port_id)
        self.add_log("📡 Starting servo scan...", self.port_id)

    def on_system_command_result(self, cmd_type, success, message, port_id):
        """Handle system command results (mid-point calibration, clear limits, etc.)"""
        if port_id != self.port_id:
            return
        prefix = "✅" if success else "❌"
        self.add_log(f"{prefix} {message}", self.port_id)

    def update_status(self, servos, connected, port_id):
        """Update the status display"""
        if port_id != self.port_id:
            return

        print(f"[DEBUG] {port_id} update_status called: servos={servos}, connected={connected}")
        if connected:
            self.connection_status.setText("🟢 Connected")
            self.connection_status.setStyleSheet("color: #28a745; font-size: 12px; font-weight: bold;")
        else:
            self.connection_status.setText("🔴 Not Connected")
            self.connection_status.setStyleSheet("color: #dc3545; font-size: 12px; font-weight: bold;")

        if servos:
            self.current_servos_label.setText(f"Current servos: {', '.join(map(str, servos))}")
            found_html = "<br>".join([f"<span style='color: #28a745; font-weight: bold;'>• Servo ID: {servo_id}</span>" for servo_id in servos])
            self.servo_list_found.setHtml(found_html)

            # 计算 1-6 号槽位中未识别的ID并显示
            expected_ids = set(range(1, 7))
            found_ids = set(servos)
            missing_ids = sorted(expected_ids - found_ids)
            if missing_ids:
                missing_html = "<br>".join([f"<span style='color: #dc3545; font-weight: bold;'>• ID {servo_id}</span>" for servo_id in missing_ids])
                self.servo_list_missing.setHtml(missing_html)
            else:
                self.servo_list_missing.setHtml("<span style='color: #28a745; font-weight: bold;'>✅ All slots 1-6 recognized</span>")
        else:
            self.current_servos_label.setText("Current servos: none")
            self.servo_list_found.setHtml("<span style='color: #dc3545;'>📡 No servos found<br><br>Please check:<br>1. Is the servo controller connected?<br>2. Is the servo powered?<br>3. Is the serial port configured correctly?</span>")
            self.servo_list_missing.setHtml("")

        # 更新按钮状态
        self.update_button_states(servos, connected)

        # 更新单舵机控制面板状态
        self.update_servo_control_state(servos, connected)

    def update_button_states(self, servos, connected):
        """Update button states"""
        has_servos = connected and len(servos) > 0

        for i, btn in enumerate(self.id_buttons):
            target_id = i + 1
            is_assigned = target_id in servos

            # 按钮始终启用（只要有舵机），方便用户点击修改任意槽位
            btn.setEnabled(has_servos)
            btn.setText(str(target_id))

            if is_assigned:
                # 识别到的舵机显示绿色
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #28a745;
                        color: white;
                        font-size: 24px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #218838;
                    }
                """)
            else:
                # 未识别到的槽位显示红色
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #dc3545;
                        color: white;
                        font-size: 24px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #c82333;
                    }
                """)

    def update_servo_control_state(self, servos, connected):
        """Update slider and torque button availability based on online servos"""
        has_servos = connected and len(servos) > 0
        servo_set = set(servos) if servos else set()

        for servo_id in range(1, 7):
            online = servo_id in servo_set and has_servos
            slider = self.servo_sliders[servo_id]
            torque_btn = self.servo_torque_btns[servo_id]
            middle_btn = self.servo_middle_btns[servo_id]
            clear_limit_btn = self.servo_clear_limit_btns[servo_id]

            slider.setEnabled(online)
            torque_btn.setEnabled(online)
            middle_btn.setEnabled(online)
            clear_limit_btn.setEnabled(online)

            if not online:
                # 离线时重置显示
                self.servo_pos_labels[servo_id].setText("Pos: --")
                self.servo_voltage_labels[servo_id].setText("V: --")
                self.servo_temp_labels[servo_id].setText("T: --")
                self.servo_speed_labels[servo_id].setText("Spd: --")
                self.servo_load_labels[servo_id].setText("Load: --")
                self.servo_current_labels[servo_id].setText("Cur: --")
                self.servo_moving_labels[servo_id].setText("Mov: --")
                self.servo_model_labels[servo_id].setText("Model: --")
                self.servo_status_labels[servo_id].setText("Status: --")
                self.servo_status_labels[servo_id].setStyleSheet(
                    "font-size: 10px; min-width: 100px; color: #6c757d; font-weight: bold;"
                )
                self.servo_voltage_labels[servo_id].setToolTip("")
                self.servo_temp_labels[servo_id].setToolTip("")
                torque_btn.setChecked(False)
                torque_btn.setText("⚡ Torque")

    def update_positions(self, positions: dict):
        """Update each servo's current position display (legacy-signal compatible)"""
        if not positions:
            return

        for servo_id, pos in positions.items():
            if servo_id in self.servo_pos_labels:
                self.servo_pos_labels[servo_id].setText(f"Pos: {pos}")

    def update_servo_info(self, info: dict):
        """Update each servo's full status display (voltage, temperature, speed, load, current, moving state, model, etc.)"""
        if not info:
            return

        for servo_id, servo_info in info.items():
            if servo_id not in self.servo_pos_labels:
                continue

            pos = servo_info.get("position")
            voltage = servo_info.get("voltage")
            temperature = servo_info.get("temperature")
            speed = servo_info.get("speed")
            load = servo_info.get("load")
            current = servo_info.get("current")
            moving = servo_info.get("moving")
            model = servo_info.get("model")

            if pos is not None:
                self.servo_pos_labels[servo_id].setText(f"Pos: {pos}")
            if voltage is not None:
                self.servo_voltage_labels[servo_id].setText(f"V: {voltage:.1f}V")
            if temperature is not None:
                self.servo_temp_labels[servo_id].setText(f"T: {temperature}°C")
            if speed is not None:
                self.servo_speed_labels[servo_id].setText(f"Spd: {speed}")
            if load is not None:
                self.servo_load_labels[servo_id].setText(f"Load: {load}")
            if current is not None:
                # Feetech STS 系列舵机电流转换：1 单位 ≈ 6.5 mA
                current_ma = current * 6.5
                self.servo_current_labels[servo_id].setText(f"Cur: {current_ma:.1f}mA")
            if moving is not None:
                self.servo_moving_labels[servo_id].setText(f"Mov: {'Yes' if moving else 'No'}")
            if model is not None:
                model_name = get_servo_model_name(model)
                self.servo_model_labels[servo_id].setText(f"Model: {model_name}")

            # 更新保护状态显示
            errors = servo_info.get("errors", {})
            if errors:
                active_errors = []
                if errors.get("overload"):
                    active_errors.append("Overload")
                if errors.get("over_current"):
                    active_errors.append("Overcurrent")
                if errors.get("over_voltage"):
                    active_errors.append("Overvoltage")
                if errors.get("over_heat"):
                    active_errors.append("Overheat")

                if active_errors:
                    status_text = "Status: " + ",".join(active_errors)
                    self.servo_status_labels[servo_id].setText(status_text)
                    self.servo_status_labels[servo_id].setStyleSheet(
                        "font-size: 10px; min-width: 100px; color: #dc3545; font-weight: bold;"
                    )
                else:
                    self.servo_status_labels[servo_id].setText("Status: OK")
                    self.servo_status_labels[servo_id].setStyleSheet(
                        "font-size: 10px; min-width: 100px; color: #28a745; font-weight: bold;"
                    )

            # Tooltip 显示更详细信息
            tooltip_lines = [f"ID: {servo_id}"]
            if model is not None:
                tooltip_lines.append(f"Model: {get_servo_model_name(model)}")
            if speed is not None:
                tooltip_lines.append(f"Speed: {speed}")
            if load is not None:
                tooltip_lines.append(f"Load: {load}")
            if current is not None:
                tooltip_lines.append(f"Current: {current_ma:.1f} mA")
            if moving is not None:
                tooltip_lines.append(f"Moving: {'Yes' if moving else 'No'}")
            if errors:
                tooltip_lines.append("")
                tooltip_lines.append("Protection Status:")
                tooltip_lines.append(f"  Overload: {'Yes' if errors.get('overload') else 'No'}")
                tooltip_lines.append(f"  Overcurrent: {'Yes' if errors.get('over_current') else 'No'}")
                tooltip_lines.append(f"  Overvoltage: {'Yes' if errors.get('over_voltage') else 'No'}")
                tooltip_lines.append(f"  Overheat: {'Yes' if errors.get('over_heat') else 'No'}")
                tooltip_lines.append("")
                tooltip_lines.append("Protection Info:")
                tooltip_lines.append("  Overload: triggers after >80% stall for 2s")
                tooltip_lines.append("  Overcurrent: triggers after >2A for 2s")
                tooltip_lines.append("  Overvoltage: triggers at >8V or <4V")
                tooltip_lines.append("  Overheat: torque disabled above 70℃")
            tooltip = "\n".join(tooltip_lines)
            self.servo_voltage_labels[servo_id].setToolTip(tooltip)
            self.servo_temp_labels[servo_id].setToolTip(tooltip)
            self.servo_status_labels[servo_id].setToolTip(tooltip)

        # 健康检查
        self.check_servo_health_ui(info)

    def check_servo_health_ui(self, info: dict):
        """Check servo health and report it in the log/status bar"""
        warnings = []
        for servo_id, servo_info in info.items():
            voltage = servo_info.get("voltage")
            temperature = servo_info.get("temperature")
            errors = servo_info.get("errors", {})

            if voltage is not None:
                v_min, v_max = get_voltage_range(voltage)
                if voltage < v_min or voltage > v_max:
                    warnings.append(
                        f"ID{servo_id} voltage abnormal: {voltage:.1f}V (safe range {v_min:.1f}V~{v_max:.1f}V)"
                    )
            if temperature is not None and temperature > SAFE_TEMPERATURE_MAX:
                warnings.append(
                    f"ID{servo_id} temperature too high: {temperature}°C (recommended < {SAFE_TEMPERATURE_MAX:.0f}°C)"
                )

            # 保护状态警告
            if errors.get("overload"):
                warnings.append(f"ID{servo_id} overload protection: stall >80% for 2s, send a new position command to clear")
            if errors.get("over_current"):
                warnings.append(f"ID{servo_id} overcurrent protection: current >2A for 2s, send a new position command to clear")
            if errors.get("over_voltage"):
                warnings.append(f"ID{servo_id} overvoltage protection: voltage >8V or <4V")
            if errors.get("over_heat"):
                warnings.append(f"ID{servo_id} overheat protection: temperature >70℃, torque output disabled")

        if warnings:
            # 避免过于频繁提示：同一端口 5 秒内最多提示一次
            now = time.time()
            last_warn = getattr(self, "_last_health_warning", 0)
            if now - last_warn > 5:
                self._last_health_warning = now
                warning_text = " | ".join(warnings)
                self.add_log(f"🚨 Health warning: {warning_text}", self.port_id)
                # 如果有父窗口且状态栏可用，也显示在状态栏
                main_window = self.window()
                if main_window and hasattr(main_window, "status_bar"):
                    main_window.status_bar.showMessage(f"🚨 {self.port_id} port: {warning_text}", 5000)

    def on_slider_value_changed(self, servo_id: int, value: int):
        """Update the target position display when the slider value changes"""
        if servo_id in self.servo_target_labels:
            self.servo_target_labels[servo_id].setText(f"T: {value}")

    def on_slider_released(self, servo_id: int):
        """Send the target position after the slider is released"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, "Warning", "Current port is not connected, can't send position command")
            return

        slider = self.servo_sliders[servo_id]
        target = slider.value()

        # 确认力矩已开启（若未开启则自动开启并提示）
        torque_btn = self.servo_torque_btns[servo_id]
        if not torque_btn.isChecked():
            reply = QMessageBox.question(
                self,
                "Torque not enabled",
                f"ID{servo_id} torque is not enabled, enable torque before moving?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return
            torque_btn.setChecked(True)

        self.add_log(f"🎚️ ID{servo_id} target position: {target}", self.port_id)
        self.worker.set_servo_position(servo_id, target)

    def on_torque_toggled(self, servo_id: int, checked: bool):
        """Toggle a single servo's torque button"""
        if self.worker is None or not self.worker.is_connected:
            return

        btn = self.servo_torque_btns[servo_id]
        btn.setText("⚡ ON" if checked else "⚡ OFF")
        self.worker.set_servo_torque(servo_id, checked)

    def on_set_middle_clicked(self, servo_id: int):
        """Set a single servo's mid-point value (set current position to 2048)"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, "Warning", "Current port is not connected")
            return
        if servo_id not in self.worker.current_servos:
            QMessageBox.warning(self, "Warning", f"ID{servo_id} is offline")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Set Mid-Point",
            f"Set ID{servo_id}'s current position as its mid-point value (2048)?\n\n"
            f"Make sure the servo is at the desired mid-point position first.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "set_middle",
            "servo_id": servo_id,
            "desc": f"Set ID{servo_id} Mid-Point"
        })

    def on_clear_limits_clicked(self, servo_id: int):
        """Clear a single servo's min/max angle limits"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, "Warning", "Current port is not connected")
            return
        if servo_id not in self.worker.current_servos:
            QMessageBox.warning(self, "Warning", f"ID{servo_id} is offline")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Clear Limits",
            f"Clear ID{servo_id}'s angle limits?\n\n"
            f"After clearing, the servo can move across the full 0~4095 range.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "clear_angle_limits",
            "servo_id": servo_id,
            "desc": f"Clear ID{servo_id} Angle Limits"
        })

    def enable_all_torque(self):
        """Enable torque on all online servos"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, "Warning", "Current port is not connected")
            return

        for servo_id in self.worker.current_servos:
            if servo_id in self.servo_torque_btns:
                self.servo_torque_btns[servo_id].setChecked(True)
                self.worker.set_servo_torque(servo_id, True)

    def disable_all_torque(self):
        """Disable torque on all online servos"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, "Warning", "Current port is not connected")
            return

        for servo_id in self.worker.current_servos:
            if servo_id in self.servo_torque_btns:
                self.servo_torque_btns[servo_id].setChecked(False)
                self.worker.set_servo_torque(servo_id, False)

    def change_servo_id(self, slot_index):
        """Change servo ID - opens a dialog for the user to set a custom source/target ID"""
        print(f"[DEBUG {self.port_id}] change_servo_id called for slot {slot_index}")
        if self.worker is None:
            print(f"[DEBUG {self.port_id}] worker is None, aborting")
            QMessageBox.warning(self, "Warning", "Current port is disabled, can't change ID")
            return
        if not self.worker.current_servos:
            print(f"[DEBUG {self.port_id}] current_servos empty, aborting")
            QMessageBox.warning(self, "Warning", "No servos available for ID change")
            return

        # 槽位默认目标ID（按钮上显示的数字）
        default_new_id = slot_index + 1

        # 如果该槽位已被占用，默认源ID为该舵机
        default_old_id = None
        if default_new_id in self.worker.current_servos:
            default_old_id = default_new_id

        # 弹出修改对话框
        dialog = IDChangeDialog(
            self.worker.current_servos,
            default_old_id=default_old_id,
            default_new_id=default_new_id,
            parent=self
        )

        if dialog.exec() != QDialog.Accepted:
            return

        old_id, new_id = dialog.get_values()

        msg_box_style = """
            QMessageBox { background-color: #f8f9fa; color: #212529; }
            QMessageBox QLabel { color: #212529; }
            QMessageBox QPushButton {
                background-color: #007bff; color: white; padding: 5px 15px;
                border-radius: 4px; font-weight: bold;
            }
            QMessageBox QPushButton:hover { background-color: #0056b3; }
        """

        if old_id == new_id:
            box = QMessageBox(self)
            box.setWindowTitle("Notice")
            box.setText("Source ID and target ID are the same, no change needed")
            box.setStyleSheet(msg_box_style)
            box.exec()
            return

        if new_id in self.worker.current_servos and new_id != old_id:
            box = QMessageBox(self)
            box.setWindowTitle("Confirm Overwrite")
            box.setText(f"Target ID {new_id} is already used by another servo, continue anyway?")
            box.setInformativeText("Continuing may cause a bus ID conflict!")
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            box.setStyleSheet(msg_box_style)
            if box.exec() != QMessageBox.Yes:
                return

        # 确认对话框
        box = QMessageBox(self)
        box.setWindowTitle(f"Confirm ID Change ({self.port_name})")
        box.setText(f"Change servo ID {old_id} to ID {new_id}?")
        box.setInformativeText("The system will automatically pause scanning to ensure the change succeeds.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setStyleSheet(msg_box_style)
        reply = box.exec()

        if reply == QMessageBox.Yes:
            self.add_log(f"🎯 Submitting ID change request: {old_id} -> {new_id}", self.port_id)

            # 将请求加入队列（立即返回）
            success, message = self.worker.change_servo_id(old_id, new_id)

            if success:
                self.add_log(f"✅ {message}", self.port_id)
                # 禁用源ID对应的按钮，防止重复提交
                for btn in self.id_buttons:
                    if btn.text() == str(old_id):
                        btn.setEnabled(False)
                        btn.setStyleSheet("background-color: #ffc107; color: black; font-size: 24px;")
                        break
            else:
                self.add_log(f"❌ {message}", self.port_id)

    def request_rescan(self):
        """Request an immediate servo rescan"""
        self.add_log("🔄 Manual rescan requested...", self.port_id)
        if self.worker:
            self.worker.request_rescan()

    def on_id_changed(self, old_id, new_id, success, message, port_id):
        """Handle the ID-change result"""
        if port_id != self.port_id:
            return

        print(f"[DEBUG] {port_id} on_id_changed called: {old_id} -> {new_id}, success={success}, message={message}")

        if self.worker is None:
            return

        if success:
            QMessageBox.information(self, f"Change Successful ({self.port_name})", f"ID changed successfully!\n{old_id} -> {new_id}")
            # 强制重新扫描舵机列表
            self.add_log(f"🔄 ID changed successfully, rescanning servos...", self.port_id)
            # 给舵机一点时间响应新ID
            time.sleep(0.5)
            # 更新内部的舵机列表
            if old_id in self.worker.current_servos:
                self.worker.current_servos.remove(old_id)
            if new_id not in self.worker.current_servos:
                self.worker.current_servos.append(new_id)
            self.worker.current_servos.sort()
            # 手动触发状态更新，刷新按钮显示
            self.update_status(self.worker.current_servos, self.worker.is_connected, self.port_id)
        else:
            QMessageBox.critical(self, f"Change Failed ({self.port_name})", f"ID change failed!\n{message}")
            self.add_log(f"❌ Queued ID change failed: {old_id} -> {new_id}", self.port_id)
            # 刷新按钮状态
            self.update_button_states(self.worker.current_servos, self.worker.is_connected)

    def add_log(self, message, port_id):
        """Add a log message"""
        if port_id != self.port_id:
            return

        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        # Remove emojis for console output
        clean_message = message.encode('ascii', 'ignore').decode('ascii')
        clean_log_entry = f"[{timestamp}] {clean_message}"
        print(f"[DEBUG {port_id}] {clean_log_entry}")
        self.log_text.append(log_entry)

        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # 限制日志行数 - 修复Qt API错误
        document = self.log_text.document()
        if document.blockCount() > 500:
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.select(QTextCursor.LineUnderCursor)
            cursor.removeSelectedText()

    def update_port_name(self, new_port_name: str):
        """Update the port name and title"""
        self.port_name = new_port_name
        self.title_label.setText(f"🏭 {self.port_name} - Servo Calibration")

    def stop(self):
        """Stop the worker thread"""
        if self.worker:
            self.worker.stop()


class AdvancedToolsPanel(QWidget):
    """Advanced tools panel: register read/write, baud rate change, factory reset"""

    def __init__(self, servo_panel: ServoPanel):
        super().__init__()
        self.servo_panel = servo_panel
        self.worker = servo_panel.worker
        self.init_ui()
        self.init_connections()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        # 设置面板样式，确保 QGroupBox 标题完整显示
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                padding-left: 8px;
                padding-right: 8px;
                padding-bottom: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #495057;
            }
            QLabel { color: #495057; }
            QPushButton {
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:disabled { background-color: #6c757d; }
        """)

        # 标题
        title = QLabel(f"🔧 Advanced Tools - {self.servo_panel.port_name}")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 舵机选择
        servo_group = QGroupBox("🎯 Target Servo")
        servo_layout = QHBoxLayout()
        servo_group.setLayout(servo_layout)

        servo_label = QLabel("Servo ID:")
        servo_label.setStyleSheet("font-size: 12px;")
        servo_layout.addWidget(servo_label)

        self.servo_id_combo = QComboBox()
        self.servo_id_combo.setMinimumWidth(80)
        self.servo_id_combo.setStyleSheet("""
            QComboBox {
                font-size: 11px;
                padding: 3px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                background-color: white;
            }
        """)
        servo_layout.addWidget(self.servo_id_combo)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Refresh Servo List")
        refresh_btn.clicked.connect(self.refresh_servo_ids)
        servo_layout.addWidget(refresh_btn)

        servo_layout.addStretch()
        layout.addWidget(servo_group)

        # 寄存器读取
        read_group = QGroupBox("📖 Register Read")
        read_layout = QGridLayout()
        read_group.setLayout(read_layout)

        read_layout.addWidget(QLabel("Address:"), 0, 0)
        self.read_addr_spin = QSpinBox()
        self.read_addr_spin.setRange(0, 255)
        self.read_addr_spin.setDisplayIntegerBase(16)
        self.read_addr_spin.setPrefix("0x")
        read_layout.addWidget(self.read_addr_spin, 0, 1)

        read_layout.addWidget(QLabel("Length:"), 0, 2)
        self.read_len_combo = QComboBox()
        self.read_len_combo.addItems(["1 byte", "2 bytes", "4 bytes"])
        self.read_len_combo.setItemData(0, 1)
        self.read_len_combo.setItemData(1, 2)
        self.read_len_combo.setItemData(2, 4)
        read_layout.addWidget(self.read_len_combo, 0, 3)

        self.read_btn = QPushButton("🔍 Read")
        self.read_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8; color: white; border: none;
                padding: 6px 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #138496; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.read_btn.clicked.connect(self.on_read_register)
        read_layout.addWidget(self.read_btn, 1, 0, 1, 2)

        self.read_result_label = QLabel("Result: --")
        self.read_result_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 12px; color: #495057;")
        read_layout.addWidget(self.read_result_label, 1, 2, 1, 2)

        layout.addWidget(read_group)

        # 寄存器写入
        write_group = QGroupBox("✏️ Register Write")
        write_layout = QGridLayout()
        write_group.setLayout(write_layout)

        write_layout.addWidget(QLabel("Address:"), 0, 0)
        self.write_addr_spin = QSpinBox()
        self.write_addr_spin.setRange(0, 255)
        self.write_addr_spin.setDisplayIntegerBase(16)
        self.write_addr_spin.setPrefix("0x")
        write_layout.addWidget(self.write_addr_spin, 0, 1)

        write_layout.addWidget(QLabel("Length:"), 0, 2)
        self.write_len_combo = QComboBox()
        self.write_len_combo.addItems(["1 byte", "2 bytes", "4 bytes"])
        self.write_len_combo.setItemData(0, 1)
        self.write_len_combo.setItemData(1, 2)
        self.write_len_combo.setItemData(2, 4)
        write_layout.addWidget(self.write_len_combo, 0, 3)

        write_layout.addWidget(QLabel("Value:"), 1, 0)
        self.write_value_spin = QSpinBox()
        self.write_value_spin.setRange(0, 2147483647)
        self.write_value_spin.setDisplayIntegerBase(10)
        write_layout.addWidget(self.write_value_spin, 1, 1)

        self.write_btn = QPushButton("✏️ Write")
        self.write_btn.setStyleSheet("""
            QPushButton {
                background-color: #fd7e14; color: white; border: none;
                padding: 6px 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #e56b0a; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.write_btn.clicked.connect(self.on_write_register)
        write_layout.addWidget(self.write_btn, 1, 2, 1, 2)

        layout.addWidget(write_group)

        # 波特率修改
        baud_group = QGroupBox("🔌 Baud Rate Change")
        baud_layout = QHBoxLayout()
        baud_group.setLayout(baud_layout)

        baud_layout.addWidget(QLabel("New Baud Rate:"))
        self.baud_combo = QComboBox()
        for rate in [1000000, 500000, 250000, 128000, 115200, 76800, 57600, 38400]:
            self.baud_combo.addItem(str(rate), rate)
        baud_layout.addWidget(self.baud_combo)

        self.baud_btn = QPushButton("🔧 Change Baud Rate")
        self.baud_btn.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1; color: white; border: none;
                padding: 6px 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #5a32a3; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.baud_btn.clicked.connect(self.on_change_baud_rate)
        baud_layout.addWidget(self.baud_btn)
        baud_layout.addStretch()

        layout.addWidget(baud_group)

        # 恢复出厂设置
        reset_group = QGroupBox("🔄 Factory Reset")
        reset_layout = QHBoxLayout()
        reset_group.setLayout(reset_layout)

        reset_info = QLabel("⚠️ Restore the servo to factory state (ID reverts to 1, baud rate reverts to 1000000)")
        reset_info.setStyleSheet("color: #856404; font-size: 11px;")
        reset_info.setWordWrap(True)
        reset_layout.addWidget(reset_info)

        self.reset_btn = QPushButton("🔄 Factory Reset")
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545; color: white; border: none;
                padding: 6px 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #c82333; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.reset_btn.clicked.connect(self.on_factory_reset)
        reset_layout.addWidget(self.reset_btn)

        layout.addWidget(reset_group)

        # 操作日志
        log_group = QGroupBox("📋 Operation Log")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)

        self.adv_log_text = QTextEdit()
        self.adv_log_text.setReadOnly(True)
        self.adv_log_text.setMaximumHeight(150)
        self.adv_log_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa; color: #212529;
                border: 1px solid #ced4da; border-radius: 4px;
                font-family: 'Consolas', monospace; font-size: 11px;
            }
        """)
        log_layout.addWidget(self.adv_log_text)

        clear_btn = QPushButton("Clear")
        clear_btn.setMaximumWidth(60)
        clear_btn.clicked.connect(self.adv_log_text.clear)
        log_layout.addWidget(clear_btn)

        layout.addWidget(log_group)
        layout.addStretch()

        # 初始状态
        self.refresh_servo_ids()
        self.update_button_states()

    def init_connections(self):
        """Initialize signal connections"""
        if self.worker is None:
            return
        self.worker.register_read_result.connect(self.on_register_read_result)
        self.worker.system_command_result.connect(self.on_system_command_result)
        self.worker.status_updated.connect(self.on_status_updated)

    def refresh_servo_ids(self):
        """Refresh the servo ID list"""
        self.servo_id_combo.clear()
        servos = []
        if self.worker:
            servos = sorted(self.worker.current_servos)
        if servos:
            for sid in servos:
                self.servo_id_combo.addItem(f"ID{sid}", sid)
        else:
            self.servo_id_combo.addItem("No Servos", None)
        self.update_button_states()

    def update_button_states(self):
        """Update button state based on whether any servo is online"""
        has_worker = self.worker is not None and self.worker.is_connected
        has_servos = has_worker and len(self.worker.current_servos) > 0
        enabled = has_servos and self.servo_id_combo.currentData() is not None

        self.read_btn.setEnabled(enabled)
        self.write_btn.setEnabled(enabled)
        self.baud_btn.setEnabled(enabled)
        self.reset_btn.setEnabled(enabled)

    def get_selected_servo_id(self):
        """Get the selected servo ID"""
        return self.servo_id_combo.currentData()

    def add_log(self, message):
        """Add a log entry"""
        timestamp = time.strftime("%H:%M:%S")
        self.adv_log_text.append(f"[{timestamp}] {message}")
        scrollbar = self.adv_log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_read_register(self):
        """Read a register"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, "Warning", "Please select a servo first")
            return

        address = self.read_addr_spin.value()
        length = self.read_len_combo.currentData()

        self.read_result_label.setText("Result: reading...")
        self.worker.queue_system_command({
            "type": "register_read",
            "servo_id": servo_id,
            "address": address,
            "length": length,
            "desc": f"Read ID{servo_id} register 0x{address:02X}",
        })

    def on_write_register(self):
        """Write a register"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, "Warning", "Please select a servo first")
            return

        address = self.write_addr_spin.value()
        length = self.write_len_combo.currentData()
        value = self.write_value_spin.value()

        reply = QMessageBox.question(
            self,
            "Confirm Write",
            f"Write ID{servo_id} register 0x{address:02X} = {value} ({length} bytes)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "register_write",
            "servo_id": servo_id,
            "address": address,
            "length": length,
            "value": value,
            "desc": f"Write ID{servo_id} register 0x{address:02X}",
        })

    def on_change_baud_rate(self):
        """Change baud rate"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, "Warning", "Please select a servo first")
            return

        new_baud = self.baud_combo.currentData()
        reply = QMessageBox.warning(
            self,
            "Warning: Change Baud Rate",
            f"After changing the baud rate, the serial port will switch to {new_baud} bps immediately.\n"
            f"If it fails, the tool will try to restore the original baud rate.\n\n"
            f"Change ID{servo_id}'s baud rate?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "baud_rate_change",
            "servo_id": servo_id,
            "baud_rate": new_baud,
            "desc": f"Change ID{servo_id} baud rate to {new_baud}",
        })

    def on_factory_reset(self):
        """Factory reset"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, "Warning", "Please select a servo first")
            return

        reply = QMessageBox.critical(
            self,
            "Danger: Factory Reset",
            f"Restore ID{servo_id} to factory settings?\n\n"
            f"This will:\n"
            f"• Revert the servo ID to 1\n"
            f"• Revert the baud rate to 1000000\n"
            f"• Restore all parameters to defaults\n\n"
            f"This action cannot be undone!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "factory_reset",
            "servo_id": servo_id,
            "desc": f"Restore ID{servo_id} Factory Settings",
        })

    def on_register_read_result(self, servo_id, address, length, value, result, port_id):
        """Handle register read result"""
        if port_id != self.servo_panel.port_id:
            return
        if result == "Read successful":
            self.read_result_label.setText(
                f"Result: {value} (0x{value:X})"
            )
            self.add_log(f"✅ ID{servo_id} 0x{address:02X} = {value} (0x{value:X})")
        else:
            self.read_result_label.setText(f"Result: {result}")
            self.add_log(f"❌ ID{servo_id} 0x{address:02X} {result}")

    def on_system_command_result(self, cmd_type, success, message, port_id):
        """Handle system command result"""
        if port_id != self.servo_panel.port_id:
            return
        prefix = "✅" if success else "❌"
        self.add_log(f"{prefix} {message}")
        if cmd_type in ("baud_rate_change", "factory_reset") and success:
            # 这些操作后需要重新扫描
            self.add_log("🔄 Please click Rescan manually to update the servo list")

    def on_status_updated(self, servos, connected, port_id):
        """Refresh ID selection when the servo list changes"""
        if port_id != self.servo_panel.port_id:
            return
        self.refresh_servo_ids()


class EZToolUI(QMainWindow):
    """EZ Tool - Simplified dual-serial-port factory servo calibration tool"""

    def __init__(self, left_port: str = None, right_port: str = None):
        # Auto-detect default ports using port_utils
        if PORT_UTILS_AVAILABLE:
            if left_port is None:
                left_port = get_default_port(0)
            if right_port is None:
                right_port = get_default_port(1)
        else:
            # Fallback to platform-based detection
            import platform
            if left_port is None:
                left_port = "COM1" if platform.system() == "Windows" else "/dev/ttyUSB0"
            if right_port is None:
                right_port = "COM2" if platform.system() == "Windows" else "/dev/ttyUSB1"
        super().__init__()
        self.left_port = left_port
        self.right_port = right_port

        # 遥控工作线程
        self.remote_worker = None

        # 可用串口列表
        self.available_ports = []

        # 每个串口当前运行的工具子进程（校准/中位测试/失能）及操作代次。
        # 新操作到来时先终止旧进程，避免 Windows 串口被独占导致后续操作静默失败
        self._tool_procs = {}
        self._tool_gen = {}

        self.init_ui()
        self.init_connections()
        self.refresh_ports()

        # 定时刷新串口列表，支持热插拔自动识别
        self.port_refresh_timer = QTimer(self)
        self.port_refresh_timer.timeout.connect(self.refresh_ports)
        self.port_refresh_timer.start(2000)  # 每 2 秒刷新一次

    def stop_port_refresh(self):
        """Stop automatic serial port refresh (e.g. to avoid interference during calibration)"""
        if hasattr(self, 'port_refresh_timer') and self.port_refresh_timer.isActive():
            self.port_refresh_timer.stop()

    def start_port_refresh(self):
        """Resume automatic serial port refresh"""
        if hasattr(self, 'port_refresh_timer') and not self.port_refresh_timer.isActive():
            self.port_refresh_timer.start(2000)

    def init_ui(self):
        """Initialize the UI"""
        self.setWindowTitle("🏭 Dual-Serial-Port Factory Servo Calibration Tool")
        # 初始尺寸限制在屏幕可用区域内：
        # 否则在 125%/150% 缩放的 Windows 小屏上，窗口比屏幕还大，
        # 最大化时窗口反而缩小，面板内容高度不足导致控件相互重叠
        screen_rect = QApplication.primaryScreen().availableGeometry()
        init_w = min(1600, screen_rect.width() - 40)
        init_h = min(900, screen_rect.height() - 40)
        self.setGeometry(20, 20, init_w, init_h)

        # 设置字体
        font = QFont("Microsoft YaHei", 10)
        self.setFont(font)

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)

        # 创建顶部标题栏（包含串口选择、遥控按钮和中间值校准按钮）
        header_layout = QHBoxLayout()

        # 左侧标题
        title_label = QLabel("🏭 Dual-Serial-Port Factory Servo Calibration Tool")
        title_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(title_label)

        # 串口选择区域
        port_selection_group = QGroupBox("Serial Port Selection")
        port_selection_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin-top: 5px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
                color: #495057;
            }
        """)
        port_selection_layout = QHBoxLayout(port_selection_group)
        port_selection_layout.setSpacing(10)

        # 左串口选择
        left_port_layout = QVBoxLayout()
        left_port_layout.setSpacing(2)
        left_label = QLabel("Port 1:")
        left_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        left_port_layout.addWidget(left_label)

        self.left_port_combo = QComboBox()
        self.left_port_combo.setMinimumWidth(80)
        self.left_port_combo.setMaximumWidth(120)
        self.left_port_combo.setStyleSheet("""
            QComboBox {
                font-size: 11px;
                padding: 3px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                background-color: white;
            }
            QComboBox:hover {
                border: 1px solid #80bdff;
            }
        """)
        self.left_port_combo.currentTextChanged.connect(self.on_left_port_changed)
        left_port_layout.addWidget(self.left_port_combo)
        port_selection_layout.addLayout(left_port_layout)

        # 右串口选择
        right_port_layout = QVBoxLayout()
        right_port_layout.setSpacing(2)
        right_label = QLabel("Port 2:")
        right_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        right_port_layout.addWidget(right_label)

        self.right_port_combo = QComboBox()
        self.right_port_combo.setMinimumWidth(80)
        self.right_port_combo.setMaximumWidth(120)
        self.right_port_combo.setStyleSheet("""
            QComboBox {
                font-size: 11px;
                padding: 3px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                background-color: white;
            }
            QComboBox:hover {
                border: 1px solid #80bdff;
            }
        """)
        self.right_port_combo.currentTextChanged.connect(self.on_right_port_changed)
        right_port_layout.addWidget(self.right_port_combo)
        port_selection_layout.addLayout(right_port_layout)

        # 刷新按钮
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #17a2b8, stop:1 #138496);
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #138496, stop:1 #117a8b);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #117a8b, stop:1 #0c5460);
            }
        """)
        refresh_btn.clicked.connect(self.refresh_ports)
        refresh_btn.setToolTip("Refresh Port List")
        port_selection_layout.addWidget(refresh_btn)

        header_layout.addWidget(port_selection_group)

        # 添加6个按钮水平排列区域
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        # 创建水平排列的6个按钮容器
        buttons_container = QWidget()
        buttons_container_layout = QVBoxLayout(buttons_container)
        buttons_container_layout.setSpacing(3)
        buttons_container_layout.setContentsMargins(0, 0, 0, 0)

        # 按钮行布局 - 6个按钮水平排开
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)

        # 串口1中位校准按钮
        self.left_calib_btn = QPushButton("Port 1 Mid-Point Calibration")
        self.left_calib_btn.setFixedSize(100, 35)
        self.left_calib_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4caf50, stop:1 #45a049);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #047857, stop:1 #035b69);
            }
        """)
        self.left_calib_btn.clicked.connect(self.run_quick_calibration_left)
        buttons_row.addWidget(self.left_calib_btn)

        # 串口1中位测试按钮
        self.left_test_btn = QPushButton("Port 1 Mid-Point Test")
        self.left_test_btn.setFixedSize(100, 35)
        self.left_test_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2196f3, stop:1 #1976d2);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1976d2, stop:1 #1565c0);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1565c0, stop:1 #0d47a1);
            }
        """)
        self.left_test_btn.clicked.connect(self.run_quick_test_left)
        buttons_row.addWidget(self.left_test_btn)

        # 串口1失能电机按钮
        self.left_disable_btn = QPushButton("Port 1 Disable Motor")
        self.left_disable_btn.setFixedSize(100, 35)
        self.left_disable_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff9800, stop:1 #f57c00);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f57c00, stop:1 #ef6c00);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ef6c00, stop:1 #e65100);
            }
        """)
        self.left_disable_btn.clicked.connect(self.run_quick_disable_left)
        buttons_row.addWidget(self.left_disable_btn)

        # 分隔线
        separator_label = QLabel("|")
        separator_label.setStyleSheet("color: #ccc; font-size: 20px; margin: 0 5px;")
        buttons_row.addWidget(separator_label)

        # 串口2中位校准按钮
        self.right_calib_btn = QPushButton("Port 2 Mid-Point Calibration")
        self.right_calib_btn.setFixedSize(100, 35)
        self.right_calib_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4caf50, stop:1 #45a049);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #047857, stop:1 #035b69);
            }
        """)
        self.right_calib_btn.clicked.connect(self.run_quick_calibration_right)
        buttons_row.addWidget(self.right_calib_btn)

        # 串口2中位测试按钮
        self.right_test_btn = QPushButton("Port 2 Mid-Point Test")
        self.right_test_btn.setFixedSize(100, 35)
        self.right_test_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2196f3, stop:1 #1976d2);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1976d2, stop:1 #1565c0);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1565c0, stop:1 #0d47a1);
            }
        """)
        self.right_test_btn.clicked.connect(self.run_quick_test_right)
        buttons_row.addWidget(self.right_test_btn)

        # 串口2失能电机按钮
        self.right_disable_btn = QPushButton("Port 2 Disable Motor")
        self.right_disable_btn.setFixedSize(100, 35)
        self.right_disable_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff9800, stop:1 #f57c00);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f57c00, stop:1 #ef6c00);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ef6c00, stop:1 #e65100);
            }
        """)
        self.right_disable_btn.clicked.connect(self.run_quick_disable_right)
        buttons_row.addWidget(self.right_disable_btn)

        buttons_container_layout.addLayout(buttons_row)
        buttons_layout.addWidget(buttons_container)

        main_layout.addLayout(header_layout)

        # 创建副标题
        # subtitle_label = QLabel("双串口工厂舵机标定工具 - 支持中位校准、测试、失能功能")
        # subtitle_label.setAlignment(Qt.AlignCenter)
        # subtitle_label.setStyleSheet("font-size: 14px; color: #6c757d; margin-bottom: 10px;")
        # main_layout.addWidget(subtitle_label)

        # 创建状态栏（必须先创建，因为标签页初始化会使用 status_bar）
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Dual-serial-port system started - independent left/right operation + mid-point calibration")

        # 创建标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # === Tab 1: 舵机标定 ===
        servo_tab = QWidget()
        servo_tab_layout = QVBoxLayout(servo_tab)
        servo_tab_layout.setContentsMargins(10, 10, 10, 10)
        servo_tab_layout.setSpacing(10)

        # 添加6个快捷按钮到舵机标定页
        servo_tab_layout.addLayout(buttons_layout)

        # 创建分割器（stretch=1：多余垂直空间全部分给面板区，按钮行保持紧凑）
        splitter = QSplitter(Qt.Horizontal)
        servo_tab_layout.addWidget(splitter, 1)

        # 创建左侧面板（包在滚动区域内，高度不足时出滚动条而不是控件重叠）
        self.left_panel = ServoPanel(self.left_port, "left")
        splitter.addWidget(self._wrap_in_scroll_area(self.left_panel))

        # 创建右侧面板
        self.right_panel = ServoPanel(self.right_port, "right")
        splitter.addWidget(self._wrap_in_scroll_area(self.right_panel))

        # 设置分割器比例
        splitter.setSizes([800, 800])

        self.tab_widget.addTab(servo_tab, "🦾 Servo Calibration")

        # === Tab 2: 单舵机控制 ===
        single_control_tab = QWidget()
        single_control_layout = QHBoxLayout(single_control_tab)
        single_control_layout.setContentsMargins(10, 10, 10, 10)
        single_control_layout.setSpacing(10)

        single_control_splitter = QSplitter(Qt.Horizontal)
        single_control_splitter.addWidget(self._wrap_in_scroll_area(self.left_panel.servo_control_widget))
        single_control_splitter.addWidget(self._wrap_in_scroll_area(self.right_panel.servo_control_widget))
        single_control_splitter.setSizes([800, 800])

        single_control_layout.addWidget(single_control_splitter)
        self.tab_widget.addTab(single_control_tab, "🎚️ Single Servo Control")

        # === Tab 3: 高级工具 ===
        advanced_tab = QWidget()
        advanced_tab_layout = QHBoxLayout(advanced_tab)
        advanced_tab_layout.setContentsMargins(10, 10, 10, 10)
        advanced_tab_layout.setSpacing(10)

        advanced_splitter = QSplitter(Qt.Horizontal)
        self.left_advanced_panel = AdvancedToolsPanel(self.left_panel)
        self.right_advanced_panel = AdvancedToolsPanel(self.right_panel)
        advanced_splitter.addWidget(self._wrap_in_scroll_area(self.left_advanced_panel))
        advanced_splitter.addWidget(self._wrap_in_scroll_area(self.right_advanced_panel))
        advanced_splitter.setSizes([800, 800])

        advanced_tab_layout.addWidget(advanced_splitter)
        self.tab_widget.addTab(advanced_tab, "🔧 Advanced Tools")

        # 设置整体样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f8f9fa;
            }
        """)

    @staticmethod
    def _wrap_in_scroll_area(widget):
        """Wrap the panel in a scroll area: shows a scrollbar when the window is too short,
        preventing the layout from being compressed enough that controls (e.g. the ID calibration 1-6 buttons) overlap"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def init_connections(self):
        """Initialize signal connections"""
        # 添加初始日志
        self.status_bar.showMessage("Dual-serial-port system started - independent left/right operation + mid-point calibration", 3000)

    def toggle_remote_control(self):
        """Toggle remote-control operation"""
        if self.remote_worker is None:
            # 创建遥控工作线程，传递当前选择的端口
            self.remote_worker = RemoteControlWorker(
                read_port=self.left_port,    # 左端口用于读取
                control_port=self.right_port # 右端口用于控制
            )
            self.remote_worker.log_message.connect(self.add_remote_log)
            self.remote_worker.control_started.connect(self.on_remote_started)
            self.remote_worker.control_stopped.connect(self.on_remote_stopped)

        if not self.remote_worker.running:
            # 启动遥控操作
            self.start_remote_control()
        else:
            # 停止遥控操作
            self.stop_remote_control()

    def start_remote_control(self):
        """Start remote-control operation"""
        # 停止现有的舵机标定操作，避免端口冲突
        if self.left_panel.worker.is_connected:
            self.left_panel.worker.stop()
        if self.right_panel.worker.is_connected:
            self.right_panel.worker.stop()

        # 启动遥控操作
        success, message = self.remote_worker.start_remote_control()

        if success:
            self.remote_btn.setText("⏹️ Stop")
            self.remote_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ef4444, stop:1 #dc2626);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #dc2626, stop:1 #b91c1c);
                }
            """)
            self.add_remote_log(f"✅ {message}")
            self.status_bar.showMessage(f"Remote-control operation started - reading {self.left_port}, controlling {self.right_port}", 5000)
        else:
            self.add_remote_log(f"❌ {message}")
            QMessageBox.critical(self, "Start Failed", f"Can't start remote-control operation:\n{message}")

    def stop_remote_control(self):
        """Stop remote-control operation"""
        if self.remote_worker is None:
            return False

        success, message = self.remote_worker.stop_remote_control()

        if success:
            self.remote_btn.setText("🎮 Remote Control")
            self.remote_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #10b981, stop:1 #059669);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #059669, stop:1 #047857);
                }
                """)
            self.add_remote_log(f"✅ {message}")
            self.status_bar.showMessage("Remote-control operation stopped", 3000)

            # 重新启动舵机标定操作
            self.left_panel.worker.start()
            self.right_panel.worker.start()
        else:
            self.add_remote_log(f"❌ {message}")

    def _begin_tool_action(self, port_name: str) -> int:
        """Start a serial port tool operation (calibration/mid-point test/disable).

        Increments this port's operation generation counter, and terminates any tool subprocess
        still running for this port, guaranteeing the new operation can always claim the serial
        port (serial ports are exclusive on Windows -- an old process that doesn't release it causes a PermissionError).
        Returns this operation's generation number.
        """
        gen = self._tool_gen.get(port_name, 0) + 1
        self._tool_gen[port_name] = gen

        proc = self._tool_procs.get(port_name)
        if proc is not None and proc.poll() is None:
            self.add_remote_log(f"⏹️ Terminating {port_name}'s previous still-running tool process, releasing serial port...")
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._tool_procs.pop(port_name, None)
        return gen

    def _is_latest_tool_action(self, port_name: str, gen: int) -> bool:
        """Check whether this operation is still the latest for this port (an old thread superseded by a new operation should not resume the scan thread)"""
        return self._tool_gen.get(port_name) == gen

    def _register_tool_process(self, port_name: str, process):
        """Register the tool subprocess currently running for this port"""
        self._tool_procs[port_name] = process

    def _tool_panel_log(self, port_name: str, message: str):
        """Write the tool's execution result to the corresponding panel's operation log (forwarded via worker signal, thread-safe),
        so a failure message doesn't just flash in the status bar and make the user think nothing happened"""
        panel = self.left_panel if port_name == self.left_port else self.right_panel
        try:
            if panel is not None and panel.worker is not None:
                panel.worker.log_message.emit(message, panel.port_id)
        except Exception:
            pass

    def run_quick_calibration(self, port_name: str):
        """Quick mid-point calibration - non-blocking"""
        self.add_remote_log(f"🔧 Starting {port_name} quick mid-point calibration...")
        self.status_bar.showMessage(f"Running {port_name} mid-point calibration...", 5000)

        # 先终止该端口上一个仍在运行的工具进程，确保能拿到串口
        gen = self._begin_tool_action(port_name)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ Stopped {port_name} scan thread, preparing to calibrate")
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ Stopped {port_name} scan thread, preparing to calibrate")
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        # 使用线程非阻塞执行
        from threading import Thread
        thread = Thread(target=self._execute_quick_calibration, args=(port_name, gen))
        thread.daemon = True
        thread.start()

        self.add_remote_log(f"📝 {port_name} calibration process started, please wait for it to finish")

    def _execute_quick_calibration(self, port_name: str, gen: int):
        """Thread function that performs quick mid-point calibration"""
        try:
            self.add_remote_log(f"🔍 Looking for calibration script...")
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk

            # 检查使用哪个脚本
            tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools')
            quick_script = os.path.join(tools_dir, 'servo_quick_calibration.py')

            if os.path.exists(quick_script):
                self.add_remote_log(f"✅ Found calibration script: servo_quick_calibration.py")
                command = [sys.executable, '-m', 'src.tools.servo_quick_calibration', port_name]
            else:
                self.add_remote_log(f"⚠️ servo_quick_calibration.py not found, using servo_middle_calibration.py")
                command = [sys.executable, '-m', 'src.tools.servo_middle_calibration', port_name, "2"]  # 使用自动模式

            self.add_remote_log(f"🚀 Starting calibration process: {' '.join(command)}")

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )
            self._register_tool_process(port_name, process)

            # 监控输出
            important_keywords = ["Connect", "Scan", "Calibrate", "Done", "Failed", "Error", "Success", "Found"]
            while process.poll() is None:
                try:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        if line:
                            print(f"[{port_name} CALIB] {line}")
                            # 只显示包含重要关键词的日志
                            if any(keyword in line for keyword in important_keywords):
                                self.add_remote_log(f"[{port_name}] {line}")
                except:
                    break

            return_code = process.wait()
            self._tool_procs.pop(port_name, None)
            if not self._is_latest_tool_action(port_name, gen):
                self.add_remote_log(f"ℹ️ {port_name} mid-point calibration was interrupted/superseded by a new operation")
                return
            if return_code == 0:
                self.add_remote_log(f"✅ {port_name} mid-point calibration complete - process exited normally")
                self._tool_panel_log(port_name, f"✅ {port_name} mid-point calibration complete")
                self.status_bar.showMessage(f"{port_name} calibration complete", 3000)
            else:
                self.add_remote_log(f"❌ {port_name} mid-point calibration failed - exit code: {return_code}")
                self._tool_panel_log(port_name, f"❌ {port_name} mid-point calibration failed - exit code: {return_code}")
                self.status_bar.showMessage(f"{port_name} calibration failed", 3000)

            # 重新启动相应端口的扫描线程
            self.add_remote_log(f"⏳ Waiting for port to be released...")
            import time
            time.sleep(1.0)  # 增加等待时间确保端口完全释放

            if port_name == self.left_port:
                self.left_panel.worker.start()
                self.add_remote_log(f"▶️ Restarted {port_name} scan thread")
            elif port_name == self.right_port:
                self.right_panel.worker.start()
                self.add_remote_log(f"▶️ Restarted {port_name} scan thread")

        except Exception as e:
            self._tool_procs.pop(port_name, None)
            self.add_remote_log(f"❌ {port_name} calibration exception: {e}")
            self._tool_panel_log(port_name, f"❌ {port_name} calibration exception: {e}")
            self.status_bar.showMessage(f"{port_name} calibration exception: {e}", 3000)
            # 即使出现异常也要尝试重新启动扫描线程（被新操作取代时除外）
            if not self._is_latest_tool_action(port_name, gen):
                return
            try:
                import time
                time.sleep(1.0)
                if port_name == self.left_port:
                    self.left_panel.worker.start()
                    self.add_remote_log(f"🔄 Restarting {port_name} scan thread after exception")
                elif port_name == self.right_port:
                    self.right_panel.worker.start()
                    self.add_remote_log(f"🔄 Restarting {port_name} scan thread after exception")
            except:
                self.add_remote_log(f"⚠️ Failed to restart {port_name} scan thread")

    def run_quick_test(self, port_name: str):
        """Quick mid-point test - non-blocking"""
        self.add_remote_log(f"🧪 Starting {port_name} mid-point test...")
        self.status_bar.showMessage(f"Running {port_name} mid-point test...", 5000)

        # 先终止该端口上一个仍在运行的工具进程，确保能拿到串口
        gen = self._begin_tool_action(port_name)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ Stopped {port_name} scan thread, preparing to test")
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ Stopped {port_name} scan thread, preparing to test")
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        from threading import Thread
        thread = Thread(target=self._execute_quick_test, args=(port_name, gen))
        thread.daemon = True
        thread.start()

        self.add_remote_log(f"📝 {port_name} test process started, please wait for it to finish")

    def _execute_quick_test(self, port_name: str, gen: int):
        """Thread function that performs quick mid-point test"""
        try:
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk
            command = [sys.executable, '-m', 'src.tools.servo_center_test', port_name]

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )
            self._register_tool_process(port_name, process)

            # 监控输出
            while process.poll() is None:
                try:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        if line:
                            print(f"[{port_name} TEST] {line}")
                except:
                    break

            return_code = process.wait()
            self._tool_procs.pop(port_name, None)
            if not self._is_latest_tool_action(port_name, gen):
                self.add_remote_log(f"ℹ️ {port_name} mid-point test was interrupted/superseded by a new operation")
                return
            if return_code == 0:
                self.add_remote_log(f"✅ {port_name} mid-point test complete")
                self._tool_panel_log(port_name, f"✅ {port_name} mid-point test complete (torque stays on; click \"Disable Motor\" to release)")
            else:
                self.add_remote_log(f"❌ {port_name} mid-point test failed")
                self._tool_panel_log(port_name, f"❌ {port_name} mid-point test failed - exit code: {return_code}")

            # 重新启动相应端口的扫描线程
            import time
            time.sleep(0.5)  # 等待端口完全释放

            if port_name == self.left_port:
                self.left_panel.worker.start()
                self.add_remote_log(f"▶️ Restarted {port_name} scan thread")
            elif port_name == self.right_port:
                self.right_panel.worker.start()
                self.add_remote_log(f"▶️ Restarted {port_name} scan thread")

        except Exception as e:
            self._tool_procs.pop(port_name, None)
            self.add_remote_log(f"❌ {port_name} test exception: {e}")
            self._tool_panel_log(port_name, f"❌ {port_name} test exception: {e}")
            # 即使出现异常也要尝试重新启动扫描线程（被新操作取代时除外）
            if not self._is_latest_tool_action(port_name, gen):
                return
            try:
                import time
                time.sleep(0.5)
                if port_name == self.left_port:
                    self.left_panel.worker.start()
                elif port_name == self.right_port:
                    self.right_panel.worker.start()
            except:
                pass

    def run_quick_disable(self, port_name: str):
        """Quick disable motor - non-blocking"""
        self.add_remote_log(f"⏹️ Starting {port_name} disable motor...")
        self.status_bar.showMessage(f"Running {port_name} disable motor...", 5000)

        # 先终止该端口上一个仍在运行的工具进程（如中位测试），确保能拿到串口。
        # 否则 Windows 串口独占会让失能进程打不开端口，表现为"点失能没反应"
        gen = self._begin_tool_action(port_name)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker and self.left_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ Stopped {port_name} scan thread, preparing to disable")
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker and self.right_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ Stopped {port_name} scan thread, preparing to disable")
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        from threading import Thread
        thread = Thread(target=self._execute_quick_disable, args=(port_name, gen))
        thread.daemon = True
        thread.start()

        self.add_remote_log(f"📝 {port_name} disable process started, please wait for it to finish")

    def _execute_quick_disable(self, port_name: str, gen: int):
        """Thread function that performs quick disable motor"""
        try:
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk
            command = [sys.executable, '-m', 'src.tools.servo_disable', port_name]

            self.add_remote_log(f"🚀 Starting disable process: {' '.join(command)}")
            print(f"[DEBUG DISABLE] Port name: {port_name}")
            print(f"[DEBUG DISABLE] Full command: {command}")

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )
            self._register_tool_process(port_name, process)

            # 监控输出 - 显示重要信息
            important_keywords = ["Connect", "Scan", "Disable", "Done", "Failed", "Error", "Success", "Found", "Torque", "Rotate"]
            while process.poll() is None:
                try:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        if line:
                            print(f"[{port_name} DISABLE] {line}")
                            # 只显示包含重要关键词的日志
                            if any(keyword in line for keyword in important_keywords):
                                self.add_remote_log(f"[{port_name}] {line}")
                            # 失败/错误类信息同时写到面板日志，避免用户看不到原因
                            if "❌" in line or "Can't Open" in line or "Error" in line:
                                self._tool_panel_log(port_name, line)
                except:
                    break

            return_code = process.wait()
            self._tool_procs.pop(port_name, None)
            if not self._is_latest_tool_action(port_name, gen):
                self.add_remote_log(f"ℹ️ {port_name} disable operation was interrupted/superseded by a new operation")
                return
            if return_code == 0:
                self.add_remote_log(f"✅ {port_name} motor disabled, can be rotated by hand")
                self._tool_panel_log(port_name, f"✅ {port_name} motor disabled, can be rotated by hand")
                self.status_bar.showMessage(f"{port_name} disable complete", 3000)
            else:
                self.add_remote_log(f"❌ {port_name} disable failed - exit code: {return_code}")
                self._tool_panel_log(port_name, f"❌ {port_name} disable failed - exit code: {return_code}, please retry")
                self.status_bar.showMessage(f"{port_name} disable failed", 3000)

            # 重新启动相应端口的扫描线程
            import time
            time.sleep(0.5)  # 等待端口完全释放

            if port_name == self.left_port and self.left_panel.worker:
                self.left_panel.worker.start()
                self.add_remote_log(f"▶️ Restarted {port_name} scan thread")
            elif port_name == self.right_port and self.right_panel.worker:
                self.right_panel.worker.start()
                self.add_remote_log(f"▶️ Restarted {port_name} scan thread")

        except Exception as e:
            self._tool_procs.pop(port_name, None)
            self.add_remote_log(f"❌ {port_name} disable exception: {e}")
            self._tool_panel_log(port_name, f"❌ {port_name} disable exception: {e}")
            self.status_bar.showMessage(f"{port_name} disable exception: {e}", 3000)
            # 即使出现异常也要尝试重新启动扫描线程（被新操作取代时除外）
            if not self._is_latest_tool_action(port_name, gen):
                return
            try:
                import time
                time.sleep(0.5)
                if port_name == self.left_port and self.left_panel.worker:
                    self.left_panel.worker.start()
                    self.add_remote_log(f"🔄 Restarting {port_name} scan thread after exception")
                elif port_name == self.right_port and self.right_panel.worker:
                    self.right_panel.worker.start()
                    self.add_remote_log(f"🔄 Restarting {port_name} scan thread after exception")
            except:
                pass

    def add_remote_log(self, message):
        """Add a remote-control log entry"""
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[REMOTE] {message}"
        try:
            print(f"[REMOTE] {log_entry}")
        except UnicodeEncodeError:
            # GBK 控制台下 emoji 无法编码，降级为可显示字符，避免整个按钮动作被异常打断
            print(f"[REMOTE] {log_entry.encode('gbk', 'replace').decode('gbk')}")
        self.status_bar.showMessage(f"Remote: {message}", 3000)

    def on_remote_started(self):
        """Remote-control start callback"""
        pass

    def on_remote_stopped(self):
        """Remote-control stop callback"""
        pass

    def refresh_ports(self):
        """Refresh the list of available serial ports"""
        try:
            self.available_ports = get_available_ports()
            print(f"[DEBUG] Available ports: {self.available_ports}")

            disabled_text = ServoPanel.DISABLED_PORT

            # 保存当前选择
            current_left = self.left_port_combo.currentText() if hasattr(self, 'left_port_combo') else (
                self.left_port if self.left_port else disabled_text
            )
            current_right = self.right_port_combo.currentText() if hasattr(self, 'right_port_combo') else (
                self.right_port if self.right_port else disabled_text
            )

            # 临时断开信号，避免 clear/add 触发多次端口切换
            self.left_port_combo.currentTextChanged.disconnect(self.on_left_port_changed)
            self.right_port_combo.currentTextChanged.disconnect(self.on_right_port_changed)

            try:
                # 清空下拉框
                self.left_port_combo.clear()
                self.right_port_combo.clear()

                # 添加禁用选项
                self.left_port_combo.addItem(disabled_text)
                self.right_port_combo.addItem(disabled_text)

                # 添加可用串口
                for port in self.available_ports:
                    self.left_port_combo.addItem(port)
                    self.right_port_combo.addItem(port)

                # 尝试恢复之前的选择；如果之前选中的真实端口已消失，则禁用该侧，
                # 避免自动切换到其他设备造成误操作。
                left_index = self.left_port_combo.findText(current_left)
                if left_index >= 0:
                    self.left_port_combo.setCurrentIndex(left_index)
                else:
                    self.left_port_combo.setCurrentIndex(0)

                right_index = self.right_port_combo.findText(current_right)
                if right_index >= 0:
                    self.right_port_combo.setCurrentIndex(right_index)
                else:
                    self.right_port_combo.setCurrentIndex(0)

                # 避免左右两侧指向同一个真实串口
                if (
                    self.left_port_combo.currentText() != disabled_text
                    and self.left_port_combo.currentText() == self.right_port_combo.currentText()
                ):
                    self.right_port_combo.setCurrentIndex(0)
                    print(
                        f"[DEBUG] Left/right port conflict, disabled right port: "
                        f"{self.left_port_combo.currentText()}"
                    )
            finally:
                # 恢复信号连接
                self.left_port_combo.currentTextChanged.connect(self.on_left_port_changed)
                self.right_port_combo.currentTextChanged.connect(self.on_right_port_changed)

            # 手动同步当前端口状态（防止信号断开期间状态不一致）
            new_left = self.left_port_combo.currentText()
            new_right = self.right_port_combo.currentText()

            # 左侧：真实端口变化 或 从真实端口变为禁用，都需要处理
            if new_left == disabled_text:
                if self.left_port is not None:
                    self.on_left_port_changed(disabled_text)
            elif new_left != (self.left_port or ""):
                self.on_left_port_changed(new_left)

            # 右侧：同上
            if new_right == disabled_text:
                if self.right_port is not None:
                    self.on_right_port_changed(disabled_text)
            elif new_right != (self.right_port or ""):
                self.on_right_port_changed(new_right)

            self.status_bar.showMessage(f"Serial port list refreshed - found {len(self.available_ports)} ports", 3000)

        except Exception as e:
            print(f"[DEBUG] Refresh ports error: {e}")
            self.status_bar.showMessage(f"Failed to refresh serial port list: {e}", 3000)

    def on_left_port_changed(self, port_name):
        """Left serial port selection changed"""
        if port_name == self.left_port or (
            not self.left_port and port_name == ServoPanel.DISABLED_PORT
        ):
            return

        # 检查是否与右端口冲突
        if port_name != ServoPanel.DISABLED_PORT and port_name == self.right_port:
            QMessageBox.warning(
                self, "Port Conflict",
                f"Port 2 is already using {port_name}, can't select the same port twice."
            )
            # 恢复左下拉框到之前的状态
            self.left_port_combo.blockSignals(True)
            self.left_port_combo.setCurrentText(
                self.left_port if self.left_port else ServoPanel.DISABLED_PORT
            )
            self.left_port_combo.blockSignals(False)
            return

        print(f"[DEBUG] Left port changed from {self.left_port} to {port_name}")

        # 停止当前工作线程
        self.left_panel.stop()

        if port_name == ServoPanel.DISABLED_PORT:
            self.left_port = None
            self.left_panel.update_port_name(ServoPanel.DISABLED_PORT)
            self.left_panel.connection_status.setText("⚫ Disabled")
            self.left_panel.worker = None
            # 清空舵机列表显示，避免拔掉设备后仍显示旧数据
            self.left_panel.update_status([], False, self.left_panel.port_id)
            self.status_bar.showMessage("Port 1 Disabled", 3000)
            return

        self.left_port = port_name

        # 更新面板的端口名称和标题
        self.left_panel.update_port_name(self.left_port)

        # 创建新的工作线程
        self.left_panel.worker = ServoWorker(self.left_port, "left")

        # 重新连接信号
        self.left_panel.init_connections()

        # 启动新的工作线程
        self.left_panel.worker.start()

        self.status_bar.showMessage(f"Port 1 switched to: {port_name}", 3000)

    def on_right_port_changed(self, port_name):
        """Right serial port selection changed"""
        if port_name == self.right_port or (
            not self.right_port and port_name == ServoPanel.DISABLED_PORT
        ):
            return

        # 检查是否与左端口冲突
        if port_name != ServoPanel.DISABLED_PORT and port_name == self.left_port:
            QMessageBox.warning(
                self, "Port Conflict",
                f"Port 1 is already using {port_name}, can't select the same port twice."
            )
            # 恢复右下拉框到之前的状态
            self.right_port_combo.blockSignals(True)
            self.right_port_combo.setCurrentText(
                self.right_port if self.right_port else ServoPanel.DISABLED_PORT
            )
            self.right_port_combo.blockSignals(False)
            return

        print(f"[DEBUG] Right port changed from {self.right_port} to {port_name}")

        # 停止当前工作线程
        self.right_panel.stop()

        if port_name == ServoPanel.DISABLED_PORT:
            self.right_port = None
            self.right_panel.update_port_name(ServoPanel.DISABLED_PORT)
            self.right_panel.connection_status.setText("⚫ Disabled")
            self.right_panel.worker = None
            # 清空舵机列表显示，避免拔掉设备后仍显示旧数据
            self.right_panel.update_status([], False, self.right_panel.port_id)
            self.status_bar.showMessage("Port 2 Disabled", 3000)
            return

        self.right_port = port_name

        # 更新面板的端口名称和标题
        self.right_panel.update_port_name(self.right_port)

        # 创建新的工作线程
        self.right_panel.worker = ServoWorker(self.right_port, "right")

        # 重新连接信号
        self.right_panel.init_connections()

        # 启动新的工作线程
        self.right_panel.worker.start()

        self.status_bar.showMessage(f"Port 2 switched to: {port_name}", 3000)

    def run_quick_calibration_left(self):
        """Port 1 quick mid-point calibration"""
        self.run_quick_calibration(self.left_port)

    def run_quick_test_left(self):
        """Port 1 quick mid-point test"""
        self.run_quick_test(self.left_port)

    def run_quick_disable_left(self):
        """Port 1 quick disable motor"""
        self.run_quick_disable(self.left_port)

    def run_quick_calibration_right(self):
        """Port 2 quick mid-point calibration"""
        self.run_quick_calibration(self.right_port)

    def run_quick_test_right(self):
        """Port 2 quick mid-point test"""
        self.run_quick_test(self.right_port)

    def run_quick_disable_right(self):
        """Port 2 quick disable motor"""
        self.run_quick_disable(self.right_port)

    def closeEvent(self, event):
        """Close event"""
        # 停止串口自动刷新定时器
        self.stop_port_refresh()

        # 停止遥控操作
        if self.remote_worker and self.remote_worker.running:
            self.remote_worker.stop_remote_control()

        # 停止舵机标定操作
        self.left_panel.stop()
        self.right_panel.stop()

        super().closeEvent(event)


def get_available_ports():
    """Get the list of available serial ports - uses the already-filtered ports from port_utils"""
    try:
        from src.port_utils import get_available_ports as get_ports
        ports = get_ports()
        return [p.device for p in ports]
    except ImportError:
        print("Warning: port_utils not available, using fallback")
        try:
            import serial.tools.list_ports
            ports = []
            for port in serial.tools.list_ports.comports():
                device = port.device
                # Linux 过滤虚拟串口 ttyS*
                if platform.system() == "Linux" and "ttyS" in device:
                    continue
                ports.append(device)
            return sorted(ports)
        except ImportError:
            print("Warning: pyserial not available, using default ports")
            if platform.system() == "Windows":
                return ["COM1", "COM2"]
            else:
                return ["/dev/ttyUSB0", "/dev/ttyUSB1"]


def main():
    """Main function"""
    import platform
    import argparse

    # Windows 下子进程默认可能使用 GBK 编码，导致脚本里的 emoji 输出报错。
    # 强制子进程使用 utf-8 编码标准输出。
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # 解析命令行参数
    parser = argparse.ArgumentParser(description='Dual-serial-port factory servo calibration tool')
    parser.add_argument('--port1', type=str, help='Specify serial port 1 (e.g. COM1 or /dev/ttyUSB0)')
    parser.add_argument('--port2', type=str, help='Specify serial port 2 (e.g. COM2 or /dev/ttyUSB1)')
    parser.add_argument('--list-ports', action='store_true', help='List available serial ports and exit')
    args = parser.parse_args()

    # 如果只是列出串口
    if args.list_ports:
        try:
            available_ports = get_available_ports()
            print("Available serial ports:")
            for i, port in enumerate(available_ports, 1):
                print(f"  {i}. {port}")
            if not available_ports:
                print("  No available serial ports found")
        except Exception as e:
            print(f"Failed to get serial port list: {e}")
        return

    app = QApplication(sys.argv)

    # 设置 Ctrl+C 信号处理，使其能正常关闭 Qt 应用
    import signal

    def handle_sigint(signum, frame):
        print("\nReceived Ctrl+C, shutting down...")
        app.quit()

    signal.signal(signal.SIGINT, handle_sigint)

    # 启动定时器让 Python 有机会处理信号
    sig_timer = QTimer()
    sig_timer.start(200)
    sig_timer.timeout.connect(lambda: None)

    if THEME_UTILS_AVAILABLE:
        setup_light_theme(app)
    else:
        app.setStyle('Fusion')

    # 根据操作系统选择默认端口
    system = platform.system()
    if system == "Windows":
        default_left_port = "COM1"
        default_right_port = "COM2"
    else:  # Linux - 支持USB转串口和ACM设备
        default_left_port = "/dev/ttyUSB0"  # USB转串口设备
        default_right_port = "/dev/ttyUSB1"
        # 如果USB设备不存在，系统会自动检测可用的ACM设备

    # 使用命令行参数或默认端口
    left_port = args.port1 if args.port1 else default_left_port
    right_port = args.port2 if args.port2 else default_right_port

    print(f"Starting dual-serial-port factory servo calibration tool")
    print(f"System: {system}")
    print(f"Port 1: {left_port}")
    print(f"Port 2: {right_port}")

    # 检查可用端口
    try:
        available_ports = get_available_ports()
        print(f"Detected available serial ports: {available_ports}")

        # 如果没有指定命令行参数，自动选择最佳端口
        if not args.port1 or not args.port2:
            if system == "Windows":
                preferred_ports = ["COM1", "COM2"]
            else:  # Linux - 优先选择USB设备，然后是ACM设备
                preferred_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"]

            if len(available_ports) >= 2:
                # 查找首选端口
                found_ports = []
                for pref_port in preferred_ports:
                    if pref_port in available_ports:
                        found_ports.append(pref_port)

                # 如果找到两个首选端口，使用它们
                if len(found_ports) >= 2 and not args.port1 and not args.port2:
                    left_port, right_port = found_ports[0], found_ports[1]
                    print(f"Using preferred ports: {left_port}, {right_port}")
                # 如果只找到一个首选端口
                elif len(found_ports) == 1:
                    if not args.port1:
                        left_port = found_ports[0]
                    if not args.port2:
                        # 选择一个不是首选端口的其他端口
                        for port in available_ports:
                            if port != (args.port1 or found_ports[0]):
                                right_port = port
                                break
                    print(f"Using mixed port configuration: {left_port}, {right_port}")
                # 没有找到首选端口
                elif not args.port1 and not args.port2:
                    left_port, right_port = available_ports[0], available_ports[1]
                    print(f"Using the first two available ports: {left_port}, {right_port}")

            elif len(available_ports) == 1:
                if not args.port1:
                    left_port = available_ports[0]
                if not args.port2:
                    right_port = None  # 只有一个真实串口，禁用右端口避免冲突
                print(f"Only one port available: {available_ports[0]}, fallback port: {right_port if right_port else 'Disabled'}")
            else:
                print("No available serial ports found, using default configuration")

    except Exception as e:
        print(f"Error checking available ports: {e}")

    # 创建并显示主窗口
    window = EZToolUI(left_port, right_port)
    window.show()

    print("UI started")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()