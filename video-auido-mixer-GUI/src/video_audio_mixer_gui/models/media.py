"""媒体相关数据模型。

该模块定义视频条目、音频条目、轨道配置与混流会话等核心数据结构，以便在 GUI
与服务层之间进行清晰的数据交换。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid


class AudioCategory(Enum):
    """音频类别枚举。

    目前包括特效音 SE、配音 VO 与背景音乐 MUSIC。
    """

    SE = "se"
    VO = "vo"
    MUSIC = "music"


class LengthMode(Enum):
    """音乐轨道截取模式。"""

    MATCH_VIDEO = "match_video"
    FIXED_SECONDS = "fixed_seconds"
    FIXED_FRAMES = "fixed_frames"


def _generate_id() -> str:
    """生成唯一标识符。"""

    return uuid.uuid4().hex


@dataclass(slots=True)
class VideoClip:
    """视频片段实体。"""

    file_path: Path
    display_name: str
    duration_seconds: float
    fps: float
    resolution: Tuple[int, int]
    has_audio: bool
    clip_id: str = field(default_factory=_generate_id, init=False)

    @property
    def duration_frames(self) -> int:
        """以帧为单位返回时长。"""

        return int(self.duration_seconds * self.fps)

    def to_payload(self) -> Dict[str, Any]:
        """转换为 GUI 可消费的字典。"""

        payload: Dict[str, Any] = asdict(self)
        payload["file_path"] = str(self.file_path)
        payload["resolution"] = {
            "width": self.resolution[0],
            "height": self.resolution[1],
        }
        return payload


@dataclass(slots=True)
class AudioClip:
    """音频片段实体。"""

    file_path: Path
    category: AudioCategory
    duration_seconds: float
    sample_rate: int
    display_name: str
    start_frame: Optional[int] = None
    source_start_seconds: float = 0.0
    clip_id: str = field(default_factory=_generate_id, init=False)

    def start_seconds(self, fps: float) -> float:
        """根据帧率换算起始秒数。"""

        start_frame: int = self.start_frame or 0
        if fps <= 0:
            return 0.0
        return start_frame / fps


@dataclass(slots=True)
class TrackConfig:
    """视频轨道混流配置。"""

    video_id: str
    override_original: bool = False
    enable_limiter: bool = True
    music_random_seed: Optional[int] = None
    music_retry_limit: int = 3
    music_random_enabled: bool = False
    music_length_mode: LengthMode = LengthMode.MATCH_VIDEO
    music_length_value: Optional[float] = None
    music_start_offset: float = 0.0
    video_audio_lead: float = 0.0


@dataclass(slots=True)
class MixSession:
    """混流会话数据。"""

    video_clip: VideoClip
    audio_clips: List[AudioClip]
    config: TrackConfig
    target_output: Path
    session_id: str = field(default_factory=_generate_id, init=False)

    def requires_black_extension(self) -> bool:
        """判断是否需要黑屏补帧。"""

        return self.black_extension_duration() > 0.0

    def generate_summary(self) -> Dict[str, Any]:
        """生成会话概要信息。"""

        summary: Dict[str, Any] = {
            "video": self.video_clip.to_payload(),
            "audios": [clip.display_name for clip in self.audio_clips],
            "config": {
                "override_original": self.config.override_original,
                "enable_limiter": self.config.enable_limiter,
                "music_length_mode": self.config.music_length_mode.value,
            },
            "target_output": str(self.target_output),
        }
        return summary

    def black_extension_duration(self) -> float:
        """计算需要补齐的黑屏时长（秒）。"""

        video_duration: float = self.video_clip.duration_seconds
        se_vo_end: float = video_duration
        for clip in self.audio_clips:
            if clip.category not in {AudioCategory.SE, AudioCategory.VO}:
                continue
            start_seconds: float = clip.start_seconds(self.video_clip.fps)
            end_time: float = start_seconds + clip.duration_seconds
            se_vo_end = max(se_vo_end, end_time)
        return max(0.0, se_vo_end - video_duration)


@dataclass(slots=True)
class ImportResult:
    """拖入媒体后的结果。"""

    videos: List[VideoClip] = field(default_factory=list)
    audios: List[AudioClip] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def extend(self, other: "ImportResult") -> None:
        """合并另一个导入结果。"""

        self.videos.extend(other.videos)
        self.audios.extend(other.audios)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)


