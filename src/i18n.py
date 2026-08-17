#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
轻量级中/英文国际化支持。

GUI 与 CLI 工具共用：语言通过环境变量 ``SEEED_LANG`` 传递，
GUI 启动时选择语言后写入该环境变量，子进程（CLI 工具）自动继承。

用法::

    from src.i18n import tr, set_lang

    print(tr("未发现可用串口"))
    # 带参数的字符串使用 format，保证字典 key 固定：
    print(tr("串口1: {}").format(port))
"""

import os

from src.i18n_translations import TRANSLATIONS

_LANG_ZH = "zh"
_LANG_EN = "en"


def _normalize(lang) -> str:
    """把各种语言写法规范为 'zh' 或 'en'。"""
    if lang and str(lang).strip().lower() in ("en", "en_us", "en-us", "english"):
        return _LANG_EN
    return _LANG_ZH


def get_lang() -> str:
    """返回当前语言：'zh' 或 'en'（默认读环境变量 SEEED_LANG，未设置时为中文）。"""
    return _normalize(os.environ.get("SEEED_LANG", _LANG_ZH))


def set_lang(lang) -> str:
    """设置当前进程语言，并写入环境变量供子进程继承。返回规范后的语言代码。"""
    lang = _normalize(lang)
    os.environ["SEEED_LANG"] = lang
    return lang


def lang_from_argv(argv) -> str:
    """从命令行参数中解析 --lang zh|en（或 --lang=en），未指定返回 None。"""
    args = list(argv)
    for i, arg in enumerate(args):
        if arg == "--lang" and i + 1 < len(args):
            return _normalize(args[i + 1])
        if arg.startswith("--lang="):
            return _normalize(arg.split("=", 1)[1])
    return None


def tr(text: str) -> str:
    """翻译为用户所选语言；英文模式下查不到译文时回落为中文原文。"""
    if not text or get_lang() != _LANG_EN:
        return text
    return TRANSLATIONS.get(text, text)
