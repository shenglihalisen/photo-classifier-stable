# -*- coding: utf-8 -*-
"""
重复照片检测器
通过图像指纹（感知哈希）检测几乎相同的照片
"""

import os
import logging
import cv2
import numpy as np
from typing import Callable

logger = logging.getLogger("photo_classifier.duplicate")


class DuplicateDetector:
    """
    重复照片检测器

    使用 pHash（感知哈希）算法，对图片缩放后做 DCT 变换，
    比较哈希汉明距离来判断两张图片是否几乎相同。
    """

    HASH_SIZE = 16        # 哈希尺寸（16x16 = 256 bit）
    SIMILARITY_THRESHOLD = 5  # 汉明距离阈值（越小越严格）

    def find_duplicates(
        self,
        image_paths: list[str],
        callback: Callable[[int, int, str], None] | None = None,
    ) -> list[list[str]]:
        """
        找出所有重复照片组

        参数:
            image_paths: 图片文件路径列表
            callback: 进度回调 callback(current, total, current_path)

        返回:
            重复组列表，每组包含路径列表（至少 2 张）
        """
        if len(image_paths) < 2:
            return []

        # 1. 计算所有图片的感知哈希
        hashes = {}
        total = len(image_paths)
        for i, path in enumerate(image_paths):
            if callback:
                callback(i + 1, total, path)
            h = self._compute_phash(path)
            if h is not None:
                hashes[path] = h

        if len(hashes) < 2:
            return []

        # 2. 两两比较汉明距离
        paths = list(hashes.keys())
        visited = set()
        groups = []

        for i in range(len(paths)):
            if paths[i] in visited:
                continue
            group = [paths[i]]
            for j in range(i + 1, len(paths)):
                if paths[j] in visited:
                    continue
                distance = self._hamming_distance(hashes[paths[i]], hashes[paths[j]])
                if distance <= self.SIMILARITY_THRESHOLD:
                    group.append(paths[j])
                    visited.add(paths[j])
            if len(group) >= 2:
                visited.add(paths[i])
                groups.append(sorted(group))

        return groups

    def _compute_phash(self, image_path: str) -> np.ndarray | None:
        """
        计算图片的感知哈希 (pHash)

        返回:
            256-bit 哈希数组，失败返回 None
        """
        try:
            with open(image_path, 'rb') as f:
                data = np.frombuffer(f.read(), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return None

            # 缩放到 hash_size*4 x hash_size*4
            resize_size = self.HASH_SIZE * 4
            img = cv2.resize(img, (resize_size, resize_size), interpolation=cv2.INTER_AREA)

            # DCT 变换
            img_float = np.float64(img)
            dct = cv2.dct(img_float)

            # 取左上角低频系数
            dct_low = dct[:self.HASH_SIZE, :self.HASH_SIZE]

            # 计算中位数作为阈值
            median = np.median(dct_low)

            # 生成哈希：大于中位数为 1，否则为 0
            hash_array = (dct_low > median).flatten().astype(np.uint8)
            return hash_array

        except Exception as e:
            logger.warning(f"计算感知哈希失败: {image_path}, 错误: {e}")
            return None

    def _hamming_distance(self, hash1: np.ndarray, hash2: np.ndarray) -> int:
        """计算两个哈希的汉明距离"""
        if len(hash1) != len(hash2):
            return len(hash1)
        return int(np.sum(hash1 != hash2))
