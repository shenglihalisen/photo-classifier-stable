# -*- coding: utf-8 -*-
"""
检测器基类模块
定义所有检测器的抽象基类、缺陷类型枚举和检测结果数据类
"""

import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("photo_classifier.base")

# 文件大小上限（100MB）
MAX_FILE_SIZE = 100 * 1024 * 1024


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
            # 文件大小检查
            file_size = os.path.getsize(image_path)
            if file_size > MAX_FILE_SIZE:
                logger.warning(
                    f"文件过大，跳过读取: {image_path} "
                    f"(大小={file_size / 1024 / 1024:.1f}MB, 上限={MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"
                )
                return None

            with open(image_path, 'rb') as f:
                data = np.frombuffer(f.read(), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                logger.warning(f"图像解码失败: {image_path}")
            return img
        except FileNotFoundError:
            logger.warning(f"文件不存在: {image_path}")
            return None
        except Exception as e:
            logger.error(f"读取图像异常: {image_path}, 错误: {e}")
            return None

    @property
    @abstractmethod
    def defect_type(self) -> DefectType:
        """返回该检测器对应的缺陷类型"""
        pass
