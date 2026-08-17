#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EZ Tool - 简化版双串口工厂舵机标定工具
基于原始工具，只增加一个中间值校准按钮
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
    QTabWidget, QSlider, QScrollArea, QSizePolicy
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

# 引入国际化支持
try:
    from src.i18n import tr, set_lang
except ImportError:
    def tr(text):
        return text

    def set_lang(lang):
        return lang


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
    """根据型号编号获取舵机型号名称，未知则返回原始编号字符串"""
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
    """遥控操作后台工作线程"""
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
        """启动遥控操作"""
        if self.running:
            return False, tr("遥控操作已在运行")

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
            self.log_message.emit(tr("🚀 遥控操作已启动 (10ms更新间隔)"))
            self.control_started.emit()

            # 启动监控线程
            threading.Thread(target=self._monitor_process, daemon=True).start()

            return True, tr("遥控操作启动成功")

        except Exception as e:
            return False, tr("启动遥控操作失败: {}").format(e)

    def stop_remote_control(self):
        """停止遥控操作"""
        if not self.running:
            return False, tr("遥控操作未运行")

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
            self.log_message.emit(tr("⏹️ 遥控操作已停止"))
            self.control_stopped.emit()
            return True, tr("遥控操作停止成功")

        except Exception as e:
            return False, tr("停止遥控操作失败: {}").format(e)

    def _monitor_process(self):
        """监控遥控进程的输出"""
        if not self.remote_process:
            return

        try:
            while self.running and self.remote_process.poll() is None:
                line = self.remote_process.stdout.readline()
                if line:
                    line = line.strip()
                    if line:
                        self.log_message.emit(tr("遥控: {}").format(line))
                time.sleep(0.1)

            # 进程结束
            if self.remote_process.poll() is not None:
                self.running = False
                self.remote_process = None
                self.log_message.emit(tr("🔚 遥控进程已结束"))
                self.control_stopped.emit()

        except Exception as e:
            self.log_message.emit(tr("监控遥控进程异常: {}").format(e))
            self.running = False
            self.control_stopped.emit()


class IDChangeDialog(QDialog):
    """修改舵机ID对话框 - 允许用户自定义源ID和目标ID"""

    def __init__(self, current_servos, default_old_id=None, default_new_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("修改舵机ID"))
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
            self.old_id_combo.addItem(tr("舵机 ID {}").format(servo_id), servo_id)
        if default_old_id and default_old_id in current_servos:
            index = self.old_id_combo.findData(default_old_id)
            if index >= 0:
                self.old_id_combo.setCurrentIndex(index)
        layout.addRow(tr("源舵机ID:"), self.old_id_combo)

        # 目标ID（数字输入）
        self.new_id_input = QSpinBox()
        self.new_id_input.setRange(1, 253)
        if default_new_id:
            self.new_id_input.setValue(default_new_id)
        else:
            self.new_id_input.setValue(1)
        layout.addRow(tr("修改ID为:"), self.new_id_input)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return self.old_id_combo.currentData(), self.new_id_input.value()


