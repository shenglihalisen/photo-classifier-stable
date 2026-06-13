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

# 文件大小上限（10GB）
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024

# 图像处理最大边长（超过此值会缩放）
MAX_PROCESS_DIMENSION = 2048


class DefectType(Enum):
    """照片缺陷类型枚举"""
    CORRUPTED = "corrupted"        # 损坏/不完整
    EMPTY = "empty"                # 空镜/无内容
    BLINK = "blink"                # 闭眼/眨眼
    BLURRY = "blurry"              # 模糊
    OBSTRUCTION = "obstruction"    # 遮挡
    EXPOSURE = "exposure"          # 过曝/欠曝
    NOISY = "noisy"                # 噪点


@dataclass
class DetectionResult:
    """检测结果数据类"""
    is_defective: bool                          # 是否存在缺陷
    defect_type: DefectType | None              # 缺陷类型
    confidence: float                           # 置信度 (0.0 - 1.0)
    description: str                            # 描述信息


class PrecomputedImage:
    """
    预计算图像数据类

    在 classify() 中一次性计算所有检测器共享的中间结果，
    避免每个检测器重复计算灰度图、拉普拉斯方差等。
    """

    __slots__ = ('img', 'gray', 'mean_brightness', 'laplacian_var',
                 'std_b', 'std_g', 'std_r', 'h', 'w')

    def __init__(self, img):
        import cv2
        import numpy as np

        self.img = img
        self.h, self.w = img.shape[:2]

        # 缩放大图以加速计算
        if max(self.h, self.w) > MAX_PROCESS_DIMENSION:
            scale = MAX_PROCESS_DIMENSION / max(self.h, self.w)
            self.gray = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), None, fx=scale, fy=scale)
        else:
            self.gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 预计算共享值
        self.mean_brightness = float(np.mean(self.gray))
        self.laplacian_var = float(cv2.Laplacian(self.gray, cv2.CV_64F).var())

        # 颜色通道标准差（用于空镜/遮挡检测）
        self.std_b = float(np.std(img[:, :, 0]))
        self.std_g = float(np.std(img[:, :, 1]))
        self.std_r = float(np.std(img[:, :, 2]))


class BaseDetector(ABC):
    """检测器抽象基类，所有具体检测器必须继承此类"""

    @abstractmethod
    def detect(self, image_path: str, image=None, precomputed=None) -> DetectionResult:
        """
        检测图片是否存在缺陷

        参数:
            image_path: 图片文件路径
            image: 预加载的 numpy 数组（BGR 格式），为 None 时自行读取
            precomputed: PrecomputedImage 预计算数据，为 None 时自行计算

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
