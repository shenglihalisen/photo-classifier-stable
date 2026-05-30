# -*- coding: utf-8 -*-
"""
检测器公共工具模块
提供 FaceLandmarker 线程安全单例工厂，消除各检测器中的重复初始化代码
"""

import os
import logging
import threading

logger = logging.getLogger("photo_classifier.utils")


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
