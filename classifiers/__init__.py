# -*- coding: utf-8 -*-
"""照片缺陷检测模块"""

from .base import BaseDetector, DetectionResult, DefectType
from .corrupted import CorruptedDetector
from .empty import EmptyDetector
from .blink import BlinkDetector
from .blur import BlurDetector
from .obstruction import ObstructionDetector

__all__ = [
    "BaseDetector",
    "DetectionResult",
    "DefectType",
    "CorruptedDetector",
    "EmptyDetector",
    "BlinkDetector",
    "BlurDetector",
    "ObstructionDetector",
]
