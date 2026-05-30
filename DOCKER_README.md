# 照片自动分类工具 - Docker 版本使用指南

## 快速开始

### 方式一：使用 Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/shenglihalisen/photo-classifier-stable.git
cd photo-classifier-stable

# 2. 构建并启动
docker-compose up -d

# 3. 访问应用
浏览器打开 http://localhost:5000
```

### 方式二：使用 Docker 命令

```bash
# 1. 构建镜像
docker build -t photo-classifier:latest .

# 2. 运行容器
docker run -d \
  --name photo-classifier-web \
  -p 5000:5000 \
  -v /path/to/your/photos:/data/photos:ro \
  photo-classifier:latest

# 3. 访问应用
浏览器打开 http://localhost:5000
```

## 配置说明

### 端口配置

默认端口为 `5000`，如需修改：

```bash
# Docker Compose 方式：修改 docker-compose.yml 中的 ports
ports:
  - "8080:5000"  # 将外部端口改为 8080

# Docker 命令方式
docker run -d -p 8080:5000 photo-classifier:latest
```

### 照片目录映射

要扫描本地照片目录，需要将其映射到容器内：

```bash
# Docker Compose 方式：修改 docker-compose.yml 中的 volumes
volumes:
  - /your/local/photos:/data/photos:ro

# 或使用环境变量
export PHOTO_DIR=/your/local/photos
docker-compose up -d

# Docker 命令方式
docker run -d \
  -v /your/local/photos:/data/photos:ro \
  photo-classifier:latest
```

在Web界面中，选择"选择文件夹"功能时，输入容器内的路径 `/data/photos`。

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `FLASK_ENV` | Flask运行环境 | `production` |
| `CSRF_SECRET_KEY` | CSRF密钥（生产环境建议修改） | `photo-classifier-csrf-secret-key-2024` |
| `TZ` | 时区设置 | `Asia/Shanghai` |

```bash
# 设置环境变量
docker run -d \
  -e CSRF_SECRET_KEY=your-custom-secret-key \
  -e TZ=America/New_York \
  photo-classifier:latest
```

## 常用命令

```bash
# 查看容器状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 重新构建
docker-compose build --no-cache
docker-compose up -d
```

## 健康检查

容器内置健康检查，可通过以下方式验证：

```bash
# 查看容器健康状态
docker inspect --format='{{.State.Health.Status}}' photo-classifier-web

# 手动健康检查
curl http://localhost:5000/api/health
```

## 资源限制

默认配置了资源限制：

```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 2G
```

可根据实际需求调整 `docker-compose.yml` 中的配置。

## 注意事项

1. **文件上传限制**：单文件最大50MB，总上传最大200MB
2. **支持的图片格式**：JPG, JPEG, PNG, BMP, TIFF, WebP, GIF, HEIC, HEIF
3. **安全特性**：已内置CSRF防护、频率限制、路径安全检查等安全机制
4. **临时文件**：上传的文件会存储在容器内的 `/app/uploads` 目录，定期自动清理

## 生产环境建议

1. **修改CSRF密钥**：使用强随机密钥
   ```bash
   docker run -d -e CSRF_SECRET_KEY=$(openssl rand -hex 32) photo-classifier:latest
   ```

2. **使用HTTPS**：建议配合反向代理（如Nginx）配置SSL证书

3. **数据持久化**：重要数据建议映射到外部存储

4. **监控日志**：配置日志收集系统

## 示例：配合Nginx反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://photo-classifier-web:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 问题排查

### 容器无法启动

```bash
# 查看详细日志
docker-compose logs photo-classifier

# 检查依赖安装
docker run -it photo-classifier:latest pip list
```

### 无法访问照片目录

确保目录映射正确，且容器有读取权限：

```bash
# 检查容器内目录
docker exec photo-classifier-web ls -la /data/photos
```

### 内存不足

调整资源限制或使用更小的图片批次：

```yaml
deploy:
  resources:
    limits:
      memory: 4G  # 增加内存限制
```