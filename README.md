# 照片自动分类工具

智能检测损坏、空镜、闭眼、模糊、遮挡、曝光异常、噪点等缺陷照片，一键整理您的相册。

<div align="center">

[![GitHub release](https://img.shields.io/github/v/release/shenglihalisen/photo-classifier-stable)](https://github.com/shenglihalisen/photo-classifier-stable/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/shenglihalisen/photo-classifier-stable)](https://github.com/shenglihalisen/photo-classifier-stable/commits/main)

</div>

---

## 功能特性

- **7 种缺陷检测**：损坏、空镜、闭眼、模糊、遮挡、曝光异常、噪点
- **重复照片检测**：基于感知哈希（pHash）自动识别重复照片
- **双端支持**：PyQt5 桌面端 + Flask Web 端
- **两种模式**：自动模式（一键处理）/ 手动确认（逐张审核）
- **批量处理**：支持文件夹批量扫描和文件拖拽上传
- **灵活操作**：自动将废片按缺陷类型分类到子文件夹
- **图片预览**：点击图片大图预览，支持滚轮缩放
- **标记正常**：预览中标记误判为废片的照片为正常
- **下载功能**：支持单张下载、多文件下载、打包 ZIP 下载
- **并行处理**：多线程并行检测，预计算共享值加速扫描

## 支持的图片格式

```
JPG, JPEG, PNG, BMP, TIFF, WebP, GIF, HEIC, HEIF
```

## 安装

### 下载发行版（推荐）

前往 [Releases](https://github.com/shenglihalisen/photo-classifier-stable/releases) 页面下载最新版本。

| 文件 | 说明 |
|------|------|
| `PhotoClassifier-Web.exe` | Web 端，双击运行后浏览器访问 `http://localhost:5000` |

### 从源码运行

```bash
# 克隆仓库
git clone https://github.com/shenglihalisen/photo-classifier-stable.git
cd photo-classifier-stable

# 安装依赖
pip install -r requirements.txt

# 运行 Web 端
python run_web.py
```

Web 端启动后访问 `http://localhost:5000`。

## 使用方法

### Web 端

1. 打开浏览器访问 `http://localhost:5000`
2. 选择「上传文件」Tab 点击选择或拖拽照片
3. 选择「选择文件夹」Tab 点击选择或拖拽整个文件夹
4. 选择扫描模式（自动 / 手动确认）
5. 点击「开始扫描」
6. 扫描完成后查看结果：
   - hover 照片可勾选
   - 点击照片可预览大图并标记正常
   - 操作栏可移动/删除废片、检测重复、下载照片

## 检测器说明

| 检测器 | 检测内容 | 技术原理 |
|--------|----------|----------|
| 损坏检测 | 文件损坏、无法打开、截断的图片 | 文件头魔数验证 + PIL/OpenCV 解码 |
| 空镜检测 | 纯色、全黑、全白、大面积单一颜色 | 灰度均值 + 拉普拉斯方差 + 直方图分析 |
| 闭眼检测 | 人物闭眼的照片 | MediaPipe Face Mesh + EAR 算法 |
| 模糊检测 | 对焦不准、运动模糊的照片 | 拉普拉斯方差 + Sobel 边缘强度 |
| 遮挡检测 | 镜头/手指遮挡的照片 | 边缘均匀性 + 肤色区域分析 |
| 曝光检测 | 严重过曝或欠曝的照片 | 亮度均值 + 高亮/极暗像素占比 |
| 噪点检测 | 高 ISO 噪点严重的照片 | 拉普拉斯方差 + FFT 高频能量 |
| 重复检测 | 几乎相同的照片 | pHash 感知哈希 + 汉明距离 |

## 项目结构

```
photo-classifier-stable/
├── classifiers/              # 缺陷检测器
│   ├── base.py              # 基类、类型定义、PrecomputedImage
│   ├── utils.py             # FaceLandmarkerFactory、FaceDetectorMixin
│   ├── corrupted.py         # 损坏检测
│   ├── empty.py             # 空镜检测
│   ├── blink.py             # 闭眼检测
│   ├── blur.py              # 模糊检测
│   ├── obstruction.py       # 遮挡检测
│   ├── exposure.py          # 曝光检测
│   ├── noise.py             # 噪点检测
│   └── duplicate.py         # 重复照片检测
├── engine/                  # 分类引擎
│   └── classifier.py        # 统一分类引擎（并行处理）
├── web/                     # Web 端
│   ├── app.py               # Flask 应用
│   └── templates/           # HTML 模板
├── desktop/                 # 桌面端
│   └── app.py               # PyQt5 界面
├── run_web.py               # Web 端入口
├── run_desktop.py           # 桌面端入口
├── requirements.txt         # Python 依赖
├── Dockerfile               # Docker 镜像配置
├── docker-compose.yml       # Docker Compose 配置
├── CHANGELOG.md             # 更新日志
└── README.md                # 本文件
```

## 技术栈

- **图像处理**：OpenCV、MediaPipe、Pillow、NumPy
- **Web 端**：Flask + Layui
- **桌面端**：PyQt5
- **打包**：PyInstaller
- **部署**：Docker

## 安全特性（Web 端）

- CSRF Token 防护（HMAC-SHA256）
- 请求频率限制（60 次/分钟/IP）
- 文件类型白名单验证（扩展名 + 魔数双重检查）
- 路径遍历攻击防护
- 删除操作二次确认 Token 机制
- 并发扫描限制（信号量控制）
- 安全响应头（X-Frame-Options、CSP、XSS-Protection）
- 错误信息脱敏
- Server 版本信息隐藏
- 临时文件自动清理

## 性能优化

- 预计算共享值（灰度图、拉普拉斯方差、颜色标准差）
- 大图自动缩放（超过 2048px 自动缩小）
- 多线程并行检测（4 线程 ThreadPoolExecutor）
- 图像只读取一次，所有检测器共享
- FaceLandmarker 线程安全单例

## 更新日志

查看 [CHANGELOG.md](CHANGELOG.md) 了解详细更新记录。

## 许可证

MIT License
