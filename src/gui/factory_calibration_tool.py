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
    QTabWidget, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import QTimer, Signal, QObject, Qt
from PySide6.QtGui import QFont, QPalette, QColor, QTextCursor

from scservo_sdk.port_handler import PortHandler
from scservo_sdk.sms_sts import sms_sts
from scservo_sdk.scservo_def import COMM_SUCCESS

# 引入端口工具
try:
    from src.port_utils import get_default_port, get_available_ports
    PORT_UTILS_AVAILABLE = True
except ImportError:
    PORT_UTILS_AVAILABLE = False
    print("Warning: port_utils not found, using fallback port detection")

# 引入 LeRobot 校准文件管理器
try:
    from src.calibration_manager import CalibrationManager, JOINT_NAME_MAP
    from src.gui.calibration_wizard import CalibrationWizard
    CALIBRATION_MANAGER_AVAILABLE = True
except ImportError:
    CALIBRATION_MANAGER_AVAILABLE = False
    print("Warning: calibration_manager not found, calibration file view disabled")


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
            return False, "遥控操作已在运行"

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
                bufsize=1,
                cwd=self.project_root
            )

            self.running = True
            self.log_message.emit("🚀 遥控操作已启动 (10ms更新间隔)")
            self.control_started.emit()

            # 启动监控线程
            threading.Thread(target=self._monitor_process, daemon=True).start()

            return True, "遥控操作启动成功"

        except Exception as e:
            return False, f"启动遥控操作失败: {e}"

    def stop_remote_control(self):
        """停止遥控操作"""
        if not self.running:
            return False, "遥控操作未运行"

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
            self.log_message.emit("⏹️ 遥控操作已停止")
            self.control_stopped.emit()
            return True, "遥控操作停止成功"

        except Exception as e:
            return False, f"停止遥控操作失败: {e}"

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
                        self.log_message.emit(f"遥控: {line}")
                time.sleep(0.1)

            # 进程结束
            if self.remote_process.poll() is not None:
                self.running = False
                self.remote_process = None
                self.log_message.emit("🔚 遥控进程已结束")
                self.control_stopped.emit()

        except Exception as e:
            self.log_message.emit(f"监控遥控进程异常: {e}")
            self.running = False
            self.control_stopped.emit()


