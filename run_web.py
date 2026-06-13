# -*- coding: utf-8 -*-
"""
照片自动分类工具 - Flask Web 端入口

启动方式:
    python run_web.py

启动后访问 http://localhost:5000
"""

import os
import sys

# 将项目根目录加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.app import create_app


def main():
    app = create_app()

    print("=" * 50)
    print("  照片自动分类工具 - Web 端")
    print("=" * 50)
    print("  访问地址: http://localhost:5000")
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)

    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    # 生产环境只监听 localhost，debug 模式可绑定 0.0.0.0
    host = "0.0.0.0" if debug else "127.0.0.1"
    app.run(host=host, port=5000, debug=debug)


if __name__ == "__main__":
    main()
