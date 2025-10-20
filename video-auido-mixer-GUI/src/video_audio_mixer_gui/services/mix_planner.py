"""混流计划构建服务。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4
import random

from video_audio_mixer_gui.models.media import AudioCategory, AudioClip, MixSession


@dataclass(slots=True)
class MixPlan:
    """混流计划数据结构。"""

    video_input: Path
    audio_inputs: List[Path] = field(default_factory=list)
    audio_filters: List[str] = field(default_factory=list)
    output_args: List[str] = field(default_factory=list)
    needs_black_extension: bool = False
    black_extension_duration: float = 0.0
    video_resolution: tuple[int, int] = (0, 0)
    video_fps: float = 0.0
    black_clip_path: Path | None = None
    concat_list_path: Path | None = None
    extended_video_path: Path | None = None
    audio_output_label: str = "aout"
    include_original_audio: bool = False
    amix_normalize: int = 0


class MixPlanner:
    """根据会话构建混流计划。"""

    def build_plan(self, session: MixSession) -> MixPlan:
        """构建混流计划，包含黑屏延伸信息。"""

        plan = MixPlan(video_input=session.video_clip.file_path)
        plan.video_resolution = session.video_clip.resolution
        plan.video_fps = session.video_clip.fps
        plan.include_original_audio = not session.config.override_original and session.video_clip.has_audio
        plan.amix_normalize = 1 if session.config.enable_limiter else 0

        audio_outputs: List[str] = []
        for index, audio_clip in enumerate(session.audio_clips):
            plan.audio_inputs.append(audio_clip.file_path)
            final_label, filters = self._build_clip_filters(index=index, clip=audio_clip, session=session)
            plan.audio_filters.extend(filters)
            audio_outputs.append(final_label)

        if plan.include_original_audio:
            final_label, filters = self._build_original_filters(session)
            plan.audio_filters.extend(filters)
            audio_outputs.append(final_label)

        if audio_outputs:
            mix_inputs = "".join(f"[{label}]" for label in audio_outputs)
            plan.audio_filters.append(
                f"{mix_inputs}amix=inputs={len(audio_outputs)}:normalize={plan.amix_normalize}[{plan.audio_output_label}]"
            )

        plan.output_args = ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
        plan.black_extension_duration = session.black_extension_duration()
        plan.needs_black_extension = plan.black_extension_duration > 0.0

        if plan.needs_black_extension:
            unique_token = uuid4().hex
            base_dir = session.video_clip.file_path.parent
            stem = session.video_clip.file_path.stem
            plan.black_clip_path = base_dir / f"{stem}_black_{unique_token}.mp4"
            plan.concat_list_path = base_dir / f"{stem}_concat_{unique_token}.txt"
            plan.extended_video_path = base_dir / f"{stem}_extended_{unique_token}.mp4"

        return plan

    def _build_clip_filters(self, index: int, clip: AudioClip, session: MixSession) -> Tuple[str, List[str]]:
        """为单个音频片段构建滤镜链。"""

        filters: List[str] = []
        current_ref = f"[{index + 1}:a]"
        label_counter = 0
        output_label = f"a{index}"

        def next_label(suffix: str) -> str:
            nonlocal label_counter
            label_counter += 1
            return f"{output_label}_{suffix}_{label_counter}"

        def apply_filter(filter_expr: str) -> None:
            nonlocal current_ref
            new_label = next_label("flt")
            filters.append(f"{current_ref}{filter_expr}[{new_label}]")
            current_ref = f"[{new_label}]"

        # 音源起始偏移
        source_offset = clip.source_start_seconds
        if clip.category == AudioCategory.MUSIC:
            source_offset += max(0.0, session.config.music_start_offset)
            if session.config.music_random_enabled:
                random_offset = self._random_music_offset(clip, session)
                source_offset += random_offset
        if source_offset > 0:
            apply_filter(f"atrim=start={source_offset},asetpts=PTS-STARTPTS")

        # 音乐长度截断
        if clip.category == AudioCategory.MUSIC:
            trim_expr = self._music_length_trim(session)
            if trim_expr:
                apply_filter(f"{trim_expr},asetpts=PTS-STARTPTS")

        # 视频时间轴偏移 + 单独起始帧偏移
        delay_seconds = max(
            0.0,
            clip.start_seconds(session.video_clip.fps) + max(0.0, session.config.video_audio_lead),
        )
        if delay_seconds > 0:
            delay_ms = int(delay_seconds * 1000)
            apply_filter(f"adelay={delay_ms}|{delay_ms}")

        if current_ref != f"[{output_label}]":
            filters.append(f"{current_ref}anull[{output_label}]")

        return output_label, filters

    def _music_length_trim(self, session: MixSession) -> str | None:
        """生成音乐截断表达式。"""

        mode = session.config.music_length_mode
        value = session.config.music_length_value
        if mode == session.config.music_length_mode.MATCH_VIDEO or value is None:
            return None
        if mode == session.config.music_length_mode.FIXED_SECONDS:
            return f"atrim=0:{value}"
        if mode == session.config.music_length_mode.FIXED_FRAMES:
            seconds = value / max(session.video_clip.fps, 1.0)
            return f"atrim=0:{seconds}"
        return None

    def _build_original_filters(self, session: MixSession) -> Tuple[str, List[str]]:
        """构建原始音频滤镜链。"""

        filters: List[str] = []
        current_ref = "[0:a]"
        output_label = "orig_audio"

        delay_seconds = max(0.0, session.config.video_audio_lead)
        if delay_seconds > 0:
            delay_ms = int(delay_seconds * 1000)
            filters.append(f"{current_ref}adelay={delay_ms}|{delay_ms}[{output_label}_delay]")
            current_ref = f"[{output_label}_delay]"

        if current_ref != f"[{output_label}]":
            filters.append(f"{current_ref}anull[{output_label}]")

        return output_label, filters

    def _random_music_offset(self, clip: AudioClip, session: MixSession) -> float:
        """根据配置生成音乐随机起点。"""

        total_duration = max(clip.duration_seconds, 0.0)
        if session.video_clip.duration_seconds <= 0 or total_duration <= 0:
            return 0.0
        max_start = max(total_duration - session.video_clip.duration_seconds, 0.0)
        if max_start <= 0:
            return 0.0
        rng = random.Random(session.config.music_random_seed)
        best_value = 0.0
        attempts = max(session.config.music_retry_limit, 1)
        for _ in range(attempts):
            candidate = rng.uniform(0.0, max_start)
            best_value = candidate
        return best_value
