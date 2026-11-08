# 多阶段构建：编译出静态单文件，运行镜像只留二进制（约 9MB）
# 支持 buildx 多架构：GOOS/GOARCH 跟着 TARGET* 走
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS build
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags "-s -w" -o /out/pcs .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=build /out/pcs /usr/local/bin/pcs
# 照片目录挂到这里，同时也是唯一允许扫描的目录
WORKDIR /data

# 容器监听 0.0.0.0 才能被外部访问，因此程序会强制启用口令认证。
# 口令来自 PCP_PASS；没设置就启动时随机生成并打印到 docker logs。
# -base-dir /data 把 /api/scan 的 root 锁死在挂载目录内。
ENV PCP_PASS=""
EXPOSE 8080
ENTRYPOINT ["pcs", "-addr", "0.0.0.0", "-port", "8080", "-no-browser", "-base-dir", "/data"]
