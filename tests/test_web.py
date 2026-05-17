import pytest, os, sys, json, tempfile, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app, sanitize_error_message
from classifiers.base import DetectionResult, DefectType


@pytest.fixture
def app():
    application = create_app()
    application.config['TESTING'] = True
    application.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def scan_state():
    """Create a pre-populated scan_state for testing remove-defect"""
    path = os.path.join(tempfile.gettempdir(), f"test_photo_{uuid.uuid4().hex[:8]}.jpg")
    with open(path, "w") as f:
        f.write("fake")
    return {
        "is_scanning": False,
        "progress": 1,
        "total": 1,
        "current_file": "",
        "results": {
            path: [
                DetectionResult(is_defective=True, defect_type=DefectType.EMPTY,
                                confidence=0.8, description="空镜测试"),
                DetectionResult(is_defective=False, defect_type=None,
                                confidence=0.0, description="其他检测正常"),
            ],
        },
        "error": None,
        "temp_dir": None,
        "removed_paths": set(),
    }, path


@pytest.fixture
def app_with_state(scan_state):
    state, path = scan_state
    application = create_app(_test_scan_state=state)
    application.config['TESTING'] = True
    return application, path


# ============================================================
# Health
# ============================================================

class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_contains_scanning(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "scanning" in data


# ============================================================
# CSRF Token
# ============================================================

class TestCSRFToken:
    def test_get_csrf_token(self, client):
        resp = client.get("/api/csrf-token")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "csrf_token" in data
        token = data["csrf_token"]
        parts = token.split(":")
        assert len(parts) == 3

    def test_csrf_token_required_for_post(self, client):
        resp = client.post("/api/scan", json={"path": "/tmp"})
        assert resp.status_code == 403


# ============================================================
# Index
# ============================================================

class TestIndex:
    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        ct = resp.content_type
        assert "html" in ct


# ============================================================
# Scan
# ============================================================

class TestScan:
    def test_scan_no_path_no_files(self, client):
        resp = client.post("/api/scan", json={},
                          headers={"X-CSRF-Token": _get_token(client)})
        assert resp.status_code in (400, 403)

    def test_scan_nonexistent_folder(self, client):
        resp = client.post("/api/scan", json={"path": "/nonexistent_path_xyz"},
                          headers={"X-CSRF-Token": _get_token(client)})
        assert resp.status_code in (400, 403)


# ============================================================
# Status
# ============================================================

class TestStatus:
    def test_status_no_scan(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "is_scanning" in data

    def test_status_completed_filters_removed(self, app_with_state):
        state, test_path = app_with_state
        client = state.test_client()
        resp = client.get("/api/status")
        data = resp.get_json()
        assert data["completed"] is True
        assert data["defective_count"] == 1
        assert data["normal_count"] == 0

        # Remove the defective photo
        token = _get_token(client)
        resp = client.post("/api/remove-defect",
                          json={"path": test_path},
                          headers={"X-CSRF-Token": token})
        assert resp.status_code == 200

        # Now it should be in normal
        resp2 = client.get("/api/status")
        data2 = resp2.get_json()
        assert data2["defective_count"] == 0
        assert data2["normal_count"] == 1

    def test_status_completed_empty_results(self, client):
        resp = client.get("/api/status")
        data = resp.get_json()
        assert "is_scanning" in data


# ============================================================
# Remove Defect
# ============================================================

class TestRemoveDefect:
    def test_requires_csrf(self, app_with_state):
        state, _ = app_with_state
        client = state.test_client()
        resp = client.post("/api/remove-defect", json={"path": "/fake"})
        assert resp.status_code == 403

    def test_no_json_body(self, app_with_state):
        state, _ = app_with_state
        client = state.test_client()
        token = _get_token(client)
        resp = client.post("/api/remove-defect", data="",
                          headers={"X-CSRF-Token": token, "Content-Type": "application/json"})
        assert resp.status_code == 400

    def test_missing_path(self, app_with_state):
        state, _ = app_with_state
        client = state.test_client()
        token = _get_token(client)
        resp = client.post("/api/remove-defect", json={},
                          headers={"X-CSRF-Token": token})
        assert resp.status_code == 400
        assert "路径" in resp.get_json()["error"]

    def test_path_not_in_results(self, app_with_state):
        state, _ = app_with_state
        client = state.test_client()
        token = _get_token(client)
        resp = client.post("/api/remove-defect", json={"path": "/nonexistent.jpg"},
                          headers={"X-CSRF-Token": token})
        assert resp.status_code == 400
        assert "扫描结果" in resp.get_json()["error"]

    def test_successful_remove(self, app_with_state):
        state, test_path = app_with_state
        client = state.test_client()
        token = _get_token(client)
        resp = client.post("/api/remove-defect", json={"path": test_path},
                          headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["message"] == "已标记为正常"
        assert data["path"] == test_path

    def test_remove_same_path_twice_idempotent(self, app_with_state):
        state, test_path = app_with_state
        client = state.test_client()
        token = _get_token(client)
        client.post("/api/remove-defect", json={"path": test_path},
                   headers={"X-CSRF-Token": token})
        resp = client.post("/api/remove-defect", json={"path": test_path},
                          headers={"X-CSRF-Token": token})
        assert resp.status_code == 200

    def test_removed_photo_appears_as_normal(self, app_with_state):
        state, test_path = app_with_state
        client = state.test_client()
        token = _get_token(client)

        client.post("/api/remove-defect", json={"path": test_path},
                   headers={"X-CSRF-Token": token})

        status = client.get("/api/status").get_json()
        normal_paths = [p["path"] for p in status["normal_photos"]]
        assert test_path in normal_paths

    def test_defective_photos_no_longer_contains_removed(self, app_with_state):
        state, test_path = app_with_state
        client = state.test_client()
        token = _get_token(client)

        client.post("/api/remove-defect", json={"path": test_path},
                   headers={"X-CSRF-Token": token})

        status = client.get("/api/status").get_json()
        for group in status.get("defective_photos", {}).values():
            for p in group:
                assert p["path"] != test_path


# ============================================================
# Sanitize Error Message
# ============================================================

class TestSanitizeErrorMessage:
    def test_windows_path_removed(self):
        msg = sanitize_error_message(ValueError("Error at C:\\Users\\test\\file.txt"))
        assert "C:" not in msg
        assert "Users" not in msg
        assert "[路径已隐藏]" in msg or "[用户]" in msg

    def test_windows_path_trailing_backslash(self):
        msg = sanitize_error_message(ValueError("C:\\Users\\test\\"))
        assert "[路径已隐藏]" in msg or "[用户]" in msg

    def test_unix_path_removed(self):
        msg = sanitize_error_message(ValueError("Error at /home/user/file.txt"))
        assert "/home" not in msg or "[路径已隐藏]" in msg or "[用户]" in msg

    def test_no_sensitive_data_unchanged(self):
        msg = sanitize_error_message(ValueError("普通错误信息"))
        assert "普通错误信息" in msg

    def test_empty_error(self):
        msg = sanitize_error_message(ValueError())
        assert msg == ""

    def test_multiple_paths(self):
        msg = sanitize_error_message(
            ValueError("File C:\\Users\\alice\\a.jpg not found at /home/bob/b.jpg"))
        assert "[路径已隐藏]" in msg


# ============================================================
# Helper
# ============================================================

def _get_token(client):
    resp = client.get("/api/csrf-token")
    return resp.get_json()["csrf_token"]
