"""GUI 音视频混合工具启动入口。

运行 `python main.py` 将调用 PySide6 图形界面，实现音视频混流工作流程。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from video_audio_mixer_gui import run_app


if __name__ == "__main__":
    # 启动 GUI 程序，内部已完成配置加载与界面初始化
    run_app()
