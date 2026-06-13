# -*- coding: utf-8 -*-
"""
噪点检测器
通过拉普拉斯方差和频域分析检测高 ISO 噪点严重的照片
"""

import cv2
import numpy as np

from .base import BaseDetector, DetectionResult, DefectType


class NoiseDetector(BaseDetector):
    """
    噪点检测器

    判断标准:
    1. 拉普拉斯方差异常高（噪声导致边缘检测器响应强烈）
    2. 高频能量占比过高（FFT 分析）
    3. 相邻像素差值方差大（局部噪声特征）
    """

    LAPLACIAN_VAR_THRESHOLD = 5000    # 拉普拉斯方差上限（正常图片一般低于此值）
    HIGH_FREQ_RATIO_THRESHOLD = 0.35  # 高频能量占比阈值
    LOCAL_DIFF_THRESHOLD = 25         # 局部像素差值方差阈值

    @property
    def defect_type(self) -> DefectType:
        return DefectType.NOISY

    def detect(self, image_path: str, image=None, precomputed=None) -> DetectionResult:
        """检测图片噪点是否严重"""
        try:
            if precomputed is not None:
                gray = precomputed.gray
                mean_brightness = precomputed.mean_brightness
                laplacian_var = precomputed.laplacian_var
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
                        description="无法读取图像，跳过噪点检测"
                    )
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                mean_brightness = float(np.mean(gray))
                laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

            # 跳过纯黑/纯白图像
            if mean_brightness < 15 or mean_brightness > 240:
                return DetectionResult(
                    is_defective=False,
                    defect_type=None,
                    confidence=0.0,
                    description=f"图像亮度异常(均值={mean_brightness:.1f})，跳过噪点检测"
                )

            scores = []
            reasons = []

            # 1. 拉普拉斯方差检测（噪声导致高频响应异常高）
            if laplacian_var > self.LAPLACIAN_VAR_THRESHOLD:
                lap_score = min(1.0, (laplacian_var - self.LAPLACIAN_VAR_THRESHOLD) / self.LAPLACIAN_VAR_THRESHOLD)
                scores.append(lap_score)
                reasons.append(f"拉普拉斯方差异常高({laplacian_var:.0f})")

            # 2. FFT 高频能量占比
            high_freq_ratio = self._calculate_high_freq_ratio(gray)
            if high_freq_ratio > self.HIGH_FREQ_RATIO_THRESHOLD:
                fft_score = min(1.0, (high_freq_ratio - self.HIGH_FREQ_RATIO_THRESHOLD) / (1.0 - self.HIGH_FREQ_RATIO_THRESHOLD))
                scores.append(fft_score)
                reasons.append(f"高频能量占比过高({high_freq_ratio:.1%})")

            # 3. 局部像素差值方差
            local_diff_var = self._calculate_local_diff_variance(gray)
            if local_diff_var > self.LOCAL_DIFF_THRESHOLD:
                diff_score = min(1.0, (local_diff_var - self.LOCAL_DIFF_THRESHOLD) / self.LOCAL_DIFF_THRESHOLD)
                scores.append(diff_score)
                reasons.append(f"局部噪声特征明显(差值方差={local_diff_var:.1f})")

            # 综合判断（至少 2 项异常才判定为噪点）
            if len(scores) >= 2:
                confidence = min(1.0, np.mean(scores))
                return DetectionResult(
                    is_defective=True,
                    defect_type=self.defect_type,
                    confidence=confidence,
                    description=f"噪点检测: {'; '.join(reasons)} (综合评分={confidence:.2f})"
                )

            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.85,
                description=f"图像清晰无明显噪点 (拉普拉斯方差={laplacian_var:.0f}, 高频占比={high_freq_ratio:.1%})"
            )

        except Exception as e:
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.0,
                description=f"噪点检测异常: {str(e)}"
            )

    def _calculate_high_freq_ratio(self, gray: np.ndarray) -> float:
        """
        通过 FFT 计算高频能量占比

        噪点图片的高频分量明显高于正常图片
        """
        h, w = gray.shape
        # 缩小到 256x256 加速计算
        small = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA)

        # FFT 变换
        f = np.fft.fft2(small.astype(np.float64))
        f_shift = np.fft.fftshift(f)
        magnitude = np.abs(f_shift)

        # 计算低频和高频能量
        cy, cx = 128, 128
        radius = 30  # 低频半径

        # 创建低频掩码
        y, x = np.ogrid[:256, :256]
        low_freq_mask = ((x - cx) ** 2 + (y - cy) ** 2) <= radius ** 2

        total_energy = float(np.sum(magnitude ** 2))
        if total_energy == 0:
            return 0.0

        low_freq_energy = float(np.sum(magnitude[low_freq_mask] ** 2))
        high_freq_energy = total_energy - low_freq_energy

        return high_freq_energy / total_energy

    def _calculate_local_diff_variance(self, gray: np.ndarray) -> float:
        """
        计算相邻像素差值的方差

        噪点图片的像素间跳变更大
        """
        h, w = gray.shape
        # 缩小加速
        small = cv2.resize(gray, (min(w, 512), min(h, 512)), interpolation=cv2.INTER_AREA)

        # 水平差值
        h_diff = np.abs(small[:, 1:].astype(np.int16) - small[:, :-1].astype(np.int16))
        # 垂直差值
        v_diff = np.abs(small[1:, :].astype(np.int16) - small[:-1, :].astype(np.int16))

        # 差值的方差
        h_var = float(np.var(h_diff))
        v_var = float(np.var(v_diff))

        return (h_var + v_var) / 2.0
