"""混流任务执行服务。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from typing import Callable

from video_audio_mixer_gui.core.ffmpeg_adapter import FFmpegAdapter
from video_audio_mixer_gui.core.logger import RichLogger
from video_audio_mixer_gui.services.mix_planner import MixPlan


class TaskExecutor:
    """执行混流计划的服务。"""

    def __init__(self, ffmpeg_adapter: FFmpegAdapter, logger: RichLogger, max_workers: int = 4) -> None:
        self._adapter = ffmpeg_adapter
        self._logger = logger
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit_plan(self, plan: MixPlan, output_path: Path) -> Future:
        """提交混流计划到线程池。"""

        return self._executor.submit(self._run_plan, plan, output_path)

    def _run_plan(self, plan: MixPlan, output_path: Path) -> None:
        """执行混流计划。"""

        temp_paths: list[Path] = []
        video_input: Path = plan.video_input

        if plan.needs_black_extension and plan.black_clip_path and plan.concat_list_path and plan.extended_video_path:
            black_result = self._adapter.generate_black_clip(
                output_path=plan.black_clip_path,
                resolution=plan.video_resolution,
                duration=plan.black_extension_duration,
                fps=plan.video_fps,
            )
            if black_result.return_code != 0:
                self._logger.log_error(f"黑屏生成失败: {black_result.stderr}")
                return

            concat_content = (
                f"file '{plan.video_input.as_posix()}'\n"
                f"file '{plan.black_clip_path.as_posix()}'\n"
            )
            plan.concat_list_path.write_text(concat_content, encoding="utf-8")
            concat_result = self._adapter.concat_videos(
                list_file=plan.concat_list_path,
                output_path=plan.extended_video_path,
            )
            if concat_result.return_code != 0:
                self._logger.log_error(f"视频拼接失败: {concat_result.stderr}")
                return

            temp_paths.extend([plan.black_clip_path, plan.concat_list_path, plan.extended_video_path])
            video_input = plan.extended_video_path

        command: list[str] = ["-i", str(video_input)]
        for audio_path in plan.audio_inputs:
            command.extend(["-i", str(audio_path)])

        if plan.audio_filters:
            command.extend(["-filter_complex", ";".join(plan.audio_filters)])
            command.extend(["-map", "0:v:0", "-map", f"[{plan.audio_output_label}]"])
        elif plan.audio_inputs:
            command.extend(["-map", "0:v:0", "-map", "1:a:0"])
        else:
            command.extend(["-map", "0:v:0"])

        command.extend(plan.output_args)
        command.append(str(output_path))

        result = self._adapter.run_command(command)
        if result.return_code == 0:
            self._logger.log_success(f"完成混流: {output_path}")
        else:
            self._logger.log_error(f"混流失败: {output_path}\n{result.stderr}")

        for temp in temp_paths:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


