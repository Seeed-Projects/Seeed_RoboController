#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
位置限制设置专用上位机
实时显示舵机位置值，采集MIN/MAX值，并写入位置限制
"""

import sys
import os
import time
from threading import Thread
from typing import List, Dict

# 添加SDK路径
sys.path.append('.')
sys.path.append('./scservo_sdk')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QGroupBox,
    QHeaderView, QMessageBox, QStatusBar, QComboBox
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QColor

try:
    from src.gui.theme_utils import setup_light_theme
except ImportError:
    setup_light_theme = None

try:
    from src.i18n import tr, set_lang, lang_from_argv
except ImportError:
    def tr(text):
        return text

    def set_lang(lang):
        return lang

    def lang_from_argv(argv):
        return None

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError as e:
    print(f"Error: Cannot import SCServo SDK: {e}")
    sys.exit(1)

# 寄存器地址
SMS_STS_MIN_ANGLE_LIMIT_L = 9
SMS_STS_MIN_ANGLE_LIMIT_H = 10
SMS_STS_MAX_ANGLE_LIMIT_L = 11
SMS_STS_MAX_ANGLE_LIMIT_H = 12
SMS_STS_TORQUE_ENABLE = 40
SMS_STS_PRESENT_POSITION_L = 56
SMS_STS_PRESENT_POSITION_H = 57

# 常量
SMS_STS_MIDDLE_POSITION = 2048
ANGLE_RESOLUTION = 360.0 / 4096.0  # 每步0.088度


class ServoData:
    """舵机数据类"""
    def __init__(self, servo_id: int):
        self.id = servo_id
        self.current_pos = 2048  # 原始位置值
        self.min_pos = 4095      # 初始最大值
        self.max_pos = 0         # 初始最小值
        self.connected = False
        self.was_connected = False  # 用于检测热插拔


class ServoMonitorWorker(QObject):
    """舵机监控工作线程"""
    data_updated = Signal(list)  # 数据更新信号
    status_changed = Signal(str)  # 状态改变信号

    def __init__(self, port_name: str):
        super().__init__()
        self.port_name = port_name
        self.port_handler = None
        self.servo_handler = None
        self.running = False
        self.servo_data: Dict[int, ServoData] = {}
        self.servo_ids = list(range(1, 7))  # 监控ID 1-6

    def position_to_degrees(self, position: int) -> float:
        """位置值转角度 - 保留但不使用"""
        return (position - SMS_STS_MIDDLE_POSITION) * ANGLE_RESOLUTION

    def connect(self) -> bool:
        """连接串口"""
        try:
            self.port_handler = PortHandler(self.port_name)
            if not self.port_handler.openPort():
                self.status_changed.emit(tr("❌ 无法打开串口: {}").format(self.port_name))
                return False

            if not self.port_handler.setBaudRate(1000000):
                self.status_changed.emit(tr("❌ 无法设置波特率"))
                self.port_handler.closePort()
                return False

            self.servo_handler = sms_sts(self.port_handler)
            self.status_changed.emit(tr("✅ 成功连接到 {}").format(self.port_name))
            return True

        except Exception as e:
            self.status_changed.emit(tr("❌ 连接失败: {}").format(e))
            return False

    def disconnect(self):
        """断开连接"""
        if self.port_handler:
            self.port_handler.closePort()
        self.status_changed.emit(tr("🔌 已断开连接"))

    def scan_servos(self) -> List[int]:
        """扫描舵机 - 支持热插拔"""
        found_servos = []
        self.status_changed.emit(tr("📡 扫描舵机中..."))

        for servo_id in self.servo_ids:
            try:
                model_number, result, error = self.servo_handler.ping(servo_id)
                was_connected = self.servo_data.get(servo_id, ServoData(servo_id)).connected

                if result == COMM_SUCCESS:
                    found_servos.append(servo_id)
                    if servo_id not in self.servo_data:
                        self.servo_data[servo_id] = ServoData(servo_id)

                    # 热插拔检测 - 新连接
                    if not was_connected and self.servo_data[servo_id].was_connected:
                        self.status_changed.emit(tr("  🔌 重新连接舵机 ID{}").format(servo_id))
                    elif not was_connected and not self.servo_data[servo_id].was_connected:
                        self.status_changed.emit(tr("  ✅ 发现舵机 ID{}").format(servo_id))

                    self.servo_data[servo_id].connected = True
                    self.servo_data[servo_id].was_connected = True
                else:
                    # 热插拔检测 - 断开连接
                    if was_connected:
                        self.status_changed.emit(tr("  ❌ 舵机 ID{} 已断开").format(servo_id))

                    if servo_id in self.servo_data:
                        self.servo_data[servo_id].connected = False
            except Exception as e:
                self.status_changed.emit(tr("  ❌ 扫描ID{}失败: {}").format(servo_id, e))

        return found_servos

    def read_positions(self) -> bool:
        """读取所有舵机位置 - 直接显示原始数值"""
        success = True
        for servo_id in self.servo_ids:
            if servo_id in self.servo_data and self.servo_data[servo_id].connected:
                try:
                    # 直接读取2字节原始数据，避免符号转换
                    position, result, error = self.servo_handler.read2ByteTxRx(
                        servo_id, SMS_STS_PRESENT_POSITION_L
                    )
                    if result == COMM_SUCCESS:
                        self.servo_data[servo_id].current_pos = position

                        # 更新最小值
                        if position < self.servo_data[servo_id].min_pos:
                            self.servo_data[servo_id].min_pos = position

                        # 更新最大值
                        if position > self.servo_data[servo_id].max_pos:
                            self.servo_data[servo_id].max_pos = position
                    else:
                        success = False
                except Exception as e:
                    self.status_changed.emit(tr("❌ 读取ID{}位置失败: {}").format(servo_id, e))
                    success = False

        return success

    def start_monitoring(self):
        """启动监控"""
        if not self.connect():
            return

        found_servos = self.scan_servos()
        if not found_servos:
            self.status_changed.emit(tr("⚠️ 未发现舵机"))
            return

        self.running = True
        self.status_changed.emit(tr("🚀 开始监控 {} 个舵机...").format(len(found_servos)))

        # 启动监控线程
        thread = Thread(target=self._monitor_loop, daemon=True)
        thread.start()

    def stop_monitoring(self):
        """停止监控"""
        self.running = False
        self.disconnect()

    def _monitor_loop(self):
        """监控循环 - 支持热插拔"""
        while self.running:
            try:
                # 每次循环都扫描舵机（热插拔检测）
                self.scan_servos()

                # 读取位置数据
                if self.read_positions():
                    self.data_updated.emit(list(self.servo_data.values()))
                time.sleep(0.1)  # 100ms更新间隔
            except Exception as e:
                self.status_changed.emit(tr("❌ 监控异常: {}").format(e))
                time.sleep(1)

    def reset_min_max(self):
        """重置MIN/MAX值 - 重新记录"""
        for servo_id in self.servo_data:
            self.servo_data[servo_id].min_pos = 4095
            self.servo_data[servo_id].max_pos = 0
        self.status_changed.emit(tr("🔄 MIN/MAX值已重置，可重新开始记录"))

    def write_angle_limits(self) -> bool:
        """写入位置限制到EEPROM"""
        success_count = 0
        self.status_changed.emit(tr("💾 开始写入位置限制..."))

        for servo_id in self.servo_data:
            if self.servo_data[servo_id].connected:
                try:
                    # 解锁EEPROM
                    result, error = self.servo_handler.unLockEprom(servo_id)
                    if result != COMM_SUCCESS:
                        self.status_changed.emit(tr("  ❌ ID{}: EEPROM解锁失败").format(servo_id))
                        continue

                    time.sleep(0.05)

                    # 写入最小角度限制
                    min_pos = self.servo_data[servo_id].min_pos
                    result, error = self.servo_handler.write2ByteTxRx(
                        servo_id, SMS_STS_MIN_ANGLE_LIMIT_L, min_pos
                    )
                    if result != COMM_SUCCESS:
                        self.status_changed.emit(tr("  ❌ ID{}: 写入最小角度失败").format(servo_id))
                        self.servo_handler.LockEprom(servo_id)
                        continue

                    time.sleep(0.05)

                    # 写入最大角度限制
                    max_pos = self.servo_data[servo_id].max_pos
                    result, error = self.servo_handler.write2ByteTxRx(
                        servo_id, SMS_STS_MAX_ANGLE_LIMIT_L, max_pos
                    )
                    if result != COMM_SUCCESS:
                        self.status_changed.emit(tr("  ❌ ID{}: 写入最大角度失败").format(servo_id))
                        self.servo_handler.LockEprom(servo_id)
                        continue

                    time.sleep(0.05)

                    # 锁定EEPROM
                    self.servo_handler.LockEprom(servo_id)

                    success_count += 1
                    min_pos = self.servo_data[servo_id].min_pos
                    max_pos = self.servo_data[servo_id].max_pos
                    self.status_changed.emit(
                        tr("  ✅ ID{}: 最小值{}, 最大值{}").format(servo_id, min_pos, max_pos)
                    )

                except Exception as e:
                    self.status_changed.emit(tr("  ❌ ID{}: 写入异常 {}").format(servo_id, e))

        self.status_changed.emit(
            tr("✅ 写入完成: {}/{} 个舵机").format(success_count, len(self.servo_data))
        )
        return success_count > 0


class AngleLimitGUI(QMainWindow):
    """位置限制设置GUI"""

    # 基准窗口尺寸（用于计算缩放比例）
    BASE_WIDTH = 750
    BASE_HEIGHT = 520

    def __init__(self, port_name: str = None):
        super().__init__()
        self.port_name = port_name
        self.worker = None
        self.port_refresh_timer = None
        # 保存采集的数据，停止监控后仍可写入
        self.collected_data: Dict[int, ServoData] = {}
        # 保存上一次的数据，用于检测变化
        self.last_data: Dict[int, dict] = {}
        # 闪烁状态管理
        self.flash_cells: Dict[tuple, int] = {}  # (row, col) -> flash_count
        self.flash_timer = None
        # 缩放比例
        self.scale_factor = 1.0

        self.init_ui()
        self.init_connections()
        self.refresh_ports()
        self.start_port_refresh_timer()  # 启动串口自动刷新
        self.start_flash_timer()  # 启动闪烁定时器

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle(tr("舵机位置限制设置工具"))
        self.setGeometry(100, 100, 750, 520)
        self.setMinimumSize(600, 400)  # 设置最小尺寸

        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setSpacing(8)
        self.main_layout.setContentsMargins(12, 8, 12, 8)

        # 控制面板
        self.create_control_panel(self.main_layout)

        # 数据显示表格
        self.create_data_table(self.main_layout)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(tr("就绪"))

        # 应用初始样式
        self.apply_scaled_styles()

    def apply_scaled_styles(self):
        """应用缩放后的样式"""
        s = self.scale_factor

        # 计算缩放后的尺寸
        group_font = int(13 * s)
        btn_font = int(12 * s)
        btn_height = int(28 * s)
        btn_padding_v = int(6 * s)
        btn_padding_h = int(12 * s)
        btn_radius = int(4 * s)
        table_font = int(13 * s)
        header_font = int(12 * s)
        header_padding = int(6 * s)
        combo_height = int(24 * s)
        status_font = int(12 * s)
        group_radius = int(6 * s)
        group_margin = int(8 * s)

        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: #f8f9fa;
            }}
            QGroupBox {{
                font-weight: bold;
                font-size: {group_font}px;
                color: #37474f;
                border: 1px solid #cfd8dc;
                border-radius: {group_radius}px;
                margin-top: {group_margin}px;
                padding: {group_margin}px {btn_padding_v}px {btn_padding_v}px {btn_padding_v}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {int(12 * s)}px;
                padding: 0 {btn_padding_v}px;
            }}
            QPushButton {{
                background-color: #546e7a;
                color: white;
                border: none;
                padding: {btn_padding_v}px {btn_padding_h}px;
                border-radius: {btn_radius}px;
                font-size: {btn_font}px;
                font-weight: bold;
                min-height: {btn_height}px;
            }}
            QPushButton:hover {{
                background-color: #455a64;
            }}
            QPushButton:pressed {{
                background-color: #37474f;
            }}
            QPushButton:disabled {{
                background-color: #b0bec5;
                color: #eceff1;
            }}
            QPushButton#startBtn {{
                background-color: #43a047;
            }}
            QPushButton#startBtn:hover {{
                background-color: #388e3c;
            }}
            QPushButton#stopBtn {{
                background-color: #e53935;
            }}
            QPushButton#stopBtn:hover {{
                background-color: #c62828;
            }}
            QPushButton#writeBtn {{
                background-color: #1e88e5;
            }}
            QPushButton#writeBtn:hover {{
                background-color: #1565c0;
            }}
            QPushButton#resetBtn {{
                background-color: #ff9800;
            }}
            QPushButton#resetBtn:hover {{
                background-color: #f57c00;
            }}
            QPushButton#readBtn {{
                background-color: #7e57c2;
            }}
            QPushButton#readBtn:hover {{
                background-color: #5e35b1;
            }}
            QPushButton#refreshBtn {{
                background-color: #00acc1;
            }}
            QPushButton#refreshBtn:hover {{
                background-color: #00838f;
            }}
            QPushButton#startBtn:disabled,
            QPushButton#stopBtn:disabled,
            QPushButton#resetBtn:disabled,
            QPushButton#readBtn:disabled,
            QPushButton#writeBtn:disabled,
            QPushButton#refreshBtn:disabled {{
                background-color: #b0bec5;
                color: #eceff1;
            }}
            QTableWidget {{
                background-color: white;
                border: 1px solid #cfd8dc;
                border-radius: {btn_radius}px;
                gridline-color: #eceff1;
                font-size: {table_font}px;
            }}
            QTableWidget::item {{
                padding: {int(4 * s)}px;
            }}
            QHeaderView::section {{
                background-color: #455a64;
                color: white;
                padding: {header_padding}px;
                border: none;
                font-weight: bold;
                font-size: {header_font}px;
            }}
            QComboBox {{
                padding: {int(4 * s)}px {int(8 * s)}px;
                border: 1px solid #b0bec5;
                border-radius: {btn_radius}px;
                background: white;
                min-height: {combo_height}px;
                font-size: {btn_font}px;
            }}
            QComboBox:hover {{
                border-color: #78909c;
            }}
            QComboBox QAbstractItemView {{
                font-size: {btn_font}px;
            }}
            QStatusBar {{
                background-color: #eceff1;
                color: #546e7a;
                font-size: {status_font}px;
            }}
            QLabel {{
                font-size: {int(11 * s)}px;
            }}
        """)

        # 更新表格字体和行高
        table_font_obj = QFont("Consolas", int(12 * s))
        self.data_table.setFont(table_font_obj)
        self.data_table.verticalHeader().setDefaultSectionSize(int(32 * s))

        # 更新按钮宽度
        self.refresh_btn.setMinimumWidth(int(50 * s))
        self.start_btn.setMinimumWidth(int(70 * s))
        self.stop_btn.setMinimumWidth(int(70 * s))
        self.reset_btn.setMinimumWidth(int(55 * s))
        self.read_limits_btn.setMinimumWidth(int(55 * s))
        self.write_btn.setMinimumWidth(int(95 * s))
        self.port_combo.setMinimumWidth(int(110 * s))

        # 更新提示标签样式
        self.info_label.setStyleSheet(f"""
            background-color: #e8f5e9;
            border: 1px solid #c8e6c9;
            padding: {int(6 * s)}px {int(10 * s)}px;
            border-radius: {btn_radius}px;
            color: #2e7d32;
            font-size: {int(11 * s)}px;
        """)

    def resizeEvent(self, event):
        """窗口大小改变事件 - 动态缩放"""
        super().resizeEvent(event)

        # 计算新的缩放比例（取宽高缩放比例的较小值）
        width_scale = self.width() / self.BASE_WIDTH
        height_scale = self.height() / self.BASE_HEIGHT
        new_scale = min(width_scale, height_scale)

        # 只有当缩放比例变化超过阈值时才更新（避免频繁刷新）
        if abs(new_scale - self.scale_factor) > 0.05:
            self.scale_factor = new_scale
            self.apply_scaled_styles()

    def create_control_panel(self, layout):
        """创建控制面板 - 紧凑布局"""
        control_group = QGroupBox(tr("控制面板"))
        control_layout = QHBoxLayout(control_group)
        control_layout.setSpacing(8)
        control_layout.setContentsMargins(10, 10, 10, 10)

        # 串口选择（紧凑横向布局）
        self.port_label = QLabel(tr("串口:"))
        self.port_label.setStyleSheet("font-weight: bold; color: #455a64;")
        control_layout.addWidget(self.port_label)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(110)
        control_layout.addWidget(self.port_combo)

        self.refresh_btn = QPushButton(tr("刷新"))
        self.refresh_btn.setObjectName("refreshBtn")
        self.refresh_btn.setMinimumWidth(50)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        control_layout.addWidget(self.refresh_btn)

        # 分隔线
        control_layout.addSpacing(15)

        # 操作按钮组
        self.start_btn = QPushButton(tr("▶ 开始"))
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setMinimumWidth(70)
        self.start_btn.clicked.connect(self.start_monitoring)
        control_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton(tr("■ 停止"))
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setMinimumWidth(70)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_monitoring)
        control_layout.addWidget(self.stop_btn)

        self.reset_btn = QPushButton(tr("重置"))
        self.reset_btn.setObjectName("resetBtn")
        self.reset_btn.setMinimumWidth(55)
        self.reset_btn.clicked.connect(self.reset_min_max)
        control_layout.addWidget(self.reset_btn)

        control_layout.addSpacing(15)

        self.read_limits_btn = QPushButton(tr("读取"))
        self.read_limits_btn.setObjectName("readBtn")
        self.read_limits_btn.setMinimumWidth(55)
        self.read_limits_btn.clicked.connect(self.read_current_limits)
        control_layout.addWidget(self.read_limits_btn)

        self.write_btn = QPushButton(tr("写入EEPROM"))
        self.write_btn.setObjectName("writeBtn")
        self.write_btn.setMinimumWidth(95)
        self.write_btn.setEnabled(False)
        self.write_btn.clicked.connect(self.write_limits)
        control_layout.addWidget(self.write_btn)

        control_layout.addStretch()
        layout.addWidget(control_group)

    def create_data_table(self, layout):
        """创建数据表格"""
        table_group = QGroupBox(tr("实时位置数据"))
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(8, 12, 8, 8)

        self.data_table = QTableWidget(6, 4)  # 6行4列
        self.data_table.setHorizontalHeaderLabels([
            "ID", "MIN", "POS", "MAX"
        ])

        # 设置表格属性
        header = self.data_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.setShowGrid(True)

        # 设置字体
        font = QFont("Consolas", 12)
        self.data_table.setFont(font)

        # 设置行高
        self.data_table.verticalHeader().setDefaultSectionSize(32)

        # 初始化表格数据
        for row in range(6):
            servo_id = row + 1
            item = QTableWidgetItem(f"{servo_id}")
            item.setTextAlignment(Qt.AlignCenter)
            self.data_table.setItem(row, 0, item)
            for col in range(1, 4):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignCenter)
                self.data_table.setItem(row, col, item)

        table_layout.addWidget(self.data_table)

        # 简洁说明
        self.info_label = QLabel(
            tr("操作: 开始→转动舵机采集范围→停止→写入EEPROM | 热插拔后请先重置 | 读取可查看已标定值")
        )
        self.info_label.setStyleSheet("""
            background-color: #e8f5e9;
            border: 1px solid #c8e6c9;
            padding: 6px 10px;
            border-radius: 4px;
            color: #2e7d32;
            font-size: 11px;
        """)
        table_layout.addWidget(self.info_label)

        layout.addWidget(table_group)

    def init_connections(self):
        """初始化信号连接"""
        self.port_combo.currentTextChanged.connect(self.on_port_changed)

    def refresh_ports(self):
        """刷新串口列表 - 实时检测可用串口"""
        available_ports = get_available_ports()

        # 保存当前选择的端口
        current_port = self.port_combo.currentText() if self.port_combo.count() > 0 else ""

        # 清空下拉框
        self.port_combo.clear()

        # 添加可用串口
        if available_ports:
            self.port_combo.addItems(available_ports)

            # 尝试恢复之前的选择
            if current_port and current_port in available_ports:
                self.port_combo.setCurrentText(current_port)
            elif self.port_name and self.port_name in available_ports:
                self.port_combo.setCurrentText(self.port_name)
            else:
                self.port_combo.setCurrentIndex(0)
        else:
            # 没有可用串口，添加提示
            self.port_combo.addItem(tr("未检测到串口"))
            self.port_combo.setEnabled(False)

        self.update_status(tr("检测到 {} 个可用串口").format(len(available_ports)))

    def start_flash_timer(self):
        """启动闪烁定时器"""
        if self.flash_timer is None:
            self.flash_timer = QTimer()
            self.flash_timer.timeout.connect(self.process_flash)
            self.flash_timer.start(150)  # 150ms闪烁间隔

    def process_flash(self):
        """处理闪烁效果"""
        cells_to_remove = []
        for (row, col), count in self.flash_cells.items():
            item = self.data_table.item(row, col)
            if item:
                if count % 2 == 0:
                    # 闪烁时显示亮橙色高亮
                    item.setBackground(QColor(255, 167, 38))  # 亮橙色
                else:
                    # 恢复原色（柔和色调）
                    if col == 1:  # MIN
                        item.setBackground(QColor(255, 205, 210))  # 柔和红
                    elif col == 2:  # POS
                        item.setBackground(QColor(200, 230, 201))  # 柔和绿
                    elif col == 3:  # MAX
                        item.setBackground(QColor(187, 222, 251))  # 柔和蓝

                self.flash_cells[(row, col)] = count - 1
                if count <= 1:
                    cells_to_remove.append((row, col))

        for cell in cells_to_remove:
            del self.flash_cells[cell]

    def trigger_flash(self, row: int, col: int):
        """触发单元格闪烁"""
        self.flash_cells[(row, col)] = 6  # 闪烁3次（6次切换）

    def start_port_refresh_timer(self):
        """启动串口刷新定时器"""
        if self.port_refresh_timer is None:
            self.port_refresh_timer = QTimer()
            self.port_refresh_timer.timeout.connect(self.refresh_ports)
            self.port_refresh_timer.start(2000)  # 每2秒刷新一次

    def stop_port_refresh_timer(self):
        """停止串口刷新定时器"""
        if self.port_refresh_timer:
            self.port_refresh_timer.stop()
            self.port_refresh_timer = None

    def on_port_changed(self, port_name):
        """端口改变"""
        if port_name and port_name != tr("未检测到串口"):
            self.port_name = port_name

    def start_monitoring(self):
        """开始监控"""
        if self.worker and self.worker.running:
            return

        if not self.port_name or self.port_name == tr("未检测到串口"):
            self.update_status(tr("❌ 请选择有效的串口"))
            return

        self.worker = ServoMonitorWorker(self.port_name)
        self.worker.data_updated.connect(self.update_table)
        self.worker.status_changed.connect(self.update_status)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.write_btn.setEnabled(False)

        # 停止串口刷新（避免冲突）
        self.stop_port_refresh_timer()

        self.worker.start_monitoring()

    def stop_monitoring(self):
        """停止监控"""
        if self.worker:
            # 保存采集的数据
            self.collected_data = dict(self.worker.servo_data)
            self.worker.stop_monitoring()
            self.worker = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        # 只有采集到数据才启用写入按钮
        self.write_btn.setEnabled(len(self.collected_data) > 0)

        # 恢复串口刷新
        self.refresh_ports()
        self.start_port_refresh_timer()

    def reset_min_max(self):
        """重置MIN/MAX记录"""
        if self.worker:
            self.worker.reset_min_max()
            # 清空表格中的MIN/MAX数据
            for row in range(6):
                self.data_table.setItem(row, 1, QTableWidgetItem("--"))
                self.data_table.setItem(row, 3, QTableWidgetItem("--"))

    def read_current_limits(self):
        """读取当前EEPROM中存储的角度限制"""
        if not self.port_name or self.port_name == tr("未检测到串口"):
            self.update_status(tr("❌ 请选择有效的串口"))
            return

        # 临时连接读取
        try:
            port_handler = PortHandler(self.port_name)
            if not port_handler.openPort():
                self.update_status(tr("❌ 无法打开串口: {}").format(self.port_name))
                return
            if not port_handler.setBaudRate(1000000):
                self.update_status(tr("❌ 无法设置波特率"))
                port_handler.closePort()
                return

            servo_handler = sms_sts(port_handler)
            self.update_status(tr("📖 正在读取EEPROM中的角度限制..."))

            results = []
            for servo_id in range(1, 7):
                try:
                    # ping检测舵机是否存在
                    _, result, _ = servo_handler.ping(servo_id)
                    if result != COMM_SUCCESS:
                        results.append(tr("ID{}: 未连接").format(servo_id))
                        continue

                    # 读取最小角度限制
                    min_val, result, _ = servo_handler.read2ByteTxRx(
                        servo_id, SMS_STS_MIN_ANGLE_LIMIT_L
                    )
                    if result != COMM_SUCCESS:
                        results.append(tr("ID{}: 读取失败").format(servo_id))
                        continue

                    # 读取最大角度限制
                    max_val, result, _ = servo_handler.read2ByteTxRx(
                        servo_id, SMS_STS_MAX_ANGLE_LIMIT_L
                    )
                    if result != COMM_SUCCESS:
                        results.append(tr("ID{}: 读取失败").format(servo_id))
                        continue

                    results.append(f"ID{servo_id}: MIN={min_val}, MAX={max_val}")
                except Exception as e:
                    results.append(tr("ID{}: 异常 {}").format(servo_id, e))

            port_handler.closePort()

            # 显示结果
            msg = tr("当前EEPROM中存储的角度限制：\n\n") + "\n".join(results)
            QMessageBox.information(self, tr("📖 角度限制读取结果"), msg)
            self.update_status(tr("✅ 角度限制读取完成"))

        except Exception as e:
            self.update_status(tr("❌ 读取失败: {}").format(e))

    def write_limits(self):
        """写入角度限制 - 使用保存的采集数据"""
        if not self.collected_data:
            self.update_status(tr("❌ 没有采集到数据，请先开始监控并采集MIN/MAX值"))
            return

        # 检查是否有有效的MIN/MAX数据
        valid_count = 0
        for servo_id, data in self.collected_data.items():
            if data.min_pos != 4095 and data.max_pos != 0:
                valid_count += 1

        if valid_count == 0:
            self.update_status(tr("❌ 没有有效的MIN/MAX数据，请先转动舵机采集范围"))
            return

        reply = QMessageBox.question(
            self,
            tr("确认写入"),
            tr("确定要将采集到的位置限制写入到舵机EEPROM吗？\n共有 {} 个舵机的数据将被写入。\n此操作将永久修改舵机的角度限制设置！").format(valid_count),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # 执行写入
        try:
            port_handler = PortHandler(self.port_name)
            if not port_handler.openPort():
                self.update_status(tr("❌ 无法打开串口: {}").format(self.port_name))
                return
            if not port_handler.setBaudRate(1000000):
                self.update_status(tr("❌ 无法设置波特率"))
                port_handler.closePort()
                return

            servo_handler = sms_sts(port_handler)
            self.update_status(tr("💾 开始写入位置限制..."))

            success_count = 0
            results = []

            for servo_id, data in self.collected_data.items():
                # 跳过没有有效数据的舵机
                if data.min_pos == 4095 or data.max_pos == 0:
                    results.append(tr("ID{}: 跳过（无有效数据）").format(servo_id))
                    continue

                try:
                    # 解锁EEPROM
                    result, error = servo_handler.unLockEprom(servo_id)
                    if result != COMM_SUCCESS:
                        results.append(tr("ID{}: EEPROM解锁失败").format(servo_id))
                        continue

                    time.sleep(0.05)

                    # 写入最小角度限制
                    result, error = servo_handler.write2ByteTxRx(
                        servo_id, SMS_STS_MIN_ANGLE_LIMIT_L, data.min_pos
                    )
                    if result != COMM_SUCCESS:
                        results.append(tr("ID{}: 写入MIN失败").format(servo_id))
                        servo_handler.LockEprom(servo_id)
                        continue

                    time.sleep(0.05)

                    # 写入最大角度限制
                    result, error = servo_handler.write2ByteTxRx(
                        servo_id, SMS_STS_MAX_ANGLE_LIMIT_L, data.max_pos
                    )
                    if result != COMM_SUCCESS:
                        results.append(tr("ID{}: 写入MAX失败").format(servo_id))
                        servo_handler.LockEprom(servo_id)
                        continue

                    time.sleep(0.05)

                    # 锁定EEPROM
                    servo_handler.LockEprom(servo_id)

                    success_count += 1
                    results.append(tr("ID{}: ✅ MIN={}, MAX={}").format(servo_id, data.min_pos, data.max_pos))

                except Exception as e:
                    results.append(tr("ID{}: 异常 {}").format(servo_id, e))

            port_handler.closePort()

            # 显示结果
            msg = tr("写入完成: {}/{}\n\n").format(success_count, valid_count) + "\n".join(results)
            QMessageBox.information(self, tr("💾 写入结果"), msg)
            self.update_status(tr("✅ 写入完成: {}/{}").format(success_count, valid_count))

        except Exception as e:
            self.update_status(tr("❌ 写入失败: {}").format(e))

    def update_table(self, servo_data_list: List[ServoData]):
        """更新表格数据 - 显示原始位置值，变化时闪烁"""
        for servo_data in servo_data_list:
            row = servo_data.id - 1
            servo_id = servo_data.id

            # 获取上一次的数据
            last = self.last_data.get(servo_id, {})

            # POS (当前位置值) - 变化超过阈值才闪烁
            pos_item = QTableWidgetItem(str(servo_data.current_pos))
            pos_item.setTextAlignment(Qt.AlignCenter)
            if abs(servo_data.current_pos - 2048) < 10:
                pos_item.setBackground(QColor(200, 230, 201))  # 柔和绿
            self.data_table.setItem(row, 2, pos_item)
            if 'pos' in last and abs(servo_data.current_pos - last['pos']) > 50:
                self.trigger_flash(row, 2)

            # MIN (最小位置值) - 更新时闪烁
            if servo_data.min_pos != 4095:
                min_item = QTableWidgetItem(str(servo_data.min_pos))
                min_item.setTextAlignment(Qt.AlignCenter)
                min_item.setBackground(QColor(255, 205, 210))  # 柔和红
                self.data_table.setItem(row, 1, min_item)
                if 'min' in last and servo_data.min_pos != last['min']:
                    self.trigger_flash(row, 1)
            else:
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignCenter)
                self.data_table.setItem(row, 1, item)

            # MAX (最大位置值) - 更新时闪烁
            if servo_data.max_pos != 0:
                max_item = QTableWidgetItem(str(servo_data.max_pos))
                max_item.setTextAlignment(Qt.AlignCenter)
                max_item.setBackground(QColor(187, 222, 251))  # 柔和蓝
                self.data_table.setItem(row, 3, max_item)
                if 'max' in last and servo_data.max_pos != last['max']:
                    self.trigger_flash(row, 3)
            else:
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignCenter)
                self.data_table.setItem(row, 3, item)

            # 保存当前数据用于下次比较
            self.last_data[servo_id] = {
                'pos': servo_data.current_pos,
                'min': servo_data.min_pos,
                'max': servo_data.max_pos
            }

    def update_status(self, message: str):
        """更新状态栏"""
        self.status_bar.showMessage(message, 3000)

    def closeEvent(self, event):
        """关闭事件"""
        # 停止所有任务
        if self.worker:
            self.worker.stop_monitoring()
        self.stop_port_refresh_timer()
        super().closeEvent(event)


