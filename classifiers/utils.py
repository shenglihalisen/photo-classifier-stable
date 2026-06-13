# -*- coding: utf-8 -*-
"""
检测器公共工具模块
提供 FaceLandmarker 线程安全单例工厂，消除各检测器中的重复初始化代码
"""

import os
import logging
import threading
import numpy as np

logger = logging.getLogger("photo_classifier.utils")

# 图像像素数上限（防止超大图片导致内存溢出）
MAX_IMAGE_PIXELS = 89478485  # 约 9500x9400


class FaceDetectorMixin:
    """
    人脸检测器共享基类

    提供 FaceLandmarker 初始化、资源释放、图像像素检查等公共方法，
    供 BlinkDetector 和 ObstructionDetector 继承，消除重复代码。
    """

    def _init_face_detector(self):
        """初始化人脸检测器资源"""
        self._face_landmarker = None

    def _release_face_detector(self):
        """释放 FaceLandmarker 资源"""
        if self._face_landmarker is not None:
            try:
                self._face_landmarker.close()
            except Exception as e:
                logger.warning("释放 FaceLandmarker 资源时出错: %s", e)
            finally:
                self._face_landmarker = None

    def _get_face_landmarker(self):
        """获取 FaceLandmarker 实例（使用单例工厂）"""
        if self._face_landmarker is None:
            self._face_landmarker = FaceLandmarkerFactory.get_instance()
        return self._face_landmarker

    @staticmethod
    def _check_pixel_limit(img) -> bool:
        """检查图像像素数是否超出限制，返回 True 表示正常"""
        h, w = img.shape[:2]
        return h * w <= MAX_IMAGE_PIXELS


class FaceLandmarkerFactory:
    """
    FaceLandmarker 线程安全单例工厂

    所有需要 FaceLandmarker 的检测器共享同一个实例，
    避免重复加载模型文件和占用 GPU/内存资源。
    """

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """
        获取 FaceLandmarker 单例实例（线程安全）

        首次调用时延迟初始化，后续调用直接返回已有实例。

        返回:
            mediapipe FaceLandmarker 实例
        """
        if cls._instance is None:
            with cls._lock:
                # 双重检查锁定
                if cls._instance is None:
                    cls._instance = cls._create_landmarker()
        return cls._instance

    @classmethod
    def _create_landmarker(cls):
        """创建 FaceLandmarker 实例"""
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        model_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"模型文件不存在: {model_path}")

        with open(model_path, "rb") as f:
            model_data = f.read()

        landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_buffer=model_data),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=5,
                min_face_detection_confidence=0.5,
            )
        )
        logger.info("FaceLandmarker 单例初始化成功")
        return landmarker

    @classmethod
    def release(cls):
        """
        释放 FaceLandmarker 单例资源

        在应用关闭或不再需要检测时调用。
        """
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.close()
                    logger.info("FaceLandmarker 单例资源已释放")
                except Exception as e:
                    logger.warning(f"释放 FaceLandmarker 资源时出错: {e}")
                finally:
                    cls._instance = None
