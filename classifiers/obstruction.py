# -*- coding: utf-8 -*-
"""
遮挡检测器
检测手指遮挡和镜头遮挡

支持平台：
- x86_64 (Linux/Windows/Mac)
- ARM64 (Linux/Mac Apple Silicon)

MediaPipe >= 0.10.9 已原生支持 ARM64
"""

import os
import platform
import logging
import cv2
import numpy as np

# 设置日志
logger = logging.getLogger("photo_classifier.obstruction")

# MediaPipe 导入（带错误处理）
_mediapipe_available = False

try:
    import mediapipe as mp
    _mediapipe_available = True
    logger.info(f"MediaPipe 已加载，版本: {mp.__version__}, 平台: {platform.machine()}")
except ImportError as e:
    logger.warning(f"MediaPipe 未安装，手指遮挡检测将被禁用: {e}")
except OSError as e:
    logger.warning(f"MediaPipe 加载失败（可能是缺少系统库），手指遮挡检测将被禁用: {e}")

from .base import BaseDetector, DetectionResult, DefectType


class ObstructionDetector(BaseDetector):
    """
    遮挡检测器

    检测两种类型的遮挡:
    1. 镜头遮挡: 分析图像四角和边缘区域，大面积均匀色块（与中心差异大）表示遮挡
    2. 手指遮挡: 在人脸周围检测肤色像素异常集中区域（需要 MediaPipe）

    注意：手指遮挡检测需要 MediaPipe，如果未安装则仅执行镜头遮挡检测。
    """

    CORNER_OBSTRUCTION_RATIO = 0.50
    EDGE_OBSTRUCTION_RATIO = 0.50
    CORNER_UNIFORMITY_THRESHOLD = 12
    CORNER_CHECK_SIZE = 0.15

    SKIN_LOWER = np.array([0, 20, 50], dtype=np.uint8)
    SKIN_UPPER = np.array([25, 180, 255], dtype=np.uint8)

    def __init__(self):
        self._face_landmarker = None
        self._init_error = None

    @property
    def defect_type(self) -> DefectType:
        return DefectType.OBSTRUCTION

    @property
    def is_available(self) -> bool:
        """检查检测器是否可用"""
        return True  # 镜头遮挡检测始终可用，手指遮挡检测依赖 MediaPipe

    @property
    def finger_detection_available(self) -> bool:
        """检查手指遮挡检测是否可用（需要 MediaPipe）"""
        return _mediapipe_available

    def _get_face_landmarker(self):
        """获取 FaceLandmarker 实例（延迟初始化）"""
        if self._init_error:
            return None

        if self._face_landmarker is None:
            if not _mediapipe_available:
                self._init_error = "MediaPipe 未安装或加载失败"
                return None

            try:
                from mediapipe.tasks import python
                from mediapipe.tasks.python import vision

                model_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")

                if not os.path.exists(model_path):
                    self._init_error = f"模型文件不存在: {model_path}"
                    logger.error(self._init_error)
                    return None

                with open(model_path, "rb") as f:
                    model_data = f.read()

                self._face_landmarker = vision.FaceLandmarker.create_from_options(
                    vision.FaceLandmarkerOptions(
                        base_options=python.BaseOptions(model_asset_buffer=model_data),
                        running_mode=vision.RunningMode.IMAGE,
                        num_faces=5,
                        min_face_detection_confidence=0.5,
                    )
                )
                logger.info("FaceLandmarker 初始化成功（遮挡检测器）")

            except Exception as e:
                self._init_error = f"FaceLandmarker 初始化失败: {e}"
                logger.error(self._init_error)
                return None

        return self._face_landmarker

    def detect(self, image_path: str) -> DetectionResult:
        """检测图片是否存在遮挡"""
        try:
            img = self.read_image(image_path)
            if img is None:
                return DetectionResult(
                    is_defective=False,
                    defect_type=None,
                    confidence=0.0,
                    description="无法读取图像，跳过遮挡检测"
                )

            reasons = []
            scores = []

            # 预检查：跳过纯黑/纯白图像
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            mean_brightness = float(np.mean(gray))
            if mean_brightness < 15 or mean_brightness > 240:
                return DetectionResult(
                    is_defective=False,
                    defect_type=None,
                    confidence=0.0,
                    description=f"图像亮度异常(均值={mean_brightness:.1f})，跳过遮挡检测"
                )

            # 1. 镜头遮挡检测（始终执行，不依赖 MediaPipe）
            lens_result = self._detect_lens_obstruction(img)
            if lens_result["is_obstructed"]:
                scores.append(lens_result["confidence"])
                reasons.append(lens_result["description"])

            # 2. 手指遮挡检测（需要 MediaPipe 和人脸）
            if _mediapipe_available:
                finger_result = self._detect_finger_obstruction(img)
                if finger_result["is_obstructed"]:
                    scores.append(finger_result["confidence"])
                    reasons.append(finger_result["description"])
            else:
                # MediaPipe 不可用时，记录但不影响检测结果
                logger.debug("手指遮挡检测跳过：MediaPipe 不可用")

            # 综合判断
            if scores:
                max_confidence = max(scores)
                return DetectionResult(
                    is_defective=True,
                    defect_type=self.defect_type,
                    confidence=max_confidence,
                    description=f"遮挡检测: {'; '.join(reasons)}"
                )
            else:
                return DetectionResult(
                    is_defective=False,
                    defect_type=None,
                    confidence=0.8,
                    description="未检测到遮挡"
                )

        except Exception as e:
            logger.error(f"遮挡检测异常: {e}")
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.0,
                description=f"遮挡检测异常: {str(e)}"
            )

    def _detect_lens_obstruction(self, img: np.ndarray) -> dict:
        """镜头遮挡检测（不依赖 MediaPipe）"""
        h, w = img.shape[:2]

        rows, cols = 5, 5
        cell_h, cell_w = h // rows, w // cols

        cell_stats = []
        for r in range(rows):
            for c in range(cols):
                y1, y2 = r * cell_h, (r + 1) * cell_h if r < rows - 1 else h
                x1, x2 = c * cell_w, (c + 1) * cell_w if c < cols - 1 else w
                cell = img[y1:y2, x1:x2]
                mean_bright = float(np.mean(cell))
                std_b = float(np.std(cell[:, :, 0]))
                std_g = float(np.std(cell[:, :, 1]))
                std_r = float(np.std(cell[:, :, 2]))
                avg_std = (std_b + std_g + std_r) / 3.0
                cell_stats.append({
                    "row": r, "col": c,
                    "brightness": mean_bright,
                    "std": avg_std,
                })

        center_cells = [s for s in cell_stats if 1 <= s["row"] <= 3 and 1 <= s["col"] <= 3]
        center_avg_bright = float(np.mean([c["brightness"] for c in center_cells])) if center_cells else 128

        edge_cells = [s for s in cell_stats if s["row"] == 0 or s["row"] == 4 or s["col"] == 0 or s["col"] == 4]
        corner_cells = [s for s in cell_stats if (s["row"] == 0 or s["row"] == 4) and (s["col"] == 0 or s["col"] == 4)]

        reasons = []
        scores = []

        # Check 1: Edge cells darker than center
        dark_edge_count = 0
        for s in edge_cells:
            if s["brightness"] < center_avg_bright * 0.5 and s["std"] < 25:
                dark_edge_count += 1
        dark_edge_ratio = dark_edge_count / len(edge_cells) if edge_cells else 0
        if dark_edge_ratio >= 0.4:
            scores.append(min(1.0, dark_edge_ratio))
            reasons.append(f"边缘偏暗{dark_edge_count}/{len(edge_cells)}")

        # Check 2: Corner cells uniform and different from center
        obstructed_corners = 0
        for s in corner_cells:
            color_diff = abs(s["brightness"] - center_avg_bright)
            if s["std"] < self.CORNER_UNIFORMITY_THRESHOLD and color_diff > 30:
                obstructed_corners += 1
        corner_ratio = obstructed_corners / len(corner_cells) if corner_cells else 0
        if corner_ratio >= 0.25:
            scores.append(min(1.0, corner_ratio + 0.2))
            reasons.append(f"角落异常{obstructed_corners}/{len(corner_cells)}")

        # Check 3: Overall darkness uniformity
        all_brights = [s["brightness"] for s in cell_stats]
        overall_std = float(np.std(all_brights))
        overall_mean = float(np.mean(all_brights))
        if overall_mean < 60 and overall_std < 20:
            scores.append(0.8)
            reasons.append("整体偏暗均匀")

        # Check 4: Edge cells very uniform
        uniform_edge_count = 0
        for s in edge_cells:
            color_diff = abs(s["brightness"] - center_avg_bright)
            if s["std"] < 8 and color_diff > 25:
                uniform_edge_count += 1
        uniform_edge_ratio = uniform_edge_count / len(edge_cells) if edge_cells else 0
        if uniform_edge_ratio >= 0.3:
            scores.append(min(1.0, uniform_edge_ratio + 0.1))
            reasons.append(f"边缘均匀异常{uniform_edge_count}/{len(edge_cells)}")

        if scores:
            return {
                "is_obstructed": True,
                "confidence": max(scores),
                "description": f"镜头遮挡: {'; '.join(reasons)}"
            }

        return {"is_obstructed": False, "confidence": 0.0, "description": ""}

    def _detect_finger_obstruction(self, img: np.ndarray) -> dict:
        """手指遮挡检测（需要 MediaPipe）"""
        if not _mediapipe_available:
            return {"is_obstructed": False, "confidence": 0.0, "description": ""}

        face_landmarker = self._get_face_landmarker()
        if face_landmarker is None:
            return {"is_obstructed": False, "confidence": 0.0, "description": ""}

        try:
            h, w = img.shape[:2]
            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_img)

            detection_result = face_landmarker.detect(image)

            if not detection_result.face_landmarks:
                return {"is_obstructed": False, "confidence": 0.0, "description": ""}

            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            skin_mask = cv2.inRange(hsv, self.SKIN_LOWER, self.SKIN_UPPER)

            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, kernel, iterations=1)

            total_pixels = h * w
            total_skin = cv2.countNonZero(skin_mask)
            skin_ratio = total_skin / total_pixels

            if skin_ratio > 0.55:
                conf = min(1.0, (skin_ratio - 0.55) / 0.25 + 0.5)
                return {
                    "is_obstructed": True,
                    "confidence": conf,
                    "description": f"手指遮挡: 肤色占比={skin_ratio:.1%}"
                }

            for face_landmarks in detection_result.face_landmarks:
                xs = [lm.x * w for lm in face_landmarks]
                ys = [lm.y * h for lm in face_landmarks]
                x_min, x_max = int(min(xs)), int(max(xs))
                y_min, y_max = int(min(ys)), int(max(ys))
                face_w, face_h = x_max - x_min, y_max - y_min
                margin = 20

                regions = [
                    ("上方", max(0, y_min - face_h // 2), y_min,
                     max(0, x_min - margin), min(w, x_max + margin)),
                    ("下方", y_max, min(h, y_max + face_h // 2),
                     max(0, x_min - margin), min(w, x_max + margin)),
                    ("左侧", max(0, y_min - margin), min(h, y_max + margin),
                     max(0, x_min - face_w // 2), x_min),
                    ("右侧", max(0, y_min - margin), min(h, y_max + margin),
                     x_max, min(w, x_max + face_w // 2)),
                ]

                for name, y1, y2, x1, x2 in regions:
                    if y2 > y1 and x2 > x1:
                        region = skin_mask[y1:y2, x1:x2]
                        region_ratio = cv2.countNonZero(region) / region.size
                        if region_ratio > 0.6:
                            conf = min(1.0, region_ratio)
                            return {
                                "is_obstructed": True,
                                "confidence": conf,
                                "description": f"手指遮挡: 人脸{name}肤色集中(占比={region_ratio:.1%})"
                            }

            return {"is_obstructed": False, "confidence": 0.0, "description": ""}

        except Exception as e:
            logger.error(f"手指遮挡检测异常: {e}")
            return {"is_obstructed": False, "confidence": 0.0, "description": ""}