def get_available_ports():
    """获取可用串口列表 - 根据操作系统实时检测"""
    import platform
    system = platform.system()

    try:
        import serial.tools.list_ports
        ports = []

        if system == "Windows":
            # Windows: 检测所有COM口
            for port in serial.tools.list_ports.comports():
                if port.device.startswith('COM'):
                    ports.append(port.device)
        else:
            # Linux: 检测ttyACM*和ttyUSB*
            for port in serial.tools.list_ports.comports():
                device = port.device
                if device.startswith('/dev/ttyACM') or device.startswith('/dev/ttyUSB'):
                    ports.append(device)

        return sorted(ports)
    except ImportError:
        # 如果没有pyserial，返回空列表（不显示不存在的东西）
        return []


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description=tr('舵机位置限制设置工具'))
    parser.add_argument('--port', type=str, default=None, help=tr('指定串口（不指定则自动检测）'))
    parser.add_argument('--list-ports', action='store_true', help=tr('列出可用串口'))
    parser.add_argument('--lang', choices=['zh', 'en'], default=None,
                        help=tr('界面语言 (zh=中文, en=English)，不指定则启动时选择'))
    args = parser.parse_args()

    if args.list_ports:
        ports = get_available_ports()
        print(tr("可用串口:"))
        if ports:
            for port in ports:
                print(f"  {port}")
        else:
            print(tr("  未检测到可用串口"))
        return

    app = QApplication(sys.argv)
    if setup_light_theme:
        setup_light_theme(app)
    else:
        app.setStyle('Fusion')

    # 语言选择：--lang 指定时直接使用，否则弹出选择对话框
    if args.lang:
        set_lang(args.lang)
    else:
        from src.gui.language_dialog import choose_language
        set_lang(choose_language())

    # 使用命令行参数中的端口，但允许为None（自动检测）
    window = AngleLimitGUI(args.port)
    window.show()

    if args.port:
        print(tr("启动位置限制设置工具 - 串口: {}").format(args.port))
    else:
        print(tr("启动位置限制设置工具 - 自动检测串口"))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
