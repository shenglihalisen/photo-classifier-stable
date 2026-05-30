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
    TMPDIR=/tmp

# 安装系统依赖
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
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
RUN sed -i '/PyQt5/d' requirements.txt && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY classifiers/ ./classifiers/
COPY engine/ ./engine/
COPY web/ ./web/
COPY run_web.py .

# 创建临时目录并设置权限
RUN mkdir -p /tmp && chmod 1777 /tmp

# 创建非root用户运行应用
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

# 启动命令
CMD ["python", "run_web.py"]
