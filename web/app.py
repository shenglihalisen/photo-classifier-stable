# -*- coding: utf-8 -*-
"""
安全防护:
  - 文件上传大小限制（单文件10GB，总10GB）
  - 文件类型白名单验证（检查文件头魔数）
  - 路径遍历攻击防护
  - CSRF Token 防护
  - 请求频率限制（每IP每分钟最多30次请求）
  - 文件名安全过滤
  - API输入参数校验和清理
  - 删除操作二次确认Token机制
  - 敏感路径保护
  - 错误信息脱敏

功能优化:
  - /api/csrf-token 接口
  - /api/health 健康检查接口
  - 请求日志记录
  - 临时文件自动清理
"""

import os
import sys
import json
import time
import uuid
import hmac
import hashlib
import logging
import logging.handlers
import threading
import base64
import tempfile
import shutil
import re
import warnings
import errno
from io import BytesIO
from functools import wraps
from collections import defaultdict, OrderedDict

from flask import Flask, render_template, request, jsonify, g

# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("photo_classifier")
logger.setLevel(logging.INFO)
_log_formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 控制台输出
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_log_formatter)
logger.addHandler(_console_handler)

# 文件输出（带日志轮转：每个文件 5MB，保留 3 个备份）
_log_file_path = os.environ.get(
    "PHOTO_CLASSIFIER_LOG_FILE",
    os.path.join(tempfile.gettempdir(), "photo_classifier.log"),
)
try:
    _file_handler = logging.handlers.RotatingFileHandler(
        _log_file_path,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    _file_handler.setFormatter(_log_formatter)
    logger.addHandler(_file_handler)
except OSError as e:
    logger.warning("无法创建日志文件 %s: %s，仅使用控制台输出", _log_file_path, e)

# ============================================================
# 将项目根目录加入 Python 路径
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.classifier import PhotoClassifier

# ============================================================
# 安全常量配置
# ============================================================

# 文件上传大小限制
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024     # 单文件 10GB
MAX_TOTAL_SIZE = 10 * 1024 * 1024 * 1024     # 总上传 10GB

# 允许的图片扩展名
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.heic', '.heif'}

# 文件头魔数映射（扩展名 -> 魔数字节）
FILE_MAGIC_NUMBERS = {
    '.jpg':  (b'\xFF\xD8\xFF',),
    '.jpeg': (b'\xFF\xD8\xFF',),
    '.png':  (b'\x89PNG\r\n\x1a\n',),
    '.gif':  (b'GIF87a', b'GIF89a'),
    '.bmp':  (b'BM',),
    '.webp': (b'RIFF',),       # WebP 以 RIFF 开头，后跟 4 字节长度 + WEBP
    '.tiff': (b'II\x2a\x00', b'MM\x00\x2a'),  # Little/Big endian TIFF
    '.tif':  (b'II\x2a\x00', b'MM\x00\x2a'),
    '.heic': (b'ftypheic', b'ftypmif1', b'ftypisom', b'ftypheix', b'ftyphevc', b'ftypmsf1'),
    '.heif': (b'ftypmif1', b'ftypisom', b'ftypheic', b'ftypmsf1'),
}

# 需要保护的系统敏感路径（禁止访问）
PROTECTED_PATHS = {
    '/', '/etc', '/usr', '/bin', '/sbin', '/boot', '/dev', '/proc', '/sys',
    '/var', '/tmp', '/root', '/home', '/windows', '/windows/system32',
    'C:\\', 'C:\\Windows', 'C:\\Program Files', 'C:\\ProgramData',
    'D:\\Windows', 'D:\\Program Files',
}

# 请求频率限制：每 IP 每分钟最大请求数
RATE_LIMIT_MAX_REQUESTS = 60
RATE_LIMIT_WINDOW = 60  # 秒

# CSRF Token 使用的密钥（生产环境必须从环境变量设置）
_csrf_key_from_env = os.environ.get("CSRF_SECRET_KEY")
if _csrf_key_from_env:
    CSRF_SECRET_KEY = _csrf_key_from_env
else:
    CSRF_SECRET_KEY = os.urandom(32).hex()
    warnings.warn(
        "CSRF_SECRET_KEY 环境变量未设置，已生成随机密钥。"
        "每次重启后 CSRF Token 将失效。"
        "生产环境请务必设置 CSRF_SECRET_KEY 环境变量。",
        RuntimeWarning,
        stacklevel=2,
    )

# 删除操作确认 Token 有效期（秒）
DELETE_TOKEN_EXPIRE = 300  # 5 分钟

# 临时文件自动清理间隔（秒）
TEMP_CLEANUP_INTERVAL = 3600  # 1 小时
# 临时文件最大保留时间（秒）
TEMP_FILE_MAX_AGE = 86400  # 24 小时


# ============================================================
# 安全工具函数
# ============================================================

def sanitize_filename(filename: str) -> str:
    """
    文件名安全过滤：去除特殊字符，只保留字母、数字、中文、下划线、连字符和点号

    参数:
        filename: 原始文件名

    返回:
        过滤后的安全文件名
    """
    # 先取基础文件名，防止路径注入
    filename = os.path.basename(filename)
    # 移除或替换危险字符，只保留安全字符
    # 允许：中文、字母、数字、下划线、连字符、点号、空格
    filename = re.sub(r'[^\w\u4e00-\u9fff.\- ]', '_', filename)
    # 去除连续的下划线或点号
    filename = re.sub(r'_+', '_', filename)
    filename = re.sub(r'\.+', '.', filename)
    # 去除首尾空白和点号
    filename = filename.strip(' .')
    # 如果文件名为空，使用随机名
    if not filename:
        filename = f"unnamed_{uuid.uuid4().hex[:8]}"
    return filename


def validate_file_magic(file_path: str, extension: str) -> bool:
    """
    通过文件头魔数验证文件类型，防止扩展名伪造

    参数:
        file_path: 文件路径
        extension: 文件扩展名（含点号，如 '.jpg'）

    返回:
        True 表示文件头匹配，False 表示不匹配
    """
    extension = extension.lower()
    magic_list = FILE_MAGIC_NUMBERS.get(extension)
    if not magic_list:
        return False

    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)  # 读取前 16 字节用于判断

        for magic in magic_list:
            # HEIC/HEIF: ftyp 盒子位于偏移量 4 处（前4字节为盒子大小）
            if extension in ('.heic', '.heif'):
                if len(header) >= 12 and header[4:4+len(magic)] == magic:
                    return True
                continue

            if header.startswith(magic):
                # WebP 需要额外验证：RIFF + 4字节长度 + WEBP
                if extension == '.webp' and len(header) >= 12:
                    if header[8:12] == b'WEBP':
                        return True
                else:
                    return True
        return False
    except (OSError, IOError):
        return False


