import os
import pytest
from classifiers.blur import BlurDetector
from classifiers.base import DefectType


class TestBlurDetector:
    def setup_method(self):
        self.detector = BlurDetector()

    def test_sharp_image(self):
        from tests.helpers import make_sharp_image
        path = make_sharp_image()
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_blurry_image(self):
        from tests.helpers import make_blurry_image
        path = make_blurry_image()
        result = self.detector.detect(path)
        assert result.is_defective
        assert result.defect_type == DefectType.BLURRY
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
        assert self.detector.defect_type == DefectType.BLURRY
