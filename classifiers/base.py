# -*- coding: utf-8 -*-
"""
检测器基类模块
定义所有检测器的抽象基类、缺陷类型枚举和检测结果数据类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class DefectType(Enum):
    """照片缺陷类型枚举"""
    CORRUPTED = "corrupted"        # 损坏/不完整
    EMPTY = "empty"                # 空镜/无内容
    BLINK = "blink"                # 闭眼/眨眼
    BLURRY = "blurry"              # 模糊
    OBSTRUCTION = "obstruction"    # 遮挡


@dataclass
class DetectionResult:
    """检测结果数据类"""
    is_defective: bool                          # 是否存在缺陷
    defect_type: DefectType | None              # 缺陷类型
    confidence: float                           # 置信度 (0.0 - 1.0)
    description: str                            # 描述信息


class BaseDetector(ABC):
    """检测器抽象基类，所有具体检测器必须继承此类"""

    @abstractmethod
    def detect(self, image_path: str) -> DetectionResult:
        """
        检测图片是否存在缺陷

        参数:
            image_path: 图片文件路径

        返回:
            DetectionResult 检测结果
        """
        pass

    @staticmethod
    def read_image(image_path: str):
        """
        安全读取图片（支持中文路径）

        OpenCV 的 cv2.imread 不支持中文路径，
        使用 np.fromfile + cv2.imdecode 替代。

        参数:
            image_path: 图片文件路径

        返回:
            numpy.ndarray 图像数组，读取失败返回 None
        """
        import cv2
        import numpy as np
        try:
            with open(image_path, 'rb') as f:
                data = np.frombuffer(f.read(), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            return img
        except Exception:
            return None

    @property
    @abstractmethod
    def defect_type(self) -> DefectType:
        """返回该检测器对应的缺陷类型"""
        pass
