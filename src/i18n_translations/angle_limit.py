#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""src/gui/servo_angle_limit_set.py 的英文翻译表（key 为中文原文）。"""

TRANSLATIONS = {
    # --- 监控工作线程状态消息 ---
    "❌ 无法打开串口: {}": "❌ Cannot open serial port: {}",
    "❌ 无法设置波特率": "❌ Cannot set baud rate",
    "✅ 成功连接到 {}": "✅ Connected to {}",
    "❌ 连接失败: {}": "❌ Connection failed: {}",
    "🔌 已断开连接": "🔌 Disconnected",
    "📡 扫描舵机中...": "📡 Scanning for servos...",
    "  🔌 重新连接舵机 ID{}": "  🔌 Servo ID{} reconnected",
    "  ✅ 发现舵机 ID{}": "  ✅ Found servo ID{}",
    "  ❌ 舵机 ID{} 已断开": "  ❌ Servo ID{} disconnected",
    "  ❌ 扫描ID{}失败: {}": "  ❌ Failed to scan ID{}: {}",
    "❌ 读取ID{}位置失败: {}": "❌ Failed to read position of ID{}: {}",
    "⚠️ 未发现舵机": "⚠️ No servos found",
    "🚀 开始监控 {} 个舵机...": "🚀 Monitoring {} servos...",
    "❌ 监控异常: {}": "❌ Monitor error: {}",
    "🔄 MIN/MAX值已重置，可重新开始记录": "🔄 MIN/MAX values reset; recording can restart",
    "💾 开始写入位置限制...": "💾 Writing position limits...",
    "  ❌ ID{}: EEPROM解锁失败": "  ❌ ID{}: EEPROM unlock failed",
    "  ❌ ID{}: 写入最小角度失败": "  ❌ ID{}: Failed to write min angle",
    "  ❌ ID{}: 写入最大角度失败": "  ❌ ID{}: Failed to write max angle",
    "  ✅ ID{}: 最小值{}, 最大值{}": "  ✅ ID{}: MIN={}, MAX={}",
    "  ❌ ID{}: 写入异常 {}": "  ❌ ID{}: Write error {}",
    "✅ 写入完成: {}/{} 个舵机": "✅ Write complete: {}/{} servos",

    # --- 界面控件 ---
    "舵机位置限制设置工具": "Servo Position Limit Setting Tool",
    "就绪": "Ready",
    "控制面板": "Control Panel",
    "串口:": "Port:",
    "刷新": "Refresh",
    "▶ 开始": "▶ Start",
    "■ 停止": "■ Stop",
    "重置": "Reset",
    "读取": "Read",
    "写入EEPROM": "Write EEPROM",
    "实时位置数据": "Real-time Position Data",
    "操作: 开始→转动舵机采集范围→停止→写入EEPROM | 热插拔后请先重置 | 读取可查看已标定值":
        "Steps: Start → move servos to capture range → Stop → Write EEPROM | Reset after hot-plug | Read shows calibrated values",
    "未检测到串口": "No serial port detected",
    "检测到 {} 个可用串口": "Detected {} available serial ports",
    "❌ 请选择有效的串口": "❌ Please select a valid serial port",

    # --- 读取/写入角度限制 ---
    "📖 正在读取EEPROM中的角度限制...": "📖 Reading angle limits from EEPROM...",
    "ID{}: 未连接": "ID{}: Not connected",
    "ID{}: 读取失败": "ID{}: Read failed",
    "ID{}: 异常 {}": "ID{}: Error {}",
    "当前EEPROM中存储的角度限制：\n\n": "Angle limits currently stored in EEPROM:\n\n",
    "📖 角度限制读取结果": "📖 Angle Limit Read Result",
    "✅ 角度限制读取完成": "✅ Angle limit read complete",
    "❌ 读取失败: {}": "❌ Read failed: {}",
    "❌ 没有采集到数据，请先开始监控并采集MIN/MAX值":
        "❌ No data collected; start monitoring first to capture MIN/MAX values",
    "❌ 没有有效的MIN/MAX数据，请先转动舵机采集范围":
        "❌ No valid MIN/MAX data; move the servos to capture the range first",
    "确认写入": "Confirm Write",
    "确定要将采集到的位置限制写入到舵机EEPROM吗？\n共有 {} 个舵机的数据将被写入。\n此操作将永久修改舵机的角度限制设置！":
        "Write the collected position limits to servo EEPROM?\nData for {} servo(s) will be written.\nThis permanently changes the servo's angle limit settings!",
    "ID{}: 跳过（无有效数据）": "ID{}: Skipped (no valid data)",
    "ID{}: EEPROM解锁失败": "ID{}: EEPROM unlock failed",
    "ID{}: 写入MIN失败": "ID{}: Failed to write MIN",
    "ID{}: 写入MAX失败": "ID{}: Failed to write MAX",
    "ID{}: ✅ MIN={}, MAX={}": "ID{}: ✅ MIN={}, MAX={}",
    "写入完成: {}/{}\n\n": "Write complete: {}/{}\n\n",
    "💾 写入结果": "💾 Write Result",
    "✅ 写入完成: {}/{}": "✅ Write complete: {}/{}",
    "❌ 写入失败: {}": "❌ Write failed: {}",

    # --- 命令行入口 ---
    "指定串口（不指定则自动检测）": "Serial port (auto-detect if omitted)",
    "列出可用串口": "List available serial ports",
    "界面语言 (zh=中文, en=English)，不指定则启动时选择":
        "UI language (zh=Chinese, en=English); chosen at startup if omitted",
    "可用串口:": "Available serial ports:",
    "  未检测到可用串口": "  No available serial ports detected",
    "启动位置限制设置工具 - 串口: {}": "Starting position limit tool - port: {}",
    "启动位置限制设置工具 - 自动检测串口": "Starting position limit tool - auto-detecting port",
}
