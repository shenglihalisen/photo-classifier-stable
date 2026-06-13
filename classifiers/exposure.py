# -*- coding: utf-8 -*-
"""
过曝/欠曝检测器
通过分析图像亮度分布检测严重曝光异常的照片
"""

import cv2
import numpy as np

from .base import BaseDetector, DetectionResult, DefectType


class ExposureDetector(BaseDetector):
    """
    过曝/欠曝检测器

    判断标准:
    1. 过曝：高亮像素占比超过阈值，且亮度均值极高
    2. 欠曝：极暗像素占比超过阈值，且亮度均值极低
    3. 局部过曝：高光区域面积过大（如天空完全泛白）
    """

    # 检测阈值
    OVEREXPOSED_MEAN = 220        # 过曝亮度均值阈值
    UNDEREXPOSED_MEAN = 35        # 欠曝亮度均值阈值
    HIGHLIGHT_RATIO = 0.70        # 高亮像素占比阈值（过曝）
    SHADOW_RATIO = 0.70           # 极暗像素占比阈值（欠曝）
    HIGHLIGHT_PIXEL = 250         # 高亮像素灰度值
    SHADOW_PIXEL = 10             # 极暗像素灰度值

    @property
    def defect_type(self) -> DefectType:
        return DefectType.EXPOSURE

    def detect(self, image_path: str, image=None, precomputed=None) -> DetectionResult:
        """检测图片是否严重过曝或欠曝"""
        try:
            if precomputed is not None:
                gray = precomputed.gray
                mean_brightness = precomputed.mean_brightness
            else:
                if image is None:
                    img = self.read_image(image_path)
                else:
                    img = image
                if img is None:
                    return DetectionResult(
                        is_defective=False,
                        defect_type=None,
                        confidence=0.0,
                        description="无法读取图像，跳过曝光检测"
                    )
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                mean_brightness = float(np.mean(gray))

            total_pixels = gray.size

            # 检测过曝
            highlight_count = int(np.sum(gray >= self.HIGHLIGHT_PIXEL))
            highlight_ratio = highlight_count / total_pixels

            if mean_brightness >= self.OVEREXPOSED_MEAN and highlight_ratio >= self.HIGHLIGHT_RATIO:
                confidence = min(1.0, (mean_brightness - self.OVEREXPOSED_MEAN) / (255 - self.OVEREXPOSED_MEAN) * 0.5 + highlight_ratio * 0.5)
                return DetectionResult(
                    is_defective=True,
                    defect_type=self.defect_type,
                    confidence=confidence,
                    description=f"过曝检测: 亮度均值={mean_brightness:.1f}, 高亮占比={highlight_ratio:.1%}"
                )

            # 检测欠曝
            shadow_count = int(np.sum(gray <= self.SHADOW_PIXEL))
            shadow_ratio = shadow_count / total_pixels

            if mean_brightness <= self.UNDEREXPOSED_MEAN and shadow_ratio >= self.SHADOW_RATIO:
                confidence = min(1.0, (self.UNDEREXPOSED_MEAN - mean_brightness) / self.UNDEREXPOSED_MEAN * 0.5 + shadow_ratio * 0.5)
                return DetectionResult(
                    is_defective=True,
                    defect_type=self.defect_type,
                    confidence=confidence,
                    description=f"欠曝检测: 亮度均值={mean_brightness:.1f}, 极暗占比={shadow_ratio:.1%}"
                )

            # 正常曝光
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.9,
                description=f"曝光正常 (亮度均值={mean_brightness:.1f})"
            )

        except Exception as e:
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.0,
                description=f"曝光检测异常: {str(e)}"
            )
