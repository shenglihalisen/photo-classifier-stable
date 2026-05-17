import os
import pytest
from classifiers.corrupted import CorruptedDetector
from classifiers.base import DefectType


class TestCorruptedDetector:
    def setup_method(self):
        self.detector = CorruptedDetector()

    def test_normal_image(self):
        from tests.helpers import make_test_image
        path = make_test_image()
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_corrupted_file(self):
        from tests.helpers import make_corrupted_file
        path = make_corrupted_file()
        result = self.detector.detect(path)
        assert result.is_defective
        assert result.defect_type == DefectType.CORRUPTED
        os.remove(path)

    def test_empty_file(self):
        from tests.helpers import make_empty_file
        path = make_empty_file()
        result = self.detector.detect(path)
        assert result.is_defective
        assert result.defect_type == DefectType.CORRUPTED
        os.remove(path)

    def test_nonexistent_file(self):
        result = self.detector.detect("/nonexistent/path.jpg")
        assert result.is_defective
        assert result.defect_type == DefectType.CORRUPTED
        assert result.confidence == 1.0

    def test_bmp_image(self):
        from tests.helpers import make_test_image
        path = make_test_image(fmt='png')
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_defect_type_property(self):
        assert self.detector.defect_type == DefectType.CORRUPTED
