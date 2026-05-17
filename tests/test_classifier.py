import pytest, os, tempfile, shutil
from engine.classifier import PhotoClassifier
from classifiers.base import DetectionResult, DefectType


class TestPhotoClassifier:
    def setup_method(self):
        self.classifier = PhotoClassifier()

    def test_classify_normal(self):
        from tests.helpers import make_test_image
        path = make_test_image()
        results = self.classifier.classify(path)
        assert len(results) >= 1
        os.remove(path)

    def test_classify_corrupted_shortcircuit(self):
        from tests.helpers import make_corrupted_file
        path = make_corrupted_file()
        results = self.classifier.classify(path)
        assert results[-1].defect_type == DefectType.CORRUPTED
        assert results[-1].is_defective
        os.remove(path)

    def test_classify_batch(self):
        from tests.helpers import make_test_image
        paths = [make_test_image() for _ in range(3)]
        results = self.classifier.classify_batch(paths)
        assert len(results) == 3
        assert all(isinstance(v, list) for v in results.values())
        for p in paths:
            os.remove(p)

    def test_classify_batch_with_callback(self):
        from tests.helpers import make_test_image
        paths = [make_test_image() for _ in range(3)]
        calls = []
        results = self.classifier.classify_batch(
            paths, callback=lambda c, t, p: calls.append((c, t))
        )
        assert len(calls) == 3
        for i, (c, t) in enumerate(calls):
            assert c == i + 1
            assert t == 3
        for p in paths:
            os.remove(p)

    def test_get_defective_images(self):
        from tests.helpers import make_sharp_image, make_corrupted_file
        normal = make_sharp_image()
        bad = make_corrupted_file()
        results = self.classifier.get_defective_images([normal, bad])
        assert normal not in results
        assert bad in results
        os.remove(normal)
        os.remove(bad)

    def test_scan_directory(self):
        tmpdir = tempfile.mkdtemp()
        from tests.helpers import make_test_image
        p1 = make_test_image()
        p2 = make_test_image(fmt='png')
        shutil.move(p1, os.path.join(tmpdir, 'a.jpg'))
        shutil.move(p2, os.path.join(tmpdir, 'b.png'))
        files = PhotoClassifier.scan_directory(tmpdir)
        assert len(files) == 2
        shutil.rmtree(tmpdir)

    def test_scan_directory_nonexistent(self):
        files = PhotoClassifier.scan_directory("/nonexistent")
        assert files == []

    def test_move_defective(self):
        from tests.helpers import make_corrupted_file
        path = make_corrupted_file()
        tmpdir = tempfile.mkdtemp()
        defects = {path: [DetectionResult(True, DefectType.CORRUPTED, 1.0, "损坏")]}
        moved = self.classifier.move_defective(defects, tmpdir, mode="copy")
        assert path in moved
        assert os.path.exists(moved[path])
        assert "废片" in moved[path]
        assert "损坏" in moved[path]
        shutil.rmtree(tmpdir)
        os.remove(path)
