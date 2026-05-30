# Photo Classifier - Docker Image
# 照片自动分类工具 Docker 版本

FROM python:3.11-slim

LABEL maintainer="photo-classifier"
LABEL description="智能检测损坏、空镜、闭眼、模糊、遮挡等缺陷照片的Web应用"
LABEL version="1.0.0"

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=run_web.py \
    FLASK_ENV=production \
    TZ=Asia/Shanghai

# 安装系统依赖
# OpenCV 和 MediaPipe 需要以下库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    ffmpeg \
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
COPY README.md .
COPY CHANGELOG.md .

# 创建上传目录（用于临时存储）
RUN mkdir -p /app/uploads && chmod 777 /app/uploads

# 创建非root用户运行应用
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

# 启动命令
CMD ["python", "run_web.py"]