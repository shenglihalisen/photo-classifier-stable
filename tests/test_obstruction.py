import os
import pytest
from classifiers.obstruction import ObstructionDetector
from classifiers.base import DefectType


class TestObstructionDetector:
    def setup_method(self):
        self.detector = ObstructionDetector()

    def test_normal_image(self):
        from tests.helpers import make_sharp_image
        path = make_sharp_image()
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_nonexistent_file(self):
        result = self.detector.detect("/nonexistent.jpg")
        assert not result.is_defective

    def test_black_image_skipped(self):
        from tests.helpers import make_test_image
        path = make_test_image(100, 100, (0, 0, 0))
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_defect_type_property(self):
        assert self.detector.defect_type == DefectType.OBSTRUCTION

    def test_face_landmarker_caching(self):
        assert self.detector._face_landmarker is None
        lm1 = self.detector._get_face_landmarker()
        lm2 = self.detector._get_face_landmarker()
        assert lm1 is lm2
