"""预览控制器模块。"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from video_audio_mixer_gui.core.ffmpeg_adapter import FFmpegAdapter
from video_audio_mixer_gui.core.logger import RichLogger
from video_audio_mixer_gui.models.media import MixSession
from video_audio_mixer_gui.services.mix_planner import MixPlanner


@dataclass(slots=True)
class PreviewSection:
    """预览片段设置。"""

    start: float = 0.0
    duration: float = 10.0


class PreviewController:
    """负责生成预览输出并调用播放器。"""

    def __init__(
        self,
        planner: MixPlanner,
        adapter: FFmpegAdapter,
        logger: RichLogger,
    ) -> None:
        self._planner = planner
        self._adapter = adapter
        self._logger = logger
        self._active: Dict[str, _PreviewHandle] = {}

    def preview(self, session: MixSession, section: PreviewSection) -> None:
        """生成临时混流并使用 ffplay 预览。"""

        preview_dir = session.video_clip.file_path.parent
        preview_dir.mkdir(parents=True, exist_ok=True)
        temp_output = preview_dir / f"preview_{session.session_id}.mp4"

        plan = self._planner.build_plan(session)
        temp_intermediate = []
        video_input = plan.video_input

        width, height = plan.video_resolution
        if width <= 0 or height <= 0:
            width, height = session.video_clip.resolution
        if width <= 0:
            width = 1920
        if height <= 0:
            height = 1080
        fps = plan.video_fps if plan.video_fps > 0 else session.video_clip.fps
        if fps <= 0:
            fps = 25.0

        if plan.needs_black_extension and plan.black_clip_path and plan.concat_list_path and plan.extended_video_path:
            temp_intermediate.extend([plan.black_clip_path, plan.concat_list_path, plan.extended_video_path])
            result_black = self._adapter.generate_black_clip(
                output_path=plan.black_clip_path,
                resolution=(width, height),
                duration=plan.black_extension_duration,
                fps=fps,
            )
            if result_black.return_code != 0:
                self._logger.log_error(f"预览黑屏生成失败: {result_black.stderr}")
                self._cleanup_files(temp_intermediate)
                return
            plan.concat_list_path.write_text(
                f"file '{plan.video_input.as_posix()}'\nfile '{plan.black_clip_path.as_posix()}'\n",
                encoding="utf-8",
            )
            result_concat = self._adapter.concat_videos(
                list_file=plan.concat_list_path,
                output_path=plan.extended_video_path,
            )
            if result_concat.return_code != 0:
                self._logger.log_error(f"预览拼接失败: {result_concat.stderr}")
                self._cleanup_files(temp_intermediate)
                return
            video_input = plan.extended_video_path

        command = self._build_preview_command(plan, video_input, temp_output, section)

        result = self._adapter.run_command(command)
        self._cleanup_files(temp_intermediate)
        if result.return_code != 0:
            self._logger.log_error(f"预览混流失败: {result.stderr}")
            return

        ffplay_command = [
            "ffplay",
            "-autoexit",
            "-window_title",
            f"预览 - {session.video_clip.display_name}",
            str(temp_output),
        ]
        process = subprocess.Popen(ffplay_command)
        process.wait()
        try:
            temp_output.unlink(missing_ok=True)
        except OSError:
            pass

    def _build_preview_command(self, plan, video_input: Path, output_path: Path, section: PreviewSection) -> list[str]:
        command: list[str] = []
        command.extend(["-ss", f"{max(section.start, 0.0):.3f}"])
        command.extend(["-t", f"{max(section.duration, 1.0):.3f}"])
        command.extend(["-i", str(video_input)])
        for audio_path in plan.audio_inputs:
            command.extend(["-i", str(audio_path)])
        if plan.audio_filters:
            command.extend(["-filter_complex", ";".join(plan.audio_filters)])
            command.extend(["-map", "0:v:0", "-map", f"[{plan.audio_output_label}]"])
        elif plan.audio_inputs:
            command.extend(["-map", "0:v:0", "-map", "1:a:0"])
        else:
            command.extend(["-map", "0:v:0"])
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "30"])
        command.extend(["-c:a", "aac", "-b:a", "128k"])
        command.append(str(output_path))
        return command

    def _cleanup_files(self, paths: list[Path]) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup(self) -> None:
        """清理所有预览进程与临时输出（当前实现无残留）。"""
        return
