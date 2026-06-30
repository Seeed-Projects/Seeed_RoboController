#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LeRobot 校准文件管理模块
读取和管理 ~/.cache/huggingface/lerobot/calibration/ 下的
robots（从动臂）和 teleoperators（领导臂）校准文件
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_CALIBRATION_DIR = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"

# 关节显示名称映射（中英对照）
JOINT_NAME_MAP = {
    "shoulder_pan": "肩部平转 / Shoulder Pan",
    "shoulder_lift": "肩部抬升 / Shoulder Lift",
    "elbow_flex": "肘部弯曲 / Elbow Flex",
    "wrist_flex": "手腕弯曲 / Wrist Flex",
    "wrist_roll": "手腕旋转 / Wrist Roll",
    "gripper": "夹爪 / Gripper",
}


class CalibrationManager:
    """LeRobot 校准文件管理器"""

    def __init__(self, calibration_dir: Optional[str] = None):
        """
        初始化校准管理器

        Args:
            calibration_dir: 校准文件根目录，默认 ~/.cache/huggingface/lerobot/calibration
        """
        if calibration_dir:
            self.base_dir = Path(calibration_dir)
        else:
            self.base_dir = DEFAULT_CALIBRATION_DIR

        self.robots_dir = self.base_dir / "robots"
        self.teleoperators_dir = self.base_dir / "teleoperators"

    def get_arm_dirs(self, arm_type: str) -> List[Path]:
        """
        获取指定臂类型下的所有子目录

        Args:
            arm_type: "robots" 或 "teleoperators"

        Returns:
            子目录列表
        """
        target_dir = self.robots_dir if arm_type == "robots" else self.teleoperators_dir
        if not target_dir.exists():
            return []
        return [d for d in target_dir.iterdir() if d.is_dir()]

    def get_calibration_files(self, arm_type: str) -> List[Path]:
        """
        获取指定臂类型下的所有校准文件

        Args:
            arm_type: "robots" 或 "teleoperators"

        Returns:
            JSON 校准文件路径列表
        """
        target_dir = self.robots_dir if arm_type == "robots" else self.teleoperators_dir
        if not target_dir.exists():
            return []

        files = []
        for arm_dir in target_dir.iterdir():
            if arm_dir.is_dir():
                for file_path in arm_dir.iterdir():
                    if file_path.is_file() and file_path.suffix == ".json":
                        files.append(file_path)

        return sorted(files)

    def load_calibration_file(self, file_path: str) -> Optional[Dict]:
        """
        读取单个校准文件

        Args:
            file_path: JSON 文件路径

        Returns:
            校准数据字典，失败返回 None
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ERROR] 读取校准文件失败 {file_path}: {e}")
            return None

    def save_calibration_file(self, file_path: str, data: Dict) -> bool:
        """
        保存校准数据到文件

        Args:
            file_path: 目标 JSON 文件路径
            data: 校准数据字典

        Returns:
            是否保存成功
        """
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERROR] 保存校准文件失败 {file_path}: {e}")
            return False

    def get_joint_display_name(self, joint_name: str) -> str:
        """获取关节的显示名称"""
        return JOINT_NAME_MAP.get(joint_name, joint_name)

    def load_all_calibrations(self) -> Tuple[List[Dict], List[Dict]]:
        """
        加载所有校准文件

        Returns:
            (robots_calibrations, teleoperators_calibrations)
            每个元素是包含 path, name, data 的字典列表
        """
        robots = []
        teleoperators = []

        for file_path in self.get_calibration_files("robots"):
            data = self.load_calibration_file(str(file_path))
            if data is not None:
                robots.append({
                    "path": str(file_path),
                    "name": file_path.stem,
                    "arm_dir": file_path.parent.name,
                    "data": data,
                })

        for file_path in self.get_calibration_files("teleoperators"):
            data = self.load_calibration_file(str(file_path))
            if data is not None:
                teleoperators.append({
                    "path": str(file_path),
                    "name": file_path.stem,
                    "arm_dir": file_path.parent.name,
                    "data": data,
                })

        return robots, teleoperators

    def format_calibration_summary(self, data: Dict) -> str:
        """
        将校准数据格式化为可读摘要

        Args:
            data: 校准数据字典

        Returns:
            格式化字符串
        """
        lines = []
        for joint_name, joint_data in data.items():
            display_name = self.get_joint_display_name(joint_name)
            lines.append(f"{display_name}")
            lines.append(f"  ID: {joint_data.get('id', 'N/A')}")
            lines.append(f"  Homing Offset: {joint_data.get('homing_offset', 'N/A')}")
            lines.append(f"  Range: [{joint_data.get('range_min', 'N/A')}, {joint_data.get('range_max', 'N/A')}]")
            lines.append(f"  Drive Mode: {joint_data.get('drive_mode', 'N/A')}")
            lines.append("")
        return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    manager = CalibrationManager()
    print("=== 从动臂 (robots) 校准文件 ===")
    for file_path in manager.get_calibration_files("robots"):
        print(f"  {file_path}")

    print("\n=== 领导臂 (teleoperators) 校准文件 ===")
    for file_path in manager.get_calibration_files("teleoperators"):
        print(f"  {file_path}")

    robots, teleoperators = manager.load_all_calibrations()
    print(f"\n加载成功: robots={len(robots)}, teleoperators={len(teleoperators)}")

    if robots:
        print("\n=== 示例摘要 ===")
        print(manager.format_calibration_summary(robots[0]["data"]))
