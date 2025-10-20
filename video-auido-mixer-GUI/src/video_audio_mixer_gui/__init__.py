"""GUI 音视频混合工具包。

该包提供 PySide6 图形界面、媒体管理、FFmpeg 调用等模块，用于实现多音轨音视频混流功能。
"""

__all__: list[str] = []

from .app import run_app

__all__ = ["run_app"]


