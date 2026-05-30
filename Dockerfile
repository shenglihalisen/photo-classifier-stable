# Photo Classifier - Docker Image
# 照片自动分类工具 Docker 版本
# 镜像地址：ghcr.io/shenglihalisen/photo-classifier-stable

FROM python:3.11-slim

LABEL maintainer="shenglihalisen"
LABEL description="智能检测损坏、空镜、闭眼、模糊、遮挡等缺陷照片的Web应用"
LABEL version="1.1.0"
LABEL org.opencontainers.image.source="https://github.com/shenglihalisen/photo-classifier-stable"

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=run_web.py \
    FLASK_ENV=production \
    TZ=Asia/Shanghai \
    # 临时文件目录（上传文件存储位置）
    TMPDIR=/tmp \
    # 上传文件最大大小：单文件50MB，总计200MB
    MAX_FILE_SIZE=52428800 \
    MAX_TOTAL_SIZE=209715200

# 安装系统依赖
# OpenCV 和 MediaPipe 需要以下库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libgles2-mesa \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
# 移除PyQt5（桌面端依赖，Web端不需要）
RUN sed -i '/PyQt5/d' requirements.txt && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY classifiers/ ./classifiers/
COPY engine/ ./engine/
COPY web/ ./web/
COPY run_web.py .

# 创建上传/临时目录并设置权限
# Flask上传文件通过tempfile.mkdtemp存储在/tmp下
RUN mkdir -p /tmp /app/uploads && \
    chmod 777 /tmp /app/uploads

# 创建非root用户运行应用
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    chown -R appuser:appuser /tmp
USER appuser

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# 启动命令
CMD ["python", "run_web.py"]