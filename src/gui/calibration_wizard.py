#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LeRobot 校准向导对话框
在 GUI 上引导用户完成整臂校准，实时显示每个舵机的当前位置、中位值、范围
"""

import sys
import os
import time
import json
import platform
from pathlib import Path
from typing import Dict, List, Optional

sys.path.append('../..')
sys.path.append('../../scservo_sdk')

try:
    from PySide6.QtWidgets import (
        QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
        QMessageBox, QProgressBar, QGroupBox, QFormLayout, QLineEdit,
        QComboBox, QDialogButtonBox, QFileDialog
    )
    from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
    from PySide6.QtGui import QColor, QFont
except ImportError as e:
    print(f"❌ 无法导入 PySide6: {e}")
    sys.exit(1)

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError as e:
    print(f"❌ 无法导入 SCServo SDK: {e}")
    sys.exit(1)

try:
    from src.calibration_manager import CalibrationManager, JOINT_NAME_MAP
except ImportError:
    print("❌ 无法导入 calibration_manager")
    sys.exit(1)

try:
    from src.gui.theme_utils import setup_light_theme
except ImportError:
    setup_light_theme = None


BAUD_RATE = 1000000
TORQUE_ENABLE_ADDR = 40
TORQUE_ON = 1
TORQUE_OFF = 0

# ID -> 关节名映射（SO-10x 标准配置）
ID_TO_JOINT = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
}

# 连续旋转关节
CONTINUOUS_JOINTS = {"wrist_roll"}


def get_chinese_font(size=10, bold=False):
    """返回跨平台可用的中文字体。

    Ubuntu 下通常有 Noto Sans CJK / WenQuanYi 等回退字体，Qt 能正常显示中文；
    Windows 下如果显式使用西文字体（如 Consolas）显示中文表头，会出现缺字/空白。
    这里按平台选择主字体，并设置 SansSerif 风格提示以便自动回退。
    """
    system = platform.system()
    if system == "Windows":
        family = "Microsoft YaHei"
    elif system == "Darwin":
        family = "PingFang SC"
    else:
        # Linux / Ubuntu 等
        family = "Noto Sans CJK SC"

    font = QFont(family, size)
    font.setStyleHint(QFont.SansSerif)
    if bold:
        font.setBold(True)
    return font


class PositionReader(QObject):
    """后台位置读取线程"""
    positions_updated = Signal(dict)  # {servo_id: position}
    error_occurred = Signal(str)

    def __init__(self, servo_handler, servo_ids: List[int]):
        super().__init__()
        self.servo_handler = servo_handler
        self.servo_ids = servo_ids
        self.running = False
        self.error_counts = {sid: 0 for sid in servo_ids}

    def start_reading(self):
        self.running = True
        while self.running:
            positions = {}
            for servo_id in self.servo_ids:
                try:
                    pos, result, error = self.servo_handler.ReadPos(servo_id)
                    if result == COMM_SUCCESS:
                        positions[servo_id] = pos
                        self.error_counts[servo_id] = 0
                    else:
                        self.error_counts[servo_id] += 1
                        if self.error_counts[servo_id] <= 5:
                            print(f"[DEBUG] 读取 ID{servo_id} 失败: result={result}, error={error}")
                except Exception as e:
                    self.error_counts[servo_id] += 1
                    if self.error_counts[servo_id] <= 5:
                        print(f"[DEBUG] 读取 ID{servo_id} 异常: {e}")
            self.positions_updated.emit(positions)
            time.sleep(0.05)  # 20Hz

    def stop(self):
        self.running = False


class ReaderThread(QThread):
    """Qt 线程包装器"""
    def __init__(self, reader: PositionReader):
        super().__init__()
        self.reader = reader

    def run(self):
        self.reader.start_reading()

    def stop(self):
        self.reader.stop()
        self.wait(1000)


class CalibrationWizard(QDialog):
    """LeRobot 校准向导"""

    def __init__(self, port_name: str, arm_type: str = "follower", preload_file: str = None, parent=None):
        super().__init__(parent)
        self.port_name = port_name
        self.arm_type = arm_type
        self.preload_file = preload_file
        title = f"LeRobot 校准向导 - {port_name}"
        if preload_file:
            title += " (基于现有文件)"
        self.setWindowTitle(title)
        self.setMinimumSize(900, 650)
        self.setFont(get_chinese_font(10))

        # 串口对象
        self.port_handler = None
        self.servo_handler = None

        # 校准数据
        self.joints: List[Dict] = []
        self.current_joint_index = 0
        self.is_recording = False

        # 后台读取
        self.position_reader = None
        self.reader_thread = None

        self.init_ui()
        self.connect_port()

    def init_ui(self):
        """初始化界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        title = QLabel(f"🦾 LeRobot 校准向导 - {'领导臂' if self.arm_type == 'leader' else '从动臂'}")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # 状态信息
        self.status_label = QLabel(f"串口: {self.port_name} | 状态: 初始化中...")
        self.status_label.setStyleSheet("font-size: 12px; color: #6c757d;")
        main_layout.addWidget(self.status_label)

        # 主内容区：左侧表格 + 右侧操作
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)

        # 左侧：关节数据表格
        table_group = QGroupBox("📋 关节校准数据")
        table_layout = QVBoxLayout(table_group)

        self.joints_table = QTableWidget(6, 6)
        self.joints_table.setHorizontalHeaderLabels([
            "ID", "当前位置", "中位值", "最小值", "最大值", "状态"
        ])
        header = self.joints_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        # 让数值列稍微宽一点
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.joints_table.setColumnWidth(0, 50)
        self.joints_table.setAlternatingRowColors(True)
        self.joints_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.joints_table.verticalHeader().setVisible(False)
        self.joints_table.setFont(get_chinese_font(10))

        # 初始化行
        for i, servo_id in enumerate(range(1, 7)):
            joint_name = ID_TO_JOINT.get(servo_id, f"joint_{servo_id}")
            # 校准向导界面使用纯中文名称，去掉英文对照
            display_name = JOINT_NAME_MAP.get(joint_name, joint_name).split(" / ")[0]

            self.joints_table.setItem(i, 0, self._create_item(str(servo_id), align=Qt.AlignCenter))
            self.joints_table.setItem(i, 1, self._create_item("--", align=Qt.AlignCenter))
            self.joints_table.setItem(i, 2, self._create_item("--", align=Qt.AlignCenter))
            self.joints_table.setItem(i, 3, self._create_item("--", align=Qt.AlignCenter))
            self.joints_table.setItem(i, 4, self._create_item("--", align=Qt.AlignCenter))
            self.joints_table.setItem(i, 5, self._create_item("未校准", color="#dc3545"))

            self.joints.append({
                "id": servo_id,
                "name": joint_name,
                "display_name": display_name,
                "current_pos": None,
                "homing_offset": None,
                "range_min": None,
                "range_max": None,
                "status": "pending",  # pending, homing_done, done
            })

        self.joints_table.itemSelectionChanged.connect(self.on_selection_changed)
        self.joints_table.selectRow(0)

        table_layout.addWidget(self.joints_table)
        content_layout.addWidget(table_group, stretch=2)

        # 右侧：操作面板
        control_group = QGroupBox("🎮 操作面板")
        control_layout = QVBoxLayout(control_group)
        control_layout.setSpacing(15)

        # 当前关节显示
        self.current_joint_label = QLabel("当前关节: ID1 - 肩部平转")
        self.current_joint_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #495057;")
        control_layout.addWidget(self.current_joint_label)

        # 当前位置大字显示
        self.current_pos_label = QLabel("当前位置: --")
        self.current_pos_label.setStyleSheet(
            "font-size: 36px; font-weight: bold; color: #007bff; "
            "background-color: #e9ecef; padding: 15px; border-radius: 8px;"
        )
        self.current_pos_label.setAlignment(Qt.AlignCenter)
        self.current_pos_label.setMinimumHeight(80)
        control_layout.addWidget(self.current_pos_label)

        # 步骤说明
        self.instruction_label = QLabel(
            "步骤 1/2：请将当前关节移动到运动范围的中间位置，\n"
            "然后点击【记录中位值】按钮。"
        )
        self.instruction_label.setStyleSheet(
            "font-size: 13px; color: #1565c0; background-color: #e3f2fd; "
            "padding: 12px; border-radius: 6px;"
        )
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setMinimumHeight(80)
        control_layout.addWidget(self.instruction_label)

        # 记录中位按钮
        self.record_home_btn = QPushButton("✅ 记录中位值")
        self.record_home_btn.setStyleSheet(self._button_style("#28a745"))
        self.record_home_btn.setMinimumHeight(45)
        self.record_home_btn.clicked.connect(self.record_homing)
        control_layout.addWidget(self.record_home_btn)

        # 记录范围按钮
        self.record_range_layout = QHBoxLayout()
        self.start_range_btn = QPushButton("▶ 开始记录范围")
        self.start_range_btn.setStyleSheet(self._button_style("#007bff"))
        self.start_range_btn.setMinimumHeight(45)
        self.start_range_btn.clicked.connect(self.start_range_recording)

        self.stop_range_btn = QPushButton("⏹ 停止记录范围")
        self.stop_range_btn.setStyleSheet(self._button_style("#dc3545"))
        self.stop_range_btn.setMinimumHeight(45)
        self.stop_range_btn.setEnabled(False)
        self.stop_range_btn.clicked.connect(self.stop_range_recording)

        self.record_range_layout.addWidget(self.start_range_btn)
        self.record_range_layout.addWidget(self.stop_range_btn)
        control_layout.addLayout(self.record_range_layout)

        # 导航按钮
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 上一个关节")
        self.prev_btn.setStyleSheet(self._button_style("#6c757d"))
        self.prev_btn.clicked.connect(self.prev_joint)

        self.next_btn = QPushButton("下一个关节 ▶")
        self.next_btn.setStyleSheet(self._button_style("#17a2b8"))
        self.next_btn.clicked.connect(self.next_joint)

        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        control_layout.addLayout(nav_layout)

        control_layout.addStretch()

        # 保存设置
        save_group = QGroupBox("💾 保存设置")
        save_group.setMinimumHeight(120)
        save_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #212529;
                border: 2px solid #6f42c1;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 5px;
                color: #212529;
            }
            QLabel {
                color: #212529;
                font-size: 13px;
                font-weight: bold;
            }
        """)
        save_layout = QFormLayout(save_group)
        save_layout.setSpacing(10)
        save_layout.setContentsMargins(15, 20, 15, 15)

        self.id_input = QLineEdit()
        self.id_input.setMinimumHeight(35)
        self.id_input.setMinimumWidth(220)
        self.id_input.setFont(get_chinese_font(12))
        self.id_input.setStyleSheet("""
            QLineEdit {
                color: #212529;
                background-color: #ffffff;
                border: 2px solid #ced4da;
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 2px solid #6f42c1;
                background-color: #ffffff;
            }
        """)
        default_id = "my_awesome_leader_arm" if self.arm_type == "leader" else "my_awesome_follower_arm"
        self.id_input.setText(default_id)
        save_layout.addRow("校准文件 ID:", self.id_input)

        control_layout.addWidget(save_group)

        # 保存按钮
        self.save_btn = QPushButton("💾 保存校准文件")
        self.save_btn.setStyleSheet(self._button_style("#6f42c1"))
        self.save_btn.setMinimumHeight(55)
        self.save_btn.setFont(get_chinese_font(12, bold=True))
        self.save_btn.clicked.connect(self.save_calibration)
        control_layout.addWidget(self.save_btn)

        content_layout.addWidget(control_group, stretch=1)
        main_layout.addLayout(content_layout)

        # 底部按钮
        bottom_layout = QHBoxLayout()
        self.disconnect_btn = QPushButton("🔌 断开连接")
        self.disconnect_btn.setStyleSheet(self._button_style("#6c757d"))
        self.disconnect_btn.clicked.connect(self.disconnect_and_close)
        bottom_layout.addWidget(self.disconnect_btn)

        bottom_layout.addStretch()

        self.close_btn = QPushButton("关闭")
        self.close_btn.setStyleSheet(self._button_style("#6c757d"))
        self.close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(self.close_btn)

        main_layout.addLayout(bottom_layout)

        # 定时器用于刷新 UI
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_ui)
        self.ui_timer.start(50)  # 20Hz UI 刷新

        # 范围记录专用定时器（高频读取当前关节）
        self.range_recording_timer = QTimer()
        self.range_recording_timer.timeout.connect(self._record_current_position)

    def _create_item(self, text, align=None, color=None):
        """创建表格项"""
        item = QTableWidgetItem(text)
        if align:
            item.setTextAlignment(align)
        # 显式设置前景/背景色，避免在 Windows 深色主题下继承黑色背景导致文字看不见
        if color:
            item.setForeground(QColor(color))
        else:
            item.setForeground(QColor("#212529"))
        item.setBackground(QColor("#ffffff"))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _button_style(self, color: str) -> str:
        """生成按钮样式"""
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self._darken_color(color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(color, 0.7)};
            }}
            QPushButton:disabled {{
                background-color: #6c757d;
            }}
        """

    def _darken_color(self, hex_color: str, factor: float = 0.85) -> str:
        """简单加深颜色"""
        hex_color = hex_color.lstrip('#')
        r = int(int(hex_color[0:2], 16) * factor)
        g = int(int(hex_color[2:4], 16) * factor)
        b = int(int(hex_color[4:6], 16) * factor)
        return f"#{max(0, r):02x}{max(0, g):02x}{max(0, b):02x}"

    def connect_port(self):
        """连接串口"""
        try:
            self.port_handler = PortHandler(self.port_name)
            if not self.port_handler.openPort():
                QMessageBox.critical(self, "错误", f"无法打开串口: {self.port_name}")
                return False
            if not self.port_handler.setBaudRate(BAUD_RATE):
                QMessageBox.critical(self, "错误", "无法设置波特率")
                self.port_handler.closePort()
                return False

            self.servo_handler = sms_sts(self.port_handler)

            # 扫描舵机
            found_servos = self.scan_servos()
            if not found_servos:
                QMessageBox.critical(self, "错误", "未发现舵机")
                self.port_handler.closePort()
                return False

            # 过滤出 1-6
            self.servo_ids = [sid for sid in found_servos if sid in ID_TO_JOINT]
            if not self.servo_ids:
                QMessageBox.critical(self, "错误", "未发现 SO-10x 标准关节（ID 1-6）")
                self.port_handler.closePort()
                return False

            # 检查缺失的标准关节
            expected_ids = set(ID_TO_JOINT.keys())
            found_ids = set(self.servo_ids)
            missing_ids = expected_ids - found_ids
            if missing_ids:
                missing_names = [f"ID{sid}" for sid in sorted(missing_ids)]
                QMessageBox.warning(
                    self,
                    "警告",
                    f"以下标准关节未被发现：{', '.join(missing_names)}\n"
                    f"这些关节将无法校准，请检查连接。"
                )
                # 标记缺失关节为未连接
                for sid in missing_ids:
                    self.joints[sid - 1]["status"] = "disconnected"

            # 失能所有舵机
            self.set_torque(False)

            # 启动位置读取线程
            self.position_reader = PositionReader(self.servo_handler, self.servo_ids)
            self.position_reader.positions_updated.connect(self.on_positions_updated)
            self.reader_thread = ReaderThread(self.position_reader)
            self.reader_thread.start()

            self.status_label.setText(
                f"串口: {self.port_name} | 已连接 | 发现舵机: {self.servo_ids}"
            )

            # 如果指定了预加载文件，读取现有校准数据
            if self.preload_file:
                self.preload_calibration_data()

            return True

        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接失败: {e}")
            return False

    def preload_calibration_data(self):
        """从已有校准文件预填数据，允许用户选择性地重新校准"""
        try:
            with open(self.preload_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            loaded_count = 0
            for joint in self.joints:
                name = joint["name"]
                if name in data:
                    joint["homing_offset"] = data[name].get("homing_offset")
                    joint["range_min"] = data[name].get("range_min")
                    joint["range_max"] = data[name].get("range_max")
                    joint["status"] = "done"
                    loaded_count += 1

            self.status_label.setText(
                f"串口: {self.port_name} | 已连接 | 已加载 {loaded_count} 个关节数据 | "
                f"选择关节后可重新记录以覆盖"
            )
            print(
                f"[DEBUG] 已加载现有校准文件: {self.preload_file}, "
                f"预填 {loaded_count} 个关节数据"
            )
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载校准文件失败: {e}")

    def scan_servos(self) -> List[int]:
        """扫描舵机"""
        found = []
        for servo_id in range(1, 21):
            model_number, result, error = self.servo_handler.ping(servo_id)
            if result == COMM_SUCCESS:
                found.append(servo_id)
        return found

    def set_torque(self, enable: bool):
        """设置所有舵机力矩"""
        value = TORQUE_ON if enable else TORQUE_OFF
        for servo_id in self.servo_ids:
            self.servo_handler.write1ByteTxRx(servo_id, TORQUE_ENABLE_ADDR, value)
            time.sleep(0.02)

    def on_positions_updated(self, positions: dict):
        """收到新位置数据"""
        current_id = self.current_joint_index + 1
        if self.is_recording and current_id in positions:
            pos = positions[current_id]
            joint = self.joints[self.current_joint_index]
            old_min = joint["range_min"]
            old_max = joint["range_max"]
            if joint["range_min"] is None or pos < joint["range_min"]:
                joint["range_min"] = pos
            if joint["range_max"] is None or pos > joint["range_max"]:
                joint["range_max"] = pos
            if joint["range_min"] != old_min or joint["range_max"] != old_max:
                print(f"[DEBUG] 记录范围更新: ID{current_id}, pos={pos}, range=[{joint['range_min']}, {joint['range_max']}]")

        for servo_id, pos in positions.items():
            index = servo_id - 1
            if 0 <= index < len(self.joints):
                self.joints[index]["current_pos"] = pos

    def update_ui(self):
        """刷新 UI 显示"""
        for i, joint in enumerate(self.joints):
            # 当前位置
            current_pos = joint["current_pos"]
            current_text = str(current_pos) if current_pos is not None else "--"
            self.joints_table.item(i, 1).setText(current_text)

            # 中位值
            homing = joint["homing_offset"]
            self.joints_table.item(i, 2).setText(str(homing) if homing is not None else "--")

            # 最小值/最大值
            rmin = joint["range_min"]
            rmax = joint["range_max"]
            self.joints_table.item(i, 3).setText(str(rmin) if rmin is not None else "--")
            self.joints_table.item(i, 4).setText(str(rmax) if rmax is not None else "--")

            # 状态
            status_item = self.joints_table.item(i, 5)
            if joint["status"] == "done":
                status_item.setText("✅ 完成")
                status_item.setForeground(QColor("#28a745"))
            elif joint["status"] == "homing_done":
                status_item.setText("📝 已记录中位")
                status_item.setForeground(QColor("#007bff"))
            elif joint["status"] == "disconnected":
                status_item.setText("❌ 未连接")
                status_item.setForeground(QColor("#6c757d"))
            else:
                status_item.setText("⏳ 未校准")
                status_item.setForeground(QColor("#dc3545"))

        # 高亮当前行
        # 显式设置每个单元格的背景/前景，避免 Windows 深色主题下出现黑色背景
        for i in range(len(self.joints)):
            for col in range(6):
                item = self.joints_table.item(i, col)
                if i == self.current_joint_index:
                    item.setBackground(QColor("#fff3cd"))
                else:
                    # 交替行颜色：白 / 浅灰
                    item.setBackground(QColor("#ffffff" if i % 2 == 0 else "#f8f9fa"))

                # 状态列保留自定义颜色，其他列统一深色文字
                if col != 5:
                    item.setForeground(QColor("#212529"))

        # 更新当前位置大字
        current_joint = self.joints[self.current_joint_index]
        current_pos = current_joint["current_pos"]
        self.current_pos_label.setText(
            f"当前位置: {current_pos if current_pos is not None else '--'}"
        )

        # 记录中时的视觉反馈
        if self.is_recording:
            self.current_pos_label.setStyleSheet(
                "font-size: 36px; font-weight: bold; color: #856404; "
                "background-color: #fff3cd; padding: 15px; border-radius: 8px;"
            )
        else:
            self.current_pos_label.setStyleSheet(
                "font-size: 36px; font-weight: bold; color: #007bff; "
                "background-color: #e9ecef; padding: 15px; border-radius: 8px;"
            )

        # 更新说明文字和按钮状态
        self.update_instruction()

    def update_instruction(self):
        """更新操作说明和按钮可用状态"""
        joint = self.joints[self.current_joint_index]
        name = joint["display_name"]

        # 记录范围进行中：除【停止记录范围】外，其他操作按钮全部禁用
        if self.is_recording:
            self.instruction_label.setText(
                f"⏺️ 正在记录 {name} 的运动范围...\n"
                f"请将关节缓慢移动到极限位置，\n"
                f"然后点击【停止记录范围】。"
            )
            self.record_home_btn.setEnabled(False)
            self.start_range_btn.setEnabled(False)
            self.stop_range_btn.setEnabled(True)
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.current_joint_label.setText(f"当前关节: ID{joint['id']} - {name}")
            return

        if joint["status"] == "disconnected":
            self.instruction_label.setText(
                f"⚠️ 当前关节 {name} 未连接。\n"
                f"请检查舵机 ID{joint['id']} 的电源和接线，\n"
                f"然后关闭向导重新打开。"
            )
            self.record_home_btn.setEnabled(False)
            self.start_range_btn.setEnabled(False)
            self.stop_range_btn.setEnabled(False)
        elif joint["name"] in CONTINUOUS_JOINTS:
            self.instruction_label.setText(
                f"当前关节: {name}\n"
                f"这是连续旋转关节（wrist_roll），只需记录中位值，\n"
                f"范围固定为 [0, 4095]。"
            )
            self.record_home_btn.setEnabled(True)
            self.start_range_btn.setEnabled(False)
            self.stop_range_btn.setEnabled(False)
        elif joint["status"] == "pending":
            self.instruction_label.setText(
                f"步骤 1/2：请将 {name} 移动到运动范围的中间位置，\n"
                f"然后点击【记录中位值】。"
            )
            self.record_home_btn.setEnabled(True)
            self.start_range_btn.setEnabled(False)
            self.stop_range_btn.setEnabled(False)
        elif joint["status"] == "homing_done":
            self.instruction_label.setText(
                f"步骤 2/2：{name} 中位已记录为 {joint['homing_offset']}。\n"
                f"现在请缓慢移动该关节经过整个运动范围，\n"
                f"点击【开始记录范围】，移动完成后点击【停止记录范围】。"
            )
            self.record_home_btn.setEnabled(True)
            self.start_range_btn.setEnabled(True)
            self.stop_range_btn.setEnabled(False)
        elif joint["status"] == "done":
            self.instruction_label.setText(
                f"✅ {name} 校准完成！\n"
                f"中位: {joint['homing_offset']} | 范围: [{joint['range_min']}, {joint['range_max']}]"
            )
            self.record_home_btn.setEnabled(True)
            self.start_range_btn.setEnabled(True)
            self.stop_range_btn.setEnabled(False)

        # 导航按钮：首尾关节禁用对应方向
        self.prev_btn.setEnabled(self.current_joint_index > 0)
        self.next_btn.setEnabled(self.current_joint_index < len(self.joints) - 1)
        self.save_btn.setEnabled(True)

        # 更新当前关节标签
        self.current_joint_label.setText(
            f"当前关节: ID{joint['id']} - {name}"
        )

    def on_selection_changed(self):
        """表格选择改变"""
        selected = self.joints_table.selectedItems()
        if selected:
            row = selected[0].row()
            self.current_joint_index = row

    def _read_position_directly(self, servo_id: int) -> Optional[int]:
        """直接读取指定舵机位置（用于重试）"""
        if not self.servo_handler:
            return None
        try:
            pos, result, error = self.servo_handler.ReadPos(servo_id)
            if result == COMM_SUCCESS:
                return pos
            else:
                print(f"[DEBUG] 直接读取 ID{servo_id} 失败: result={result}, error={error}")
        except Exception as e:
            print(f"[DEBUG] 直接读取 ID{servo_id} 异常: {e}")
        return None

    def record_homing(self):
        """记录中位值"""
        joint = self.joints[self.current_joint_index]

        if joint["status"] == "disconnected":
            QMessageBox.warning(self, "警告", f"舵机 ID{joint['id']} 未连接，无法记录")
            return

        current_pos = joint["current_pos"]

        # 如果当前位置为空，尝试直接读取一次
        if current_pos is None:
            current_pos = self._read_position_directly(joint["id"])
            if current_pos is not None:
                joint["current_pos"] = current_pos

        if current_pos is None:
            QMessageBox.warning(
                self,
                "警告",
                f"当前无法读取舵机 ID{joint['id']} 的位置。\n"
                f"可能原因：\n"
                f"1. 该舵机未连接或没有上电\n"
                f"2. 串口被其他程序占用\n"
                f"3. 后台读取线程尚未收到数据（请等待几秒后重试）"
            )
            return

        joint["homing_offset"] = current_pos

        if joint["name"] in CONTINUOUS_JOINTS:
            joint["range_min"] = 0
            joint["range_max"] = 4095
            joint["status"] = "done"
            self.status_label.setText(f"已记录 {joint['display_name']} 中位和范围（连续旋转）")
        else:
            joint["status"] = "homing_done"
            self.status_label.setText(f"已记录 {joint['display_name']} 中位值: {current_pos}")

        # 自动下一个
        self.next_joint()

    def _record_current_position(self):
        """范围记录专用：高频读取当前关节位置并更新范围"""
        if not self.is_recording:
            return

        joint = self.joints[self.current_joint_index]
        pos = self._read_position_directly(joint["id"])

        if pos is None:
            return

        joint["current_pos"] = pos
        old_min = joint["range_min"]
        old_max = joint["range_max"]

        if joint["range_min"] is None or pos < joint["range_min"]:
            joint["range_min"] = pos
        if joint["range_max"] is None or pos > joint["range_max"]:
            joint["range_max"] = pos

        if joint["range_min"] != old_min or joint["range_max"] != old_max:
            print(f"[DEBUG] 范围记录更新: ID{joint['id']}, pos={pos}, range=[{joint['range_min']}, {joint['range_max']}]")

    def start_range_recording(self):
        """开始记录范围"""
        joint = self.joints[self.current_joint_index]

        if joint["status"] == "disconnected":
            QMessageBox.warning(self, "警告", f"舵机 ID{joint['id']} 未连接，无法记录范围")
            return

        current_pos = joint["current_pos"]

        # 如果当前位置为空，尝试直接读取一次
        if current_pos is None:
            current_pos = self._read_position_directly(joint["id"])
            if current_pos is not None:
                joint["current_pos"] = current_pos

        if current_pos is None:
            QMessageBox.warning(
                self,
                "警告",
                f"当前无法读取舵机 ID{joint['id']} 的位置。\n"
                f"请检查连接后重试。"
            )
            return

        joint["range_min"] = current_pos
        joint["range_max"] = current_pos
        self.is_recording = True

        self.start_range_btn.setEnabled(False)
        self.stop_range_btn.setEnabled(True)
        self.status_label.setText(f"正在记录 {joint['display_name']} 的运动范围...")
        print(f"[DEBUG] 开始记录范围: {joint['display_name']} (ID{joint['id']}), 初始值={current_pos}")

        # 启动高频读取定时器，确保能捕捉到运动范围的极值
        self.range_recording_timer.start(30)  # 约 33Hz

        # 立即刷新按钮状态，禁用其他操作
        self.update_instruction()

    def stop_range_recording(self):
        """停止记录范围"""
        if not self.is_recording:
            return

        self.is_recording = False
        joint = self.joints[self.current_joint_index]
        joint["status"] = "done"

        self.start_range_btn.setEnabled(True)
        self.stop_range_btn.setEnabled(False)
        self.status_label.setText(
            f"{joint['display_name']} 范围记录完成: "
            f"[{joint['range_min']}, {joint['range_max']}]"
        )
        print(f"[DEBUG] 停止记录范围: {joint['display_name']} (ID{joint['id']}), 范围=[{joint['range_min']}, {joint['range_max']}]")

        # 停止高频读取定时器
        self.range_recording_timer.stop()

        # 自动下一个
        self.next_joint()

        # 立即刷新按钮状态，恢复其他操作
        self.update_instruction()

    def next_joint(self):
        """切换到下一个关节"""
        if self.current_joint_index < len(self.joints) - 1:
            self.current_joint_index += 1
            self.joints_table.selectRow(self.current_joint_index)

    def prev_joint(self):
        """切换到上一个关节"""
        if self.current_joint_index > 0:
            self.current_joint_index -= 1
            self.joints_table.selectRow(self.current_joint_index)

    def save_calibration(self):
        """保存校准文件"""
        # 检查是否所有关节都已完成
        incomplete = []
        for joint in self.joints:
            if joint["status"] != "done":
                incomplete.append(joint["display_name"])

        if incomplete:
            reply = QMessageBox.question(
                self,
                "确认保存",
                f"以下关节尚未完成校准:\n{', '.join(incomplete)}\n\n"
                f"未完成关节将使用默认值（中位=2048, 范围=[0,4095]）。\n"
                f"是否继续保存？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # 构建校准数据
        calibration_data = {}
        for joint in self.joints:
            calibration_data[joint["name"]] = {
                "id": joint["id"],
                "drive_mode": 0,
                "homing_offset": joint["homing_offset"] if joint["homing_offset"] is not None else 2048,
                "range_min": joint["range_min"] if joint["range_min"] is not None else 0,
                "range_max": joint["range_max"] if joint["range_max"] is not None else 4095,
            }

        # 保存路径
        calib_id = self.id_input.text().strip()
        if not calib_id:
            calib_id = "my_awesome_leader_arm" if self.arm_type == "leader" else "my_awesome_follower_arm"

        manager = CalibrationManager()
        if self.arm_type == "leader":
            save_dir = manager.teleoperators_dir / "so_leader"
        else:
            save_dir = manager.robots_dir / "so_follower"

        save_path = save_dir / f"{calib_id}.json"

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(calibration_data, f, indent=4, ensure_ascii=False)

            QMessageBox.information(
                self,
                "保存成功",
                f"校准文件已保存:\n{save_path}\n\n"
                f"可以在 LeRobot 中使用 ID: {calib_id}"
            )
            self.status_label.setText(f"校准文件已保存: {save_path}")

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存校准文件失败: {e}")

    def disconnect_and_close(self):
        """断开连接并关闭"""
        self.cleanup()
        self.accept()

    def close(self):
        """关闭对话框"""
        self.cleanup()
        super().close()

    def cleanup(self):
        """清理资源"""
        if self.range_recording_timer:
            self.range_recording_timer.stop()
        if self.ui_timer:
            self.ui_timer.stop()
        if self.reader_thread:
            self.reader_thread.stop()
            self.reader_thread = None
        if self.port_handler and self.port_handler.is_open:
            try:
                self.set_torque(False)
                self.port_handler.closePort()
            except:
                pass

    def reject(self):
        """点击 X 关闭时也清理"""
        self.cleanup()
        super().reject()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if setup_light_theme:
        setup_light_theme(app)
    wizard = CalibrationWizard("/dev/ttyACM0", "follower")
    wizard.show()
    sys.exit(app.exec())
