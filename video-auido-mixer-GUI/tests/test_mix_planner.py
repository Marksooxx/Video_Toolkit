"""MixPlanner 单元测试。"""

from pathlib import Path

import pytest

from video_audio_mixer_gui.models.media import AudioCategory, AudioClip, MixSession, TrackConfig, VideoClip, LengthMode
from video_audio_mixer_gui.services.mix_planner import MixPlanner


@pytest.fixture()
def planner() -> MixPlanner:
    return MixPlanner()


def make_session(override_original: bool = False, music_random: bool = False) -> MixSession:
    video = VideoClip(
        file_path=Path("demo.mp4"),
        display_name="demo.mp4",
        duration_seconds=5.0,
        fps=25.0,
        resolution=(1920, 1080),
        has_audio=True,
    )
    se = AudioClip(
        file_path=Path("se.wav"),
        category=AudioCategory.SE,
        duration_seconds=6.0,
        sample_rate=48000,
        display_name="se.wav",
        start_frame=0,
        source_start_seconds=0.0,
    )
    music = AudioClip(
        file_path=Path("music.wav"),
        category=AudioCategory.MUSIC,
        duration_seconds=20.0,
        sample_rate=48000,
        display_name="music.wav",
        start_frame=0,
        source_start_seconds=0.0,
    )
    config = TrackConfig(
        video_id=video.clip_id,
        override_original=override_original,
        enable_limiter=True,
        music_random_enabled=music_random,
        music_retry_limit=3,
        music_start_offset=1.0,
        music_length_mode=LengthMode.FIXED_SECONDS,
        music_length_value=8.0,
    )
    return MixSession(
        video_clip=video,
        audio_clips=[se, music],
        config=config,
        target_output=Path("out.mp4"),
    )


def test_black_extension_and_normalize(planner: MixPlanner) -> None:
    session = make_session()
    plan = planner.build_plan(session)
    assert plan.needs_black_extension is True
    assert plan.black_extension_duration > 0
    assert plan.amix_normalize == 1


def test_music_random_offset(planner: MixPlanner) -> None:
    session = make_session(music_random=True)
    plan = planner.build_plan(session)
    filters = ";".join(plan.audio_filters)
    assert "amix" in filters
    assert "normalize=1" in filters
