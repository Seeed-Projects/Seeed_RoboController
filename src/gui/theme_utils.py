#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
主题工具模块
用于在 Windows 深色主题等环境下强制使用浅色主题，
避免硬编码的白色背景与系统默认浅色文字冲突导致内容看不见。
"""

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPalette, QColor
except ImportError:
    QApplication = None
    QPalette = None
    QColor = None


def setup_light_theme(app: QApplication):
    """将 QApplication 设置为统一的浅色主题 palette。

    在 Windows 深色模式下，Qt 默认可能继承深色 palette，
    但项目中很多控件的样式表硬编码了白色背景或深色文字，
    造成文字/内容看不见。强制浅色 palette 可保证所有界面一致可读。
    """
    if app is None or QPalette is None or QColor is None:
        return

    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f8f9fa"))
    palette.setColor(QPalette.WindowText, QColor("#212529"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f1f3f5"))
    palette.setColor(QPalette.Text, QColor("#212529"))
    palette.setColor(QPalette.Button, QColor("#e9ecef"))
    palette.setColor(QPalette.ButtonText, QColor("#212529"))
    palette.setColor(QPalette.Highlight, QColor("#007bff"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipBase, QColor("#fff3cd"))
    palette.setColor(QPalette.ToolTipText, QColor("#212529"))
    app.setPalette(palette)
