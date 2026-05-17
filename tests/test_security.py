import pytest, os, sys, tempfile, shutil, json, uuid, time, hmac, hashlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"))

# Import functions directly from web/app.py
import importlib.util
spec = importlib.util.spec_from_file_location(
    "web_app",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "app.py")
)
web_app = importlib.util.module_from_spec(spec)
# We can't easily import the full module due to Flask dependencies,
# so we'll test pure functions via the desktop/app.py equivalents
# and test Flask separately using the test client

from desktop.app import is_path_safe, sanitize_filename, mask_path


class TestIsPathSafe:
    def test_normal_path(self):
        assert is_path_safe("C:\\Users\\test\\photos") is True

    def test_path_traversal(self):
        assert is_path_safe("C:\\Users\\test\\..\\Windows") is False

    def test_path_traversal_forward_slash(self):
        assert is_path_safe("C:/Users/test/../Windows") is False

    def test_empty_path(self):
        assert is_path_safe("") is False

    def test_none_path(self):
        assert is_path_safe(None) is False

    def test_system_dir_windows(self):
        assert is_path_safe("C:\\Windows") is False

    def test_system_dir_program_files(self):
        assert is_path_safe("C:\\Program Files") is False

    def test_unix_etc(self):
        assert is_path_safe("/etc") is False

    def test_deep_system_subdir(self):
        assert is_path_safe("C:\\Windows\\System32\\drivers") is False


class TestSanitizeFilename:
    def test_normal_filename(self):
        assert sanitize_filename("photo.jpg") == "photo.jpg"

    def test_special_chars_removed(self):
        result = sanitize_filename("photo<test>:*.jpg")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "*" not in result

    def test_backslash_replaced(self):
        result = sanitize_filename("path\\file.jpg")
        assert "\\" not in result

    def test_empty_after_sanitize(self):
        result = sanitize_filename("...")
        assert result == "unnamed"

    def test_strip_spaces(self):
        result = sanitize_filename("  photo.jpg  ")
        assert result == "photo.jpg"
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_path_separators_removed(self):
        result = sanitize_filename("../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result


class TestMaskPath:
    def test_normal_path(self):
        result = mask_path("C:\\Users\\test\\photo.jpg")
        assert "test" in result
        assert "photo.jpg" in result

    def test_empty_path(self):
        assert mask_path("") == ""

    def test_none_path(self):
        assert mask_path(None) == ""

    def test_short_path(self):
        result = mask_path("photo.jpg")
        assert "photo.jpg" in result
