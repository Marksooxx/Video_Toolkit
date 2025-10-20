"""PreviewController 测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_audio_mixer_gui.core.ffmpeg_adapter import FFmpegAdapter, FFmpegResult
from video_audio_mixer_gui.core.logger import RichLogger
from video_audio_mixer_gui.models.media import AudioCategory, AudioClip, MixSession, TrackConfig, VideoClip, LengthMode
from video_audio_mixer_gui.services.mix_planner import MixPlanner
from video_audio_mixer_gui.services.preview_controller import PreviewController, PreviewSection


def make_session(tmp_path: Path) -> MixSession:
    video = VideoClip(
        file_path=tmp_path / "demo.mp4",
        display_name="demo.mp4",
        duration_seconds=5.0,
        fps=25.0,
        resolution=(1280, 720),
        has_audio=True,
    )
    audio = AudioClip(
        file_path=tmp_path / "music.wav",
        category=AudioCategory.MUSIC,
        duration_seconds=10.0,
        sample_rate=48000,
        display_name="music.wav",
        source_start_seconds=0.0,
    )
    config = TrackConfig(
        video_id=video.clip_id,
        enable_limiter=False,
        music_length_mode=LengthMode.MATCH_VIDEO,
    )
    return MixSession(
        video_clip=video,
        audio_clips=[audio],
        config=config,
        target_output=tmp_path / "out.mp4",
    )


def test_preview_generates_temp_file(tmp_path: Path) -> None:
    planner = MixPlanner()
    adapter = MagicMock(spec=FFmpegAdapter)
    adapter.run_command.return_value = FFmpegResult(return_code=0, stdout="", stderr="")
    logger = RichLogger()
    controller = PreviewController(planner=planner, adapter=adapter, logger=logger)
    session = make_session(tmp_path)

    with patch("subprocess.Popen") as popen_mock:
        process_mock = MagicMock()
        process_mock.wait.return_value = 0
        popen_mock.return_value = process_mock
        controller.preview(session, PreviewSection(start=0.0, duration=3.0))

    assert adapter.run_command.called
    popen_mock.assert_called()
