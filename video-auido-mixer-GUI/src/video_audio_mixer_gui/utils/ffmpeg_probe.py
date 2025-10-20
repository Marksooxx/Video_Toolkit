"""封装 ffprobe 查询工具函数。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class VideoMetadata:
    """视频元数据。"""

    duration_seconds: float
    fps: float
    width: int
    height: int
    has_audio: bool


@dataclass(slots=True)
class AudioMetadata:
    """音频元数据。"""

    duration_seconds: float
    sample_rate: int


def probe_video(path: Path) -> Optional[VideoMetadata]:
    """使用 ffprobe 获取视频信息。"""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate,width,height",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    return _run_video_probe(command)


def probe_audio(path: Path) -> Optional[AudioMetadata]:
    """使用 ffprobe 获取音频信息。"""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    return _run_audio_probe(command)


def _run_video_probe(command: list[str]) -> Optional[VideoMetadata]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    stdout, _stderr = process.communicate()
    if process.returncode != 0:
        return None
    payload = json.loads(stdout)
    duration = float(payload["format"].get("duration", 0.0))
    streams = payload.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video_stream is None:
        return None
    fps_value = stream["r_frame_rate"]
    if "/" in fps_value:
        numerator, denominator = fps_value.split("/")
        fps = float(numerator) / max(float(denominator), 1.0)
    else:
        fps = float(fps_value)
    return VideoMetadata(
        duration_seconds=duration,
        fps=fps,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        has_audio=audio_stream is not None,
    )


def _run_audio_probe(command: list[str]) -> Optional[AudioMetadata]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    stdout, _stderr = process.communicate()
    if process.returncode != 0:
        return None
    payload = json.loads(stdout)
    duration = float(payload["format"]["duration"])
    stream = payload["streams"][0]
    return AudioMetadata(
        duration_seconds=duration,
        sample_rate=int(stream["sample_rate"]),
    )


