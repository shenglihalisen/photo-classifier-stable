import os
import pytest
from classifiers.blink import BlinkDetector
from classifiers.base import DefectType


class TestBlinkDetector:
    def setup_method(self):
        self.detector = BlinkDetector()

    def test_no_face_no_blink(self):
        from tests.helpers import make_sharp_image
        path = make_sharp_image()
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_nonexistent_file(self):
        result = self.detector.detect("/nonexistent.jpg")
        assert not result.is_defective

    def test_defect_type_property(self):
        assert self.detector.defect_type == DefectType.BLINK

    def test_lazy_face_landmarker_init(self):
        assert self.detector._face_landmarker is None
        landmarker = self.detector._get_face_landmarker()
        assert landmarker is not None
        assert self.detector._face_landmarker is landmarker
