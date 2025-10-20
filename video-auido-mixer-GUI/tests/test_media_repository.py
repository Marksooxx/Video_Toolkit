"""MediaRepository 相关测试。"""

from pathlib import Path

import pytest

from video_audio_mixer_gui.models.media import AudioCategory, AudioClip, ImportResult, TrackConfig, VideoClip
from video_audio_mixer_gui.services.media_repository import MediaRepository


@pytest.fixture()
def repo() -> MediaRepository:
    return MediaRepository()


def make_video(name: str, duration: float = 5.0, fps: float = 25.0) -> VideoClip:
    return VideoClip(
        file_path=Path(f"{name}.mp4"),
        display_name=f"{name}.mp4",
        duration_seconds=duration,
        fps=fps,
        resolution=(1920, 1080),
        has_audio=True,
    )


def make_audio(name: str, category: AudioCategory, duration: float = 6.0) -> AudioClip:
    return AudioClip(
        file_path=Path(name),
        category=category,
        duration_seconds=duration,
        sample_rate=48000,
        display_name=name,
        source_start_seconds=0.0,
    )


def test_pair_audio_with_prefix(repo: MediaRepository) -> None:
    video = make_video("demo")
    audio = make_audio("a1_demo.wav", AudioCategory.SE)
    import_result = ImportResult(videos=[video], audios=[audio])
    repo.register_import(import_result)

    sessions = repo.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].audio_clips[0].display_name == "a1_demo.wav"


def test_update_audio_parameters(repo: MediaRepository) -> None:
    video = make_video("demo")
    audio = make_audio("demo.wav", AudioCategory.VO)
    repo.register_import(ImportResult(videos=[video], audios=[audio]))

    session = repo.list_sessions()[0]
    repo.update_audio_parameters(
        video_id=session.video_clip.clip_id,
        audio_id=session.audio_clips[0].clip_id,
        start_seconds=1.5,
        source_offset=0.3,
        fps=video.fps,
    )

    updated = repo.get_session(session.video_clip.clip_id).audio_clips[0]
    assert updated.start_frame == pytest.approx(int(1.5 * video.fps))
    assert updated.source_start_seconds == pytest.approx(0.3)
