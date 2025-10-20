"""拖放媒体收集模块。"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from video_audio_mixer_gui.models.media import AudioCategory, AudioClip, ImportResult, VideoClip
from video_audio_mixer_gui.utils.path_utils import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from video_audio_mixer_gui.utils.ffmpeg_probe import probe_audio, probe_video


def collect_media_from_paths(paths: Iterable[Path]) -> ImportResult:
    """根据拖入路径收集媒体文件。"""

    result = ImportResult()
    for path in paths:
        if path.is_dir():
            _collect_from_directory(directory_path=path, result=result)
        elif path.is_file():
            _collect_single_file(file_path=path, result=result)
        else:
            result.errors.append(f"路径不存在或无效: {path}")
    return result


def _collect_from_directory(directory_path: Path, result: ImportResult) -> None:
    """从目录中收集媒体文件。"""

    found = False
    for child in directory_path.iterdir():
        if child.is_file():
            _collect_single_file(file_path=child, result=result)
            found = True
    if not found:
        result.warnings.append(f"目录为空: {directory_path}")


def _collect_single_file(file_path: Path, result: ImportResult) -> None:
    """收集单个媒体文件。"""

    suffix = file_path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        metadata = probe_video(file_path)
        if metadata is None:
            result.warnings.append(f"无法读取视频信息: {file_path}")
            duration_seconds = 0.0
            fps = 0.0
            resolution = (0, 0)
            has_audio = False
        else:
            duration_seconds = metadata.duration_seconds
            fps = metadata.fps
            resolution = (metadata.width, metadata.height)
            has_audio = metadata.has_audio
        video = VideoClip(
            file_path=file_path,
            display_name=file_path.name,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            has_audio=has_audio,
        )
        result.videos.append(video)
    elif suffix in AUDIO_EXTENSIONS:
        category = _categorize_audio(file_path)
        metadata = probe_audio(file_path)
        if metadata is None:
            result.warnings.append(f"无法读取音频信息: {file_path}")
            duration_seconds = 0.0
            sample_rate = 0
        else:
            duration_seconds = metadata.duration_seconds
            sample_rate = metadata.sample_rate
        audio = AudioClip(
            file_path=file_path,
            category=category,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            display_name=file_path.name,
            source_start_seconds=0.0,
        )
        result.audios.append(audio)
    else:
        result.warnings.append(f"不支持的文件类型: {file_path}")


def _categorize_audio(file_path: Path) -> AudioCategory:
    """根据文件名判断音频类别。"""

    lower_name = file_path.name.lower()
    if "vo" in lower_name:
        return AudioCategory.VO
    if "music" in lower_name or "bgm" in lower_name:
        return AudioCategory.MUSIC
    return AudioCategory.SE
