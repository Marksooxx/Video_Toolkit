"""FFmpeg 适配器模块。

封装 ffprobe 与 ffmpeg 命令调用，提供黑屏生成、混流命令构建等功能。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(slots=True)
class FFmpegResult:
    """FFmpeg 执行结果。"""

    return_code: int
    stdout: str
    stderr: str


class FFmpegAdapter:
    """FFmpeg 命令封装。"""

    def __init__(self) -> None:
        self._base_command: List[str] = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y"]

    def run_command(self, command: List[str]) -> FFmpegResult:
        """执行 ffmpeg 命令。"""

        full_command = self._base_command + command
        process = subprocess.Popen(
            full_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stdout, stderr = process.communicate()
        return FFmpegResult(return_code=process.returncode, stdout=stdout, stderr=stderr)

    def concat_videos(self, list_file: Path, output_path: Path) -> FFmpegResult:
        """使用 concat demuxer 合并视频。"""

        command = [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_path),
        ]
        return self.run_command(command)

    def generate_black_clip(
        self,
        output_path: Path,
        resolution: tuple[int, int],
        duration: float,
        fps: float,
    ) -> FFmpegResult:
        """生成黑屏视频片段。"""

        width, height = resolution
        command = [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:d={duration:.3f}",
            "-r",
            f"{fps:.3f}",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        return self.run_command(command)

    def trim_video(self, input_path: Path, output_path: Path, start: float) -> FFmpegResult:
        """裁切视频从指定秒数开始。"""

        command = [
            "-ss",
            f"{max(start, 0.0):.3f}",
            "-i",
            str(input_path),
            "-c",
            "copy",
            str(output_path),
        ]
        return self.run_command(command)


