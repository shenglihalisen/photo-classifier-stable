# -*- coding: utf-8 -*-
"""
闭眼检测器
使用 MediaPipe Face Mesh 检测人脸，通过 Eye Aspect Ratio (EAR) 判断是否闭眼
"""

import cv2
import numpy as np

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
    # 左眼（从观察者角度的右眼）
    LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
    # 右眼（从观察者角度的左眼）
    RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380]

    def __init__(self):
        self._face_mesh = None

    @property
    def defect_type(self) -> DefectType:
        return DefectType.BLINK

    def _get_face_mesh(self):
        """延迟初始化 MediaPipe Face Mesh"""
        if self._face_mesh is None:
            import mediapipe as mp
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=5,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.15,
            )
        return self._face_mesh

    def detect(self, image_path: str) -> DetectionResult:
        """检测图片中是否有人闭眼"""
        try:
            img = self.read_image(image_path)
            if img is None:
                return DetectionResult(
                    is_defective=False,
                    defect_type=None,
                    confidence=0.0,
                    description="无法读取图像，跳过闭眼检测"
                )

            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            face_mesh = self._get_face_mesh()
            results = face_mesh.process(rgb_img)

            # 无人脸检测到，不判定为废片
            if not results.multi_face_landmarks:
                return DetectionResult(
                    is_defective=False,
                    defect_type=None,
                    confidence=0.0,
                    description="未检测到人脸，跳过闭眼检测"
                )

            face_count = len(results.multi_face_landmarks)
            blink_faces = []
            min_ear = 1.0

            for face_idx, face_landmarks in enumerate(results.multi_face_landmarks):
                h, w = img.shape[:2]

                # 提取左眼和右眼关键点
                left_eye_pts = self._get_eye_points(face_landmarks, self.LEFT_EYE_INDICES, w, h)
                right_eye_pts = self._get_eye_points(face_landmarks, self.RIGHT_EYE_INDICES, w, h)

                # 计算 EAR
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

        except Exception as e:
            return DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.0,
                description=f"闭眼检测异常: {str(e)}"
            )

    def _get_eye_points(self, face_landmarks, indices: list, width: int, height: int) -> np.ndarray:
        """
        从人脸关键点中提取眼部坐标

        参数:
            face_landmarks: MediaPipe 人脸关键点
            indices: 眼部关键点索引列表
            width: 图像宽度
            height: 图像高度

        返回:
            shape=(6, 2) 的 numpy 数组，每行为 (x, y) 坐标
        """
        points = []
        for idx in indices:
            landmark = face_landmarks.landmark[idx]
            x = landmark.x * width
            y = landmark.y * height
            points.append([x, y])
        return np.array(points, dtype=np.float64)

    def _calculate_ear(self, eye_points: np.ndarray) -> float:
        """
        计算 Eye Aspect Ratio (EAR)

        EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)

        其中 p1-p6 为眼部6个关键点:
            p1, p4: 眼角水平方向
            p2, p3, p5, p6: 眼睛上下边缘

        参数:
            eye_points: shape=(6, 2) 的眼部关键点坐标

        返回:
            EAR 值，越小表示眼睛越闭合
        """
        # 计算垂直距离（眼睛上下边缘）
        dist_1 = np.linalg.norm(eye_points[1] - eye_points[5])  # p2-p6
        dist_2 = np.linalg.norm(eye_points[2] - eye_points[4])  # p3-p5

        # 计算水平距离（眼角）
        dist_3 = np.linalg.norm(eye_points[0] - eye_points[3])  # p1-p4

        # 避免除以零
        if dist_3 == 0:
            return 0.0

        ear = (dist_1 + dist_2) / (2.0 * dist_3)
        return float(ear)
