"""媒体仓库服务。

负责维护视频与音频片段，提供自动配对与会话管理功能。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, List

from video_audio_mixer_gui.models.media import (
    AudioClip,
    ImportResult,
    MixSession,
    TrackConfig,
    VideoClip,
    LengthMode,
    AudioCategory,
)


class MediaRepository:
    """内存中的媒体管理仓库。"""

    def __init__(self, enable_limiter_default: bool = True, default_output_dir: Path | None = None) -> None:
        self._videos: Dict[str, VideoClip] = {}
        self._audios_by_video: Dict[str, List[AudioClip]] = defaultdict(list)
        self._configs: Dict[str, TrackConfig] = {}
        self._output_paths: Dict[str, Path] = {}
        self._last_unmatched_warning: str | None = None
        self._lock = RLock()
        self._enable_limiter_default = enable_limiter_default
        self._default_output_dir = Path(default_output_dir).expanduser() if default_output_dir else None

    def register_import(self, result: ImportResult) -> None:
        """注册导入结果。"""

        with self._lock:
            for video in result.videos:
                self._videos[video.clip_id] = video
                if video.clip_id not in self._configs:
                    default_config = TrackConfig(
                        video_id=video.clip_id,
                        enable_limiter=self._enable_limiter_default,
                        music_length_mode=LengthMode.MATCH_VIDEO,
                    )
                    self._configs[video.clip_id] = default_config
                    output_name = f"{video.file_path.name}"
                    if self._default_output_dir:
                        if self._default_output_dir.is_absolute():
                            target_dir = self._default_output_dir
                        else:
                            target_dir = (video.file_path.parent / self._default_output_dir).resolve()
                    else:
                        target_dir = video.file_path.parent
                    target_dir.mkdir(parents=True, exist_ok=True)
                    self._output_paths[video.clip_id] = target_dir / output_name

            audio_mapping = self.pair_audio_with_video(result.audios)
            for video_id, clips in audio_mapping.items():
                self._audios_by_video[video_id].extend(clips)

    def pair_audio_with_video(self, audio_clips: Iterable[AudioClip]) -> Dict[str, List[AudioClip]]:
        """根据文件名自动为视频匹配音频。"""

        mapping: Dict[str, List[AudioClip]] = defaultdict(list)
        unmatched: List[AudioClip] = []

        with self._lock:
            videos = list(self._videos.values())
            video_stems = {video.clip_id: self._collect_name_variants(video.file_path) for video in videos}

        for audio_clip in audio_clips:
            audio_names = self._collect_name_variants(audio_clip.file_path)
            matched = False
            for video in videos:
                video_names = video_stems[video.clip_id]
                if video_names.intersection(audio_names):
                    mapping[video.clip_id].append(audio_clip)
                    matched = True
                    break
            if not matched:
                unmatched.append(audio_clip)

        with self._lock:
            if unmatched:
                names = ", ".join(clip.display_name for clip in unmatched)
                self._last_unmatched_warning = f"未匹配的音频: {names}"
            else:
                self._last_unmatched_warning = None

        return mapping

    def replace_audio_list(self, video_id: str, clips: List[AudioClip]) -> None:
        """替换指定视频的音频列表。"""

        with self._lock:
            self._audios_by_video[video_id] = clips

    def get_session(self, video_id: str) -> MixSession:
        """根据视频 ID 获取混流会话。"""

        with self._lock:
            video_clip = self._videos[video_id]
            audios = list(self._audios_by_video.get(video_id, []))
            config = self._configs[video_id]
            output_path = self._output_paths[video_id]
        return MixSession(
            video_clip=video_clip,
            audio_clips=audios,
            config=config,
            target_output=output_path,
        )

    def update_session_config(self, video_id: str, config: TrackConfig) -> None:
        """更新配置。"""

        with self._lock:
            self._configs[video_id] = config

    def list_sessions(self) -> List[MixSession]:
        """列出所有会话。"""

        with self._lock:
            return [self.get_session(video_id) for video_id in self._videos]

    def remove_video(self, video_id: str) -> None:
        """删除视频及其关联数据。"""

        with self._lock:
            self._videos.pop(video_id, None)
            self._audios_by_video.pop(video_id, None)
            self._configs.pop(video_id, None)
            self._output_paths.pop(video_id, None)

    def remove_audio(self, video_id: str, audio_id: str) -> None:
        """删除指定视频下的某个音频。"""

        with self._lock:
            clips = self._audios_by_video.get(video_id, [])
            self._audios_by_video[video_id] = [clip for clip in clips if clip.clip_id != audio_id]

    def update_audio_parameters(self, video_id: str, audio_id: str, start_seconds: float, source_offset: float, fps: float) -> None:
        """更新音频起点与源偏移。"""

        with self._lock:
            clips = self._audios_by_video.get(video_id, [])
            for clip in clips:
                if clip.clip_id == audio_id:
                    clip.start_frame = int(start_seconds * fps) if fps > 0 else None
                    clip.source_start_seconds = max(0.0, source_offset)
                    break

    def last_unmatched_warning(self) -> str | None:
        """返回最近一次未匹配音频的警告信息。"""

        with self._lock:
            return self._last_unmatched_warning

    def get_audio_clips(self, video_id: str) -> List[AudioClip]:
        """返回指定视频的音频列表。"""

        with self._lock:
            return list(self._audios_by_video.get(video_id, []))

    def add_audio_to_video(self, video_id: str, audio_clip: AudioClip, category: AudioCategory) -> None:
        """将音频加入指定视频，并强制设置类别。"""

        with self._lock:
            new_clip = replace(audio_clip, category=category)
            self._audios_by_video[video_id].append(new_clip)

    def set_default_enable_limiter(self, value: bool) -> None:
        """更新默认 normalize 开关并同步已有配置。"""

        with self._lock:
            self._enable_limiter_default = value
            for video_id, config in self._configs.items():
                updated = replace(config, enable_limiter=value)
                self._configs[video_id] = updated

    def set_default_output_dir(self, path: Path) -> None:
        """更新默认输出目录。"""

        with self._lock:
            self._default_output_dir = Path(path).expanduser()

    def set_override_original(self, value: bool) -> None:
        """更新覆盖原音频的默认开关。"""

        with self._lock:
            for video_id, config in self._configs.items():
                self._configs[video_id] = replace(config, override_original=value)

    @staticmethod
    def _normalize_name(path: Path) -> str:
        """标准化文件名，参考示例代码逻辑。"""

        stem = path.stem.lower()
        for prefix in ("a1_", "a2_", "a3_", "a4_"):
            if stem.startswith(prefix):
                stem = stem[len(prefix) :]
        return stem

    @classmethod
    def _collect_name_variants(cls, path: Path) -> set[str]:
        """生成用于匹配的名称集合，包括原名与去前缀版本。"""

        variants: set[str] = set()
        stem = path.stem.lower()
        variants.add(stem)
        normalized = cls._normalize_name(path)
        variants.add(normalized)
        # 补充：去掉常见后缀如 "-mix", "_mix" 等
        for suffix in ("-mix", "_mix", "-audio", "_audio"):
            if stem.endswith(suffix):
                variants.add(stem[: -len(suffix)])
            if normalized.endswith(suffix):
                variants.add(normalized[: -len(suffix)])
        return {name for name in variants if name}


