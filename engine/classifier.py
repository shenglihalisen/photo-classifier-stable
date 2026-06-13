# -*- coding: utf-8 -*-
"""
统一分类引擎
整合所有检测器，提供统一的图片分类接口
"""

import os
import csv
import json
import logging
import shutil
import gc
from datetime import datetime
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from classifiers.base import DetectionResult, DefectType, MAX_FILE_SIZE, PrecomputedImage
from classifiers.corrupted import CorruptedDetector
from classifiers.empty import EmptyDetector
from classifiers.blink import BlinkDetector
from classifiers.blur import BlurDetector
from classifiers.obstruction import ObstructionDetector
from classifiers.exposure import ExposureDetector
from classifiers.noise import NoiseDetector
from classifiers.duplicate import DuplicateDetector

logger = logging.getLogger("photo_classifier.engine")


# 支持的图片扩展名
SUPPORTED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif',
    '.webp', '.gif', '.heic', '.heif'
}


class PhotoClassifier:
    """
    照片分类引擎

    整合所有检测器，对单张或多张照片进行缺陷检测和分类。
    """

    def classify(self, image_path: str) -> list[DetectionResult]:
        """
        对单张图片进行分类检测

        读取图像一次，共享给所有检测器，避免重复 I/O。
        如果文件损坏，直接返回，不运行其他检测器。

        参数:
            image_path: 图片文件路径

        返回:
            检测结果列表
        """
        # 文件大小预检查
        try:
            file_size = os.path.getsize(image_path)
            if file_size > MAX_FILE_SIZE:
                logger.warning(
                    f"文件过大，跳过分类: {image_path} "
                    f"(大小={file_size / 1024 / 1024:.1f}MB, 上限={MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"
                )
                return [DetectionResult(
                    is_defective=False,
                    defect_type=None,
                    confidence=0.0,
                    description=f"文件过大({file_size / 1024 / 1024:.1f}MB)，跳过所有检测"
                )]
        except OSError as e:
            logger.error(f"无法获取文件信息: {image_path}, 错误: {e}")
            return [DetectionResult(
                is_defective=False,
                defect_type=None,
                confidence=0.0,
                description=f"无法获取文件信息: {e}"
            )]

        # 统一读取图像一次，所有检测器共享
        image = self.detectors[0].read_image(image_path)

        # 预计算共享值（灰度图、拉普拉斯方差、颜色标准差）
        precomputed = PrecomputedImage(image) if image is not None else None

        results = []

        for detector in self.detectors:
            result = detector.detect(image_path, image=image, precomputed=precomputed)
            results.append(result)

            # 如果文件损坏，直接返回，不运行后续检测器
            if result.is_defective and result.defect_type == DefectType.CORRUPTED:
                break

        return results

    def classify_batch(
        self,
        image_paths: list[str],
        callback: Callable[[int, int, str], None] | None = None,
        max_workers: int = 4,
    ) -> dict[str, list[DetectionResult]]:
        """
        批量分类图片（并行处理加速）

        参数:
            image_paths: 图片文件路径列表
            callback: 进度回调函数 callback(current, total, current_path)
            max_workers: 最大并行线程数

        返回:
            字典 {图片路径: 检测结果列表}
        """
        total = len(image_paths)
        results = {}
        completed = 0

        def _classify_one(path):
            return path, self.classify(path)

        # 使用线程池并行处理（MediaPipe GIL 释放后可真正并行）
        with ThreadPoolExecutor(max_workers=min(max_workers, total or 1)) as executor:
            futures = {executor.submit(_classify_one, p): p for p in image_paths}
            for future in as_completed(futures):
                try:
                    path, detection_results = future.result()
                    results[path] = detection_results
                except Exception as e:
                    path = futures[future]
                    logger.error("分类失败 %s: %s", path, e)
                    results[path] = [DetectionResult(
                        is_defective=False, defect_type=None,
                        confidence=0.0, description=f"分类异常: {e}"
                    )]
                completed += 1
                if callback:
                    callback(completed, total, futures[future])

        return results

    def get_defective_images(
        self,
        image_paths: list[str],
        callback: Callable[[int, int, str], None] | None = None
    ) -> dict[str, list[DetectionResult]]:
        """
        批量分类并筛选出有缺陷的图片

        参数:
            image_paths: 图片文件路径列表
            callback: 进度回调函数

        返回:
            字典 {图片路径: 缺陷检测结果列表}（仅包含有缺陷的图片）
        """
        all_results = self.classify_batch(image_paths, callback)
        defective = {}

        for path, results in all_results.items():
            defects = [r for r in results if r.is_defective]
            if defects:
                defective[path] = defects

        return defective

    def find_duplicates(
        self,
        image_paths: list[str],
        callback: Callable[[int, int, str], None] | None = None
    ) -> list[list[str]]:
        """
        查找重复照片

        参数:
            image_paths: 图片文件路径列表
            callback: 进度回调函数

        返回:
            重复组列表，每组包含路径列表
        """
        return self.duplicate_detector.find_duplicates(image_paths, callback)

    def move_defective(
        self,
        defective_images: dict[str, list[DetectionResult]],
        target_base_dir: str,
        mode: str = "move"
    ) -> dict[str, str]:
        """
        将废片移动到按类型分类的子文件夹中

        在目标目录下创建 "废片" 子文件夹，按缺陷类型再分子文件夹。

        参数:
            defective_images: 废片字典 {路径: 缺陷列表}
            target_base_dir: 目标基础目录
            mode: "move" 移动文件, "copy" 复制文件

        返回:
            字典 {原路径: 新路径}
        """
        moved_files = {}

        # 缺陷类型对应的中文子文件夹名
        type_folder_names = {
            DefectType.CORRUPTED: "损坏",
            DefectType.EMPTY: "空镜",
            DefectType.BLINK: "闭眼",
            DefectType.BLURRY: "模糊",
            DefectType.OBSTRUCTION: "遮挡",
            DefectType.EXPOSURE: "曝光异常",
            DefectType.NOISY: "噪点",
        }

        for image_path, defects in defective_images.items():
            # 获取主要缺陷类型（取置信度最高的）
            main_defect = max(defects, key=lambda d: d.confidence)
            defect_type = main_defect.defect_type

            if defect_type is None:
                continue

            # 创建目标文件夹
            defect_folder_name = type_folder_names.get(defect_type, "其他")
            target_dir = os.path.join(target_base_dir, "废片", defect_folder_name)
            os.makedirs(target_dir, exist_ok=True)

            # 构建目标路径
            filename = os.path.basename(image_path)
            target_path = os.path.join(target_dir, filename)

            # 处理文件名冲突
            if os.path.exists(target_path) and target_path != image_path:
                name, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(target_path):
                    target_path = os.path.join(target_dir, f"{name}_{counter}{ext}")
                    counter += 1

            # 移动或复制文件（先复制再删除，保证原子性）
            try:
                if mode == "move":
                    shutil.copy2(image_path, target_path)
                    try:
                        os.remove(image_path)
                    except OSError as e:
                        logger.warning(f"删除源文件失败（副本已保留）{image_path}: {e}")
                elif mode == "copy":
                    shutil.copy2(image_path, target_path)
                moved_files[image_path] = target_path
            except (OSError, shutil.Error) as e:
                logger.error(f"操作文件失败 {image_path}: {e}")

        # 记录操作历史（仅移动操作支持撤销）
        if moved_files and mode == "move":
            self._operation_history.append(dict(moved_files))

        return moved_files

    @staticmethod
    def scan_directory(directory: str) -> list[str]:
        """
        扫描目录中的所有图片文件

        参数:
            directory: 要扫描的目录路径

        返回:
            图片文件路径列表（绝对路径）
        """
        image_files = []

        if not os.path.isdir(directory):
            return image_files

        for root, dirs, files in os.walk(directory):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    full_path = os.path.join(root, filename)
                    image_files.append(full_path)

        return image_files

    # ========================================================
    # 功能1：撤销支持 - 记录文件操作历史
    # ========================================================

    def __init__(self):
        """初始化所有检测器"""
        self.detectors = [
            CorruptedDetector(),
            EmptyDetector(),
            BlinkDetector(),
            BlurDetector(),
            ObstructionDetector(),
            ExposureDetector(),
            NoiseDetector(),
        ]
        self.duplicate_detector = DuplicateDetector()
        self._operation_history = []  # 操作历史记录

    def undo_last_move(self) -> dict[str, str]:
        """
        撤销上一次移动操作

        返回:
            字典 {新路径: 原路径}，表示已恢复的文件
        """
        if not self._operation_history:
            return {}

        last_ops = self._operation_history.pop()
        restored = {}

        for original_path, moved_path in last_ops.items():
            if os.path.exists(moved_path) and not os.path.exists(original_path):
                try:
                    original_dir = os.path.dirname(original_path)
                    os.makedirs(original_dir, exist_ok=True)
                    shutil.move(moved_path, original_path)
                    restored[moved_path] = original_path
                    logger.info(f"已恢复: {moved_path} -> {original_path}")
                except (OSError, shutil.Error) as e:
                    logger.error(f"恢复文件失败 {moved_path}: {e}")

        return restored

    def get_operation_history(self) -> list[dict]:
        """
        获取操作历史摘要

        返回:
            操作历史列表 [{操作类型, 文件数量, 时间}]
        """
        history = []
        for i, ops in enumerate(self._operation_history):
            history.append({
                "index": i,
                "count": len(ops),
                "files": [os.path.basename(p) for p in ops.keys()],
            })
        return history

    # ========================================================
    # 功能2：导出扫描报告
    # ========================================================

    def export_report(
        self,
        results: dict[str, list[DetectionResult]],
        output_path: str,
        format: str = "json"
    ) -> str:
        """
        导出扫描结果报告

        参数:
            results: 扫描结果字典
            output_path: 输出文件路径
            format: "json" 或 "csv"

        返回:
            输出文件路径
        """
        if format == "csv":
            return self._export_csv(results, output_path)
        else:
            return self._export_json(results, output_path)

    def _export_json(self, results: dict, output_path: str) -> str:
        """导出 JSON 格式报告"""
        report = {
            "generated_at": datetime.now().isoformat(),
            "total_photos": len(results),
            "summary": {"normal": 0, "defective": 0, "by_type": {}},
            "photos": [],
        }

        for path, detections in results.items():
            defects = [d for d in detections if d.is_defective]
            photo_info = {
                "path": path,
                "filename": os.path.basename(path),
                "is_defective": len(defects) > 0,
                "defects": [
                    {
                        "type": d.defect_type.value if d.defect_type else "unknown",
                        "confidence": round(d.confidence, 3),
                        "description": d.description,
                    }
                    for d in defects
                ],
                "all_results": [
                    {
                        "type": d.defect_type.value if d.defect_type else "ok",
                        "is_defective": d.is_defective,
                        "confidence": round(d.confidence, 3),
                    }
                    for d in detections
                ],
            }

            if defects:
                report["summary"]["defective"] += 1
                for d in defects:
                    dtype = d.defect_type.value if d.defect_type else "unknown"
                    report["summary"]["by_type"][dtype] = report["summary"]["by_type"].get(dtype, 0) + 1
            else:
                report["summary"]["normal"] += 1

            report["photos"].append(photo_info)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"JSON 报告已导出: {output_path}")
        return output_path

    def _export_csv(self, results: dict, output_path: str) -> str:
        """导出 CSV 格式报告"""
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["文件名", "路径", "是否废片", "缺陷类型", "置信度", "描述"])

            for path, detections in results.items():
                defects = [d for d in detections if d.is_defective]
                filename = os.path.basename(path)

                if defects:
                    for d in defects:
                        writer.writerow([
                            filename,
                            path,
                            "是",
                            d.defect_type.value if d.defect_type else "unknown",
                            f"{d.confidence:.1%}",
                            d.description,
                        ])
                else:
                    writer.writerow([filename, path, "否", "-", "-", "正常"])

        logger.info(f"CSV 报告已导出: {output_path}")
        return output_path

    # ========================================================
    # 功能3：EXIF 元数据提取
    # ========================================================

    @staticmethod
    def extract_metadata(image_path: str) -> dict:
        """
        提取图片 EXIF 元数据

        参数:
            image_path: 图片文件路径

        返回:
            元数据字典
        """
        metadata = {
            "filename": os.path.basename(image_path),
            "path": image_path,
            "size_bytes": 0,
            "size_human": "",
            "modified_time": "",
        }

        try:
            stat = os.stat(image_path)
            metadata["size_bytes"] = stat.st_size
            metadata["modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

            size = stat.st_size
            if size >= 1024 * 1024:
                metadata["size_human"] = f"{size / (1024 * 1024):.2f} MB"
            elif size >= 1024:
                metadata["size_human"] = f"{size / 1024:.1f} KB"
            else:
                metadata["size_human"] = f"{size} B"
        except OSError:
            pass

        # 尝试读取 EXIF
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS

            with Image.open(image_path) as img:
                metadata["width"] = img.width
                metadata["height"] = img.height
                metadata["format"] = img.format
                metadata["mode"] = img.mode

                exif_data = img.getexif()
                if exif_data:
                    exif = {}
                    for tag_id, value in exif_data.items():
                        tag = TAGS.get(tag_id, tag_id)
                        # 跳过不可序列化的值
                        try:
                            json.dumps(value)
                            exif[str(tag)] = str(value)
                        except (TypeError, ValueError):
                            exif[str(tag)] = str(value)[:100]
                    metadata["exif"] = exif

                    # 提取常用字段
                    if "DateTimeOriginal" in exif:
                        metadata["capture_time"] = exif["DateTimeOriginal"]
                    if "Make" in exif:
                        metadata["camera_make"] = exif["Make"]
                    if "Model" in exif:
                        metadata["camera_model"] = exif["Model"]
                    if "FocalLength" in exif:
                        metadata["focal_length"] = exif["FocalLength"]
                    if "FNumber" in exif:
                        metadata["aperture"] = exif["FNumber"]
                    if "ISOSpeedRatings" in exif:
                        metadata["iso"] = exif["ISOSpeedRatings"]
                    if "ExposureTime" in exif:
                        metadata["shutter_speed"] = exif["ExposureTime"]
        except Exception:
            pass

        return metadata

    # ========================================================
    # 功能4：照片质量评分
    # ========================================================

    @staticmethod
    def calculate_quality_score(detections: list[DetectionResult]) -> dict:
        """
        根据检测结果计算照片综合质量评分

        参数:
            detections: 检测结果列表

        返回:
            质量评分字典 {score, grade, details}
        """
        if not detections:
            return {"score": 0, "grade": "未知", "details": "无检测结果"}

        # 基础分 100，每个缺陷扣分
        score = 100.0
        deductions = []

        defect_names = {
            DefectType.CORRUPTED: "损坏",
            DefectType.EMPTY: "空镜",
            DefectType.BLINK: "闭眼",
            DefectType.BLURRY: "模糊",
            DefectType.OBSTRUCTION: "遮挡",
            DefectType.EXPOSURE: "曝光异常",
            DefectType.NOISY: "噪点",
        }

        defect_weights = {
            DefectType.CORRUPTED: 50,   # 损坏最严重
            DefectType.EMPTY: 40,
            DefectType.BLINK: 35,
            DefectType.OBSTRUCTION: 30,
            DefectType.BLURRY: 25,
            DefectType.EXPOSURE: 20,
            DefectType.NOISY: 15,
        }

        for d in detections:
            if d.is_defective and d.defect_type:
                weight = defect_weights.get(d.defect_type, 20)
                deduction = weight * d.confidence
                score -= deduction
                deductions.append(f"-{deduction:.0f}({defect_names.get(d.defect_type, '?')})")

        score = max(0, min(100, score))

        if score >= 80:
            grade = "优秀"
        elif score >= 60:
            grade = "良好"
        elif score >= 40:
            grade = "一般"
        elif score >= 20:
            grade = "较差"
        else:
            grade = "废片"

        return {
            "score": round(score, 1),
            "grade": grade,
            "deductions": deductions,
        }

    # ========================================================
    # 功能5：智能推荐（建议保留/删除）
    # ========================================================

    def suggest_actions(
        self,
        results: dict[str, list[DetectionResult]],
        threshold: float = 0.7
    ) -> dict[str, list[dict]]:
        """
        根据检测置信度智能推荐操作

        参数:
            results: 扫描结果字典
            threshold: 置信度阈值，高于此值建议删除

        返回:
            {"keep": [...], "review": [...], "delete": [...]}
        """
        suggestions = {"keep": [], "review": [], "delete": []}

        for path, detections in results.items():
            quality = self.calculate_quality_score(detections)
            defects = [d for d in detections if d.is_defective]
            max_confidence = max((d.confidence for d in defects), default=0)

            item = {
                "path": path,
                "filename": os.path.basename(path),
                "quality_score": quality["score"],
                "quality_grade": quality["grade"],
                "defect_count": len(defects),
                "max_confidence": round(max_confidence, 3),
            }

            if not defects:
                suggestions["keep"].append(item)
            elif max_confidence >= threshold:
                suggestions["delete"].append(item)
            else:
                suggestions["review"].append(item)

        # 按质量评分排序
        suggestions["keep"].sort(key=lambda x: x["quality_score"], reverse=True)
        suggestions["review"].sort(key=lambda x: x["quality_score"], reverse=True)
        suggestions["delete"].sort(key=lambda x: x["max_confidence"], reverse=True)

        return suggestions