class ServoWorker(QObject):
    """单个舵机控制工作线程"""
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
        """请求立即重新扫描"""
        self.rescan_requested.set()
        self.command_event.set()
        self.log_message.emit(tr("🔄 收到重新扫描请求"), self.port_id)

    def connect_servo(self) -> bool:
        """连接舵机控制器"""
        try:
            print(f"[DEBUG] {self.port_id}: Attempting to connect to {self.port_name}")
            self.log_message.emit(tr("正在连接舵机控制器: {}").format(self.port_name), self.port_id)

            # 如果已有旧连接，先彻底关闭并释放（Windows 必须等句柄释放）
            if self.port_handler is not None:
                try:
                    self.port_handler.closePort()
                except Exception as e:
                    print(f"[DEBUG] {self.port_id}: 关闭旧端口时异常: {e}")
                self.port_handler = None
                self.servo_handler = None
                if os.name == 'nt':
                    time.sleep(0.3)

            self.port_handler = PortHandler(self.port_name)

            if not self.port_handler.openPort():
                print(f"[DEBUG] {self.port_id}: Failed to open port {self.port_name}")
                self.log_message.emit(tr("❌ 无法打开串口: {}").format(self.port_name), self.port_id)
                return False

            if not self.port_handler.setBaudRate(self.baud_rate):
                print(f"[DEBUG] {self.port_id}: Failed to set baud rate {self.baud_rate}")
                self.log_message.emit(tr("❌ 无法设置波特率: {}").format(self.baud_rate), self.port_id)
                self.port_handler.closePort()
                return False

            self.servo_handler = sms_sts(self.port_handler)
            self.is_connected = True
            print(f"[DEBUG] {self.port_id}: Successfully connected to {self.port_name}")
            self.log_message.emit(tr("✅ 舵机控制器连接成功"), self.port_id)
            return True

        except Exception as e:
            print(f"[DEBUG] {self.port_id}: Connection exception: {e}")
            self.log_message.emit(tr("❌ 连接失败: {}").format(e), self.port_id)
            return False

    def disconnect_servo(self):
        """断开舵机连接"""
        try:
            if self.port_handler:
                self.port_handler.closePort()
        except Exception as e:
            print(f"[DEBUG] {self.port_id}: 断开连接异常: {e}")
        finally:
            self.is_connected = False
            self.port_handler = None
            self.servo_handler = None
            self.log_message.emit(tr("🔌 舵机控制器已断开"), self.port_id)

    def ping_servo(self, servo_id: int) -> bool:
        """检测舵机是否存在"""
        try:
            model_number, result, error = self.servo_handler.ping(servo_id)
            if result == COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: 舵机 {servo_id} 型号: {model_number}")
                return True
            else:
                print(f"[DEBUG] {self.port_id}: Ping 舵机 {servo_id} 失败: result={result}, error={error}")
                return False
        except Exception as e:
            print(f"[DEBUG] {self.port_id}: Ping 舵机 {servo_id} 异常: {e}")
            return False

    def scan_servos(self) -> List[int]:
        """扫描所有舵机"""
        if not self.is_connected:
            return []

        # 热插拔检测：在 POSIX 系统上检查端口设备文件是否仍然存在
        if os.name != 'nt' and not os.path.exists(self.port_name):
            print(f"[DEBUG] {self.port_id}: 端口设备已消失: {self.port_name}")
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
        """修改舵机ID（队列版本）"""
        # 将请求加入队列
        self.queue_id_change(old_id, new_id)
        return True, tr("ID修改请求已加入队列")

    def queue_id_change(self, old_id: int, new_id: int):
        """将ID修改请求加入队列"""
        print(f"[DEBUG] {self.port_id}: ID修改请求入队: {old_id} -> {new_id}")
        self.log_message.emit(tr("📝 ID修改请求已排队: {} -> {}").format(old_id, new_id), self.port_id)
        self.id_change_queue.put((old_id, new_id, time.time()))

        # 启动ID修改线程（如果还没启动）
        if not self.id_change_running:
            self.start_id_change_processor()

    def start_id_change_processor(self):
        """启动ID修改处理线程"""
        if not self.id_change_running:
            self.id_change_running = True
            self.id_change_thread = threading.Thread(target=self.process_id_changes, daemon=True)
            self.id_change_thread.start()
            print(f"[DEBUG] {self.port_id}: ID修改处理线程已启动")

    def process_id_changes(self):
        """处理ID修改队列"""
        print(f"[DEBUG] {self.port_id}: 开始处理ID修改队列")
        while self.id_change_running or not self.id_change_queue.empty():
            try:
                if not self.id_change_queue.empty():
                    old_id, new_id, request_time = self.id_change_queue.get(timeout=1)

                    # 暂停扫描，避免总线冲突
                    self.pause_scanning = True
                    print(f"[DEBUG] {self.port_id}: 暂停扫描，准备执行ID修改: {old_id} -> {new_id}")
                    self.log_message.emit(tr("⏸️ 暂停扫描，执行ID修改: {} -> {}").format(old_id, new_id), self.port_id)

                    # 等待一下确保扫描完全停止
                    time.sleep(0.5)

                    # 执行ID修改
                    success, message = self.execute_id_change(old_id, new_id)

                    # 恢复扫描
                    self.pause_scanning = False
                    print(f"[DEBUG] {self.port_id}: 恢复扫描")
                    self.log_message.emit(tr("▶️ 恢复扫描"), self.port_id)

                    # 发送结果
                    self.id_changed.emit(old_id, new_id, success, message, self.port_id)

                else:
                    time.sleep(0.1)  # 短暂休眠避免CPU占用

            except Exception as e:
                print(f"[DEBUG] {self.port_id}: ID修改处理异常: {e}")
                self.log_message.emit(tr("❌ ID修改处理异常: {}").format(e), self.port_id)
                # 确保扫描被恢复
                self.pause_scanning = False

        print(f"[DEBUG] {self.port_id}: ID修改处理线程结束")
        self.id_change_running = False
        self.pause_scanning = False

    def execute_id_change(self, old_id: int, new_id: int) -> (bool, str):
        """执行实际的ID修改操作"""
        try:
            if not self.is_connected:
                return False, tr("未连接舵机控制器")

            self.log_message.emit(tr("🔧 执行SMS_STS ID修改: {} -> {}").format(old_id, new_id), self.port_id)
            print(f"[DEBUG] {self.port_id}: 执行ID修改: {old_id} -> {new_id}")

            # 首先读取舵机信息（此时扫描已暂停，不会冲突）
            try:
                model_number, result, error = self.servo_handler.ping(old_id)
                if result == COMM_SUCCESS:
                    print(f"[DEBUG] {self.port_id}: SMS_STS 舵机型号: {model_number}")
                    self.log_message.emit(tr("📋 舵机型号: {}").format(model_number), self.port_id)
                else:
                    print(f"[DEBUG] {self.port_id}: 无法读取舵机信息: {error}")
                    return False, tr("无法读取舵机信息: {}").format(error)
            except Exception as e:
                return False, tr("读取舵机信息异常: {}").format(e)

            # SMS_STS EEPROM解锁流程
            print(f"[DEBUG] {self.port_id}: SMS_STS 解锁EEPROM...")
            result, error = self.servo_handler.unLockEprom(old_id)
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: EEPROM解锁失败: result={result}, error={error}")
                return False, tr("EEPROM解锁失败: {}").format(error)

            print(f"[DEBUG] {self.port_id}: EEPROM解锁成功")
            time.sleep(0.1)

            # 修改ID (使用SMS_STS_ID地址)
            print(f"[DEBUG] {self.port_id}: 写入新ID: {new_id}")
            result, error = self.servo_handler.write1ByteTxRx(old_id, 5, new_id)  # SMS_STS_ID = 5
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: ID写入失败: result={result}, error={error}")
                return False, tr("ID写入失败: {}").format(error)

            print(f"[DEBUG] {self.port_id}: ID写入成功")
            time.sleep(0.3)

            # 验证新ID（此时扫描仍暂停，ping不会冲突）
            print(f"[DEBUG] {self.port_id}: 验证新ID: {new_id}")
            if not self.ping_servo(new_id):
                print(f"[DEBUG] {self.port_id}: 新ID验证失败")
                return False, tr("验证失败，无法ping通新ID: {}").format(new_id)

            print(f"[DEBUG] {self.port_id}: 新ID验证成功")

            # 重新锁定EEPROM
            print(f"[DEBUG] {self.port_id}: 重新锁定EEPROM...")
            result, error = self.servo_handler.LockEprom(new_id)
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: 重新锁定失败: {error}")
                self.log_message.emit(tr("⚠️ 重新锁定EEPROM失败: {}").format(error), self.port_id)
            else:
                print(f"[DEBUG] {self.port_id}: 重新锁定成功")

            self.log_message.emit(tr("✅ SMS_STS ID修改成功: {} -> {}").format(old_id, new_id), self.port_id)
            print(f"[DEBUG] {self.port_id}: ID修改完成: {old_id} -> {new_id}")
            return True, ""

        except Exception as e:
            error_msg = tr("修改ID异常: {}").format(e)
            print(f"[DEBUG] {self.port_id}: 修改ID异常: {e}")
            self.log_message.emit(f"❌ {error_msg}", self.port_id)
            return False, error_msg

    # ------------------------------------------------------------------
    # 系统命令队列：寄存器读写、波特率修改、恢复出厂设置
    # ------------------------------------------------------------------
    def queue_system_command(self, command: dict):
        """将系统命令加入队列"""
        print(f"[DEBUG] {self.port_id}: 系统命令入队: {command}")
        self.system_command_queue.put(command)
        self.log_message.emit(tr("📝 {} 已排队").format(command.get('desc', tr('系统命令'))), self.port_id)
        if not self.system_command_running:
            self.start_system_command_processor()

    def start_system_command_processor(self):
        """启动系统命令处理线程"""
        if not self.system_command_running:
            self.system_command_running = True
            self.system_command_thread = threading.Thread(target=self.process_system_commands, daemon=True)
            self.system_command_thread.start()
            print(f"[DEBUG] {self.port_id}: 系统命令处理线程已启动")

    def process_system_commands(self):
        """处理系统命令队列"""
        print(f"[DEBUG] {self.port_id}: 开始处理系统命令队列")
        while self.system_command_running or not self.system_command_queue.empty():
            try:
                if not self.system_command_queue.empty():
                    command = self.system_command_queue.get(timeout=1)
                    cmd_type = command.get("type")

                    # 暂停扫描，避免总线冲突
                    self.pause_scanning = True
                    self.log_message.emit(tr("⏸️ 暂停扫描，执行: {}").format(command.get('desc', cmd_type)), self.port_id)
                    time.sleep(0.3)

                    success = False
                    message = tr("未知命令")
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
                        message = tr("执行异常: {}").format(e)
                        print(f"[DEBUG] {self.port_id}: 系统命令执行异常: {e}")

                    # 恢复扫描
                    self.pause_scanning = False
                    self.log_message.emit(tr("▶️ 恢复扫描"), self.port_id)

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
                print(f"[DEBUG] {self.port_id}: 系统命令处理异常: {e}")
                self.log_message.emit(tr("❌ 系统命令处理异常: {}").format(e), self.port_id)
                self.pause_scanning = False

        print(f"[DEBUG] {self.port_id}: 系统命令处理线程结束")
        self.system_command_running = False
        self.pause_scanning = False

    def execute_register_read(self, servo_id: int, address: int, length: int) -> (bool, str, int):
        """执行寄存器读取"""
        if not self.is_connected:
            return False, tr("未连接舵机控制器"), None

        self.log_message.emit(tr("🔍 读取 ID{} 寄存器 0x{:02X} ({}字节)").format(servo_id, address, length), self.port_id)
        try:
            if length == 1:
                value, result, error = self.servo_handler.read1ByteTxRx(servo_id, address)
            elif length == 2:
                value, result, error = self.servo_handler.read2ByteTxRx(servo_id, address)
            elif length == 4:
                value, result, error = self.servo_handler.read4ByteTxRx(servo_id, address)
            else:
                return False, tr("不支持的长度（仅支持1/2/4字节）"), None

            if result == COMM_SUCCESS:
                self.log_message.emit(tr("✅ ID{} 寄存器 0x{:02X} = {} (0x{:X})").format(servo_id, address, value, value), self.port_id)
                return True, "读取成功", value
            else:
                return False, tr("读取失败: result={}, error={}").format(result, error), None
        except Exception as e:
            return False, tr("读取异常: {}").format(e), None

    def execute_register_write(self, servo_id: int, address: int, length: int, value: int) -> (bool, str):
        """执行寄存器写入"""
        if not self.is_connected:
            return False, tr("未连接舵机控制器")

        self.log_message.emit(tr("✏️ 写入 ID{} 寄存器 0x{:02X} = {} ({}字节)").format(servo_id, address, value, length), self.port_id)
        try:
            if length == 1:
                result, error = self.servo_handler.write1ByteTxRx(servo_id, address, value)
            elif length == 2:
                result, error = self.servo_handler.write2ByteTxRx(servo_id, address, value)
            elif length == 4:
                result, error = self.servo_handler.write4ByteTxRx(servo_id, address, value)
            else:
                return False, tr("不支持的长度（仅支持1/2/4字节）")

            if result == COMM_SUCCESS:
                self.log_message.emit(tr("✅ ID{} 寄存器 0x{:02X} 写入成功").format(servo_id, address), self.port_id)
                return True, tr("写入成功")
            else:
                return False, tr("写入失败: result={}, error={}").format(result, error)
        except Exception as e:
            return False, tr("写入异常: {}").format(e)

    def execute_baud_rate_change(self, servo_id: int, new_baud_rate: int) -> (bool, str):
        """执行波特率修改"""
        if not self.is_connected:
            return False, tr("未连接舵机控制器")

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
            return False, tr("不支持的波特率: {}").format(new_baud_rate)

        reg_value = baud_to_reg[new_baud_rate]
        old_baud_rate = self.baud_rate

        self.log_message.emit(
            tr("🔧 修改 ID{} 波特率: {} -> {}").format(servo_id, old_baud_rate, new_baud_rate), self.port_id
        )

        try:
            # 解锁 EEPROM
            result, error = self.servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                return False, tr("EEPROM解锁失败: {}").format(error)

            # 写入新波特率（地址 6）
            result, error = self.servo_handler.write1ByteTxRx(servo_id, 6, reg_value)
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, tr("波特率写入失败: {}").format(error)

            # 锁定 EEPROM
            self.servo_handler.LockEprom(servo_id)
            time.sleep(0.2)

            # 尝试切换到新波特率
            self.log_message.emit(tr("🔄 串口切换到 {} bps...").format(new_baud_rate), self.port_id)
            self.port_handler.setBaudRate(new_baud_rate)
            self.baud_rate = new_baud_rate
            time.sleep(0.3)

            # 验证通信
            if self.ping_servo(servo_id):
                self.log_message.emit(tr("✅ 波特率修改成功，当前 {} bps").format(new_baud_rate), self.port_id)
                return True, tr("波特率已修改为 {} bps").format(new_baud_rate)
            else:
                # 切换失败，尝试恢复旧波特率
                self.log_message.emit(tr("⚠️ 新波特率验证失败，尝试恢复 {} bps").format(old_baud_rate), self.port_id)
                self.port_handler.setBaudRate(old_baud_rate)
                self.baud_rate = old_baud_rate
                time.sleep(0.3)
                if self.ping_servo(servo_id):
                    return False, tr("新波特率验证失败，已恢复 {} bps").format(old_baud_rate)
                else:
                    return False, tr("严重：波特率修改失败且旧波特率也丢失了，请重新连接")

        except Exception as e:
            return False, tr("波特率修改异常: {}").format(e)

    def execute_factory_reset(self, servo_id: int) -> (bool, str):
        """执行恢复出厂设置"""
        if not self.is_connected:
            return False, tr("未连接舵机控制器")

        self.log_message.emit(tr("🔄 恢复 ID{} 出厂设置...").format(servo_id), self.port_id)
        try:
            result, error = self.servo_handler.reSet(servo_id)
            if result == COMM_SUCCESS:
                self.log_message.emit(
                    tr("✅ ID{} 已恢复出厂设置（ID 将变回 1，波特率变回 1000000）").format(servo_id),
                    self.port_id
                )
                return True, tr("恢复出厂设置成功，请重新扫描（舵机ID已变为1）")
            else:
                return False, tr("恢复出厂设置失败: result={}, error={}").format(result, error)
        except Exception as e:
            return False, tr("恢复出厂设置异常: {}").format(e)

    def execute_set_middle_calibration(self, servo_id: int) -> (bool, str):
        """将当前位置设为指定舵机的中位值（2048）"""
        if not self.is_connected:
            return False, tr("未连接舵机控制器")
        if servo_id not in self.current_servos:
            return False, tr("ID{} 已离线，无法设置中位").format(servo_id)

        self.log_message.emit(tr("🔧 设置 ID{} 中位校准...").format(servo_id), self.port_id)
        try:
            # 解锁 EEPROM
            result, error = self.servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                return False, tr("EEPROM解锁失败: {}").format(error)
            time.sleep(0.1)

            # 发送中位校准命令：写 128 到地址 40
            result, error = self.servo_handler.write1ByteTxRx(
                servo_id, SMS_STS_TORQUE_ENABLE, SMS_STS_CALIBRATE_MIDDLE
            )
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, tr("中位校准命令失败: {}").format(error)
            time.sleep(0.1)

            # 重新锁定 EEPROM
            result, error = self.servo_handler.LockEprom(servo_id)
            if result != COMM_SUCCESS:
                self.log_message.emit(tr("⚠️ ID{} EEPROM重新锁定失败: {}").format(servo_id, error), self.port_id)

            return True, tr("ID{} 中位校准成功（当前位置已设为 2048）").format(servo_id)
        except Exception as e:
            return False, tr("中位校准异常: {}").format(e)

    def execute_clear_angle_limits(self, servo_id: int) -> (bool, str):
        """清除指定舵机的最小/最大角度限制（恢复为 0 ~ 4095）"""
        if not self.is_connected:
            return False, tr("未连接舵机控制器")
        if servo_id not in self.current_servos:
            return False, tr("ID{} 已离线，无法清除角度限制").format(servo_id)

        self.log_message.emit(tr("🧹 清除 ID{} 角度限制...").format(servo_id), self.port_id)
        try:
            # 解锁 EEPROM
            result, error = self.servo_handler.unLockEprom(servo_id)
            if result != COMM_SUCCESS:
                return False, tr("EEPROM解锁失败: {}").format(error)
            time.sleep(0.1)

            # 写入最小角度限制为 0
            result, error = self.servo_handler.write2ByteTxRx(
                servo_id, SMS_STS_MIN_ANGLE_LIMIT_L, 0
            )
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, tr("清除最小角度限制失败: {}").format(error)
            time.sleep(0.05)

            # 写入最大角度限制为 4095
            result, error = self.servo_handler.write2ByteTxRx(
                servo_id, SMS_STS_MAX_ANGLE_LIMIT_L, 4095
            )
            if result != COMM_SUCCESS:
                self.servo_handler.LockEprom(servo_id)
                return False, tr("清除最大角度限制失败: {}").format(error)
            time.sleep(0.05)

            # 重新锁定 EEPROM
            result, error = self.servo_handler.LockEprom(servo_id)
            if result != COMM_SUCCESS:
                self.log_message.emit(tr("⚠️ ID{} EEPROM重新锁定失败: {}").format(servo_id, error), self.port_id)

            return True, tr("ID{} 角度限制已清除（MIN=0, MAX=4095）").format(servo_id)
        except Exception as e:
            return False, tr("清除角度限制异常: {}").format(e)

    def set_servo_torque(self, servo_id: int, enable: bool):
        """设置单个舵机力矩（加入队列，由扫描线程串行执行）"""
        self.torque_queue.put((servo_id, enable))
        self.command_event.set()

    def set_servo_position(self, servo_id: int, position: int):
        """设置单个舵机目标位置（加入队列，由扫描线程串行执行）"""
        self.position_queue.put((servo_id, position))
        self.command_event.set()

    def _process_commands(self):
        """处理力矩和位置控制命令"""
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
                        tr("{} ID{} 力矩{}").format(
                            '⚡' if enable else '⏹️', servo_id, tr("开启") if enable else tr("关闭")
                        ), self.port_id
                    )
                else:
                    self.log_message.emit(tr("❌ ID{} 力矩设置失败").format(servo_id), self.port_id)
            except Exception as e:
                self.log_message.emit(tr("❌ 力矩命令异常: {}").format(e), self.port_id)

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
                    self.log_message.emit(tr("❌ ID{} 位置写入失败").format(servo_id), self.port_id)
            except Exception as e:
                self.log_message.emit(tr("❌ 位置命令异常: {}").format(e), self.port_id)

    def _read_servo_info(self) -> dict:
        """读取当前在线舵机的完整状态信息"""
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
        """解析舵机状态寄存器中的保护标志"""
        return {
            "overload": bool(status & ERRBIT_OVERLOAD),
            "over_current": bool(status & ERRBIT_OVERELE),
            "over_heat": bool(status & ERRBIT_OVERHEAT),
            "over_voltage": bool(status & ERRBIT_VOLTAGE),
        }

    def _read_positions(self) -> dict:
        """读取当前在线舵机的位置（兼容旧信号）"""
        positions = {}
        info = self._read_servo_info()
        for servo_id, servo_info in info.items():
            if servo_info["position"] is not None:
                positions[servo_id] = servo_info["position"]
        return positions

    def run_scanner(self):
        """运行扫描循环"""
        scan_count = 0
        self.running = True
        consecutive_failures = 0
        consecutive_empty_scans = 0
        max_failures = 3
        max_empty_scans = 5  # 连续空扫描阈值，超过则强制重新连接（处理热插拔）

        self.log_message.emit(tr("🚀 扫描线程启动"), self.port_id)
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
                        self.log_message.emit(tr("🔄 尝试重新连接... (第{}次)").format(consecutive_failures + 1), self.port_id)
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
                        self.log_message.emit(tr("⚠️ 连续失败{}次，等待10秒后重试...").format(max_failures), self.port_id)
                        time.sleep(10)
                        consecutive_failures = 0  # 重置计数
                        if not self.running:
                            break
                        continue

                # 检查是否暂停扫描（ID修改期间）
                if self.pause_scanning:
                    print(f"[DEBUG] {self.port_id}: 扫描已暂停（ID修改中）")
                    time.sleep(0.5)  # 短暂休眠，减少CPU占用
                    continue

                # 检查是否有手动重新扫描请求
                is_rescan = self.rescan_requested.is_set()
                if is_rescan:
                    self.rescan_requested.clear()
                    self.log_message.emit(tr("🔄 执行手动重新扫描..."), self.port_id)

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
                            tr("⚠️ 连续 {} 次未扫描到舵机，判断为串口已断开，尝试重新连接...").format(max_empty_scans),
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
                            self.log_message.emit(tr("📡 发现舵机: {}").format(new_servos), self.port_id)
                        else:
                            added = set(new_servos) - set(old_servos)
                            removed = set(old_servos) - set(new_servos)
                            changes = []
                            if added:
                                changes.append(tr("新增: {}").format(list(added)))
                            if removed:
                                changes.append(tr("移除: {}").format(list(removed)))
                            self.log_message.emit(tr("📡 舵机变化: {}").format(', '.join(changes)), self.port_id)
                    else:
                        if old_servos:
                            self.log_message.emit(tr("📡 所有舵机已断开"), self.port_id)

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
                        self.log_message.emit(tr("📊 当前舵机ID: {}").format(self.current_servos), self.port_id)
                    else:
                        self.log_message.emit(tr("📊 当前无舵机"), self.port_id)

            except Exception as e:
                consecutive_failures += 1
                self.log_message.emit(tr("❌ 扫描异常: {} (失败次数: {})").format(e, consecutive_failures), self.port_id)
                # 连续异常达到阈值时，强制重新打开串口（处理底层 serial 异常未重置 is_connected 的情况）
                if consecutive_failures >= max_failures:
                    self.log_message.emit(
                        tr("⚠️ 连续扫描异常 {} 次，强制重新连接串口...").format(max_failures), self.port_id
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
        """启动工作线程"""
        # 旧扫描线程尚未退出时不重复创建，避免两个线程并发操作同一串口
        if self._scanner_thread and self._scanner_thread.is_alive():
            self.running = True  # 让旧线程继续循环
            return
        self.running = True
        self._scanner_thread = threading.Thread(target=self.run_scanner, daemon=True)
        self._scanner_thread.start()

    def stop(self):
        """停止工作线程"""
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
    """单个舵机控制面板"""

    DISABLED_PORT = "-- 禁用 --"

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
            self.title_label.setText(tr("🏭 {} - 舵机标定").format(self.DISABLED_PORT))
            self.connection_status.setText(tr("⚫ 已禁用"))

    def init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        self.title_label = QLabel(tr("🏭 {} - 舵机标定").format(self.port_name))
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
        """创建状态面板"""
        status_group = QGroupBox(tr("📡 系统状态"))
        status_layout = QHBoxLayout()
        status_group.setLayout(status_layout)

        # 连接状态
        self.connection_status = QLabel(tr("🔴 未连接"))
        self.connection_status.setStyleSheet("font-size: 12px; font-weight: bold;")
        status_layout.addWidget(self.connection_status)

        status_layout.addStretch()

        # 当前舵机
        self.current_servos_label = QLabel(tr("当前舵机: 扫描中..."))
        self.current_servos_label.setStyleSheet("font-size: 12px;")
        status_layout.addWidget(self.current_servos_label)

        status_layout.addSpacing(15)

        # 重新扫描按钮
        self.rescan_btn = QPushButton(tr("🔄 重新扫描"))
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
        self.rescan_btn.setToolTip(tr("立即重新扫描舵机"))
        self.rescan_btn.clicked.connect(self.request_rescan)
        status_layout.addWidget(self.rescan_btn)

        layout.addWidget(status_group)

    def create_servo_panel(self, layout):
        """创建舵机状态面板"""
        servo_group = QGroupBox(tr("📡 舵机状态"))
        servo_layout = QVBoxLayout()
        servo_group.setLayout(servo_layout)

        # 左右并列布局
        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(10)

        # 左侧：发现的舵机
        found_layout = QVBoxLayout()
        found_label = QLabel(tr("✅ 发现的舵机"))
        found_label.setStyleSheet("font-weight: bold; color: #28a745; font-size: 12px;")
        found_layout.addWidget(found_label)

        self.servo_list_found = QTextEdit()
        self.servo_list_found.setReadOnly(True)
        self.servo_list_found.setMaximumHeight(150)
        self.servo_list_found.setPlainText(tr("正在扫描舵机..."))
        found_layout.addWidget(self.servo_list_found)

        lists_layout.addLayout(found_layout)

        # 右侧：未识别ID
        missing_layout = QVBoxLayout()
        missing_label = QLabel(tr("⚠️ 未识别ID"))
        missing_label.setStyleSheet("font-weight: bold; color: #dc3545; font-size: 12px;")
        missing_layout.addWidget(missing_label)

        self.servo_list_missing = QTextEdit()
        self.servo_list_missing.setReadOnly(True)
        self.servo_list_missing.setMaximumHeight(150)
        self.servo_list_missing.setPlainText(tr("正在扫描舵机..."))
        missing_layout.addWidget(self.servo_list_missing)

        lists_layout.addLayout(missing_layout)

        servo_layout.addLayout(lists_layout)
        layout.addWidget(servo_group)

    def create_calibration_panel(self, layout):
        """创建标定面板"""
        calibration_group = QGroupBox(tr("🎯 ID标定"))
        calibration_layout = QVBoxLayout()
        calibration_group.setLayout(calibration_layout)

        # 说明文字
        info_label = QLabel(tr("📋 点击目标ID执行修改\n⏸️ 自动暂停扫描确保成功"))
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
        """创建单舵机滑动条控制面板，返回一个可复用的 QWidget"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(5, 5, 5, 5)

        control_group = QGroupBox(tr("🎚️ 单舵机控制 - {}").format(self.port_name))
        control_layout = QVBoxLayout()
        control_group.setLayout(control_layout)

        # 全局力矩按钮
        global_btn_layout = QHBoxLayout()

        self.enable_all_torque_btn = QPushButton(tr("⚡ 开启所有力矩"))
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

        self.disable_all_torque_btn = QPushButton(tr("⏹️ 关闭所有力矩"))
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

            torque_btn = QPushButton(tr("⚡ 力矩"))
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
            middle_btn = QPushButton(tr("🎯 中位"))
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
            middle_btn.setToolTip(tr("将当前位置设为该舵机的中位值（2048）"))
            middle_btn.clicked.connect(lambda checked, sid=servo_id: self.on_set_middle_clicked(sid))
            self.servo_middle_btns[servo_id] = middle_btn
            row_layout.addWidget(middle_btn)

            # 清除角度限制按钮
            clear_limit_btn = QPushButton(tr("🧹 清限位"))
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
            clear_limit_btn.setToolTip(tr("清除该舵机的最小/最大角度限制（恢复 0~4095）"))
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
            tr("💡 拖动滑块并松开后，舵机将移动到目标位置。未识别到的舵机无法操作。")
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
        """创建日志面板"""
        log_group = QGroupBox(tr("📋 操作日志"))
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setPlainText(tr("系统启动..."))
        log_layout.addWidget(self.log_text)

        # 清空日志按钮
        clear_btn = QPushButton(tr("清空日志"))
        clear_btn.setMaximumWidth(80)
        clear_btn.setStyleSheet("font-size: 11px;")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)

        layout.addWidget(log_group)

    def init_connections(self):
        """初始化信号连接"""
        if self.worker is None:
            return
        self.worker.status_updated.connect(self.update_status)
        self.worker.id_changed.connect(self.on_id_changed)
        self.worker.log_message.connect(self.add_log)
        self.worker.positions_updated.connect(self.update_positions)
        self.worker.servo_info_updated.connect(self.update_servo_info)
        self.worker.system_command_result.connect(self.on_system_command_result)

        # 添加初始连接日志
        self.add_log(tr("🔄 信号连接已建立"), self.port_id)
        self.add_log(tr("📡 开始扫描舵机..."), self.port_id)

    def on_system_command_result(self, cmd_type, success, message, port_id):
        """处理系统命令执行结果（中位校准、清除限位等）"""
        if port_id != self.port_id:
            return
        prefix = "✅" if success else "❌"
        self.add_log(f"{prefix} {message}", self.port_id)

    def update_status(self, servos, connected, port_id):
        """更新状态显示"""
        if port_id != self.port_id:
            return

        print(f"[DEBUG] {port_id} update_status called: servos={servos}, connected={connected}")
        if connected:
            self.connection_status.setText(tr("🟢 已连接"))
            self.connection_status.setStyleSheet("color: #28a745; font-size: 12px; font-weight: bold;")
        else:
            self.connection_status.setText(tr("🔴 未连接"))
            self.connection_status.setStyleSheet("color: #dc3545; font-size: 12px; font-weight: bold;")

        if servos:
            self.current_servos_label.setText(tr("当前舵机: {}").format(', '.join(map(str, servos))))
            found_html = "<br>".join([f"<span style='color: #28a745; font-weight: bold;'>{tr('• 舵机 ID: {}').format(servo_id)}</span>" for servo_id in servos])
            self.servo_list_found.setHtml(found_html)

            # 计算 1-6 号槽位中未识别的ID并显示
            expected_ids = set(range(1, 7))
            found_ids = set(servos)
            missing_ids = sorted(expected_ids - found_ids)
            if missing_ids:
                missing_html = "<br>".join([f"<span style='color: #dc3545; font-weight: bold;'>• ID {servo_id}</span>" for servo_id in missing_ids])
                self.servo_list_missing.setHtml(missing_html)
            else:
                self.servo_list_missing.setHtml("<span style='color: #28a745; font-weight: bold;'>" + tr("✅ 1-6号槽位全部识别") + "</span>")
        else:
            self.current_servos_label.setText(tr("当前舵机: 无"))
            self.servo_list_found.setHtml("<span style='color: #dc3545;'>" + tr("📡 未发现舵机<br><br>请检查:<br>1. 舵机控制器是否连接<br>2. 舵机是否通电<br>3. 串口配置是否正确") + "</span>")
            self.servo_list_missing.setHtml("")

        # 更新按钮状态
        self.update_button_states(servos, connected)

        # 更新单舵机控制面板状态
        self.update_servo_control_state(servos, connected)

    def update_button_states(self, servos, connected):
        """更新按钮状态"""
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
        """根据在线舵机更新滑动条和力矩按钮可用状态"""
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
                torque_btn.setText(tr("⚡ 力矩"))

    def update_positions(self, positions: dict):
        """更新各舵机当前位置显示（兼容旧信号）"""
        if not positions:
            return

        for servo_id, pos in positions.items():
            if servo_id in self.servo_pos_labels:
                self.servo_pos_labels[servo_id].setText(f"Pos: {pos}")

    def update_servo_info(self, info: dict):
        """更新各舵机完整状态显示（电压、温度、速度、负载、电流、运行状态、型号等）"""
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
                    active_errors.append(tr("过载"))
                if errors.get("over_current"):
                    active_errors.append(tr("过流"))
                if errors.get("over_voltage"):
                    active_errors.append(tr("过压"))
                if errors.get("over_heat"):
                    active_errors.append(tr("过热"))

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
                tooltip_lines.append(tr("型号: {}").format(get_servo_model_name(model)))
            if speed is not None:
                tooltip_lines.append(tr("速度: {}").format(speed))
            if load is not None:
                tooltip_lines.append(tr("负载: {}").format(load))
            if current is not None:
                tooltip_lines.append(tr("电流: {:.1f} mA").format(current_ma))
            if moving is not None:
                tooltip_lines.append(tr("运行中: {}").format(tr("是") if moving else tr("否")))
            if errors:
                tooltip_lines.append("")
                tooltip_lines.append(tr("保护状态:"))
                tooltip_lines.append(tr("  过载: {}").format(tr("是") if errors.get('overload') else tr("否")))
                tooltip_lines.append(tr("  过流: {}").format(tr("是") if errors.get('over_current') else tr("否")))
                tooltip_lines.append(tr("  过压: {}").format(tr("是") if errors.get('over_voltage') else tr("否")))
                tooltip_lines.append(tr("  过热: {}").format(tr("是") if errors.get('over_heat') else tr("否")))
                tooltip_lines.append("")
                tooltip_lines.append(tr("保护说明:"))
                tooltip_lines.append(tr("  过载: 堵转>80%持续2s后保护"))
                tooltip_lines.append(tr("  过流: 电流>2A持续2s后保护"))
                tooltip_lines.append(tr("  过压: 电压>8V或<4V保护"))
                tooltip_lines.append(tr("  过热: 温度>70℃关闭扭矩"))
            tooltip = "\n".join(tooltip_lines)
            self.servo_voltage_labels[servo_id].setToolTip(tooltip)
            self.servo_temp_labels[servo_id].setToolTip(tooltip)
            self.servo_status_labels[servo_id].setToolTip(tooltip)

        # 健康检查
        self.check_servo_health_ui(info)

    def check_servo_health_ui(self, info: dict):
        """检查舵机健康状态并在日志/状态栏提示"""
        warnings = []
        for servo_id, servo_info in info.items():
            voltage = servo_info.get("voltage")
            temperature = servo_info.get("temperature")
            errors = servo_info.get("errors", {})

            if voltage is not None:
                v_min, v_max = get_voltage_range(voltage)
                if voltage < v_min or voltage > v_max:
                    warnings.append(
                        tr("ID{} 电压异常: {:.1f}V (安全范围 {:.1f}V~{:.1f}V)").format(servo_id, voltage, v_min, v_max)
                    )
            if temperature is not None and temperature > SAFE_TEMPERATURE_MAX:
                warnings.append(
                    tr("ID{} 温度过高: {}°C (建议 < {:.0f}°C)").format(servo_id, temperature, SAFE_TEMPERATURE_MAX)
                )

            # 保护状态警告
            if errors.get("overload"):
                warnings.append(tr("ID{} 过载保护: 堵转>80%持续2s，需重新发位置指令清除").format(servo_id))
            if errors.get("over_current"):
                warnings.append(tr("ID{} 过流保护: 电流>2A持续2s，需重新发位置指令清除").format(servo_id))
            if errors.get("over_voltage"):
                warnings.append(tr("ID{} 过压保护: 电压>8V或<4V").format(servo_id))
            if errors.get("over_heat"):
                warnings.append(tr("ID{} 过热保护: 温度>70℃，已关闭扭矩输出").format(servo_id))

        if warnings:
            # 避免过于频繁提示：同一端口 5 秒内最多提示一次
            now = time.time()
            last_warn = getattr(self, "_last_health_warning", 0)
            if now - last_warn > 5:
                self._last_health_warning = now
                warning_text = " | ".join(warnings)
                self.add_log(tr("🚨 健康警告: {}").format(warning_text), self.port_id)
                # 如果有父窗口且状态栏可用，也显示在状态栏
                main_window = self.window()
                if main_window and hasattr(main_window, "status_bar"):
                    main_window.status_bar.showMessage(tr("🚨 {}端口: {}").format(self.port_id, warning_text), 5000)

    def on_slider_value_changed(self, servo_id: int, value: int):
        """滑动条数值变化时更新目标位置显示"""
        if servo_id in self.servo_target_labels:
            self.servo_target_labels[servo_id].setText(f"T: {value}")

    def on_slider_released(self, servo_id: int):
        """滑动条释放后发送目标位置"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, tr("警告"), tr("当前端口未连接，无法发送位置命令"))
            return

        slider = self.servo_sliders[servo_id]
        target = slider.value()

        # 确认力矩已开启（若未开启则自动开启并提示）
        torque_btn = self.servo_torque_btns[servo_id]
        if not torque_btn.isChecked():
            reply = QMessageBox.question(
                self,
                tr("力矩未开启"),
                tr("ID{} 力矩未开启，是否先开启力矩再移动？").format(servo_id),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return
            torque_btn.setChecked(True)

        self.add_log(tr("🎚️ ID{} 目标位置: {}").format(servo_id, target), self.port_id)
        self.worker.set_servo_position(servo_id, target)

    def on_torque_toggled(self, servo_id: int, checked: bool):
        """单个舵机力矩按钮切换"""
        if self.worker is None or not self.worker.is_connected:
            return

        btn = self.servo_torque_btns[servo_id]
        btn.setText("⚡ ON" if checked else "⚡ OFF")
        self.worker.set_servo_torque(servo_id, checked)

    def on_set_middle_clicked(self, servo_id: int):
        """设置单个舵机中位值（将当前位置设为 2048）"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, tr("警告"), tr("当前端口未连接"))
            return
        if servo_id not in self.worker.current_servos:
            QMessageBox.warning(self, tr("警告"), tr("ID{} 不在线").format(servo_id))
            return

        reply = QMessageBox.question(
            self,
            tr("确认设置中位"),
            tr("确定要将 ID{} 的当前位置设为中位值（2048）吗？\n\n请确保舵机已处于期望的中位位置。").format(servo_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "set_middle",
            "servo_id": servo_id,
            "desc": tr("设置 ID{} 中位").format(servo_id)
        })

    def on_clear_limits_clicked(self, servo_id: int):
        """清除单个舵机的最小/最大角度限制"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, tr("警告"), tr("当前端口未连接"))
            return
        if servo_id not in self.worker.current_servos:
            QMessageBox.warning(self, tr("警告"), tr("ID{} 不在线").format(servo_id))
            return

        reply = QMessageBox.question(
            self,
            tr("确认清除限位"),
            tr("确定要清除 ID{} 的角度限制吗？\n\n清除后舵机可在完整范围 0~4095 内运动。").format(servo_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "clear_angle_limits",
            "servo_id": servo_id,
            "desc": tr("清除 ID{} 角度限制").format(servo_id)
        })

    def enable_all_torque(self):
        """开启所有在线舵机力矩"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, tr("警告"), tr("当前端口未连接"))
            return

        for servo_id in self.worker.current_servos:
            if servo_id in self.servo_torque_btns:
                self.servo_torque_btns[servo_id].setChecked(True)
                self.worker.set_servo_torque(servo_id, True)

    def disable_all_torque(self):
        """关闭所有在线舵机力矩"""
        if self.worker is None or not self.worker.is_connected:
            QMessageBox.warning(self, tr("警告"), tr("当前端口未连接"))
            return

        for servo_id in self.worker.current_servos:
            if servo_id in self.servo_torque_btns:
                self.servo_torque_btns[servo_id].setChecked(False)
                self.worker.set_servo_torque(servo_id, False)

    def change_servo_id(self, slot_index):
        """修改舵机ID - 弹出对话框让用户自定义源ID和目标ID"""
        print(f"[DEBUG {self.port_id}] change_servo_id called for slot {slot_index}")
        if self.worker is None:
            print(f"[DEBUG {self.port_id}] worker is None, aborting")
            QMessageBox.warning(self, tr("警告"), tr("当前端口已禁用，无法修改ID"))
            return
        if not self.worker.current_servos:
            print(f"[DEBUG {self.port_id}] current_servos empty, aborting")
            QMessageBox.warning(self, tr("警告"), tr("没有可用的舵机进行ID修改"))
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
            box.setWindowTitle(tr("提示"))
            box.setText(tr("源ID和目标ID相同，无需修改"))
            box.setStyleSheet(msg_box_style)
            box.exec()
            return

        if new_id in self.worker.current_servos and new_id != old_id:
            box = QMessageBox(self)
            box.setWindowTitle(tr("确认覆盖"))
            box.setText(tr("目标ID {} 已存在其他舵机，是否继续？").format(new_id))
            box.setInformativeText(tr("继续可能导致总线ID冲突！"))
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            box.setStyleSheet(msg_box_style)
            if box.exec() != QMessageBox.Yes:
                return

        # 确认对话框
        box = QMessageBox(self)
        box.setWindowTitle(tr("确认修改ID ({})").format(self.port_name))
        box.setText(tr("确定要将舵机 ID {} 修改为 ID {} 吗？").format(old_id, new_id))
        box.setInformativeText(tr("系统将自动暂停扫描确保修改成功。"))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setStyleSheet(msg_box_style)
        reply = box.exec()

        if reply == QMessageBox.Yes:
            self.add_log(tr("🎯 提交ID修改请求: {} -> {}").format(old_id, new_id), self.port_id)

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
        """请求立即重新扫描舵机"""
        self.add_log(tr("🔄 手动请求重新扫描..."), self.port_id)
        if self.worker:
            self.worker.request_rescan()

    def on_id_changed(self, old_id, new_id, success, message, port_id):
        """处理ID修改结果"""
        if port_id != self.port_id:
            return

        print(f"[DEBUG] {port_id} on_id_changed called: {old_id} -> {new_id}, success={success}, message={message}")

        if self.worker is None:
            return

        if success:
            QMessageBox.information(self, tr("修改成功 ({})").format(self.port_name), tr("ID修改成功！\n{} -> {}").format(old_id, new_id))
            # 强制重新扫描舵机列表
            self.add_log(tr("🔄 ID修改成功，重新扫描舵机..."), self.port_id)
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
            QMessageBox.critical(self, tr("修改失败 ({})").format(self.port_name), tr("ID修改失败！\n{}").format(message))
            self.add_log(tr("❌ 队列中ID修改失败: {} -> {}").format(old_id, new_id), self.port_id)
            # 刷新按钮状态
            self.update_button_states(self.worker.current_servos, self.worker.is_connected)

    def add_log(self, message, port_id):
        """添加日志消息"""
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
        """更新端口名称和标题"""
        self.port_name = new_port_name
        self.title_label.setText(tr("🏭 {} - 舵机标定").format(self.port_name))

    def stop(self):
        """停止工作线程"""
        if self.worker:
            self.worker.stop()


class AdvancedToolsPanel(QWidget):
    """高级工具面板：寄存器读写、波特率修改、恢复出厂设置"""

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
        title = QLabel(tr("🔧 高级工具 - {}").format(self.servo_panel.port_name))
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 舵机选择
        servo_group = QGroupBox(tr("🎯 目标舵机"))
        servo_layout = QHBoxLayout()
        servo_group.setLayout(servo_layout)

        servo_label = QLabel(tr("舵机ID:"))
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
        refresh_btn.setToolTip(tr("刷新舵机列表"))
        refresh_btn.clicked.connect(self.refresh_servo_ids)
        servo_layout.addWidget(refresh_btn)

        servo_layout.addStretch()
        layout.addWidget(servo_group)

        # 寄存器读取
        read_group = QGroupBox(tr("📖 寄存器读取"))
        read_layout = QGridLayout()
        read_group.setLayout(read_layout)

        read_layout.addWidget(QLabel(tr("地址:")), 0, 0)
        self.read_addr_spin = QSpinBox()
        self.read_addr_spin.setRange(0, 255)
        self.read_addr_spin.setDisplayIntegerBase(16)
        self.read_addr_spin.setPrefix("0x")
        read_layout.addWidget(self.read_addr_spin, 0, 1)

        read_layout.addWidget(QLabel(tr("长度:")), 0, 2)
        self.read_len_combo = QComboBox()
        self.read_len_combo.addItems([tr("1 字节"), tr("2 字节"), tr("4 字节")])
        self.read_len_combo.setItemData(0, 1)
        self.read_len_combo.setItemData(1, 2)
        self.read_len_combo.setItemData(2, 4)
        read_layout.addWidget(self.read_len_combo, 0, 3)

        self.read_btn = QPushButton(tr("🔍 读取"))
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

        self.read_result_label = QLabel(tr("结果: --"))
        self.read_result_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 12px; color: #495057;")
        read_layout.addWidget(self.read_result_label, 1, 2, 1, 2)

        layout.addWidget(read_group)

        # 寄存器写入
        write_group = QGroupBox(tr("✏️ 寄存器写入"))
        write_layout = QGridLayout()
        write_group.setLayout(write_layout)

        write_layout.addWidget(QLabel(tr("地址:")), 0, 0)
        self.write_addr_spin = QSpinBox()
        self.write_addr_spin.setRange(0, 255)
        self.write_addr_spin.setDisplayIntegerBase(16)
        self.write_addr_spin.setPrefix("0x")
        write_layout.addWidget(self.write_addr_spin, 0, 1)

        write_layout.addWidget(QLabel(tr("长度:")), 0, 2)
        self.write_len_combo = QComboBox()
        self.write_len_combo.addItems([tr("1 字节"), tr("2 字节"), tr("4 字节")])
        self.write_len_combo.setItemData(0, 1)
        self.write_len_combo.setItemData(1, 2)
        self.write_len_combo.setItemData(2, 4)
        write_layout.addWidget(self.write_len_combo, 0, 3)

        write_layout.addWidget(QLabel(tr("数值:")), 1, 0)
        self.write_value_spin = QSpinBox()
        self.write_value_spin.setRange(0, 2147483647)
        self.write_value_spin.setDisplayIntegerBase(10)
        write_layout.addWidget(self.write_value_spin, 1, 1)

        self.write_btn = QPushButton(tr("✏️ 写入"))
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
        baud_group = QGroupBox(tr("🔌 波特率修改"))
        baud_layout = QHBoxLayout()
        baud_group.setLayout(baud_layout)

        baud_layout.addWidget(QLabel(tr("新波特率:")))
        self.baud_combo = QComboBox()
        for rate in [1000000, 500000, 250000, 128000, 115200, 76800, 57600, 38400]:
            self.baud_combo.addItem(str(rate), rate)
        baud_layout.addWidget(self.baud_combo)

        self.baud_btn = QPushButton(tr("🔧 修改波特率"))
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
        reset_group = QGroupBox(tr("🔄 恢复出厂设置"))
        reset_layout = QHBoxLayout()
        reset_group.setLayout(reset_layout)

        reset_info = QLabel(tr("⚠️ 将舵机恢复为出厂状态（ID 变回 1，波特率变回 1000000）"))
        reset_info.setStyleSheet("color: #856404; font-size: 11px;")
        reset_info.setWordWrap(True)
        reset_layout.addWidget(reset_info)

        self.reset_btn = QPushButton(tr("🔄 恢复出厂"))
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
        log_group = QGroupBox(tr("📋 操作日志"))
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

        clear_btn = QPushButton(tr("清空"))
        clear_btn.setMaximumWidth(60)
        clear_btn.clicked.connect(self.adv_log_text.clear)
        log_layout.addWidget(clear_btn)

        layout.addWidget(log_group)
        layout.addStretch()

        # 初始状态
        self.refresh_servo_ids()
        self.update_button_states()

    def init_connections(self):
        """初始化信号连接"""
        if self.worker is None:
            return
        self.worker.register_read_result.connect(self.on_register_read_result)
        self.worker.system_command_result.connect(self.on_system_command_result)
        self.worker.status_updated.connect(self.on_status_updated)

    def refresh_servo_ids(self):
        """刷新舵机ID列表"""
        self.servo_id_combo.clear()
        servos = []
        if self.worker:
            servos = sorted(self.worker.current_servos)
        if servos:
            for sid in servos:
                self.servo_id_combo.addItem(f"ID{sid}", sid)
        else:
            self.servo_id_combo.addItem(tr("无舵机"), None)
        self.update_button_states()

    def update_button_states(self):
        """根据是否有在线舵机更新按钮状态"""
        has_worker = self.worker is not None and self.worker.is_connected
        has_servos = has_worker and len(self.worker.current_servos) > 0
        enabled = has_servos and self.servo_id_combo.currentData() is not None

        self.read_btn.setEnabled(enabled)
        self.write_btn.setEnabled(enabled)
        self.baud_btn.setEnabled(enabled)
        self.reset_btn.setEnabled(enabled)

    def get_selected_servo_id(self):
        """获取选中的舵机ID"""
        return self.servo_id_combo.currentData()

    def add_log(self, message):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        self.adv_log_text.append(f"[{timestamp}] {message}")
        scrollbar = self.adv_log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_read_register(self):
        """读取寄存器"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, tr("警告"), tr("请先选择舵机"))
            return

        address = self.read_addr_spin.value()
        length = self.read_len_combo.currentData()

        self.read_result_label.setText(tr("结果: 读取中..."))
        self.worker.queue_system_command({
            "type": "register_read",
            "servo_id": servo_id,
            "address": address,
            "length": length,
            "desc": tr("读取 ID{} 寄存器 0x{:02X}").format(servo_id, address),
        })

    def on_write_register(self):
        """写入寄存器"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, tr("警告"), tr("请先选择舵机"))
            return

        address = self.write_addr_spin.value()
        length = self.write_len_combo.currentData()
        value = self.write_value_spin.value()

        reply = QMessageBox.question(
            self,
            tr("确认写入"),
            tr("确定要写入 ID{} 寄存器 0x{:02X} = {} ({}字节) 吗？").format(servo_id, address, value, length),
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
            "desc": tr("写入 ID{} 寄存器 0x{:02X}").format(servo_id, address),
        })

    def on_change_baud_rate(self):
        """修改波特率"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, tr("警告"), tr("请先选择舵机"))
            return

        new_baud = self.baud_combo.currentData()
        reply = QMessageBox.warning(
            self,
            tr("警告：修改波特率"),
            tr("修改波特率后，串口将立即切换到 {} bps。\n如果失败，工具会尝试恢复原有波特率。\n\n确定要修改 ID{} 的波特率吗？").format(new_baud, servo_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "baud_rate_change",
            "servo_id": servo_id,
            "baud_rate": new_baud,
            "desc": tr("修改 ID{} 波特率为 {}").format(servo_id, new_baud),
        })

    def on_factory_reset(self):
        """恢复出厂设置"""
        servo_id = self.get_selected_servo_id()
        if servo_id is None or self.worker is None:
            QMessageBox.warning(self, tr("警告"), tr("请先选择舵机"))
            return

        reply = QMessageBox.critical(
            self,
            tr("危险：恢复出厂设置"),
            tr("确定要恢复 ID{} 的出厂设置吗？\n\n这将导致：\n• 舵机 ID 变回 1\n• 波特率变回 1000000\n• 所有参数恢复默认值\n\n此操作不可撤销！").format(servo_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.worker.queue_system_command({
            "type": "factory_reset",
            "servo_id": servo_id,
            "desc": tr("恢复 ID{} 出厂设置").format(servo_id),
        })

    def on_register_read_result(self, servo_id, address, length, value, result, port_id):
        """处理寄存器读取结果"""
        if port_id != self.servo_panel.port_id:
            return
        if result == "读取成功":
            self.read_result_label.setText(
                tr("结果: {} (0x{:X})").format(value, value)
            )
            self.add_log(f"✅ ID{servo_id} 0x{address:02X} = {value} (0x{value:X})")
        else:
            self.read_result_label.setText(tr("结果: {}").format(result))
            self.add_log(f"❌ ID{servo_id} 0x{address:02X} {result}")

    def on_system_command_result(self, cmd_type, success, message, port_id):
        """处理系统命令结果"""
        if port_id != self.servo_panel.port_id:
            return
        prefix = "✅" if success else "❌"
        self.add_log(f"{prefix} {message}")
        if cmd_type in ("baud_rate_change", "factory_reset") and success:
            # 这些操作后需要重新扫描
            self.add_log(tr("🔄 请手动点击重新扫描以更新舵机列表"))

    def on_status_updated(self, servos, connected, port_id):
        """舵机列表变化时刷新ID选择"""
        if port_id != self.servo_panel.port_id:
            return
        self.refresh_servo_ids()


class EZToolUI(QMainWindow):
    """EZ Tool - 简化版双串口工厂舵机标定工具"""

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
        """停止串口自动刷新（例如校准时避免干扰）"""
        if hasattr(self, 'port_refresh_timer') and self.port_refresh_timer.isActive():
            self.port_refresh_timer.stop()

    def start_port_refresh(self):
        """恢复串口自动刷新"""
        if hasattr(self, 'port_refresh_timer') and not self.port_refresh_timer.isActive():
            self.port_refresh_timer.start(2000)

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle(tr("🏭 双串口工厂舵机标定工具"))
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
        title_label = QLabel(tr("🏭 双串口工厂舵机标定工具"))
        title_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(title_label)

        # 串口选择区域
        port_selection_group = QGroupBox(tr("串口选择"))
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
        left_label = QLabel(tr("串口1:"))
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
        right_label = QLabel(tr("串口2:"))
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
        refresh_btn.setToolTip(tr("刷新串口列表"))
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
        self.left_calib_btn = QPushButton(tr("串口1中位校准"))
        self.left_calib_btn.setMinimumSize(100, 35)
        self.left_calib_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4caf50, stop:1 #45a049);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
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
        self.left_test_btn = QPushButton(tr("串口1中位测试"))
        self.left_test_btn.setMinimumSize(100, 35)
        self.left_test_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2196f3, stop:1 #1976d2);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
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
        self.left_disable_btn = QPushButton(tr("串口1失能电机"))
        self.left_disable_btn.setMinimumSize(100, 35)
        self.left_disable_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff9800, stop:1 #f57c00);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
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
        self.right_calib_btn = QPushButton(tr("串口2中位校准"))
        self.right_calib_btn.setMinimumSize(100, 35)
        self.right_calib_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4caf50, stop:1 #45a049);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
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
        self.right_test_btn = QPushButton(tr("串口2中位测试"))
        self.right_test_btn.setMinimumSize(100, 35)
        self.right_test_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2196f3, stop:1 #1976d2);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
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
        self.right_disable_btn = QPushButton(tr("串口2失能电机"))
        self.right_disable_btn.setMinimumSize(100, 35)
        self.right_disable_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff9800, stop:1 #f57c00);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
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

        # 按钮不允许压缩到 sizeHint 以下，避免英文长文本被截断（窗口最小宽度随布局自适应）
        # 同时把样式表中的 11px 加粗字体同步到 widget，确保 sizeHint 按真实字体计算宽度
        for _i in range(buttons_row.count()):
            _w = buttons_row.itemAt(_i).widget()
            if isinstance(_w, QPushButton):
                _font = _w.font()
                _font.setPointSize(11)
                _font.setBold(True)
                _w.setFont(_font)
                _w.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

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
        self.status_bar.showMessage(tr("双串口系统已启动 - 左右独立操作 + 中间值校准"))

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

        self.tab_widget.addTab(servo_tab, tr("🦾 舵机标定"))

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
        self.tab_widget.addTab(single_control_tab, tr("🎚️ 单舵机控制"))

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
        self.tab_widget.addTab(advanced_tab, tr("🔧 高级工具"))

        # 设置整体样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f8f9fa;
            }
        """)

    @staticmethod
    def _wrap_in_scroll_area(widget):
        """把面板包进滚动区域：窗口高度不足时显示滚动条，
        避免布局被过度压缩导致控件（如ID标定1-6按钮）相互重叠"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def init_connections(self):
        """初始化信号连接"""
        # 添加初始日志
        self.status_bar.showMessage(tr("双串口系统已启动 - 左右独立操作 + 中间值校准"), 3000)

    def toggle_remote_control(self):
        """切换遥控操作"""
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
        """启动遥控操作"""
        # 停止现有的舵机标定操作，避免端口冲突
        if self.left_panel.worker.is_connected:
            self.left_panel.worker.stop()
        if self.right_panel.worker.is_connected:
            self.right_panel.worker.stop()

        # 启动遥控操作
        success, message = self.remote_worker.start_remote_control()

        if success:
            self.remote_btn.setText(tr("⏹️ 停止"))
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
            self.status_bar.showMessage(tr("遥控操作已启动 - {}读取，{}控制").format(self.left_port, self.right_port), 5000)
        else:
            self.add_remote_log(f"❌ {message}")
            QMessageBox.critical(self, tr("启动失败"), tr("无法启动遥控操作:\n{}").format(message))

    def stop_remote_control(self):
        """停止遥控操作"""
        if self.remote_worker is None:
            return False

        success, message = self.remote_worker.stop_remote_control()

        if success:
            self.remote_btn.setText(tr("🎮 遥控"))
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
            self.status_bar.showMessage(tr("遥控操作已停止"), 3000)

            # 重新启动舵机标定操作
            self.left_panel.worker.start()
            self.right_panel.worker.start()
        else:
            self.add_remote_log(f"❌ {message}")

    def _begin_tool_action(self, port_name: str) -> int:
        """开始一个串口工具操作（校准/中位测试/失能）。

        递增该端口的操作代次，并终止该端口上一个仍在运行的工具子进程，
        保证新操作一定能拿到串口（Windows 下串口独占，旧进程不释放就会 PermissionError）。
        返回本次操作的代次号。
        """
        gen = self._tool_gen.get(port_name, 0) + 1
        self._tool_gen[port_name] = gen

        proc = self._tool_procs.get(port_name)
        if proc is not None and proc.poll() is None:
            self.add_remote_log(tr("⏹️ 终止{}上一个仍在运行的工具进程，释放串口...").format(port_name))
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
        """判断本次操作是否仍是该端口最新的操作（被新操作取代的旧线程不应再恢复扫描线程）"""
        return self._tool_gen.get(port_name) == gen

    def _register_tool_process(self, port_name: str, process):
        """登记该端口当前运行的工具子进程"""
        self._tool_procs[port_name] = process

    def _tool_panel_log(self, port_name: str, message: str):
        """把工具执行结果写到对应面板的操作日志（经 worker 信号转发，线程安全），
        避免失败信息只在状态栏一闪而过导致用户以为"没反应\""""
        panel = self.left_panel if port_name == self.left_port else self.right_panel
        try:
            if panel is not None and panel.worker is not None:
                panel.worker.log_message.emit(message, panel.port_id)
        except Exception:
            pass

    def run_quick_calibration(self, port_name: str):
        """快速中位校准 - 非阻塞执行"""
        self.add_remote_log(tr("🔧 开始{}快速中位校准...").format(port_name))
        self.status_bar.showMessage(tr("正在执行{}中位校准...").format(port_name), 5000)

        # 先终止该端口上一个仍在运行的工具进程，确保能拿到串口
        gen = self._begin_tool_action(port_name)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker.is_connected:
            self.add_remote_log(tr("⏸️ 已停止{}扫描线程，准备校准").format(port_name))
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker.is_connected:
            self.add_remote_log(tr("⏸️ 已停止{}扫描线程，准备校准").format(port_name))
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        # 使用线程非阻塞执行
        from threading import Thread
        thread = Thread(target=self._execute_quick_calibration, args=(port_name, gen))
        thread.daemon = True
        thread.start()

        self.add_remote_log(tr("📝 {}校准进程已启动，请等待执行完成").format(port_name))

    def _execute_quick_calibration(self, port_name: str, gen: int):
        """执行快速中位校准的线程函数"""
        try:
            self.add_remote_log(tr("🔍 查找校准脚本..."))
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk

            # 检查使用哪个脚本
            tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools')
            quick_script = os.path.join(tools_dir, 'servo_quick_calibration.py')

            if os.path.exists(quick_script):
                self.add_remote_log(tr("✅ 找到校准脚本: servo_quick_calibration.py"))
                command = [sys.executable, '-m', 'src.tools.servo_quick_calibration', port_name]
            else:
                self.add_remote_log(tr("⚠️ 未找到servo_quick_calibration.py，使用servo_middle_calibration.py"))
                command = [sys.executable, '-m', 'src.tools.servo_middle_calibration', port_name, "2"]  # 使用自动模式

            self.add_remote_log(tr("🚀 启动校准进程: {}").format(' '.join(command)))

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
            important_keywords = ["连接", "扫描", "校准", "完成", "失败", "错误", "成功", "发现",
                                  "Connect", "Scan", "Calibrat", "Complet", "Done", "Fail", "Error",
                                  "Success", "Found", "Detect", "Disabl", "Torque", "Rotat", "Cannot open"]
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
                self.add_remote_log(tr("ℹ️ {}中位校准已被新操作中断/取代").format(port_name))
                return
            if return_code == 0:
                self.add_remote_log(tr("✅ {}中位校准完成 - 进程正常退出").format(port_name))
                self._tool_panel_log(port_name, tr("✅ {}中位校准完成").format(port_name))
                self.status_bar.showMessage(tr("{}校准完成").format(port_name), 3000)
            else:
                self.add_remote_log(tr("❌ {}中位校准失败 - 退出码: {}").format(port_name, return_code))
                self._tool_panel_log(port_name, tr("❌ {}中位校准失败 - 退出码: {}").format(port_name, return_code))
                self.status_bar.showMessage(tr("{}校准失败").format(port_name), 3000)

            # 重新启动相应端口的扫描线程
            self.add_remote_log(tr("⏳ 等待端口释放..."))
            import time
            time.sleep(1.0)  # 增加等待时间确保端口完全释放

            if port_name == self.left_port:
                self.left_panel.worker.start()
                self.add_remote_log(tr("▶️ 已重新启动{}扫描线程").format(port_name))
            elif port_name == self.right_port:
                self.right_panel.worker.start()
                self.add_remote_log(tr("▶️ 已重新启动{}扫描线程").format(port_name))

        except Exception as e:
            self._tool_procs.pop(port_name, None)
            self.add_remote_log(tr("❌ {}校准异常: {}").format(port_name, e))
            self._tool_panel_log(port_name, tr("❌ {}校准异常: {}").format(port_name, e))
            self.status_bar.showMessage(tr("{}校准异常: {}").format(port_name, e), 3000)
            # 即使出现异常也要尝试重新启动扫描线程（被新操作取代时除外）
            if not self._is_latest_tool_action(port_name, gen):
                return
            try:
                import time
                time.sleep(1.0)
                if port_name == self.left_port:
                    self.left_panel.worker.start()
                    self.add_remote_log(tr("🔄 异常后重启{}扫描线程").format(port_name))
                elif port_name == self.right_port:
                    self.right_panel.worker.start()
                    self.add_remote_log(tr("🔄 异常后重启{}扫描线程").format(port_name))
            except:
                self.add_remote_log(tr("⚠️ 重启{}扫描线程失败").format(port_name))

    def run_quick_test(self, port_name: str):
        """快速中位测试 - 非阻塞执行"""
        self.add_remote_log(tr("🧪 开始{}中位测试...").format(port_name))
        self.status_bar.showMessage(tr("正在执行{}中位测试...").format(port_name), 5000)

        # 先终止该端口上一个仍在运行的工具进程，确保能拿到串口
        gen = self._begin_tool_action(port_name)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker.is_connected:
            self.add_remote_log(tr("⏸️ 已停止{}扫描线程，准备测试").format(port_name))
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker.is_connected:
            self.add_remote_log(tr("⏸️ 已停止{}扫描线程，准备测试").format(port_name))
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        from threading import Thread
        thread = Thread(target=self._execute_quick_test, args=(port_name, gen))
        thread.daemon = True
        thread.start()

        self.add_remote_log(tr("📝 {}测试进程已启动，请等待执行完成").format(port_name))

    def _execute_quick_test(self, port_name: str, gen: int):
        """执行快速中位测试的线程函数"""
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
                self.add_remote_log(tr("ℹ️ {}中位测试已被新操作中断/取代").format(port_name))
                return
            if return_code == 0:
                self.add_remote_log(tr("✅ {}中位测试完成").format(port_name))
                self._tool_panel_log(port_name, tr("✅ {}中位测试完成（力矩保持开启，点“失能电机”可松开）").format(port_name))
            else:
                self.add_remote_log(tr("❌ {}中位测试失败").format(port_name))
                self._tool_panel_log(port_name, tr("❌ {}中位测试失败 - 退出码: {}").format(port_name, return_code))

            # 重新启动相应端口的扫描线程
            import time
            time.sleep(0.5)  # 等待端口完全释放

            if port_name == self.left_port:
                self.left_panel.worker.start()
                self.add_remote_log(tr("▶️ 已重新启动{}扫描线程").format(port_name))
            elif port_name == self.right_port:
                self.right_panel.worker.start()
                self.add_remote_log(tr("▶️ 已重新启动{}扫描线程").format(port_name))

        except Exception as e:
            self._tool_procs.pop(port_name, None)
            self.add_remote_log(tr("❌ {}测试异常: {}").format(port_name, e))
            self._tool_panel_log(port_name, tr("❌ {}测试异常: {}").format(port_name, e))
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
        """快速失能电机 - 非阻塞执行"""
        self.add_remote_log(tr("⏹️ 开始{}失能电机...").format(port_name))
        self.status_bar.showMessage(tr("正在执行{}失能电机...").format(port_name), 5000)

        # 先终止该端口上一个仍在运行的工具进程（如中位测试），确保能拿到串口。
        # 否则 Windows 串口独占会让失能进程打不开端口，表现为"点失能没反应"
        gen = self._begin_tool_action(port_name)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker and self.left_panel.worker.is_connected:
            self.add_remote_log(tr("⏸️ 已停止{}扫描线程，准备失能").format(port_name))
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker and self.right_panel.worker.is_connected:
            self.add_remote_log(tr("⏸️ 已停止{}扫描线程，准备失能").format(port_name))
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        from threading import Thread
        thread = Thread(target=self._execute_quick_disable, args=(port_name, gen))
        thread.daemon = True
        thread.start()

        self.add_remote_log(tr("📝 {}失能进程已启动，请等待执行完成").format(port_name))

    def _execute_quick_disable(self, port_name: str, gen: int):
        """执行快速失能电机的线程函数"""
        try:
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk
            command = [sys.executable, '-m', 'src.tools.servo_disable', port_name]

            self.add_remote_log(tr("🚀 启动失能进程: {}").format(' '.join(command)))
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
            important_keywords = ["连接", "扫描", "失能", "完成", "失败", "错误", "成功", "发现", "扭矩", "旋转",
                                  "Connect", "Scan", "Calibrat", "Complet", "Done", "Fail", "Error",
                                  "Success", "Found", "Detect", "Disabl", "Torque", "Rotat", "Cannot open"]
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
                            if "❌" in line or "无法打开" in line or "错误" in line or "Cannot open" in line or "Error" in line or "Fail" in line:
                                self._tool_panel_log(port_name, line)
                except:
                    break

            return_code = process.wait()
            self._tool_procs.pop(port_name, None)
            if not self._is_latest_tool_action(port_name, gen):
                self.add_remote_log(tr("ℹ️ {}失能操作已被新操作中断/取代").format(port_name))
                return
            if return_code == 0:
                self.add_remote_log(tr("✅ {}电机已失能，可手动旋转").format(port_name))
                self._tool_panel_log(port_name, tr("✅ {}电机已失能，可手动旋转").format(port_name))
                self.status_bar.showMessage(tr("{}失能完成").format(port_name), 3000)
            else:
                self.add_remote_log(tr("❌ {}失能失败 - 退出码: {}").format(port_name, return_code))
                self._tool_panel_log(port_name, tr("❌ {}失能失败 - 退出码: {}，请重试").format(port_name, return_code))
                self.status_bar.showMessage(tr("{}失能失败").format(port_name), 3000)

            # 重新启动相应端口的扫描线程
            import time
            time.sleep(0.5)  # 等待端口完全释放

            if port_name == self.left_port and self.left_panel.worker:
                self.left_panel.worker.start()
                self.add_remote_log(tr("▶️ 已重新启动{}扫描线程").format(port_name))
            elif port_name == self.right_port and self.right_panel.worker:
                self.right_panel.worker.start()
                self.add_remote_log(tr("▶️ 已重新启动{}扫描线程").format(port_name))

        except Exception as e:
            self._tool_procs.pop(port_name, None)
            self.add_remote_log(tr("❌ {}失能异常: {}").format(port_name, e))
            self._tool_panel_log(port_name, tr("❌ {}失能异常: {}").format(port_name, e))
            self.status_bar.showMessage(tr("{}失能异常: {}").format(port_name, e), 3000)
            # 即使出现异常也要尝试重新启动扫描线程（被新操作取代时除外）
            if not self._is_latest_tool_action(port_name, gen):
                return
            try:
                import time
                time.sleep(0.5)
                if port_name == self.left_port and self.left_panel.worker:
                    self.left_panel.worker.start()
                    self.add_remote_log(tr("🔄 异常后重启{}扫描线程").format(port_name))
                elif port_name == self.right_port and self.right_panel.worker:
                    self.right_panel.worker.start()
                    self.add_remote_log(tr("🔄 异常后重启{}扫描线程").format(port_name))
            except:
                pass

    def add_remote_log(self, message):
        """添加遥控日志"""
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[REMOTE] {message}"
        try:
            print(f"[REMOTE] {log_entry}")
        except UnicodeEncodeError:
            # GBK 控制台下 emoji 无法编码，降级为可显示字符，避免整个按钮动作被异常打断
            print(f"[REMOTE] {log_entry.encode('gbk', 'replace').decode('gbk')}")
        self.status_bar.showMessage(tr("遥控: {}").format(message), 3000)

    def on_remote_started(self):
        """遥控启动回调"""
        pass

    def on_remote_stopped(self):
        """遥控停止回调"""
        pass

    def refresh_ports(self):
        """刷新可用串口列表"""
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
                        f"[DEBUG] 左右端口冲突，已禁用右端口: "
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

            self.status_bar.showMessage(tr("串口列表已刷新 - 发现 {} 个串口").format(len(self.available_ports)), 3000)

        except Exception as e:
            print(f"[DEBUG] Refresh ports error: {e}")
            self.status_bar.showMessage(tr("刷新串口列表失败: {}").format(e), 3000)

    def on_left_port_changed(self, port_name):
        """左串口选择改变"""
        if port_name == self.left_port or (
            not self.left_port and port_name == ServoPanel.DISABLED_PORT
        ):
            return

        # 检查是否与右端口冲突
        if port_name != ServoPanel.DISABLED_PORT and port_name == self.right_port:
            QMessageBox.warning(
                self, tr("端口冲突"),
                tr("串口2 已经在使用 {}，不能重复选择同一串口。").format(port_name)
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
            self.left_panel.connection_status.setText(tr("⚫ 已禁用"))
            self.left_panel.worker = None
            # 清空舵机列表显示，避免拔掉设备后仍显示旧数据
            self.left_panel.update_status([], False, self.left_panel.port_id)
            self.status_bar.showMessage(tr("串口1已禁用"), 3000)
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

        self.status_bar.showMessage(tr("串口1已切换到: {}").format(port_name), 3000)

    def on_right_port_changed(self, port_name):
        """右串口选择改变"""
        if port_name == self.right_port or (
            not self.right_port and port_name == ServoPanel.DISABLED_PORT
        ):
            return

        # 检查是否与左端口冲突
        if port_name != ServoPanel.DISABLED_PORT and port_name == self.left_port:
            QMessageBox.warning(
                self, tr("端口冲突"),
                tr("串口1 已经在使用 {}，不能重复选择同一串口。").format(port_name)
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
            self.right_panel.connection_status.setText(tr("⚫ 已禁用"))
            self.right_panel.worker = None
            # 清空舵机列表显示，避免拔掉设备后仍显示旧数据
            self.right_panel.update_status([], False, self.right_panel.port_id)
            self.status_bar.showMessage(tr("串口2已禁用"), 3000)
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

        self.status_bar.showMessage(tr("串口2已切换到: {}").format(port_name), 3000)

    def run_quick_calibration_left(self):
        """串口1快速中位校准"""
        self.run_quick_calibration(self.left_port)

    def run_quick_test_left(self):
        """串口1快速中位测试"""
        self.run_quick_test(self.left_port)

    def run_quick_disable_left(self):
        """串口1快速失能电机"""
        self.run_quick_disable(self.left_port)

    def run_quick_calibration_right(self):
        """串口2快速中位校准"""
        self.run_quick_calibration(self.right_port)

    def run_quick_test_right(self):
        """串口2快速中位测试"""
        self.run_quick_test(self.right_port)

    def run_quick_disable_right(self):
        """串口2快速失能电机"""
        self.run_quick_disable(self.right_port)

    def closeEvent(self, event):
        """关闭事件"""
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
    """获取可用串口列表 - 使用 port_utils 中已过滤的端口"""
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
    """主函数"""
    import platform
    import argparse

    # Windows 下子进程默认可能使用 GBK 编码，导致脚本里的 emoji 输出报错。
    # 强制子进程使用 utf-8 编码标准输出。
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # 解析命令行参数
    parser = argparse.ArgumentParser(description=tr('双串口工厂舵机标定工具'))
    parser.add_argument('--port1', type=str, help=tr('指定串口1 (例如: COM1 或 /dev/ttyUSB0)'))
    parser.add_argument('--port2', type=str, help=tr('指定串口2 (例如: COM2 或 /dev/ttyUSB1)'))
    parser.add_argument('--list-ports', action='store_true', help=tr('列出可用串口并退出'))
    parser.add_argument('--lang', choices=['zh', 'en'], default=None,
                        help=tr('界面语言 (zh=中文, en=English)，不指定则启动时选择'))
    args = parser.parse_args()

    # 如果只是列出串口
    if args.list_ports:
        try:
            available_ports = get_available_ports()
            print(tr("可用串口列表:"))
            for i, port in enumerate(available_ports, 1):
                print(f"  {i}. {port}")
            if not available_ports:
                print(tr("  未发现可用串口"))
        except Exception as e:
            print(tr("获取串口列表失败: {}").format(e))
        return

    app = QApplication(sys.argv)

    # 设置 Ctrl+C 信号处理，使其能正常关闭 Qt 应用
    import signal

    def handle_sigint(signum, frame):
        print(tr("\n收到 Ctrl+C，正在关闭..."))
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

    # 语言选择：--lang 指定时直接使用，否则弹出选择对话框
    if args.lang:
        set_lang(args.lang)
    else:
        from src.gui.language_dialog import choose_language
        set_lang(choose_language())

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

    print(tr("启动双串口工厂舵机标定工具"))
    print(tr("系统: {}").format(system))
    print(tr("串口1: {}").format(left_port))
    print(tr("串口2: {}").format(right_port))

    # 检查可用端口
    try:
        available_ports = get_available_ports()
        print(tr("检测到的可用串口: {}").format(available_ports))

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
                    print(tr("使用首选端口: {}, {}").format(left_port, right_port))
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
                    print(tr("使用混合端口配置: {}, {}").format(left_port, right_port))
                # 没有找到首选端口
                elif not args.port1 and not args.port2:
                    left_port, right_port = available_ports[0], available_ports[1]
                    print(tr("使用前两个可用端口: {}, {}").format(left_port, right_port))

            elif len(available_ports) == 1:
                if not args.port1:
                    left_port = available_ports[0]
                if not args.port2:
                    right_port = None  # 只有一个真实串口，禁用右端口避免冲突
                print(tr("只有一个可用端口: {}, 备用端口: {}").format(available_ports[0], right_port if right_port else tr('禁用')))
            else:
                print(tr("未发现可用串口，使用默认配置"))

    except Exception as e:
        print(tr("检查可用端口时出错: {}").format(e))

    # 创建并显示主窗口
    window = EZToolUI(left_port, right_port)
    window.show()

    print(tr("UI界面已启动"))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()