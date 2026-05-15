# -*- coding: utf-8 -*-
"""
照片自动分类工具 - PyQt5 桌面端入口

启动方式:
    python run_desktop.py
"""

import os
import sys

# 将项目根目录加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from desktop.app import run


def main():
    print("=" * 50)
    print("  照片自动分类工具 - 桌面端")
    print("=" * 50)
    run()


if __name__ == "__main__":
    main()