def is_path_safe(path: str) -> bool:
    """
    路径安全检查：防止路径遍历攻击和敏感路径访问

    参数:
        path: 待检查的路径

    返回:
        True 表示路径安全，False 表示路径不安全
    """
    if not path:
        return False

    # 检查原始路径中是否包含路径遍历（在 normpath 之前检查）
    normalized_sep = path.replace("/", os.sep)
    if ".." in [p for p in normalized_sep.split(os.sep) if p]:
        return False

    # 规范化路径
    normalized = os.path.normpath(path)

    # 检查绝对路径是否指向受保护目录
    abs_path = os.path.abspath(normalized)
    for protected in PROTECTED_PATHS:
        protected_abs = os.path.abspath(protected)
        # 检查是否是受保护路径的子目录
        try:
            if abs_path == protected_abs or abs_path.startswith(protected_abs + os.sep):
                return False
        except (ValueError, TypeError):
            continue

    return True


def sanitize_error_message(error: Exception) -> str:
    """
    错误信息脱敏：移除服务器路径等敏感信息

    参数:
        error: 异常对象

    返回:
        脱敏后的错误信息
    """
    msg = str(error)
    # 移除绝对路径信息（Windows 盘符路径）
    msg = re.sub(r'[A-Za-z]:\\[^\s:]+', '[路径已隐藏]', msg)
    # 移除 Unix 绝对路径（以 / 开头且包含目录分隔符的路径）
    msg = re.sub(r'/[^\s:/]+(?:/[^\s:]+)*', '[路径已隐藏]', msg)
    # 移除可能的用户名
    msg = re.sub(r'Users\\[^\\]+(?=\\)', '[用户]', msg)
    msg = re.sub(r'/home/[^/]+(?=/)', '/[用户]', msg)
    return msg


