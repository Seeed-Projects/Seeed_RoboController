#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
英文翻译表汇总。

按模块拆分为多个文件，避免并行维护时互相冲突：
- factory.py     -> src/gui/factory_calibration_tool.py
- wizard.py      -> src/gui/calibration_wizard.py
- angle_limit.py -> src/gui/servo_angle_limit_set.py
- tools.py       -> src/tools/ 下由 GUI 启动的 CLI 工具

每个文件定义 ``TRANSLATIONS`` 字典：key 为代码中的中文原文，value 为英文译文。
"""

from src.i18n_translations.factory import TRANSLATIONS as _FACTORY
from src.i18n_translations.wizard import TRANSLATIONS as _WIZARD
from src.i18n_translations.angle_limit import TRANSLATIONS as _ANGLE_LIMIT
from src.i18n_translations.tools import TRANSLATIONS as _TOOLS

TRANSLATIONS = {}
for _dict in (_FACTORY, _WIZARD, _ANGLE_LIMIT, _TOOLS):
    TRANSLATIONS.update(_dict)
