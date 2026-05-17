import os
import tempfile
import numpy as np
import cv2
import pytest
from classifiers.empty import EmptyDetector
from classifiers.base import DefectType


class TestEmptyDetector:
    def setup_method(self):
        self.detector = EmptyDetector()

    def test_normal_image_not_empty(self):
        img = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        fd, path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        cv2.imwrite(path, img)
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_pure_black_image(self):
        from tests.helpers import make_test_image
        path = make_test_image(100, 100, (0, 0, 0))
        result = self.detector.detect(path)
        assert result.is_defective
        assert result.defect_type == DefectType.EMPTY
        os.remove(path)

    def test_pure_white_image(self):
        from tests.helpers import make_blank_image
        path = make_blank_image(100, 100)
        result = self.detector.detect(path)
        assert result.is_defective
        assert result.defect_type == DefectType.EMPTY
        os.remove(path)

    def test_nonexistent_file(self):
        result = self.detector.detect("/nonexistent.jpg")
        assert not result.is_defective

    def test_colorful_image_not_empty(self):
        import numpy as np, cv2
        img = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        fd, path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        cv2.imwrite(path, img)
        result = self.detector.detect(path)
        assert not result.is_defective
        os.remove(path)

    def test_defect_type_property(self):
        assert self.detector.defect_type == DefectType.EMPTY