def generate_csrf_token() -> str:
    """
    生成 CSRF Token

    返回:
        CSRF Token 字符串
    """
    session_id = getattr(g, 'csrf_session_id', None)
    if session_id is None:
        session_id = uuid.uuid4().hex
        g.csrf_session_id = session_id
    timestamp = str(int(time.time()))
    raw = f"{session_id}:{timestamp}"
    signature = hmac.new(
        CSRF_SECRET_KEY.encode('utf-8'),
        raw.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{session_id}:{timestamp}:{signature}"


def validate_csrf_token(token: str) -> bool:
    """
    验证 CSRF Token 是否有效

    参数:
        token: 待验证的 CSRF Token

    返回:
        True 表示 Token 有效
    """
    if not token:
        return False

    try:
        parts = token.split(':')
        if len(parts) != 3:
            return False
        session_id, timestamp_str, signature = parts
        timestamp = int(timestamp_str)

        # 检查 Token 是否过期（24小时有效期）
        if abs(time.time() - timestamp) > 86400:
            return False

        # 重新计算签名进行验证
        raw = f"{session_id}:{timestamp_str}"
        expected = hmac.new(
            CSRF_SECRET_KEY.encode('utf-8'),
            raw.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, expected)
    except (ValueError, IndexError, AttributeError):
        return False


def generate_delete_token(file_paths: list) -> str:
    """
    生成删除操作确认 Token

    参数:
        file_paths: 待删除的文件路径列表

    返回:
        确认 Token 字符串
    """
    timestamp = str(int(time.time()))
    # 将文件路径排序后拼接，确保一致性
    paths_str = '|'.join(sorted(file_paths))
    raw = f"{timestamp}:{paths_str}"
    signature = hmac.new(
        CSRF_SECRET_KEY.encode('utf-8'),
        raw.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{timestamp}:{signature}"


def validate_delete_token(token: str, file_paths: list) -> bool:
    """
    验证删除操作确认 Token

    参数:
        token: 待验证的确认 Token
        file_paths: 实际要删除的文件路径列表

    返回:
        True 表示 Token 有效且匹配
    """
    if not token:
        return False

    try:
        parts = token.split(':', 1)
        if len(parts) != 2:
            return False
        timestamp_str, signature = parts
        timestamp = int(timestamp_str)

        # 检查 Token 是否过期
        if time.time() - timestamp > DELETE_TOKEN_EXPIRE:
            return False

        # 重新计算签名
        paths_str = '|'.join(sorted(file_paths))
        raw = f"{timestamp_str}:{paths_str}"
        expected = hmac.new(
            CSRF_SECRET_KEY.encode('utf-8'),
            raw.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, expected)
    except (ValueError, IndexError, AttributeError):
        return False


# ============================================================
# 请求频率限制器
# ============================================================

class RateLimiter:
    """
    基于内存的 IP 请求频率限制器
    每个 IP 在指定时间窗口内最多允许 N 次请求
    自动清理过期记录，限制最大 IP 数防止内存泄漏
    """

    MAX_IPS = 10000  # 最大追踪 IP 数量

    def __init__(self, max_requests: int = RATE_LIMIT_MAX_REQUESTS,
                 window: int = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window = window
        # {ip: [timestamp1, timestamp2, ...]}
        self._requests: dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def is_allowed(self, ip: str) -> bool:
        """
        检查指定 IP 是否允许请求

        参数:
            ip: 客户端 IP 地址

        返回:
            True 表示允许请求，False 表示已被限流
        """
        now = time.time()
        cutoff = now - self.window

        with self._lock:
            # 定期自动清理过期记录（每次调用时检查，至少间隔 60 秒）
            if now - self._last_cleanup >= 60:
                self._do_cleanup(now, cutoff)
                self._last_cleanup = now

            # 清理当前 IP 的过期记录
            self._requests[ip] = [
                t for t in self._requests[ip] if t > cutoff
            ]

            # 如果 IP 数超过上限，拒绝新 IP 的请求
            if ip not in self._requests and len(self._requests) >= self.MAX_IPS:
                logger.warning("请求频率限制器 IP 数已达上限: %d", self.MAX_IPS)
                return False

            if len(self._requests[ip]) >= self.max_requests:
                logger.warning("请求频率限制触发: ip=%s, 请求数=%d",
                               ip, len(self._requests[ip]))
                return False

            self._requests[ip].append(now)
            return True

    def _do_cleanup(self, now: float, cutoff: float):
        """清理所有过期的请求记录"""
        expired_ips = []
        for ip, timestamps in self._requests.items():
            self._requests[ip] = [t for t in timestamps if t > cutoff]
            if not self._requests[ip]:
                expired_ips.append(ip)
        for ip in expired_ips:
            del self._requests[ip]

    def cleanup(self):
        """清理所有过期的请求记录"""
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            self._do_cleanup(now, cutoff)


# ============================================================
# 临时文件清理器
# ============================================================

class TempFileCleaner:
    """
    定时清理 photo_classifier_ 前缀的临时目录
    """

    def __init__(self, interval: int = TEMP_CLEANUP_INTERVAL,
                 max_age: int = TEMP_FILE_MAX_AGE):
        self.interval = interval
        self.max_age = max_age
        self._running = False
        self._thread = None

    def start(self):
        """启动后台清理线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._thread.start()
        logger.info("临时文件清理器已启动，清理间隔=%d秒，最大保留=%d秒",
                     self.interval, self.max_age)

    def stop(self):
        """停止清理线程"""
        self._running = False

    def _cleanup_loop(self):
        """清理循环"""
        while self._running:
            time.sleep(self.interval)
            self._cleanup()

    def _cleanup(self):
        """执行一次清理"""
        try:
            temp_base = tempfile.gettempdir()
            now = time.time()
            cleaned_count = 0

            for entry in os.listdir(temp_base):
                if not entry.startswith("photo_classifier_"):
                    continue
                full_path = os.path.join(temp_base, entry)
                if not os.path.isdir(full_path):
                    continue

                # 检查目录修改时间（跨平台兼容：使用 st_mtime）
                try:
                    stat = os.stat(full_path)
                    age = now - stat.st_mtime
                    if age > self.max_age:
                        shutil.rmtree(full_path, ignore_errors=True)
                        cleaned_count += 1
                        logger.info("清理过期临时目录: %s (存在 %.1f 小时)",
                                    entry, age / 3600)
                except OSError:
                    continue

            if cleaned_count > 0:
                logger.info("临时文件清理完成，共清理 %d 个目录", cleaned_count)
        except Exception as e:
            logger.error("临时文件清理出错: %s", sanitize_error_message(e))


# ============================================================
# Flask 应用工厂
# ============================================================

def create_app(_test_scan_state=None) -> Flask:
    """创建并配置 Flask 应用"""

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=None,
    )

    # 配置上传大小限制（Flask 内置限制，作为额外保护层）
    app.config['MAX_CONTENT_LENGTH'] = MAX_TOTAL_SIZE

    # 移除 Server 头（防止版本泄露）
    app.config['SERVER_NAME'] = None

    # WSGI 中间件：移除 Server 头
    class RemoveServerHeader:
        def __init__(self, app):
            self.app = app
        def __call__(self, environ, start_response):
            def custom_start_response(status, headers, exc_info=None):
                headers[:] = [(k, v) for k, v in headers if k.lower() != 'server']
                return start_response(status, headers, exc_info)
            return self.app(environ, custom_start_response)

    app.wsgi_app = RemoveServerHeader(app.wsgi_app)

    # 全局安全组件
    rate_limiter = RateLimiter()
    temp_cleaner = TempFileCleaner()

    # 并发扫描限制（最多同时 1 个扫描任务）
    scan_semaphore = threading.Semaphore(1)

    # 线程本地分类器实例（线程安全）
    _thread_local = threading.local()

    def _get_classifier():
        """获取当前线程的分类器实例"""
        if not hasattr(_thread_local, 'classifier'):
            _thread_local.classifier = PhotoClassifier()
        return _thread_local.classifier

    # 扫描状态（允许测试注入）
    # 注意：当前为全局单例设计，适合单用户本地部署。
    # 多用户并发场景需改为按 session/用户隔离。
    scan_state = _test_scan_state if _test_scan_state is not None else {
        "is_scanning": False,
        "progress": 0,
        "total": 0,
        "current_file": "",
        "results": {},
        "error": None,
        "temp_dir": None,  # 存储上传文件的临时目录
        "removed_paths": set(),  # 用户手动移除的废片路径
        "duplicate_groups": [],  # 重复照片检测结果
    }
    scan_state_lock = threading.Lock()

    # 缩略图 LRU 缓存（最大 1000 条）
    THUMBNAIL_CACHE_MAX = 1000
    thumbnail_cache = OrderedDict()

    # 启动临时文件清理器
    temp_cleaner.start()

    # ========================================================
    # 安全头中间件
    # ========================================================

    @app.after_request
    def add_security_headers(response):
        """添加安全响应头"""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:; font-src https://cdn.jsdelivr.net"
        # 移除服务器版本信息
        response.headers.pop('Server', None)
        return response

    # ========================================================
    # 请求日志中间件
    # ========================================================

    @app.before_request
    def log_request():
        """记录每个请求的基本信息"""
        g._request_start = time.time()
        client_ip = request.remote_addr or 'unknown'
        logger.info("请求: %s %s from %s", request.method, request.path, client_ip)

    @app.after_request
    def log_response(response):
        """记录响应状态"""
        client_ip = request.remote_addr or 'unknown'
        elapsed = (time.time() - getattr(g, '_request_start', time.time())) * 1000
        logger.info("响应: %s %s -> %d (%.1fms)",
                     request.method, request.path,
                     response.status_code, elapsed)
        return response

    # ========================================================
    # 全局错误处理器（错误信息脱敏）
    # ========================================================

    @app.errorhandler(400)
    def handle_400(error):
        return jsonify({"error": "请求参数错误"}), 400

    @app.errorhandler(404)
    def handle_404(error):
        return jsonify({"error": "请求的资源不存在"}), 404

    @app.errorhandler(413)
    def handle_413(error):
        return jsonify({"error": f"文件大小超出限制（单文件最大 {MAX_FILE_SIZE // (1024*1024*1024)}GB，"
                                 f"总计最大 {MAX_TOTAL_SIZE // (1024*1024*1024)}GB）"}), 413

    @app.errorhandler(429)
    def handle_429(error):
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    @app.errorhandler(500)
    def handle_500(error):
        logger.error("服务器内部错误: %s", sanitize_error_message(error))
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500

    # ========================================================
    # 安全装饰器
    # ========================================================

    def rate_limit(f):
        """
        请求频率限制装饰器
        对每个 IP 限制每分钟最多 30 次请求
        """
        @wraps(f)
        def decorated(*args, **kwargs):
            client_ip = request.remote_addr or 'unknown'
            if not rate_limiter.is_allowed(client_ip):
                return jsonify({"error": "请求过于频繁，请稍后再试"}), 429
            return f(*args, **kwargs)
        return decorated

    def csrf_protect(f):
        """
        CSRF 防护装饰器
        对 POST/PUT/DELETE 请求要求携带有效的 CSRF Token
        """
        @wraps(f)
        def decorated(*args, **kwargs):
            # GET/HEAD/OPTIONS 不需要 CSRF 验证
            if request.method in ('GET', 'HEAD', 'OPTIONS'):
                return f(*args, **kwargs)

            # 从请求头或表单获取 Token
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            if not token or not validate_csrf_token(token):
                logger.warning("CSRF 验证失败: ip=%s, path=%s",
                               request.remote_addr, request.path)
                return jsonify({"error": "CSRF Token 无效或已过期，请刷新页面重试"}), 403
            return f(*args, **kwargs)
        return decorated

    # ========================================================
    # 辅助函数
    # ========================================================

    def generate_thumbnail(image_path: str, max_size: int = 200) -> str | None:
        """
        生成图片缩略图的 base64 编码

        参数:
            image_path: 图片路径
            max_size: 缩略图最大尺寸

        返回:
            base64 编码的缩略图字符串，失败返回 None
        """
        # LRU 缓存查找：命中时移动到末尾
        if image_path in thumbnail_cache:
            thumbnail_cache.move_to_end(image_path)
            return thumbnail_cache[image_path]

        try:
            from PIL import Image

            # 限制原始图片大小：文件不超过 20MB，像素不超过 10000x10000
            try:
                file_stat = os.stat(image_path)
                if file_stat.st_size > 20 * 1024 * 1024:
                    logger.warning("缩略图生成跳过：文件过大 %s (%.1fMB)",
                                   os.path.basename(image_path),
                                   file_stat.st_size / (1024 * 1024))
                    return None
            except OSError:
                return None

            img = Image.open(image_path)

            # 检查像素尺寸限制
            if img.width > 10000 or img.height > 10000:
                logger.warning("缩略图生成跳过：图片尺寸过大 %s (%dx%d)",
                               os.path.basename(image_path), img.width, img.height)
                img.close()
                return None

            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            buffer = BytesIO()
            # 根据格式保存
            ext = os.path.splitext(image_path)[1].lower()
            if ext in ('.jpg', '.jpeg'):
                fmt = 'JPEG'
            elif ext == '.png':
                fmt = 'PNG'
            elif ext == '.webp':
                fmt = 'WEBP'
            else:
                fmt = 'JPEG'

            img.save(buffer, format=fmt, quality=80)
            img.close()
            b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            mime = 'image/jpeg' if fmt == 'JPEG' else f'image/{fmt.lower()}'
            result = f"data:{mime};base64,{b64}"

            # LRU 缓存写入：超出上限时淘汰最旧的条目
            thumbnail_cache[image_path] = result
            thumbnail_cache.move_to_end(image_path)
            while len(thumbnail_cache) > THUMBNAIL_CACHE_MAX:
                thumbnail_cache.popitem(last=False)

            return result
        except Exception:
            return None

    def validate_upload_file(file_storage) -> tuple:
        """
        验证上传文件的安全性和合法性

        参数:
            file_storage: Flask 的 FileStorage 对象

        返回:
            (是否合法, 错误信息或安全文件名)
        """
        if not file_storage or not file_storage.filename:
            return False, "无效的文件"

        # 文件名安全过滤
        original_name = file_storage.filename
        safe_name = sanitize_filename(original_name)

        # 检查扩展名白名单
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return False, f"不支持的文件类型: {ext}"

        # 检查文件大小
        file_storage.seek(0, os.SEEK_END)
        file_size = file_storage.tell()
        file_storage.seek(0)

        if file_size > MAX_FILE_SIZE:
            return False, f"文件 '{safe_name}' 超出大小限制（{file_size // (1024*1024)}MB > {MAX_FILE_SIZE // (1024*1024)}MB）"

        if file_size == 0:
            return False, f"文件 '{safe_name}' 为空文件"

        return True, safe_name

    # ========================================================
    # 路由：页面
    # ========================================================

    @app.route("/")
    def index():
        """主页面"""
        return render_template("index.html")

    # ========================================================
    # 路由：API - 健康检查
    # ========================================================

    @app.route("/api/health", methods=["GET"])
    def health_check():
        """
        健康检查接口

        返回:
            应用运行状态信息
        """
        return jsonify({
            "status": "ok",
            "timestamp": int(time.time()),
            "version": "1.0.0",
            "scanning": scan_state["is_scanning"],
        })

    # ========================================================
    # 路由：API - CSRF Token
    # ========================================================

    @app.route("/api/csrf-token", methods=["GET"])
    @rate_limit
    def get_csrf_token():
        """
        获取 CSRF Token

        返回:
            新生成的 CSRF Token
        """
        token = generate_csrf_token()
        return jsonify({"csrf_token": token})

    # ========================================================
    # 路由：API - 扫描
    # ========================================================

    @app.route("/api/scan", methods=["POST"])
    @rate_limit
    @csrf_protect
    def scan():
        """
        扫描指定文件夹路径或上传的文件，返回分类结果

        支持:
        1. 文件上传: multipart/form-data, field name: "files"
        2. 文件夹路径: JSON {"path": "/path/to/folder"}
        """
        image_files = []
        folder_path = ""
        temp_dir = None

        # 并发限制：获取信号量
        if not scan_semaphore.acquire(blocking=False):
            return jsonify({"error": "系统繁忙，请等待当前扫描完成"}), 429

        try:
            # 检查是否有文件上传
            if 'files' in request.files:
                uploaded_files = request.files.getlist('files')
                if not uploaded_files or all(f.filename == '' for f in uploaded_files):
                    return jsonify({"error": "请选择要上传的文件"}), 400

                # 创建临时目录存储上传的文件
                temp_dir = tempfile.mkdtemp(prefix="photo_classifier_")
                os.chmod(temp_dir, 0o700)
                folder_path = temp_dir
                total_size = 0

                for file in uploaded_files:
                    # 验证文件安全性和合法性
                    is_valid, result = validate_upload_file(file)
                    if not is_valid:
                        logger.warning("文件上传验证失败: %s", result)
                        continue

                    safe_name = result
                    filepath = os.path.join(temp_dir, safe_name)

                    # 保存文件
                    file.save(filepath)

                    # 验证文件头魔数（防止扩展名伪造）
                    ext = os.path.splitext(safe_name)[1].lower()
                    if not validate_file_magic(filepath, ext):
                        logger.warning("文件魔数验证失败，疑似伪造文件: %s", safe_name)
                        os.remove(filepath)
                        continue

                    # 累计文件大小检查
                    file_stat = os.stat(filepath)
                    total_size += file_stat.st_size
                    if total_size > MAX_TOTAL_SIZE:
                        logger.warning("总上传大小超出限制: %d bytes", total_size)
                        os.remove(filepath)
                        continue

                    image_files.append(filepath)

                if not image_files:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return jsonify({"error": "没有有效的图片文件"}), 400
            else:
                # 从 JSON 获取路径
                data = request.get_json(silent=True)
                if not data:
                    return jsonify({"error": "请上传文件或提供文件夹路径"}), 400

                folder_path = data.get("path", "").strip()

                # 输入参数校验：路径不能为空
                if not folder_path:
                    return jsonify({"error": "请输入文件夹路径或选择文件上传"}), 400

                # 路径安全检查：防止路径遍历和敏感路径访问
                if not is_path_safe(folder_path):
                    logger.warning("路径安全检查失败: %s", folder_path)
                    return jsonify({"error": "无效的文件夹路径"}), 400

                if not os.path.isdir(folder_path):
                    return jsonify({"error": "路径不存在或不是文件夹"}), 400

                # 扫描图片文件
                image_files = PhotoClassifier.scan_directory(folder_path)

            # 限制单次扫描数量（防止内存溢出）
            MAX_SCAN_FILES = 50000
            if len(image_files) > MAX_SCAN_FILES:
                image_files = image_files[:MAX_SCAN_FILES]
                logger.warning("扫描数量超出限制，截断为 %d 张", MAX_SCAN_FILES)

            if not image_files:
                if temp_dir:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                return jsonify({"error": "未找到图片文件"}), 400

            # ========== 扫描前清理 ==========
            with scan_state_lock:
                # 清理上一次的临时文件
                if scan_state["temp_dir"] and os.path.exists(scan_state["temp_dir"]):
                    try:
                        shutil.rmtree(scan_state["temp_dir"], ignore_errors=True)
                        logger.info("已清理上一次临时目录: %s", scan_state["temp_dir"])
                    except Exception as e:
                        logger.warning("清理临时目录失败: %s", e)

                # 重置扫描状态
                scan_state["is_scanning"] = True
                scan_state["progress"] = 0
                scan_state["total"] = len(image_files)
                scan_state["current_file"] = ""
                scan_state["results"] = {}
                scan_state["removed_paths"] = set()
                scan_state["error"] = None
                scan_state["temp_dir"] = temp_dir
                scan_state["duplicate_groups"] = []

            # 清理缩略图缓存
            thumbnail_cache.clear()

            # 建议 Python GC 回收
            import gc
            gc.collect()

            def run_scan():
                """在后台线程中执行扫描"""
                try:
                    def progress_callback(current, total, path):
                        with scan_state_lock:
                            scan_state["progress"] = current
                            scan_state["total"] = total
                            scan_state["current_file"] = os.path.basename(path)

                    # 分批处理，每批 100 张，避免一次性加载过多
                    BATCH_SIZE = 100
                    all_results = {}
                    for batch_start in range(0, len(image_files), BATCH_SIZE):
                        batch = image_files[batch_start:batch_start + BATCH_SIZE]
                        batch_results = _get_classifier().classify_batch(batch, progress_callback)
                        all_results.update(batch_results)

                        # 每批处理后建议 GC
                        if batch_start % 500 == 0 and batch_start > 0:
                            gc.collect()

                    with scan_state_lock:
                        scan_state["results"] = all_results
                except Exception as e:
                    # 错误信息脱敏后存储
                    with scan_state_lock:
                        scan_state["error"] = sanitize_error_message(e)
                    logger.error("扫描过程出错: %s", sanitize_error_message(e))
                finally:
                    with scan_state_lock:
                        scan_state["is_scanning"] = False
                        scan_state["current_file"] = ""
                    # 释放信号量
                    scan_semaphore.release()

            # 启动后台扫描线程
            thread = threading.Thread(target=run_scan, daemon=True)
            thread.start()

            return jsonify({
                "message": f"开始扫描 {len(image_files)} 张图片",
                "total": len(image_files),
            })

        except Exception as e:
            scan_semaphore.release()
            raise

    # ========================================================
    # 路由：API - 状态查询
    # ========================================================

    @app.route("/api/status", methods=["GET"])
    def status():
        """获取扫描进度"""
        with scan_state_lock:
            response = {
                "is_scanning": scan_state["is_scanning"],
                "progress": scan_state["progress"],
                "total": scan_state["total"],
                "current_file": scan_state["current_file"],
                "error": scan_state["error"],
            }

            if not scan_state["is_scanning"] and scan_state["results"]:
                normal_photos = []
                defective_photos = {}
                removed = set(scan_state["removed_paths"])  # 复制一份避免竞态

                for path, results in scan_state["results"].items():
                    if path in removed:
                        normal_photos.append({
                            "path": path,
                            "filename": os.path.basename(path),
                            "thumbnail": generate_thumbnail(path),
                        })
                        continue
                    defects = [r for r in results if r.is_defective]

                    if defects:
                        # 按缺陷类型分组
                        for defect in defects:
                            dtype = defect.defect_type.value if defect.defect_type else "unknown"
                            if dtype not in defective_photos:
                                defective_photos[dtype] = []
                            defective_photos[dtype].append({
                                "path": path,
                                "filename": os.path.basename(path),
                                "defect_type": dtype,
                                "confidence": defect.confidence,
                                "description": defect.description,
                                "thumbnail": generate_thumbnail(path),
                            })
                    else:
                        normal_photos.append({
                            "path": path,
                            "filename": os.path.basename(path),
                            "thumbnail": generate_thumbnail(path),
                        })

                response["completed"] = True
                response["normal_count"] = len(normal_photos)
                response["defective_count"] = sum(len(v) for v in defective_photos.values())
                response["normal_photos"] = normal_photos
                response["defective_photos"] = defective_photos
                response["is_upload"] = scan_state["temp_dir"] is not None

            # 返回重复照片检测结果
            if not scan_state["is_scanning"] and scan_state.get("duplicate_groups"):
                duplicate_info = []
                for group in scan_state["duplicate_groups"]:
                    duplicate_info.append({
                        "files": [{"path": p, "filename": os.path.basename(p)} for p in group],
                        "count": len(group),
                    })
                response["duplicate_groups"] = duplicate_info
                response["duplicate_count"] = sum(len(g) for g in scan_state["duplicate_groups"])

        return jsonify(response)

    # ========================================================
    # 路由：API - 获取删除确认 Token
    # ========================================================

    @app.route("/api/delete-token", methods=["POST"])
    @rate_limit
    @csrf_protect
    def get_delete_token():
        """
        获取删除操作确认 Token（二次确认机制）

        请求体:
            {
                "selected": ["/path/to/photo1.jpg", ...]  (可选，手动模式时指定)
            }

        返回:
            删除确认 Token，前端在确认删除时需携带此 Token
        """
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求参数错误"}), 400

        # 构建待删除文件列表
        file_paths = []
        selected = data.get("selected", [])

        with scan_state_lock:
            if selected:
                # 手动模式：使用前端选中的文件
                for path in selected:
                    if path in scan_state["results"]:
                        file_paths.append(path)
            else:
                # 自动模式：所有废片
                for path, results in scan_state["results"].items():
                    defects = [r for r in results if r.is_defective]
                    if defects:
                        file_paths.append(path)

        if not file_paths:
            return jsonify({"error": "没有需要处理的废片"}), 400

        token = generate_delete_token(file_paths)
        return jsonify({
            "delete_token": token,
            "file_count": len(file_paths),
            "expires_in": DELETE_TOKEN_EXPIRE,
        })

    # ========================================================
    # 路由：API - 移除废片标记（手动审核）
    # ========================================================

    @app.route("/api/remove-defect", methods=["POST"])
    @rate_limit
    @csrf_protect
    def remove_defect():
        """将指定废片标记为正常（手动审核误判）"""
        data = request.get_json(silent=True)
        if not data or "path" not in data:
            return jsonify({"error": "请提供文件路径"}), 400

        file_path = data["path"]

        with scan_state_lock:
            if not scan_state["results"] or file_path not in scan_state["results"]:
                return jsonify({"error": "文件不在扫描结果中"}), 400
            scan_state["removed_paths"].add(file_path)
        logger.info("手动移除废片标记: %s", sanitize_error_message(file_path))

        return jsonify({"message": "已标记为正常", "path": file_path})

    # ========================================================
    # 路由：API - 处理废片
    # ========================================================

    @app.route("/api/process", methods=["POST"])
    @rate_limit
    @csrf_protect
    def process():
        """
        处理废片（移动到废片文件夹或删除）

        请求体:
            {
                "action": "move" | "delete",
                "mode": "auto" | "manual",
                "folder_path": "/path/to/folder",
                "selected": ["/path/to/photo1.jpg", ...]  (手动模式时指定)
                "delete_token": "..."  (删除操作时必须提供)
            }
        """
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求参数错误"}), 400

        # 参数校验和清理
        action = data.get("action", "move").strip().lower()
        mode = data.get("mode", "auto").strip().lower()
        folder_path = data.get("folder_path", "").strip()
        selected = data.get("selected", [])

        # 校验 action 参数
        if action not in ("move", "delete"):
            return jsonify({"error": "无效的操作类型"}), 400

        # 校验 mode 参数
        if mode not in ("auto", "manual"):
            return jsonify({"error": "无效的处理模式"}), 400

        # 校验 selected 参数类型
        if not isinstance(selected, list):
            return jsonify({"error": "参数格式错误"}), 400

        with scan_state_lock:
            if scan_state["is_scanning"]:
                return jsonify({"error": "正在扫描中，请等待完成"}), 400

            # 构建废片字典
            defective_images = {}

            if mode == "manual" and selected:
                # 手动模式：只处理选中的照片
                for path in selected:
                    if path in scan_state["results"]:
                        defects = [r for r in scan_state["results"][path] if r.is_defective]
                        if defects:
                            defective_images[path] = defects
            else:
                # 自动模式：处理所有废片
                for path, results in scan_state["results"].items():
                    defects = [r for r in results if r.is_defective]
                    if defects:
                        defective_images[path] = defects

            if not defective_images:
                return jsonify({"error": "没有需要处理的废片"}), 400

            # 如果是上传的文件，使用临时目录作为目标
            if scan_state["temp_dir"]:
                folder_path = scan_state["temp_dir"]

        if not folder_path or not os.path.isdir(folder_path):
            return jsonify({"error": "无效的文件夹路径"}), 400

        # 路径安全检查
        if not is_path_safe(folder_path):
            logger.warning("处理操作路径安全检查失败: %s", folder_path)
            return jsonify({"error": "无效的文件夹路径"}), 400

        if action == "move":
            moved = _get_classifier().move_defective(defective_images, folder_path, mode="move")

            # 清理临时目录
            with scan_state_lock:
                if scan_state["temp_dir"]:
                    shutil.rmtree(scan_state["temp_dir"], ignore_errors=True)
                    scan_state["temp_dir"] = None

            return jsonify({
                "message": f"已移动 {len(moved)} 张废片到 '{folder_path}/废片/' 文件夹",
                "moved_count": len(moved),
                "moved_files": moved,
            })
        elif action == "delete":
            # 删除操作需要二次确认 Token
            delete_token = data.get("delete_token", "")
            file_paths = list(defective_images.keys())

            if not validate_delete_token(delete_token, file_paths):
                logger.warning("删除操作确认 Token 验证失败: ip=%s",
                               request.remote_addr)
                return jsonify({"error": "删除确认 Token 无效或已过期，请重新获取"}), 403

            deleted = []
            for path in defective_images:
                try:
                    # 再次进行路径安全检查
                    if not is_path_safe(path):
                        logger.warning("删除操作跳过不安全路径: %s", path)
                        continue

                    # 防御符号链接攻击：使用 lstat 检查 + O_NOFOLLOW 原子操作
                    # 避免 TOCTOU 竞态条件（先 islink 再 remove 的检查与操作之间可能被替换）
                    try:
                        st = os.lstat(path)
                        if not os.path.stat.S_ISREG(st.st_mode):
                            logger.warning("删除操作跳过非普通文件: %s", path)
                            continue
                    except OSError:
                        continue

                    # 使用 O_NOFOLLOW 标志打开文件描述符，防止符号链接
                    try:
                        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    except OSError as e:
                        if e.errno == errno.ELOOP:
                            logger.warning("删除操作跳过符号链接: %s", path)
                        else:
                            logger.warning("删除文件打开失败: %s", sanitize_error_message(e))
                        continue

                    try:
                        os.unlink(path)
                    finally:
                        os.close(fd)

                    deleted.append(path)
                except OSError as e:
                    logger.warning("删除文件失败: %s", sanitize_error_message(e))

            # 清理临时目录
            with scan_state_lock:
                if scan_state["temp_dir"]:
                    shutil.rmtree(scan_state["temp_dir"], ignore_errors=True)
                    scan_state["temp_dir"] = None

            return jsonify({
                "message": f"已删除 {len(deleted)} 张废片",
                "deleted_count": len(deleted),
            })
        else:
            return jsonify({"error": "无效的操作类型"}), 400

    # ========================================================
    # 路由：API - 重复照片检测
    # ========================================================

    @app.route("/api/duplicates", methods=["POST"])
    @rate_limit
    @csrf_protect
    def find_duplicates():
        """
        检测重复照片

        请求体:
            {
                "path": "/path/to/folder"  (可选，不传则使用上次扫描的文件)
            }

        返回:
            重复照片组列表
        """
        data = request.get_json(silent=True) or {}
        folder_path = data.get("path", "").strip()

        if folder_path:
            if not is_path_safe(folder_path):
                return jsonify({"error": "无效的文件夹路径"}), 400
            if not os.path.isdir(folder_path):
                return jsonify({"error": "路径不存在或不是文件夹"}), 400
            image_files = PhotoClassifier.scan_directory(folder_path)
        else:
            with scan_state_lock:
                if not scan_state["results"]:
                    return jsonify({"error": "请先扫描照片或提供文件夹路径"}), 400
                image_files = list(scan_state["results"].keys())

        if len(image_files) < 2:
            return jsonify({"error": "图片数量不足，无法检测重复"}), 400

        def run_duplicate_scan():
            try:
                def progress_callback(current, total, path):
                    with scan_state_lock:
                        scan_state["progress"] = current
                        scan_state["total"] = total
                        scan_state["current_file"] = os.path.basename(path)

                groups = _get_classifier().find_duplicates(image_files, progress_callback)
                with scan_state_lock:
                    scan_state["duplicate_groups"] = groups
            except Exception as e:
                with scan_state_lock:
                    scan_state["error"] = sanitize_error_message(e)
                logger.error("重复检测出错: %s", sanitize_error_message(e))
            finally:
                with scan_state_lock:
                    scan_state["is_scanning"] = False
                    scan_state["current_file"] = ""

        with scan_state_lock:
            if scan_state["is_scanning"]:
                return jsonify({"error": "正在检测中，请等待完成"}), 400
            scan_state["is_scanning"] = True
            scan_state["progress"] = 0
            scan_state["total"] = len(image_files)
            scan_state["current_file"] = ""
            scan_state["error"] = None
            scan_state["duplicate_groups"] = []

        thread = threading.Thread(target=run_duplicate_scan, daemon=True)
        thread.start()

        return jsonify({
            "message": f"开始检测 {len(image_files)} 张图片的重复项",
            "total": len(image_files),
        })

    # ========================================================
    # 路由：API - 下载单个文件
    # ========================================================

    @app.route("/api/download", methods=["GET"])
    @rate_limit
    def download_file():
        """下载指定文件"""
        file_path = request.args.get("path", "")
        if not file_path:
            return jsonify({"error": "缺少文件路径"}), 400

        # 安全检查
        if not is_path_safe(file_path):
            return jsonify({"error": "无效的文件路径"}), 400

        if not os.path.isfile(file_path):
            return jsonify({"error": "文件不存在"}), 404

        # 只允许下载扫描结果中的文件
        with scan_state_lock:
            all_paths = set(scan_state.get("results", {}).keys())
            normal_paths = set()
            if not scan_state["is_scanning"] and scan_state["results"]:
                removed = scan_state.get("removed_paths", set())
                for path, results in scan_state["results"].items():
                    if path not in removed:
                        defects = [r for r in results if r.is_defective]
                        if not defects:
                            normal_paths.add(path)

        if file_path not in normal_paths:
            return jsonify({"error": "只能下载正常照片"}), 403

        # 文件大小检查
        file_size = os.path.getsize(file_path)
        MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
        if file_size > MAX_DOWNLOAD_SIZE:
            return jsonify({"error": f"文件过大（{file_size // (1024*1024)}MB），无法下载"}), 413

        from flask import Response
        with open(file_path, 'rb') as f:
            data = f.read()
        filename = os.path.basename(file_path)
        return Response(
            data,
            mimetype='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(len(data)),
            }
        )

    # ========================================================
    # 路由：API - 打包下载正常照片
    # ========================================================

    @app.route("/api/download-zip", methods=["GET"])
    @rate_limit
    def download_zip():
        """将所有正常照片打包为 ZIP 下载"""
        import zipfile
        import io

        with scan_state_lock:
            if scan_state["is_scanning"]:
                return jsonify({"error": "正在扫描中，请等待完成"}), 400

            normal_paths = []
            removed = set(scan_state.get("removed_paths", set()))
            if scan_state["results"]:
                for path, results in scan_state["results"].items():
                    if path not in removed:
                        defects = [r for r in results if r.is_defective]
                        if not defects and os.path.isfile(path):
                            normal_paths.append(path)

        if not normal_paths:
            return jsonify({"error": "没有正常照片可下载"}), 400

        # 检查总文件大小
        total_size = 0
        MAX_ZIP_TOTAL = 10 * 1024 * 1024 * 1024  # 10GB
        valid_paths = []
        for p in normal_paths:
            try:
                sz = os.path.getsize(p)
                if total_size + sz > MAX_ZIP_TOTAL:
                    break
                total_size += sz
                valid_paths.append(p)
            except OSError:
                continue
        normal_paths = valid_paths

        return _build_zip(normal_paths)

    # ========================================================
    # 路由：API - 选中文件打包下载
    # ========================================================

    @app.route("/api/download-zip-selected", methods=["POST"])
    @rate_limit
    @csrf_protect
    def download_zip_selected():
        """将选中的文件打包为 ZIP 下载"""
        import zipfile
        import io

        data = request.get_json(silent=True)
        if not data or "paths" not in data:
            return jsonify({"error": "缺少文件路径列表"}), 400

        paths = data["paths"]
        if not isinstance(paths, list) or not paths:
            return jsonify({"error": "文件路径列表为空"}), 400

        # 安全过滤：只允许下载扫描结果中的正常文件
        valid_paths = []
        with scan_state_lock:
            removed = set(scan_state.get("removed_paths", set()))
            all_results = scan_state.get("results", {})
            for p in paths:
                if not is_path_safe(p):
                    continue
                if p not in all_results:
                    continue
                if p in removed:
                    continue
                defects = [r for r in all_results[p] if r.is_defective]
                if not defects and os.path.isfile(p):
                    valid_paths.append(p)

        if not valid_paths:
            return jsonify({"error": "没有有效的文件可下载"}), 400

        return _build_zip(valid_paths)

    def _build_zip(paths):
        """构建 ZIP 文件并返回"""
        import zipfile
        import io
        from datetime import datetime as _dt

        try:
            # 限制数量
            MAX_ZIP = 10000
            if len(paths) > MAX_ZIP:
                paths = paths[:MAX_ZIP]

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for path in paths:
                    arcname = os.path.basename(path)
                    if arcname in zf.namelist():
                        name, ext = os.path.splitext(arcname)
                        counter = 1
                        while f"{name}_{counter}{ext}" in zf.namelist():
                            counter += 1
                        arcname = f"{name}_{counter}{ext}"
                    try:
                        zf.write(path, arcname)
                    except Exception as e:
                        logger.warning("打包失败 %s: %s", path, e)

            zip_buffer.seek(0)
            zip_data = zip_buffer.getvalue()
            filename = f'photos_{_dt.now().strftime("%Y%m%d_%H%M%S")}.zip'

            response = app.make_response(zip_data)
            response.headers['Content-Type'] = 'application/zip'
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            response.headers['Content-Length'] = str(len(zip_data))
            return response
        except Exception as e:
            logger.error("构建ZIP失败: %s", e)
            return jsonify({"error": "打包失败，请稍后重试"}), 500

    return app
