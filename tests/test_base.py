import os
import pytest
from classifiers.base import DefectType, DetectionResult, BaseDetector


class TestDefectType:
    def test_values(self):
        assert DefectType.CORRUPTED.value == "corrupted"
        assert DefectType.EMPTY.value == "empty"
        assert DefectType.BLINK.value == "blink"
        assert DefectType.BLURRY.value == "blurry"
        assert DefectType.OBSTRUCTION.value == "obstruction"

    def test_uniqueness(self):
        values = [t.value for t in DefectType]
        assert len(values) == len(set(values))


class TestDetectionResult:
    def test_defective_result(self):
        r = DetectionResult(is_defective=True, defect_type=DefectType.BLURRY, confidence=0.85, description="模糊")
        assert r.is_defective
        assert r.defect_type == DefectType.BLURRY
        assert r.confidence == 0.85
        assert r.description == "模糊"

    def test_normal_result(self):
        r = DetectionResult(is_defective=False, defect_type=None, confidence=1.0, description="正常")
        assert not r.is_defective
        assert r.defect_type is None

    def test_dataclass_repr(self):
        r = DetectionResult(True, DefectType.CORRUPTED, 0.9, "损坏")
        s = repr(r)
        assert "is_defective=True" in s
        assert "corrupted" in s
        assert "0.9" in s


class TestBaseDetector:
    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseDetector()

    def test_read_image_valid(self):
        from tests.helpers import make_test_image
        path = make_test_image()
        img = BaseDetector.read_image(path)
        assert img is not None
        assert img.shape == (80, 100, 3)
        os.remove(path)

    def test_read_image_nonexistent(self):
        img = BaseDetector.read_image("nonexistent.jpg")
        assert img is None
