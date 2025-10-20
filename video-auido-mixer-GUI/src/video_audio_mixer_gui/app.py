"""应用入口。"""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from video_audio_mixer_gui.core.config_manager import AppConfig, load_config, save_config
from video_audio_mixer_gui.core.ffmpeg_adapter import FFmpegAdapter
from video_audio_mixer_gui.core.logger import RichLogger
from video_audio_mixer_gui.gui.main_window import MainWindow
from video_audio_mixer_gui.models.media import AudioCategory, MixSession
from video_audio_mixer_gui.services.media_repository import MediaRepository
from video_audio_mixer_gui.services.mix_planner import MixPlanner
from video_audio_mixer_gui.services.task_executor import TaskExecutor
from video_audio_mixer_gui.services.preview_controller import PreviewController, PreviewSection
from video_audio_mixer_gui.dragdrop.file_collector import collect_media_from_paths


def run_app() -> None:
    """启动应用。"""

    config: AppConfig = load_config()
    app = QtWidgets.QApplication([])

    logger = RichLogger()
    repository = MediaRepository(
        enable_limiter_default=config.enable_limiter,
        default_output_dir=config.output_directory,
    )
    if config.override_original:
        repository.set_override_original(True)
    planner = MixPlanner()
    ffmpeg_adapter = FFmpegAdapter()
    executor = TaskExecutor(ffmpeg_adapter=ffmpeg_adapter, logger=logger, max_workers=config.max_workers)
    preview_controller = PreviewController(planner=planner, adapter=ffmpeg_adapter, logger=logger)

    window = MainWindow(app_config=config)

    def handle_import(result) -> None:
        repository.register_import(result)
        sessions = repository.list_sessions()
        window.set_video_sessions(sessions)
        warning = repository.last_unmatched_warning()
        if warning:
            window.show_warning(warning)
        current_id = window.current_video_id
        if current_id:
            session = repository.get_session(current_id)
            window.set_audio_clips(current_id, session.audio_clips, session.video_clip.fps)

    window.mediaImported.connect(handle_import)

    def on_session_selected(video_id: str) -> None:
        session = repository.get_session(video_id)
        window.set_audio_clips(video_id, session.audio_clips, session.video_clip.fps)

    def on_video_delete(video_id: str) -> None:
        repository.remove_video(video_id)
        window.set_video_sessions(repository.list_sessions())
        window.clear_selection()

    def on_audio_delete(video_id: str, audio_id: str) -> None:
        repository.remove_audio(video_id, audio_id)
        session = repository.get_session(video_id)
        window.set_audio_clips(video_id, session.audio_clips, session.video_clip.fps)

    def on_audio_parameters_changed(video_id: str, audio_id: str, start_seconds: float, source_offset: float) -> None:
        session = repository.get_session(video_id)
        repository.update_audio_parameters(video_id, audio_id, start_seconds, source_offset, session.video_clip.fps)
        window.set_audio_clips(video_id, session.audio_clips, session.video_clip.fps)

    def on_global_config_changed(
        random_enabled: bool,
        retry_limit: int,
        seed: int,
        music_offset: float,
        video_lead: float,
        enable_limiter: bool,
        output_directory: Path,
        override_original: bool,
    ) -> None:
        config.music_random_enabled = random_enabled
        config.music_retry_limit = retry_limit
        config.music_default_seed = seed if seed >= 0 else None
        config.music_start_offset = music_offset
        config.video_audio_lead = video_lead
        config.enable_limiter = enable_limiter
        repository.set_default_enable_limiter(enable_limiter)
        config.output_directory = output_directory
        repository.set_default_output_dir(output_directory)
        config.override_original = override_original
        repository.set_override_original(override_original)
        save_config(config)

    def on_audio_dropped(paths: list[Path], category: AudioCategory) -> None:
        current_id = window.current_video_id
        if not current_id:
            return
        import_result = collect_media_from_paths(paths)
        if import_result.audios:
            for clip in import_result.audios:
                repository.add_audio_to_video(current_id, clip, category)
            session = repository.get_session(current_id)
            window.set_audio_clips(current_id, session.audio_clips, session.video_clip.fps)
        if import_result.errors or import_result.warnings:
            msgs = import_result.errors + import_result.warnings
            window.show_warning("\n".join(msgs))

    def on_batch_audio_selected(video_ids: list[str], category: AudioCategory, paths: list[Path]) -> None:
        import_result = collect_media_from_paths(paths)
        audio_clips = import_result.audios
        if not audio_clips:
            if import_result.errors or import_result.warnings:
                msgs = import_result.errors + import_result.warnings
                window.show_warning("\n".join(msgs))
            return
        for video_id in video_ids:
            for clip in audio_clips:
                repository.add_audio_to_video(video_id, replace(clip), category)
            session = repository.get_session(video_id)
            window.set_audio_clips(video_id, session.audio_clips, session.video_clip.fps)
        window.set_video_sessions(repository.list_sessions())
        if import_result.errors or import_result.warnings:
            msgs = import_result.errors + import_result.warnings
            window.show_warning("\n".join(msgs))

    def on_mix(video_id: str) -> None:
        session = repository.get_session(video_id)
        plan = planner.build_plan(session)
        executor_job = executor.submit_plan(plan, session.target_output)
        executor_job.add_done_callback(lambda _future: preview_controller.cleanup())

    def on_preview(video_id: str) -> None:
        session = repository.get_session(video_id)
        section = PreviewSection(start=0.0, duration=config.preview_duration)
        preview_controller.preview(session, section)

    window.sessionSelected.connect(on_session_selected)
    window.videoDeleteRequested.connect(on_video_delete)
    window.audioDeleteRequested.connect(on_audio_delete)
    window.audioParametersChanged.connect(on_audio_parameters_changed)
    window.globalConfigChanged.connect(on_global_config_changed)
    window.audioFilesDropped.connect(on_audio_dropped)
    window.batchAudioSelected.connect(on_batch_audio_selected)
    window.mixRequested.connect(on_mix)
    window.previewRequested.connect(on_preview)

    def cleanup_on_exit() -> None:
        preview_controller.cleanup()

    app.aboutToQuit.connect(cleanup_on_exit)

    window.show()
    app.exec()
