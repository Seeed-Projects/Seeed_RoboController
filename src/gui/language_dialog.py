#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动时的语言选择对话框（双语静态文本，无需翻译）。"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt


def choose_language(parent=None) -> str:
    """弹出语言选择对话框，返回 'zh' 或 'en'。直接关闭对话框时默认为中文。"""
    dialog = _LanguageDialog(parent)
    dialog.exec()
    return dialog.selected_lang


class _LanguageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_lang = "zh"
        self.setWindowTitle("Select Language / 选择语言")
        self.setModal(True)
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        label = QLabel("Please select a language\n请选择界面语言")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        button_row = QHBoxLayout()
        btn_zh = QPushButton("中文")
        btn_en = QPushButton("English")
        btn_zh.clicked.connect(lambda: self._select("zh"))
        btn_en.clicked.connect(lambda: self._select("en"))
        button_row.addWidget(btn_zh)
        button_row.addWidget(btn_en)
        layout.addLayout(button_row)

    def _select(self, lang: str):
        self.selected_lang = lang
        self.accept()