class IDChangeDialog(QDialog):
    """修改舵机ID对话框 - 允许用户自定义源ID和目标ID"""

    def __init__(self, current_servos, default_old_id=None, default_new_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("修改舵机ID")
        self.setMinimumWidth(280)

        layout = QFormLayout(self)

        # 源ID（下拉选择当前在线的舵机）
        self.old_id_combo = QComboBox()
        for servo_id in sorted(current_servos):
            self.old_id_combo.addItem(f"舵机 ID {servo_id}", servo_id)
        if default_old_id and default_old_id in current_servos:
            index = self.old_id_combo.findData(default_old_id)
            if index >= 0:
                self.old_id_combo.setCurrentIndex(index)
        layout.addRow("源舵机ID:", self.old_id_combo)

        # 目标ID（数字输入）
        self.new_id_input = QSpinBox()
        self.new_id_input.setRange(1, 253)
        if default_new_id:
            self.new_id_input.setValue(default_new_id)
        else:
            self.new_id_input.setValue(1)
        layout.addRow("修改ID为:", self.new_id_input)

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

    def __init__(self, port_name: str, port_id: str):
        super().__init__()
        self.port_name = port_name
        self.port_id = port_id  # 端口标识 (left/right)
        self.port_handler = None
        self.servo_handler = None
        self.is_connected = False
        self.current_servos = []
        self.running = False

        # 连接配置
        self.baud_rate = 1000000

        # ID修改队列
        self.id_change_queue = Queue()
        self.id_change_thread = None
        self.id_change_running = False

        # 扫描控制
        self.pause_scanning = False  # 是否暂停扫描
        self.rescan_requested = threading.Event()  # 手动重新扫描请求

    def request_rescan(self):
        """请求立即重新扫描"""
        self.rescan_requested.set()
        self.log_message.emit("🔄 收到重新扫描请求", self.port_id)

    def connect_servo(self) -> bool:
        """连接舵机控制器"""
        try:
            print(f"[DEBUG] {self.port_id}: Attempting to connect to {self.port_name}")
            self.log_message.emit(f"正在连接舵机控制器: {self.port_name}", self.port_id)
            self.port_handler = PortHandler(self.port_name)

            if not self.port_handler.openPort():
                print(f"[DEBUG] {self.port_id}: Failed to open port {self.port_name}")
                self.log_message.emit(f"❌ 无法打开串口: {self.port_name}", self.port_id)
                return False

            if not self.port_handler.setBaudRate(self.baud_rate):
                print(f"[DEBUG] {self.port_id}: Failed to set baud rate {self.baud_rate}")
                self.log_message.emit(f"❌ 无法设置波特率: {self.baud_rate}", self.port_id)
                self.port_handler.closePort()
                return False

            self.servo_handler = sms_sts(self.port_handler)
            self.is_connected = True
            print(f"[DEBUG] {self.port_id}: Successfully connected to {self.port_name}")
            self.log_message.emit("✅ 舵机控制器连接成功", self.port_id)
            return True

        except Exception as e:
            print(f"[DEBUG] {self.port_id}: Connection exception: {e}")
            self.log_message.emit(f"❌ 连接失败: {e}", self.port_id)
            return False

    def disconnect_servo(self):
        """断开舵机连接"""
        try:
            if self.port_handler:
                self.port_handler.closePort()
                self.is_connected = False
                self.log_message.emit("🔌 舵机控制器已断开", self.port_id)
        except:
            pass

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

        found_servos = []
        for servo_id in range(1, 21):  # 扫描 ID 1-20，与命令行工具保持一致
            if self.ping_servo(servo_id):
                found_servos.append(servo_id)

        return found_servos

    def change_servo_id(self, old_id: int, new_id: int) -> (bool, str):
        """修改舵机ID（队列版本）"""
        # 将请求加入队列
        self.queue_id_change(old_id, new_id)
        return True, "ID修改请求已加入队列"

    def queue_id_change(self, old_id: int, new_id: int):
        """将ID修改请求加入队列"""
        print(f"[DEBUG] {self.port_id}: ID修改请求入队: {old_id} -> {new_id}")
        self.log_message.emit(f"📝 ID修改请求已排队: {old_id} -> {new_id}", self.port_id)
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
                    self.log_message.emit(f"⏸️ 暂停扫描，执行ID修改: {old_id} -> {new_id}", self.port_id)

                    # 等待一下确保扫描完全停止
                    time.sleep(0.5)

                    # 执行ID修改
                    success, message = self.execute_id_change(old_id, new_id)

                    # 恢复扫描
                    self.pause_scanning = False
                    print(f"[DEBUG] {self.port_id}: 恢复扫描")
                    self.log_message.emit(f"▶️ 恢复扫描", self.port_id)

                    # 发送结果
                    self.id_changed.emit(old_id, new_id, success, message, self.port_id)

                else:
                    time.sleep(0.1)  # 短暂休眠避免CPU占用

            except Exception as e:
                print(f"[DEBUG] {self.port_id}: ID修改处理异常: {e}")
                self.log_message.emit(f"❌ ID修改处理异常: {e}", self.port_id)
                # 确保扫描被恢复
                self.pause_scanning = False

        print(f"[DEBUG] {self.port_id}: ID修改处理线程结束")
        self.id_change_running = False
        self.pause_scanning = False

    def execute_id_change(self, old_id: int, new_id: int) -> (bool, str):
        """执行实际的ID修改操作"""
        try:
            if not self.is_connected:
                return False, "未连接舵机控制器"

            self.log_message.emit(f"🔧 执行SMS_STS ID修改: {old_id} -> {new_id}", self.port_id)
            print(f"[DEBUG] {self.port_id}: 执行ID修改: {old_id} -> {new_id}")

            # 首先读取舵机信息（此时扫描已暂停，不会冲突）
            try:
                model_number, result, error = self.servo_handler.ping(old_id)
                if result == COMM_SUCCESS:
                    print(f"[DEBUG] {self.port_id}: SMS_STS 舵机型号: {model_number}")
                    self.log_message.emit(f"📋 舵机型号: {model_number}", self.port_id)
                else:
                    print(f"[DEBUG] {self.port_id}: 无法读取舵机信息: {error}")
                    return False, f"无法读取舵机信息: {error}"
            except Exception as e:
                return False, f"读取舵机信息异常: {e}"

            # SMS_STS EEPROM解锁流程
            print(f"[DEBUG] {self.port_id}: SMS_STS 解锁EEPROM...")
            result, error = self.servo_handler.unLockEprom(old_id)
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: EEPROM解锁失败: result={result}, error={error}")
                return False, f"EEPROM解锁失败: {error}"

            print(f"[DEBUG] {self.port_id}: EEPROM解锁成功")
            time.sleep(0.1)

            # 修改ID (使用SMS_STS_ID地址)
            print(f"[DEBUG] {self.port_id}: 写入新ID: {new_id}")
            result, error = self.servo_handler.write1ByteTxRx(old_id, 5, new_id)  # SMS_STS_ID = 5
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: ID写入失败: result={result}, error={error}")
                return False, f"ID写入失败: {error}"

            print(f"[DEBUG] {self.port_id}: ID写入成功")
            time.sleep(0.3)

            # 验证新ID（此时扫描仍暂停，ping不会冲突）
            print(f"[DEBUG] {self.port_id}: 验证新ID: {new_id}")
            if not self.ping_servo(new_id):
                print(f"[DEBUG] {self.port_id}: 新ID验证失败")
                return False, f"验证失败，无法ping通新ID: {new_id}"

            print(f"[DEBUG] {self.port_id}: 新ID验证成功")

            # 重新锁定EEPROM
            print(f"[DEBUG] {self.port_id}: 重新锁定EEPROM...")
            result, error = self.servo_handler.LockEprom(new_id)
            if result != COMM_SUCCESS:
                print(f"[DEBUG] {self.port_id}: 重新锁定失败: {error}")
                self.log_message.emit(f"⚠️ 重新锁定EEPROM失败: {error}", self.port_id)
            else:
                print(f"[DEBUG] {self.port_id}: 重新锁定成功")

            self.log_message.emit(f"✅ SMS_STS ID修改成功: {old_id} -> {new_id}", self.port_id)
            print(f"[DEBUG] {self.port_id}: ID修改完成: {old_id} -> {new_id}")
            return True, ""

        except Exception as e:
            error_msg = f"修改ID异常: {e}"
            print(f"[DEBUG] {self.port_id}: 修改ID异常: {e}")
            self.log_message.emit(f"❌ {error_msg}", self.port_id)
            return False, error_msg

    def run_scanner(self):
        """运行扫描循环"""
        scan_count = 0
        self.running = True
        consecutive_failures = 0
        max_failures = 3

        self.log_message.emit("🚀 扫描线程启动", self.port_id)
        print(f"[DEBUG] {self.port_id}: Scanner thread started")

        # 首次连接
        if not self.is_connected:
            self.connect_servo()

        while self.running:
            try:
                scan_count += 1

                # 如果未连接，尝试重新连接
                if not self.is_connected:
                    if consecutive_failures < max_failures:
                        self.log_message.emit(f"🔄 尝试重新连接... (第{consecutive_failures + 1}次)", self.port_id)
                        time.sleep(2)  # 等待2秒再重试
                        if self.connect_servo():
                            consecutive_failures = 0  # 重置失败计数
                        else:
                            consecutive_failures += 1
                        continue
                    else:
                        # 失败次数过多，延长等待时间
                        self.log_message.emit(f"⚠️ 连续失败{max_failures}次，等待10秒后重试...", self.port_id)
                        time.sleep(10)
                        consecutive_failures = 0  # 重置计数
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
                    self.log_message.emit("🔄 执行手动重新扫描...", self.port_id)

                # 扫描舵机
                new_servos = self.scan_servos()
                print(f"[DEBUG] {self.port_id}: Scan result: {new_servos}, current: {self.current_servos}")

                # 如果扫描成功，重置失败计数
                if new_servos is not None:
                    consecutive_failures = 0

                    # 如果舵机列表有变化
                    if new_servos != self.current_servos:
                        old_servos = self.current_servos.copy() if self.current_servos else []
                        self.current_servos = new_servos

                        if new_servos:
                            if not old_servos:
                                self.log_message.emit(f"📡 发现舵机: {new_servos}", self.port_id)
                            else:
                                added = set(new_servos) - set(old_servos)
                                removed = set(old_servos) - set(new_servos)
                                changes = []
                                if added:
                                    changes.append(f"新增: {list(added)}")
                                if removed:
                                    changes.append(f"移除: {list(removed)}")
                                self.log_message.emit(f"📡 舵机变化: {', '.join(changes)}", self.port_id)
                        else:
                            if old_servos:
                                self.log_message.emit("📡 所有舵机已断开", self.port_id)

                        print(f"[DEBUG] {self.port_id}: Emitting status_updated: servos={new_servos}, connected={self.is_connected}")
                        self.status_updated.emit(self.current_servos, self.is_connected, self.port_id)

                # 每30次扫描显示一次状态（减少日志频率）
                if scan_count % 30 == 0:
                    if self.current_servos:
                        self.log_message.emit(f"📊 当前舵机ID: {self.current_servos}", self.port_id)
                    else:
                        self.log_message.emit("📊 当前无舵机", self.port_id)

                # 使用 Event.wait 等待，允许手动重新扫描立即中断等待
                self.rescan_requested.wait(timeout=1.0)  # 扫描间隔

            except Exception as e:
                consecutive_failures += 1
                self.log_message.emit(f"❌ 扫描异常: {e} (失败次数: {consecutive_failures})", self.port_id)
                # 不要立即断开连接，给下次重试机会
                time.sleep(1)

    def start(self):
        """启动工作线程"""
        if not self.running:
            self.running = True
            threading.Thread(target=self.run_scanner, daemon=True).start()

    def stop(self):
        """停止工作线程"""
        self.running = False
        self.id_change_running = False
        self.disconnect_servo()

        # 等待ID修改线程结束
        if self.id_change_thread and self.id_change_thread.is_alive():
            self.id_change_thread.join(timeout=2)


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
            self.title_label.setText(f"🏭 {self.DISABLED_PORT} - 舵机标定")
            self.connection_status.setText("⚫ 已禁用")

    def init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        self.title_label = QLabel(f"🏭 {self.port_name} - 舵机标定")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50; margin: 5px;")
        layout.addWidget(self.title_label)

        # 状态面板
        self.create_status_panel(layout)

        # 舵机状态面板
        self.create_servo_panel(layout)

        # 标定面板
        self.create_calibration_panel(layout)

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
        status_group = QGroupBox("📡 系统状态")
        status_layout = QHBoxLayout()
        status_group.setLayout(status_layout)

        # 连接状态
        self.connection_status = QLabel("🔴 未连接")
        self.connection_status.setStyleSheet("font-size: 12px; font-weight: bold;")
        status_layout.addWidget(self.connection_status)

        status_layout.addStretch()

        # 当前舵机
        self.current_servos_label = QLabel("当前舵机: 扫描中...")
        self.current_servos_label.setStyleSheet("font-size: 12px;")
        status_layout.addWidget(self.current_servos_label)

        status_layout.addSpacing(15)

        # 重新扫描按钮
        self.rescan_btn = QPushButton("🔄 重新扫描")
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
        self.rescan_btn.setToolTip("立即重新扫描舵机")
        self.rescan_btn.clicked.connect(self.request_rescan)
        status_layout.addWidget(self.rescan_btn)

        layout.addWidget(status_group)

    def create_servo_panel(self, layout):
        """创建舵机状态面板"""
        servo_group = QGroupBox("📡 舵机状态")
        servo_layout = QVBoxLayout()
        servo_group.setLayout(servo_layout)

        # 左右并列布局
        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(10)

        # 左侧：发现的舵机
        found_layout = QVBoxLayout()
        found_label = QLabel("✅ 发现的舵机")
        found_label.setStyleSheet("font-weight: bold; color: #28a745; font-size: 12px;")
        found_layout.addWidget(found_label)

        self.servo_list_found = QTextEdit()
        self.servo_list_found.setReadOnly(True)
        self.servo_list_found.setMaximumHeight(150)
        self.servo_list_found.setPlainText("正在扫描舵机...")
        found_layout.addWidget(self.servo_list_found)

        lists_layout.addLayout(found_layout)

        # 右侧：未识别ID
        missing_layout = QVBoxLayout()
        missing_label = QLabel("⚠️ 未识别ID")
        missing_label.setStyleSheet("font-weight: bold; color: #dc3545; font-size: 12px;")
        missing_layout.addWidget(missing_label)

        self.servo_list_missing = QTextEdit()
        self.servo_list_missing.setReadOnly(True)
        self.servo_list_missing.setMaximumHeight(150)
        self.servo_list_missing.setPlainText("正在扫描舵机...")
        missing_layout.addWidget(self.servo_list_missing)

        lists_layout.addLayout(missing_layout)

        servo_layout.addLayout(lists_layout)
        layout.addWidget(servo_group)

    def create_calibration_panel(self, layout):
        """创建标定面板"""
        calibration_group = QGroupBox("🎯 ID标定")
        calibration_layout = QVBoxLayout()
        calibration_group.setLayout(calibration_layout)

        # 说明文字
        info_label = QLabel("📋 点击目标ID执行修改\n⏸️ 自动暂停扫描确保成功")
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
            btn.clicked.connect(lambda checked, slot=i: self.change_servo_id(slot))
            btn.setEnabled(False)

            self.id_buttons.append(btn)
            button_layout.addWidget(btn, row, col)

        calibration_layout.addLayout(button_layout)
        layout.addWidget(calibration_group)

    def create_log_panel(self, layout):
        """创建日志面板"""
        log_group = QGroupBox("📋 操作日志")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setPlainText("系统启动...")
        log_layout.addWidget(self.log_text)

        # 清空日志按钮
        clear_btn = QPushButton("清空日志")
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

        # 添加初始连接日志
        self.add_log("🔄 信号连接已建立", self.port_id)
        self.add_log("📡 开始扫描舵机...", self.port_id)

    def update_status(self, servos, connected, port_id):
        """更新状态显示"""
        if port_id != self.port_id:
            return

        print(f"[DEBUG] {port_id} update_status called: servos={servos}, connected={connected}")
        if connected:
            self.connection_status.setText("🟢 已连接")
            self.connection_status.setStyleSheet("color: #28a745; font-size: 12px; font-weight: bold;")
        else:
            self.connection_status.setText("🔴 未连接")
            self.connection_status.setStyleSheet("color: #dc3545; font-size: 12px; font-weight: bold;")

        if servos:
            self.current_servos_label.setText(f"当前舵机: {', '.join(map(str, servos))}")
            found_html = "<br>".join([f"<span style='color: #28a745; font-weight: bold;'>• 舵机 ID: {servo_id}</span>" for servo_id in servos])
            self.servo_list_found.setHtml(found_html)

            # 计算 1-6 号槽位中未识别的ID并显示
            expected_ids = set(range(1, 7))
            found_ids = set(servos)
            missing_ids = sorted(expected_ids - found_ids)
            if missing_ids:
                missing_html = "<br>".join([f"<span style='color: #dc3545; font-weight: bold;'>• ID {servo_id}</span>" for servo_id in missing_ids])
                self.servo_list_missing.setHtml(missing_html)
            else:
                self.servo_list_missing.setHtml("<span style='color: #28a745; font-weight: bold;'>✅ 1-6号槽位全部识别</span>")
        else:
            self.current_servos_label.setText("当前舵机: 无")
            self.servo_list_found.setHtml("<span style='color: #dc3545;'>📡 未发现舵机<br><br>请检查:<br>1. 舵机控制器是否连接<br>2. 舵机是否通电<br>3. 串口配置是否正确</span>")
            self.servo_list_missing.setHtml("")

        # 更新按钮状态
        self.update_button_states(servos, connected)

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

    def change_servo_id(self, slot_index):
        """修改舵机ID - 弹出对话框让用户自定义源ID和目标ID"""
        if self.worker is None:
            QMessageBox.warning(self, "警告", "当前端口已禁用，无法修改ID")
            return
        if not self.worker.current_servos:
            QMessageBox.warning(self, "警告", "没有可用的舵机进行ID修改")
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

        if old_id == new_id:
            QMessageBox.information(self, "提示", "源ID和目标ID相同，无需修改")
            return

        if new_id in self.worker.current_servos and new_id != old_id:
            reply = QMessageBox.question(
                self,
                "确认覆盖",
                f"目标ID {new_id} 已存在其他舵机，是否继续？\n继续可能导致总线ID冲突！",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # 确认对话框
        reply = QMessageBox.question(
            self,
            f"确认修改ID ({self.port_name})",
            f"确定要将舵机 ID {old_id} 修改为 ID {new_id} 吗？\n\n系统将自动暂停扫描确保修改成功。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.add_log(f"🎯 提交ID修改请求: {old_id} -> {new_id}", self.port_id)

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
        self.add_log("🔄 手动请求重新扫描...", self.port_id)
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
            QMessageBox.information(self, f"修改成功 ({self.port_name})", f"ID修改成功！\n{old_id} -> {new_id}")
            # 强制重新扫描舵机列表
            self.add_log(f"🔄 ID修改成功，重新扫描舵机...", self.port_id)
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
            QMessageBox.critical(self, f"修改失败 ({self.port_name})", f"ID修改失败！\n{message}")
            self.add_log(f"❌ 队列中ID修改失败: {old_id} -> {new_id}", self.port_id)
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
        self.title_label.setText(f"🏭 {self.port_name} - 舵机标定")

    def stop(self):
        """停止工作线程"""
        if self.worker:
            self.worker.stop()


class EZToolUI(QMainWindow):
    """EZ Tool - 简化版双串口工厂舵机标定工具"""

    calibration_log = Signal(str)  # 校准中位子进程日志信号
    calibration_state_changed = Signal(str, object)  # 校准中位状态变化信号

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

        self.init_ui()
        self.init_connections()
        self.refresh_ports()

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("🏭 双串口工厂舵机标定工具")
        self.setGeometry(50, 50, 1600, 900)

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
        title_label = QLabel("🏭 双串口工厂舵机标定工具")
        title_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(title_label)

        # 串口选择区域
        port_selection_group = QGroupBox("串口选择")
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
        left_label = QLabel("串口1:")
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
        right_label = QLabel("串口2:")
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
        refresh_btn.setToolTip("刷新串口列表")
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
        self.left_calib_btn = QPushButton("串口1中位校准")
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
        self.left_test_btn = QPushButton("串口1中位测试")
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
        self.left_disable_btn = QPushButton("串口1失能电机")
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
        self.right_calib_btn = QPushButton("串口2中位校准")
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
        self.right_test_btn = QPushButton("串口2中位测试")
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
        self.right_disable_btn = QPushButton("串口2失能电机")
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

        # 右上角遥控按钮
        self.remote_btn = QPushButton("🎮 遥控")
        self.remote_btn.setFixedSize(100, 40)
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
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #047857, stop:1 #035b69);
            }
        """)
        self.remote_btn.clicked.connect(self.toggle_remote_control)
        header_layout.addWidget(self.remote_btn)

        main_layout.addLayout(header_layout)

        # 创建副标题
        # subtitle_label = QLabel("双串口工厂舵机标定工具 - 支持中位校准、测试、失能功能")
        # subtitle_label.setAlignment(Qt.AlignCenter)
        # subtitle_label.setStyleSheet("font-size: 14px; color: #6c757d; margin-bottom: 10px;")
        # main_layout.addWidget(subtitle_label)

        # 创建状态栏（必须先创建，因为标签页初始化会使用 status_bar）
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("双串口系统已启动 - 左右独立操作 + 中间值校准")

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

        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        servo_tab_layout.addWidget(splitter)

        # 创建左侧面板
        self.left_panel = ServoPanel(self.left_port, "left")
        splitter.addWidget(self.left_panel)

        # 创建右侧面板
        self.right_panel = ServoPanel(self.right_port, "right")
        splitter.addWidget(self.right_panel)

        # 设置分割器比例
        splitter.setSizes([800, 800])

        self.tab_widget.addTab(servo_tab, "🦾 舵机标定")

        # === Tab 2: 校准管理 ===
        if CALIBRATION_MANAGER_AVAILABLE:
            calibration_tab = self.create_calibration_tab()
            self.tab_widget.addTab(calibration_tab, "📁 校准管理")

        # 设置整体样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f8f9fa;
            }
        """)

    def init_connections(self):
        """初始化信号连接"""
        # 添加初始日志
        self.status_bar.showMessage("双串口系统已启动 - 左右独立操作 + 中间值校准", 3000)

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
            self.remote_btn.setText("⏹️ 停止")
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
            self.status_bar.showMessage(f"遥控操作已启动 - {self.left_port}读取，{self.right_port}控制", 5000)
        else:
            self.add_remote_log(f"❌ {message}")
            QMessageBox.critical(self, "启动失败", f"无法启动遥控操作:\n{message}")

    def stop_remote_control(self):
        """停止遥控操作"""
        if self.remote_worker is None:
            return False

        success, message = self.remote_worker.stop_remote_control()

        if success:
            self.remote_btn.setText("🎮 遥控")
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
            self.status_bar.showMessage("遥控操作已停止", 3000)

            # 重新启动舵机标定操作
            self.left_panel.worker.start()
            self.right_panel.worker.start()
        else:
            self.add_remote_log(f"❌ {message}")

    def run_middle_calibration(self, port_name: str):
        """运行指定端口的中值校准"""
        # 使用 -m 模块方式运行，确保能找到 scservo_sdk
        command = [sys.executable, '-m', 'src.tools.servo_middle_calibration', port_name]

        self.add_remote_log(f"🚀 启动{port_name}中间值校准...")
        print(f"[CAL] Starting calibration for {port_name}")

        success, message = self.run_calibration_process(command)

        return success, message

    def run_calibration_process(self, command: list):
        """执行校准进程并监控输出"""
        try:
            print(f"[CALIBRATION] Command: {' '.join(command)}")

            # 启动进程
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=os.path.dirname(os.path.dirname(__file__))
            )

            # 监控输出
            while process.poll() is None:
                try:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        if line:
                            print(f"[CALIBRATION] {line}")
                    time.sleep(0.1)
                except:
                    break

            # 等待进程完成
            return_code = process.wait()

            if return_code == 0:
                return True, "校准完成"
            else:
                return False, f"校准失败，退出码: {return_code}"

        except Exception as e:
            return False, f"校准执行异常: {e}"

    def run_quick_calibration(self, port_name: str):
        """快速中位校准 - 非阻塞执行"""
        self.add_remote_log(f"🔧 开始{port_name}快速中位校准...")
        self.status_bar.showMessage(f"正在执行{port_name}中位校准...", 5000)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ 已停止{port_name}扫描线程，准备校准")
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ 已停止{port_name}扫描线程，准备校准")
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        # 使用线程非阻塞执行
        from threading import Thread
        thread = Thread(target=self._execute_quick_calibration, args=(port_name,))
        thread.daemon = True
        thread.start()

        self.add_remote_log(f"📝 {port_name}校准进程已启动，请等待执行完成")

    def _execute_quick_calibration(self, port_name: str):
        """执行快速中位校准的线程函数"""
        try:
            self.add_remote_log(f"🔍 查找校准脚本...")
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk

            # 检查使用哪个脚本
            tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools')
            quick_script = os.path.join(tools_dir, 'servo_quick_calibration.py')

            if os.path.exists(quick_script):
                self.add_remote_log(f"✅ 找到校准脚本: servo_quick_calibration.py")
                command = [sys.executable, '-m', 'src.tools.servo_quick_calibration', port_name]
            else:
                self.add_remote_log(f"⚠️ 未找到servo_quick_calibration.py，使用servo_middle_calibration.py")
                command = [sys.executable, '-m', 'src.tools.servo_middle_calibration', port_name, "2"]  # 使用自动模式

            self.add_remote_log(f"🚀 启动校准进程: {' '.join(command)}")

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )

            # 监控输出
            important_keywords = ["连接", "扫描", "校准", "完成", "失败", "错误", "成功", "发现"]
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
            if return_code == 0:
                self.add_remote_log(f"✅ {port_name}中位校准完成 - 进程正常退出")
                self.status_bar.showMessage(f"{port_name}校准完成", 3000)
            else:
                self.add_remote_log(f"❌ {port_name}中位校准失败 - 退出码: {return_code}")
                self.status_bar.showMessage(f"{port_name}校准失败", 3000)

            # 重新启动相应端口的扫描线程
            self.add_remote_log(f"⏳ 等待端口释放...")
            import time
            time.sleep(1.0)  # 增加等待时间确保端口完全释放

            if port_name == self.left_port:
                self.left_panel.worker.start()
                self.add_remote_log(f"▶️ 已重新启动{port_name}扫描线程")
            elif port_name == self.right_port:
                self.right_panel.worker.start()
                self.add_remote_log(f"▶️ 已重新启动{port_name}扫描线程")

        except Exception as e:
            self.add_remote_log(f"❌ {port_name}校准异常: {e}")
            self.status_bar.showMessage(f"{port_name}校准异常: {e}", 3000)
            # 即使出现异常也要尝试重新启动扫描线程
            try:
                import time
                time.sleep(1.0)
                if port_name == self.left_port:
                    self.left_panel.worker.start()
                    self.add_remote_log(f"🔄 异常后重启{port_name}扫描线程")
                elif port_name == self.right_port:
                    self.right_panel.worker.start()
                    self.add_remote_log(f"🔄 异常后重启{port_name}扫描线程")
            except:
                self.add_remote_log(f"⚠️ 重启{port_name}扫描线程失败")

    def run_quick_test(self, port_name: str):
        """快速中位测试 - 非阻塞执行"""
        self.add_remote_log(f"🧪 开始{port_name}中位测试...")
        self.status_bar.showMessage(f"正在执行{port_name}中位测试...", 5000)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ 已停止{port_name}扫描线程，准备测试")
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ 已停止{port_name}扫描线程，准备测试")
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        from threading import Thread
        thread = Thread(target=self._execute_quick_test, args=(port_name,))
        thread.daemon = True
        thread.start()

        self.add_remote_log(f"📝 {port_name}测试进程已启动，请等待执行完成")

    def _execute_quick_test(self, port_name: str):
        """执行快速中位测试的线程函数"""
        try:
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk
            command = [sys.executable, '-m', 'src.tools.servo_center_test', port_name]

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )

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
            if return_code == 0:
                self.add_remote_log(f"✅ {port_name}中位测试完成")
            else:
                self.add_remote_log(f"❌ {port_name}中位测试失败")

            # 重新启动相应端口的扫描线程
            import time
            time.sleep(0.5)  # 等待端口完全释放

            if port_name == self.left_port:
                self.left_panel.worker.start()
                self.add_remote_log(f"▶️ 已重新启动{port_name}扫描线程")
            elif port_name == self.right_port:
                self.right_panel.worker.start()
                self.add_remote_log(f"▶️ 已重新启动{port_name}扫描线程")

        except Exception as e:
            self.add_remote_log(f"❌ {port_name}测试异常: {e}")
            # 即使出现异常也要尝试重新启动扫描线程
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
        self.add_remote_log(f"⏹️ 开始{port_name}失能电机...")
        self.status_bar.showMessage(f"正在执行{port_name}失能电机...", 5000)

        # 先停止相应端口的工作线程，避免端口冲突
        if port_name == self.left_port and self.left_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ 已停止{port_name}扫描线程，准备失能")
            self.left_panel.worker.stop()
        elif port_name == self.right_port and self.right_panel.worker.is_connected:
            self.add_remote_log(f"⏸️ 已停止{port_name}扫描线程，准备失能")
            self.right_panel.worker.stop()

        # 等待端口释放
        import time
        time.sleep(1.0)

        from threading import Thread
        thread = Thread(target=self._execute_quick_disable, args=(port_name,))
        thread.daemon = True
        thread.start()

        self.add_remote_log(f"📝 {port_name}失能进程已启动，请等待执行完成")

    def _execute_quick_disable(self, port_name: str):
        """执行快速失能电机的线程函数"""
        try:
            # 使用 -m 模块方式运行，确保能找到 scservo_sdk
            command = [sys.executable, '-m', 'src.tools.servo_disable', port_name]

            self.add_remote_log(f"🚀 启动失能进程: {' '.join(command)}")
            print(f"[DEBUG DISABLE] Port name: {port_name}")
            print(f"[DEBUG DISABLE] Full command: {command}")

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )

            # 监控输出 - 显示重要信息
            important_keywords = ["连接", "扫描", "失能", "完成", "失败", "错误", "成功", "发现", "扭矩", "旋转"]
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
                except:
                    break

            return_code = process.wait()
            if return_code == 0:
                self.add_remote_log(f"✅ {port_name}电机已失能，可手动旋转")
                self.status_bar.showMessage(f"{port_name}失能完成", 3000)
            else:
                self.add_remote_log(f"❌ {port_name}失能失败 - 退出码: {return_code}")
                self.status_bar.showMessage(f"{port_name}失能失败", 3000)

            # 重新启动相应端口的扫描线程
            import time
            time.sleep(0.5)  # 等待端口完全释放

            if port_name == self.left_port:
                self.left_panel.worker.start()
                self.add_remote_log(f"▶️ 已重新启动{port_name}扫描线程")
            elif port_name == self.right_port:
                self.right_panel.worker.start()
                self.add_remote_log(f"▶️ 已重新启动{port_name}扫描线程")

        except Exception as e:
            self.add_remote_log(f"❌ {port_name}失能异常: {e}")
            self.status_bar.showMessage(f"{port_name}失能异常: {e}", 3000)
            # 即使出现异常也要尝试重新启动扫描线程
            try:
                import time
                time.sleep(0.5)
                if port_name == self.left_port:
                    self.left_panel.worker.start()
                    self.add_remote_log(f"🔄 异常后重启{port_name}扫描线程")
                elif port_name == self.right_port:
                    self.right_panel.worker.start()
                    self.add_remote_log(f"🔄 异常后重启{port_name}扫描线程")
            except:
                pass

    def add_remote_log(self, message):
        """添加遥控日志"""
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[REMOTE] {message}"
        print(f"[REMOTE] {log_entry}")
        self.status_bar.showMessage(f"遥控: {message}", 3000)

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

                # 尝试恢复之前的选择
                left_index = self.left_port_combo.findText(current_left)
                if left_index >= 0:
                    self.left_port_combo.setCurrentIndex(left_index)
                elif self.left_port_combo.count() > 1:
                    self.left_port_combo.setCurrentIndex(1)

                right_index = self.right_port_combo.findText(current_right)
                if right_index >= 0:
                    self.right_port_combo.setCurrentIndex(right_index)
                elif self.right_port_combo.count() > 2:
                    # 默认选择第二个真实串口，避免和左端口冲突
                    self.right_port_combo.setCurrentIndex(2)
                elif self.right_port_combo.count() > 1:
                    # 只有一个真实串口，默认禁用右端口
                    self.right_port_combo.setCurrentIndex(0)
            finally:
                # 恢复信号连接
                self.left_port_combo.currentTextChanged.connect(self.on_left_port_changed)
                self.right_port_combo.currentTextChanged.connect(self.on_right_port_changed)

            # 手动同步当前端口状态（防止信号断开期间状态不一致）
            new_left = self.left_port_combo.currentText()
            new_right = self.right_port_combo.currentText()
            if new_left != disabled_text and new_left != (self.left_port or ""):
                self.on_left_port_changed(new_left)
            if new_right != disabled_text and new_right != (self.right_port or ""):
                self.on_right_port_changed(new_right)

            self.status_bar.showMessage(f"串口列表已刷新 - 发现 {len(self.available_ports)} 个串口", 3000)

        except Exception as e:
            print(f"[DEBUG] Refresh ports error: {e}")
            self.status_bar.showMessage(f"刷新串口列表失败: {e}", 3000)

    def on_left_port_changed(self, port_name):
        """左串口选择改变"""
        if port_name == self.left_port or (
            not self.left_port and port_name == ServoPanel.DISABLED_PORT
        ):
            return

        print(f"[DEBUG] Left port changed from {self.left_port} to {port_name}")

        # 停止当前工作线程
        self.left_panel.stop()

        if port_name == ServoPanel.DISABLED_PORT:
            self.left_port = None
            self.left_panel.update_port_name(ServoPanel.DISABLED_PORT)
            self.left_panel.connection_status.setText("⚫ 已禁用")
            self.left_panel.worker = None
            self.status_bar.showMessage("串口1已禁用", 3000)
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

        self.status_bar.showMessage(f"串口1已切换到: {port_name}", 3000)

    def on_right_port_changed(self, port_name):
        """右串口选择改变"""
        if port_name == self.right_port or (
            not self.right_port and port_name == ServoPanel.DISABLED_PORT
        ):
            return

        print(f"[DEBUG] Right port changed from {self.right_port} to {port_name}")

        # 停止当前工作线程
        self.right_panel.stop()

        if port_name == ServoPanel.DISABLED_PORT:
            self.right_port = None
            self.right_panel.update_port_name(ServoPanel.DISABLED_PORT)
            self.right_panel.connection_status.setText("⚫ 已禁用")
            self.right_panel.worker = None
            self.status_bar.showMessage("串口2已禁用", 3000)
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

        self.status_bar.showMessage(f"串口2已切换到: {port_name}", 3000)

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

    def create_calibration_tab(self):
        """创建 LeRobot 校准文件管理标签页"""
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(10)

        calib_group = QGroupBox("📁 LeRobot 校准文件管理")
        calib_layout = QHBoxLayout(calib_group)
        calib_layout.setSpacing(10)

        self.calibration_manager = CalibrationManager()

        # 左侧：从动臂（robots）
        robot_layout = QVBoxLayout()
        robot_header = QHBoxLayout()
        robot_label = QLabel("🦾 从动臂 (robots)")
        robot_label.setStyleSheet("font-weight: bold; color: #495057;")
        robot_header.addWidget(robot_label)
        robot_header.addStretch()

        robot_refresh_btn = QPushButton("🔄")
        robot_refresh_btn.setFixedSize(28, 28)
        robot_refresh_btn.setStyleSheet("font-size: 12px;")
        robot_refresh_btn.setToolTip("刷新从动臂校准文件")
        robot_refresh_btn.clicked.connect(self.refresh_calibration_files)
        robot_header.addWidget(robot_refresh_btn)
        robot_layout.addLayout(robot_header)

        self.robot_list = QComboBox()
        self.robot_list.setMinimumWidth(200)
        self.robot_list.currentIndexChanged.connect(self.on_robot_calibration_selected)
        robot_layout.addWidget(self.robot_list)

        # 右侧：领导臂（teleoperators）
        teleop_layout = QVBoxLayout()
        teleop_header = QHBoxLayout()
        teleop_label = QLabel("🎮 领导臂 (teleoperators)")
        teleop_label.setStyleSheet("font-weight: bold; color: #495057;")
        teleop_header.addWidget(teleop_label)
        teleop_header.addStretch()

        teleop_refresh_btn = QPushButton("🔄")
        teleop_refresh_btn.setFixedSize(28, 28)
        teleop_refresh_btn.setStyleSheet("font-size: 12px;")
        teleop_refresh_btn.setToolTip("刷新领导臂校准文件")
        teleop_refresh_btn.clicked.connect(self.refresh_calibration_files)
        teleop_header.addWidget(teleop_refresh_btn)
        teleop_layout.addLayout(teleop_header)

        self.teleop_list = QComboBox()
        self.teleop_list.setMinimumWidth(200)
        self.teleop_list.currentIndexChanged.connect(self.on_teleop_calibration_selected)
        teleop_layout.addWidget(self.teleop_list)

        # 左侧：文件选择 + 操作按钮
        left_side_layout = QVBoxLayout()
        left_side_layout.setSpacing(10)

        # 文件选择区
        file_selection_layout = QHBoxLayout()
        file_selection_layout.addLayout(robot_layout)
        file_selection_layout.addLayout(teleop_layout)
        left_side_layout.addLayout(file_selection_layout)

        # 操作按钮区
        ops_group = QGroupBox("🛠️ 操作")
        ops_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                color: #495057;
                border: 1px solid #ced4da;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """)
        ops_layout = QVBoxLayout(ops_group)
        ops_layout.setSpacing(8)

        # 中位运行按钮
        self.calib_run_btn = QPushButton("🎯 运行到校准中位")
        self.calib_run_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #218838; }
            QPushButton:pressed { background-color: #1e7e34; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.calib_run_btn.setToolTip("根据选中的校准文件，将舵机移动到校准零点")
        self.calib_run_btn.clicked.connect(self.run_calibration_to_middle)
        ops_layout.addWidget(self.calib_run_btn)

        # 停止按钮
        self.calib_stop_btn = QPushButton("⏹️ 停止")
        self.calib_stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #c82333; }
            QPushButton:pressed { background-color: #bd2130; }
        """)
        self.calib_stop_btn.setToolTip("停止中位运行进程并失能电机")
        self.calib_stop_btn.setEnabled(False)
        self.calib_stop_btn.clicked.connect(self.stop_calibration_middle)
        ops_layout.addWidget(self.calib_stop_btn)

        # 编辑校准文件按钮
        self.calib_edit_btn = QPushButton("✏️ 编辑校准文件")
        self.calib_edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #20c997;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1ba87e; }
            QPushButton:pressed { background-color: #168a6b; }
        """)
        self.calib_edit_btn.setToolTip("编辑选中校准文件的中位值、最小值、最大值")
        self.calib_edit_btn.clicked.connect(self.edit_calibration_file)
        ops_layout.addWidget(self.calib_edit_btn)

        # 重新校准按钮（基于现有文件）
        self.calib_recal_btn = QPushButton("🔄 重新校准")
        self.calib_recal_btn.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5a32a3; }
            QPushButton:pressed { background-color: #4a2785; }
        """)
        self.calib_recal_btn.setToolTip("用 GUI 向导重新校准，基于当前选中文件预填数据")
        self.calib_recal_btn.clicked.connect(self.recalibrate_from_file)
        ops_layout.addWidget(self.calib_recal_btn)

        # 删除校准文件按钮
        self.calib_delete_btn = QPushButton("🗑️ 删除")
        self.calib_delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #c82333; }
            QPushButton:pressed { background-color: #bd2130; }
        """)
        self.calib_delete_btn.setToolTip("删除选中的校准文件")
        self.calib_delete_btn.clicked.connect(self.delete_calibration_file)
        ops_layout.addWidget(self.calib_delete_btn)

        left_side_layout.addWidget(ops_group)
        calib_layout.addLayout(left_side_layout, stretch=1)

        # 右侧：详情 + GUI 校准向导
        detail_layout = QVBoxLayout()
        detail_label = QLabel("📋 校准详情")
        detail_label.setStyleSheet("font-weight: bold; color: #495057;")
        detail_layout.addWidget(detail_label)

        self.calibration_detail = QTextEdit()
        self.calibration_detail.setReadOnly(True)
        self.calibration_detail.setPlaceholderText("请选择左侧的校准文件查看详情...")
        self.calibration_detail.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                color: #212529;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)
        detail_layout.addWidget(self.calibration_detail)

        # GUI 校准向导按钮（加大加明显）
        self.calib_gui_btn = QPushButton("🎯 GUI 校准向导")
        self.calib_gui_btn.setMinimumHeight(70)
        self.calib_gui_btn.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self.calib_gui_btn.setStyleSheet("""
            QPushButton {
                background-color: #fd7e14;
                color: white;
                border: none;
                padding: 18px 25px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #e56b0a; }
            QPushButton:pressed { background-color: #c95d08; }
        """)
        self.calib_gui_btn.setToolTip("在 GUI 中直接进行整臂校准，实时显示各关节数值")
        self.calib_gui_btn.clicked.connect(self.run_gui_calibration_wizard)
        detail_layout.addWidget(self.calib_gui_btn)

        calib_layout.addLayout(detail_layout, stretch=2)

        tab_layout.addWidget(calib_group)

        # 子进程跟踪
        self.calibration_process = None
        self.calibration_monitor_thread = None

        # 校准文件列表缓存（避免在 QComboBox 中存储 dict 引发 QVariant 转换错误）
        self._robot_calibrations = []
        self._teleop_calibrations = []

        # 连接校准日志信号（线程安全更新 GUI）
        self.calibration_log.connect(self._append_calibration_log)
        self.calibration_state_changed.connect(self._on_calibration_state_changed)

        # 初始加载
        self.refresh_calibration_files()

        return tab_widget

    def refresh_calibration_files(self):
        """刷新校准文件列表"""
        if not hasattr(self, 'calibration_manager'):
            return

        try:
            robots, teleoperators = self.calibration_manager.load_all_calibrations()

            # 保存当前选择的索引
            current_robot_index = self.robot_list.currentIndex()
            current_teleop_index = self.teleop_list.currentIndex()

            # 缓存校准数据到实例变量，不在 QComboBox 中存 dict
            self._robot_calibrations = [None] + robots
            self._teleop_calibrations = [None] + teleoperators

            self.robot_list.clear()
            self.teleop_list.clear()

            self.robot_list.addItem("-- 选择从动臂校准文件 --")
            for i, item in enumerate(robots, start=1):
                display = f"{item['arm_dir']} / {item['name']}"
                self.robot_list.addItem(display)

            self.teleop_list.addItem("-- 选择领导臂校准文件 --")
            for i, item in enumerate(teleoperators, start=1):
                display = f"{item['arm_dir']} / {item['name']}"
                self.teleop_list.addItem(display)

            # 恢复选择（限制在有效范围内）
            if 0 <= current_robot_index < self.robot_list.count():
                self.robot_list.setCurrentIndex(current_robot_index)
            if 0 <= current_teleop_index < self.teleop_list.count():
                self.teleop_list.setCurrentIndex(current_teleop_index)

            self.status_bar.showMessage(
                f"校准文件已刷新 - 从动臂 {len(robots)} 个, 领导臂 {len(teleoperators)} 个", 3000
            )

        except Exception as e:
            print(f"[DEBUG] Refresh calibration files error: {e}")
            self.status_bar.showMessage(f"刷新校准文件失败: {e}", 3000)

    def on_robot_calibration_selected(self, index):
        """从动臂校准文件选择改变"""
        if 0 <= index < len(self._robot_calibrations):
            item = self._robot_calibrations[index]
            if item:
                self.teleop_list.setCurrentIndex(0)
                self.display_calibration_detail(item)

    def on_teleop_calibration_selected(self, index):
        """领导臂校准文件选择改变"""
        if 0 <= index < len(self._teleop_calibrations):
            item = self._teleop_calibrations[index]
            if item:
                self.robot_list.setCurrentIndex(0)
                self.display_calibration_detail(item)

    def display_calibration_detail(self, item):
        """显示校准文件详情"""
        try:
            detail_text = f"文件路径: {item['path']}\n"
            detail_text += f"臂类型: {item['arm_dir']}\n"
            detail_text += f"文件名: {item['name']}\n"
            detail_text += "-" * 40 + "\n\n"
            detail_text += self.calibration_manager.format_calibration_summary(item['data'])
            self.calibration_detail.setPlainText(detail_text)
        except Exception as e:
            self.calibration_detail.setPlainText(f"显示校准详情失败: {e}")

    def run_calibration_to_middle(self):
        """运行选中的校准文件到中位"""
        # 获取当前选中的校准文件（通过缓存列表索引）
        robot_index = self.robot_list.currentIndex()
        teleop_index = self.teleop_list.currentIndex()
        robot_item = self._robot_calibrations[robot_index] if 0 <= robot_index < len(self._robot_calibrations) else None
        teleop_item = self._teleop_calibrations[teleop_index] if 0 <= teleop_index < len(self._teleop_calibrations) else None
        selected_item = robot_item if robot_item else teleop_item

        if not selected_item:
            QMessageBox.warning(self, "警告", "请先选择一个校准文件")
            return

        # 选择目标端口（过滤掉禁用的端口）
        available_ports = []
        if self.left_port:
            available_ports.append(("left", self.left_port, "左端口"))
        if self.right_port:
            available_ports.append(("right", self.right_port, "右端口"))

        if not available_ports:
            QMessageBox.warning(self, "警告", "没有可用的串口，请先连接机械臂并选择串口")
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("选择端口")
        msg_box.setText("选择要运行中位的串口：")
        msg_box.setInformativeText(f"校准文件: {selected_item['name']}")

        port_buttons = {}
        for side, port, label in available_ports:
            btn = msg_box.addButton(f"{label}: {port}", QMessageBox.AcceptRole)
            port_buttons[btn] = port

        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.exec()

        clicked_btn = msg_box.clickedButton()
        if clicked_btn == cancel_btn or clicked_btn not in port_buttons:
            return

        target_port = port_buttons[clicked_btn]
        self.calibration_target_port = target_port

        # 先停止对应端口的扫描线程，避免端口冲突
        if target_port == self.left_port and self.left_panel.worker.is_connected:
            self.left_panel.worker.stop()
            self.calibration_detail.append(f"\n⏸️ 已停止左端口扫描线程")
        elif target_port == self.right_port and self.right_panel.worker.is_connected:
            self.right_panel.worker.stop()
            self.calibration_detail.append(f"\n⏸️ 已停止右端口扫描线程")

        # 等待端口完全释放
        self.calibration_detail.append("\n⏳ 等待串口释放...")
        time.sleep(2.5)

        # 构建命令
        command = [
            sys.executable, '-m', 'src.tools.run_calibration_middle',
            selected_item['path'], target_port, '--mode', 'zero'
        ]

        self.calibration_detail.append(
            f"\n🚀 启动中位运行: {' '.join(command)}\n"
            f"目标端口 / Target port: {target_port}\n"
        )

        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.calibration_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=project_root
            )

            self.calib_run_btn.setEnabled(False)
            self.calib_stop_btn.setEnabled(True)
            self.status_bar.showMessage(f"正在运行校准中位 - {target_port}", 5000)

            # 启动监控线程
            self.calibration_monitor_thread = threading.Thread(
                target=self._monitor_calibration_process,
                daemon=True
            )
            self.calibration_monitor_thread.start()

        except Exception as e:
            self.calibration_detail.append(f"\n❌ 启动中位运行失败: {e}")
            self.status_bar.showMessage(f"启动中位运行失败: {e}", 3000)
            self.calib_run_btn.setEnabled(True)
            self.calib_stop_btn.setEnabled(False)

    def _monitor_calibration_process(self):
        """监控中位运行子进程输出"""
        if not self.calibration_process:
            return

        try:
            while self.calibration_process.poll() is None:
                line = self.calibration_process.stdout.readline()
                if line:
                    line = line.strip()
                    if line:
                        print(f"[CALIB MIDDLE] {line}")
                        self.calibration_log.emit(line)
                time.sleep(0.1)

            # 进程结束
            return_code = self.calibration_process.poll()
            self.calibration_state_changed.emit("finished", return_code)

        except Exception as e:
            self.calibration_state_changed.emit("error", str(e))

    def _append_calibration_log(self, text):
        """线程安全追加校准日志"""
        self.calibration_detail.append(text)
        scrollbar = self.calibration_detail.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_calibration_state_changed(self, event_type, data):
        """处理校准中位状态变化"""
        if event_type == "finished":
            return_code = data
            self.calibration_detail.append(f"\n🔚 中位运行进程已结束 (退出码: {return_code})")
            self.calib_run_btn.setEnabled(True)
            self.calib_stop_btn.setEnabled(False)
            self.status_bar.showMessage("中位运行已结束", 3000)
        elif event_type == "error":
            self.calibration_detail.append(f"\n❌ 监控中位进程异常: {data}")
            self.calib_run_btn.setEnabled(True)
            self.calib_stop_btn.setEnabled(False)
    def disable_servos_on_port(self, port_name: str):
        """对指定端口上的所有舵机执行失能（关闭力矩）"""
        if not port_name:
            return False, "端口为空"

        try:
            port_handler = PortHandler(port_name)
            if not port_handler.openPort():
                return False, f"无法打开串口 {port_name}"
            if not port_handler.setBaudRate(1000000):
                port_handler.closePort()
                return False, f"无法设置波特率 {port_name}"

            servo_handler = sms_sts(port_handler)

            # 扫描并失能所有舵机
            disabled_count = 0
            for servo_id in range(1, 21):
                try:
                    model_number, result, error = servo_handler.ping(servo_id)
                    if result == COMM_SUCCESS:
                        servo_handler.write1ByteTxRx(servo_id, 40, 0)
                        disabled_count += 1
                        time.sleep(0.02)
                except Exception:
                    pass

            port_handler.closePort()
            return True, f"已失能 {disabled_count} 个舵机"
        except Exception as e:
            return False, f"失能舵机失败: {e}"

    def stop_calibration_middle(self):
        """停止中位运行进程，并失能电机"""
        if not self.calibration_process:
            return

        target_port = getattr(self, 'calibration_target_port', None)

        try:
            self.calibration_process.terminate()
            try:
                self.calibration_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.calibration_process.kill()
                self.calibration_process.wait()

            self.calibration_detail.append("\n⏹️ 中位运行已停止")
            self.status_bar.showMessage("中位运行已停止，正在失能电机...", 3000)

            # 等待子进程完全释放串口
            time.sleep(1.0)

            # 失能电机
            if target_port:
                success, message = self.disable_servos_on_port(target_port)
                if success:
                    self.calibration_detail.append(f"\n✅ {message}")
                    self.status_bar.showMessage(f"中位运行已停止，{message}", 5000)
                else:
                    self.calibration_detail.append(f"\n⚠️ {message}")
                    self.status_bar.showMessage(f"中位运行已停止，但{message}", 5000)
            else:
                self.calibration_detail.append("\n⚠️ 未记录目标端口，无法自动失能电机")

        except Exception as e:
            self.calibration_detail.append(f"\n❌ 停止中位运行失败: {e}")
        finally:
            self.calibration_process = None
            self.calib_run_btn.setEnabled(True)
            self.calib_stop_btn.setEnabled(False)

    def edit_calibration_file(self):
        """编辑选中的校准文件"""
        robot_index = self.robot_list.currentIndex()
        teleop_index = self.teleop_list.currentIndex()
        robot_item = self._robot_calibrations[robot_index] if 0 <= robot_index < len(self._robot_calibrations) else None
        teleop_item = self._teleop_calibrations[teleop_index] if 0 <= teleop_index < len(self._teleop_calibrations) else None
        selected_item = robot_item if robot_item else teleop_item

        if not selected_item:
            QMessageBox.warning(self, "警告", "请先选择一个校准文件")
            return

        dialog = CalibrationEditorDialog(selected_item, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_calibration_files()
            # 重新显示详情
            if robot_item:
                self.display_calibration_detail(robot_item)
            elif teleop_item:
                self.display_calibration_detail(teleop_item)
            self.status_bar.showMessage("校准文件已更新", 5000)

    def recalibrate_from_file(self):
        """基于选中的校准文件，用 GUI 向导重新校准（可选择性覆盖）"""
        robot_index = self.robot_list.currentIndex()
        teleop_index = self.teleop_list.currentIndex()
        robot_item = self._robot_calibrations[robot_index] if 0 <= robot_index < len(self._robot_calibrations) else None
        teleop_item = self._teleop_calibrations[teleop_index] if 0 <= teleop_index < len(self._teleop_calibrations) else None
        selected_item = robot_item if robot_item else teleop_item

        if not selected_item:
            QMessageBox.warning(self, "警告", "请先选择一个校准文件")
            return

        # 选择目标端口
        available_ports = []
        if self.left_port:
            available_ports.append(("left", self.left_port, "左端口"))
        if self.right_port:
            available_ports.append(("right", self.right_port, "右端口"))

        if not available_ports:
            QMessageBox.warning(self, "警告", "没有可用的串口，请先连接机械臂并选择串口")
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("选择端口")
        msg_box.setText("选择要重新校准的串口：")
        msg_box.setInformativeText(f"基于文件: {selected_item['name']}")

        port_buttons = {}
        for side, port, label in available_ports:
            btn = msg_box.addButton(f"{label}: {port}", QMessageBox.AcceptRole)
            port_buttons[btn] = port

        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.exec()

        clicked_btn = msg_box.clickedButton()
        if clicked_btn == cancel_btn or clicked_btn not in port_buttons:
            return

        target_port = port_buttons[clicked_btn]
        arm_type = "leader" if "teleoperators" in str(selected_item['path']) or "leader" in selected_item['name'].lower() else "follower"

        # 停止对应端口的扫描线程
        if target_port == self.left_port and self.left_panel.worker and self.left_panel.worker.is_connected:
            self.left_panel.worker.stop()
            self.calibration_detail.append(f"\n⏸️ 已停止左端口扫描线程")
        elif target_port == self.right_port and self.right_panel.worker and self.right_panel.worker.is_connected:
            self.right_panel.worker.stop()
            self.calibration_detail.append(f"\n⏸️ 已停止右端口扫描线程")

        time.sleep(2.5)

        self.calibration_detail.append(
            f"\n🔄 启动基于文件的重新校准:\n"
            f"端口 / Port: {target_port}\n"
            f"文件 / File: {selected_item['path']}\n"
        )
        self.status_bar.showMessage("重新校准向导已启动", 5000)

        try:
            wizard = CalibrationWizard(
                target_port,
                arm_type,
                preload_file=selected_item['path'],
                parent=self
            )
            wizard.exec()
            self.refresh_calibration_files()
            if robot_item:
                self.display_calibration_detail(robot_item)
            elif teleop_item:
                self.display_calibration_detail(teleop_item)
            self.calibration_detail.append("\n✅ 重新校准向导已关闭，文件列表已刷新")
            self.status_bar.showMessage("重新校准已完成，文件列表已刷新", 5000)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动重新校准向导失败: {e}")
            self.calibration_detail.append(f"\n❌ 启动重新校准向导失败: {e}")

    def delete_calibration_file(self):
        """删除选中的校准文件"""
        robot_index = self.robot_list.currentIndex()
        teleop_index = self.teleop_list.currentIndex()
        robot_item = self._robot_calibrations[robot_index] if 0 <= robot_index < len(self._robot_calibrations) else None
        teleop_item = self._teleop_calibrations[teleop_index] if 0 <= teleop_index < len(self._teleop_calibrations) else None
        selected_item = robot_item if robot_item else teleop_item

        if not selected_item:
            QMessageBox.warning(self, "警告", "请先选择一个校准文件")
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除以下校准文件吗？\n\n"
            f"文件: {selected_item['name']}\n"
            f"路径: {selected_item['path']}\n\n"
            f"此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            import os
            os.remove(selected_item['path'])
            self.calibration_detail.append(f"\n🗑️ 已删除校准文件: {selected_item['path']}")
            self.status_bar.showMessage("校准文件已删除", 5000)
            self.refresh_calibration_files()
            self.calibration_detail.setPlainText("请选择一个校准文件查看详情...")
        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"删除校准文件失败: {e}")
            self.calibration_detail.append(f"\n❌ 删除校准文件失败: {e}")

    def run_gui_calibration_wizard(self):
        """启动 GUI 校准向导"""
        if not CALIBRATION_MANAGER_AVAILABLE:
            QMessageBox.warning(self, "警告", "校准管理模块不可用")
            return

        # 创建配置对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("GUI 校准向导")
        dialog.setMinimumWidth(350)

        layout = QFormLayout(dialog)

        # 端口选择（过滤掉禁用的端口）
        port_combo = QComboBox()
        available_target_ports = []
        if self.left_port:
            port_combo.addItem(f"左端口: {self.left_port}", self.left_port)
            available_target_ports.append(self.left_port)
        if self.right_port:
            port_combo.addItem(f"右端口: {self.right_port}", self.right_port)
            available_target_ports.append(self.right_port)

        if not available_target_ports:
            QMessageBox.warning(self, "警告", "没有可用的串口，请先连接机械臂并选择串口")
            return

        layout.addRow("目标端口:", port_combo)

        # 臂类型选择
        arm_type_combo = QComboBox()
        arm_type_combo.addItem("从动臂 (follower)", "follower")
        arm_type_combo.addItem("领导臂 (leader)", "leader")
        layout.addRow("臂类型:", arm_type_combo)

        # 说明标签
        info_label = QLabel(
            "说明：校准向导会实时显示各关节位置。\n"
            "请先确保目标端口没有正在运行的扫描线程。"
        )
        info_label.setStyleSheet("color: #6c757d; font-size: 11px;")
        info_label.setWordWrap(True)
        layout.addRow(info_label)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        target_port = port_combo.currentData()
        arm_type = arm_type_combo.currentData()

        # 检测左右端口是否指向同一个设备
        if self.left_port == self.right_port:
            reply = QMessageBox.question(
                self,
                "端口冲突警告",
                f"左端口和右端口都设置为同一个设备: {self.left_port}\n"
                f"这会导致两个扫描线程互相竞争串口。\n\n"
                f"是否继续启动校准向导？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # 停止对应端口的扫描线程，避免端口冲突
        if target_port == self.left_port and self.left_panel.worker.is_connected:
            self.left_panel.worker.stop()
            self.calibration_detail.append(f"\n⏸️ 已停止左端口扫描线程")
        elif target_port == self.right_port and self.right_panel.worker.is_connected:
            self.right_panel.worker.stop()
            self.calibration_detail.append(f"\n⏸️ 已停止右端口扫描线程")

        # 等待端口完全释放（停止线程 + 关闭串口需要时间）
        self.calibration_detail.append("\n⏳ 等待串口释放...")
        time.sleep(2.5)

        self.calibration_detail.append(
            f"\n🚀 启动 GUI 校准向导:\n"
            f"端口 / Port: {target_port}\n"
            f"臂类型 / Arm type: {arm_type}\n"
        )
        self.status_bar.showMessage("GUI 校准向导已启动", 5000)

        # 打开校准向导对话框（阻塞式）
        try:
            wizard = CalibrationWizard(target_port, arm_type, self)
            wizard.exec()

            # 校准完成后刷新文件列表
            self.refresh_calibration_files()
            self.calibration_detail.append("\n✅ GUI 校准向导已关闭，文件列表已刷新")
            self.status_bar.showMessage("GUI 校准已完成，文件列表已刷新", 5000)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动 GUI 校准向导失败: {e}")
            self.calibration_detail.append(f"\n❌ 启动 GUI 校准向导失败: {e}")

    def closeEvent(self, event):
        """关闭事件"""
        # 停止遥控操作
        if self.remote_worker and self.remote_worker.running:
            self.remote_worker.stop_remote_control()

        # 停止中位运行进程
        if self.calibration_process:
            self.stop_calibration_middle()

        # 停止舵机标定操作
        self.left_panel.stop()
        self.right_panel.stop()

        super().closeEvent(event)


class CalibrationEditorDialog(QDialog):
    """校准文件编辑器对话框"""

    # 关节显示顺序
    JOINT_ORDER = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    ]

    def __init__(self, calibration_item: dict, parent=None):
        super().__init__(parent)
        self.calibration_item = calibration_item
        self.setWindowTitle(f"✏️ 编辑校准文件 - {calibration_item['name']}")
        self.setMinimumWidth(550)
        self.setMinimumHeight(450)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 说明
        info_label = QLabel(
            f"文件路径: {self.calibration_item['path']}\n"
            f"直接修改各关节的中位值、最小值、最大值，然后点击保存。"
        )
        info_label.setStyleSheet("color: #6c757d; font-size: 12px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # 表格
        self.table = QTableWidget(len(self.JOINT_ORDER), 4)
        self.table.setHorizontalHeaderLabels(["关节名", "中位值", "最小值", "最大值"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Stretch)

        self.spinboxes = {}
        data = self.calibration_item['data']

        for row, joint_name in enumerate(self.JOINT_ORDER):
            joint_data = data.get(joint_name, {})
            display_name = JOINT_NAME_MAP.get(joint_name, joint_name)

            # 关节名
            name_item = QTableWidgetItem(display_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, name_item)

            # 中位值
            homing_spin = QSpinBox()
            homing_spin.setRange(0, 4095)
            homing_spin.setValue(joint_data.get("homing_offset", 2048))
            self.table.setCellWidget(row, 1, homing_spin)

            # 最小值
            min_spin = QSpinBox()
            min_spin.setRange(0, 4095)
            min_spin.setValue(joint_data.get("range_min", 0))
            self.table.setCellWidget(row, 2, min_spin)

            # 最大值
            max_spin = QSpinBox()
            max_spin.setRange(0, 4095)
            max_spin.setValue(joint_data.get("range_max", 4095))
            self.table.setCellWidget(row, 3, max_spin)

            self.spinboxes[joint_name] = {
                "homing": homing_spin,
                "min": min_spin,
                "max": max_spin,
            }

        layout.addWidget(self.table)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_changes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save_changes(self):
        """保存修改到文件"""
        data = self.calibration_item['data'].copy()

        for joint_name, spins in self.spinboxes.items():
            if joint_name not in data:
                continue

            homing = spins["homing"].value()
            rmin = spins["min"].value()
            rmax = spins["max"].value()

            if rmin > rmax:
                QMessageBox.warning(
                    self,
                    "数值错误",
                    f"{JOINT_NAME_MAP.get(joint_name, joint_name)} 的最小值不能大于最大值"
                )
                return

            data[joint_name]["homing_offset"] = homing
            data[joint_name]["range_min"] = rmin
            data[joint_name]["range_max"] = rmax

        try:
            manager = CalibrationManager()
            success = manager.save_calibration_file(self.calibration_item['path'], data)
            if success:
                self.calibration_item['data'] = data
                QMessageBox.information(self, "保存成功", "校准文件已更新")
                self.accept()
            else:
                QMessageBox.critical(self, "保存失败", "无法保存校准文件")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存校准文件失败: {e}")


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

    # 解析命令行参数
    parser = argparse.ArgumentParser(description='双串口工厂舵机标定工具')
    parser.add_argument('--port1', type=str, help='指定串口1 (例如: COM1 或 /dev/ttyUSB0)')
    parser.add_argument('--port2', type=str, help='指定串口2 (例如: COM2 或 /dev/ttyUSB1)')
    parser.add_argument('--list-ports', action='store_true', help='列出可用串口并退出')
    args = parser.parse_args()

    # 如果只是列出串口
    if args.list_ports:
        try:
            available_ports = get_available_ports()
            print("可用串口列表:")
            for i, port in enumerate(available_ports, 1):
                print(f"  {i}. {port}")
            if not available_ports:
                print("  未发现可用串口")
        except Exception as e:
            print(f"获取串口列表失败: {e}")
        return

    app = QApplication(sys.argv)
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

    print(f"启动双串口工厂舵机标定工具")
    print(f"系统: {system}")
    print(f"串口1: {left_port}")
    print(f"串口2: {right_port}")

    # 检查可用端口
    try:
        available_ports = get_available_ports()
        print(f"检测到的可用串口: {available_ports}")

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
                    print(f"使用首选端口: {left_port}, {right_port}")
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
                    print(f"使用混合端口配置: {left_port}, {right_port}")
                # 没有找到首选端口
                elif not args.port1 and not args.port2:
                    left_port, right_port = available_ports[0], available_ports[1]
                    print(f"使用前两个可用端口: {left_port}, {right_port}")

            elif len(available_ports) == 1:
                if not args.port1:
                    left_port = available_ports[0]
                if not args.port2:
                    right_port = None  # 只有一个真实串口，禁用右端口避免冲突
                print(f"只有一个可用端口: {available_ports[0]}, 备用端口: {right_port if right_port else '禁用'}")
            else:
                print("未发现可用串口，使用默认配置")

    except Exception as e:
        print(f"检查可用端口时出错: {e}")

    # 创建并显示主窗口
    window = EZToolUI(left_port, right_port)
    window.show()

    print("UI界面已启动")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()