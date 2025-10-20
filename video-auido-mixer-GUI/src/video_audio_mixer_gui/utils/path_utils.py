"""路径工具模块。

提供路径过滤与扩展名判断等实用函数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


VIDEO_EXTENSIONS: tuple[str, ...] = (".mp4", ".mov", ".mkv", ".avi")
AUDIO_EXTENSIONS: tuple[str, ...] = (".wav", ".mp3", ".flac", ".ogg", ".aac")


def iter_media_files(paths: Iterable[Path]) -> List[Path]:
    """遍历路径列表，返回所有媒体文件路径。"""

    collected: List[Path] = []
    for path in paths:
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and is_supported_media(child):
                    collected.append(child)
        elif path.is_file() and is_supported_media(path):
            collected.append(path)
    return collected


def is_video(path: Path) -> bool:
    """判断是否为支持的视频文件。"""

    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_audio(path: Path) -> bool:
    """判断是否为支持的音频文件。"""

    return path.suffix.lower() in AUDIO_EXTENSIONS


def is_supported_media(path: Path) -> bool:
    """判断是否为支持的媒体文件。"""

    return is_video(path) or is_audio(path)


