# Photo Classifier - Docker Image
# 镜像地址：ghcr.io/shenglihalisen/photo-classifier-stable
# 支持架构：linux/amd64, linux/arm64

FROM python:3.11-slim-bookworm

LABEL maintainer="shenglihalisen"
LABEL description="智能检测损坏、空镜、闭眼、模糊、遮挡等缺陷照片的Web应用"
LABEL version="1.2.0"
LABEL org.opencontainers.image.source="https://github.com/shenglihalisen/photo-classifier-stable"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=run_web.py \
    FLASK_ENV=production \
    TZ=Asia/Shanghai

# 安装系统依赖（兼容 x86_64 和 ARM64）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgomp1 \
        ffmpeg \
        curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN sed -i '/PyQt5/d' requirements.txt && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY classifiers/ ./classifiers/
COPY engine/ ./engine/
COPY web/ ./web/
COPY run_web.py .

# 创建临时目录
RUN mkdir -p /tmp && chmod 1777 /tmp

# 创建非root用户
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

CMD ["python", "run_web.py"]