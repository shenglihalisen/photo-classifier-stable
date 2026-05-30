# -*- coding: utf-8 -*-
"""
闭眼检测器
使用 MediaPipe Face Mesh 检测人脸，通过 Eye Aspect Ratio (EAR) 判断是否闭眼

强制使用 MediaPipe，加载失败时抛出错误
"""

import os
import platform
import logging
import cv2
import numpy as np

# 设置日志
logger = logging.getLogger("photo_classifier.blink")

# 强制导入 MediaPipe，失败时抛出错误
import mediapipe as mp
logger.info(f"MediaPipe 已加载，版本: {mp.__version__}, 平台: {platform.machine()}")

from .base import BaseDetector, DetectionResult, DefectType


class BlinkDetector(BaseDetector):
    """
    闭眼检测器

    使用 MediaPipe Face Mesh 提取眼部关键点，
    计算 Eye Aspect Ratio (EAR) 来判断是否闭眼。
    如果检测到多个人脸，任一人闭眼即标记为缺陷。
    无人脸时返回非缺陷（不判定为废片）。
    """

    # EAR 阈值
    EAR_THRESHOLD = 0.2

    # MediaPipe Face Mesh 眼部关键点索引
    LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380]

    def __init__(self):
        self._face_landmarker = None

    @property
    def defect_type(self) -> DefectType:
        return DefectType.BLINK

    def _get_face_landmarker(self):
        """获取 FaceLandmarker 实例（延迟初始化）"""
        if self._face_landmarker is None:
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            model_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")

            if not os.path.exists(model_path):
                raise FileNotFoundError(f"模型文件不存在: {model_path}")

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
            logger.info("FaceLandmarker 初始化成功")

        return self._face_landmarker

    def detect(self, image_path: str) -> DetectionResult:
        """检测图片中是否有人闭眼"""
        img = self.read_image(image_path)
        if img is None:
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.0,
                description="无法读取图像，跳过闭眼检测"
            )

        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_img)
        
        face_landmarker = self._get_face_landmarker()
        detection_result = face_landmarker.detect(image)

        if not detection_result.face_landmarks:
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.0,
                description="未检测到人脸，跳过闭眼检测"
            )

        face_count = len(detection_result.face_landmarks)
        blink_faces = []
        min_ear = 1.0

        for face_idx, face_landmarks in enumerate(detection_result.face_landmarks):
            h, w = img.shape[:2]

            left_eye_pts = self._get_eye_points(face_landmarks, self.LEFT_EYE_INDICES, w, h)
            right_eye_pts = self._get_eye_points(face_landmarks, self.RIGHT_EYE_INDICES, w, h)

            left_ear = self._calculate_ear(left_eye_pts)
            right_ear = self._calculate_ear(right_eye_pts)
            avg_ear = (left_ear + right_ear) / 2.0

            min_ear = min(min_ear, avg_ear)

            if avg_ear < self.EAR_THRESHOLD:
                blink_faces.append(face_idx + 1)

        if blink_faces:
            confidence = min(1.0, (self.EAR_THRESHOLD - min_ear) / self.EAR_THRESHOLD + 0.5)
            return DetectionResult(
                is_defective=True,
                defect_type=self.defect_type,
                confidence=confidence,
                description=f"检测到{face_count}张人脸，第{blink_faces}张人脸闭眼 "
                           f"(最小EAR={min_ear:.3f}, 阈值={self.EAR_THRESHOLD})"
            )
        else:
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=1.0,
                description=f"检测到{face_count}张人脸，均未闭眼 (最小EAR={min_ear:.3f})"
            )

    def _get_eye_points(self, face_landmarks, indices: list, width: int, height: int) -> np.ndarray:
        points = []
        for idx in indices:
            landmark = face_landmarks[idx]
            x = landmark.x * width
            y = landmark.y * height
            points.append([x, y])
        return np.array(points, dtype=np.float64)

    def _calculate_ear(self, eye_points: np.ndarray) -> float:
        """计算 Eye Aspect Ratio (EAR)"""
        dist_1 = np.linalg.norm(eye_points[1] - eye_points[5])
        dist_2 = np.linalg.norm(eye_points[2] - eye_points[4])
        dist_3 = np.linalg.norm(eye_points[0] - eye_points[3])

        if dist_3 == 0:
            return 0.0

        ear = (dist_1 + dist_2) / (2.0 * dist_3)
        return float(ear)
