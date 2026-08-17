#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""src/gui/calibration_wizard.py 的英文翻译表（key 为中文原文）。"""

TRANSLATIONS = {
    # 窗口标题
    "LeRobot 校准向导 - {}": "LeRobot Calibration Wizard - {}",
    " (基于现有文件)": " (Based on Existing File)",
    "🦾 LeRobot 校准向导 - {}": "🦾 LeRobot Calibration Wizard - {}",
    "领导臂": "Leader Arm",
    "从动臂": "Follower Arm",

    # 状态栏
    "串口: {} | 状态: 初始化中...": "Serial port: {} | Status: Initializing...",
    "串口: {} | 已连接 | 发现舵机: {}": "Serial port: {} | Connected | Servos found: {}",
    "串口: {} | 已连接 | 已加载 {} 个关节数据 | 选择关节后可重新记录以覆盖":
        "Serial port: {} | Connected | Loaded data for {} joints | Select a joint to re-record and overwrite",
    "正在记录 {} 的运动范围...": "Recording the range of {}...",
    "已记录 {} 中位和范围（连续旋转）": "Recorded middle and range for {} (continuous rotation)",
    "已记录 {} 中位值: {}": "Recorded middle value for {}: {}",
    "{} 范围记录完成: [{}, {}]": "{} range recording complete: [{}, {}]",
    "校准文件已保存: {}": "Calibration file saved: {}",

    # 表格
    "📋 关节校准数据": "📋 Joint Calibration Data",
    "当前位置": "Current Position",
    "中位值": "Middle Value",
    "最小值": "Min",
    "最大值": "Max",
    "状态": "Status",
    "未校准": "Not Calibrated",
    "✅ 完成": "✅ Done",
    "📝 已记录中位": "📝 Middle Recorded",
    "❌ 未连接": "❌ Disconnected",
    "⏳ 未校准": "⏳ Not Calibrated",

    # 关节显示名（来自 JOINT_NAME_MAP 的中文部分）
    "肩部平转": "Shoulder Pan",
    "肩部抬升": "Shoulder Lift",
    "肘部弯曲": "Elbow Flex",
    "手腕弯曲": "Wrist Flex",
    "手腕旋转": "Wrist Roll",
    "夹爪": "Gripper",

    # 操作面板
    "🎮 操作面板": "🎮 Control Panel",
    "当前关节: ID1 - 肩部平转": "Current Joint: ID1 - Shoulder Pan",
    "当前关节: ID{} - {}": "Current Joint: ID{} - {}",
    "当前位置: --": "Current Position: --",
    "当前位置: {}": "Current Position: {}",
    "步骤 1/2：请将当前关节移动到运动范围的中间位置，\n然后点击【记录中位值】按钮。":
        "Step 1/2: Move the current joint to the middle of its range,\nthen click the [Record Middle Value] button.",
    "⏺️ 正在记录 {} 的运动范围...\n请将关节缓慢移动到极限位置，\n然后点击【停止记录范围】。":
        "⏺️ Recording the range of {}...\nSlowly move the joint to its limits,\nthen click [Stop Recording Range].",
    "⚠️ 当前关节 {} 未连接。\n请检查舵机 ID{} 的电源和接线，\n然后关闭向导重新打开。":
        "⚠️ Current joint {} is not connected.\nCheck the power and wiring of servo ID{},\nthen close and reopen the wizard.",
    "当前关节: {}\n这是连续旋转关节（wrist_roll），只需记录中位值，\n范围固定为 [0, 4095]。":
        "Current joint: {}\nThis is a continuous rotation joint (wrist_roll); only the middle value is needed,\nand the range is fixed at [0, 4095].",
    "步骤 1/2：请将 {} 移动到运动范围的中间位置，\n然后点击【记录中位值】。":
        "Step 1/2: Move {} to the middle of its range,\nthen click [Record Middle Value].",
    "步骤 2/2：{} 中位已记录为 {}。\n现在请缓慢移动该关节经过整个运动范围，\n点击【开始记录范围】，移动完成后点击【停止记录范围】。":
        "Step 2/2: Middle of {} recorded as {}.\nNow slowly move the joint through its entire range:\nclick [Start Recording Range], and click [Stop Recording Range] when done.",
    "✅ {} 校准完成！\n中位: {} | 范围: [{}, {}]":
        "✅ {} calibration complete!\nMiddle: {} | Range: [{}, {}]",

    # 按钮
    "✅ 记录中位值": "✅ Record Middle Value",
    "▶ 开始记录范围": "▶ Start Recording Range",
    "⏹ 停止记录范围": "⏹ Stop Recording Range",
    "◀ 上一个关节": "◀ Previous Joint",
    "下一个关节 ▶": "Next Joint ▶",
    "💾 保存校准文件": "💾 Save Calibration File",
    "🔌 断开连接": "🔌 Disconnect",
    "关闭": "Close",

    # 保存设置
    "💾 保存设置": "💾 Save Settings",
    "校准文件 ID:": "Calibration File ID:",

    # 对话框
    "错误": "Error",
    "警告": "Warning",
    "确认保存": "Confirm Save",
    "保存成功": "Save Successful",
    "保存失败": "Save Failed",
    "无法打开串口: {}": "Cannot open serial port: {}",
    "无法设置波特率": "Cannot set baud rate",
    "未发现舵机": "No servos found",
    "未发现 SO-10x 标准关节（ID 1-6）": "No SO-10x standard joints (ID 1-6) found",
    "以下标准关节未被发现：{}\n这些关节将无法校准，请检查连接。":
        "The following standard joints were not found: {}\nThese joints cannot be calibrated. Please check the connections.",
    "连接失败: {}": "Connection failed: {}",
    "加载校准文件失败: {}": "Failed to load calibration file: {}",
    "舵机 ID{} 未连接，无法记录": "Servo ID{} is not connected; cannot record",
    "舵机 ID{} 未连接，无法记录范围": "Servo ID{} is not connected; cannot record range",
    "当前无法读取舵机 ID{} 的位置。\n可能原因：\n1. 该舵机未连接或没有上电\n2. 串口被其他程序占用\n3. 后台读取线程尚未收到数据（请等待几秒后重试）":
        "Cannot read the position of servo ID{}.\nPossible causes:\n1. The servo is not connected or not powered\n2. The serial port is occupied by another program\n3. The background reader has not received data yet (wait a few seconds and retry)",
    "当前无法读取舵机 ID{} 的位置。\n请检查连接后重试。":
        "Cannot read the position of servo ID{}.\nCheck the connection and retry.",
    "以下关节尚未完成校准:\n{}\n\n未完成关节将使用默认值（中位=2048, 范围=[0,4095]）。\n是否继续保存？":
        "The following joints have not been calibrated:\n{}\n\nUncalibrated joints will use default values (middle=2048, range=[0,4095]).\nContinue saving?",
    "校准文件已保存:\n{}\n\n可以在 LeRobot 中使用 ID: {}":
        "Calibration file saved:\n{}\n\nYou can use ID {} in LeRobot",
    "保存校准文件失败: {}": "Failed to save calibration file: {}",

    # 调试输出
    "[DEBUG] 读取 ID{} 失败: result={}, error={}": "[DEBUG] Failed to read ID{}: result={}, error={}",
    "[DEBUG] 读取 ID{} 异常: {}": "[DEBUG] Exception reading ID{}: {}",
    "[DEBUG] 已加载现有校准文件: {}, 预填 {} 个关节数据":
        "[DEBUG] Loaded existing calibration file: {}, prefilled data for {} joints",
    "[DEBUG] 记录范围更新: ID{}, pos={}, range=[{}, {}]":
        "[DEBUG] Range update: ID{}, pos={}, range=[{}, {}]",
    "[DEBUG] 范围记录更新: ID{}, pos={}, range=[{}, {}]":
        "[DEBUG] Range recording update: ID{}, pos={}, range=[{}, {}]",
    "[DEBUG] 直接读取 ID{} 失败: result={}, error={}":
        "[DEBUG] Direct read of ID{} failed: result={}, error={}",
    "[DEBUG] 直接读取 ID{} 异常: {}": "[DEBUG] Direct read of ID{} exception: {}",
    "[DEBUG] 开始记录范围: {} (ID{}), 初始值={}":
        "[DEBUG] Start recording range: {} (ID{}), initial value={}",
    "[DEBUG] 停止记录范围: {} (ID{}), 范围=[{}, {}]":
        "[DEBUG] Stop recording range: {} (ID{}), range=[{}, {}]",
}
