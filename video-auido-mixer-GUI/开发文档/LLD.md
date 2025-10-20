# GUI 音视频混合工具低阶设计 (LLD)

## 1. 基础数据结构

- `VideoClip`
  - 字段：`clip_id: str`（UUID），`file_path: Path`，`display_name: str`，`duration_frames: int`，`fps: float`，`resolution: tuple[int, int]`
  - 行为：缓存 `ffprobe` 元数据，提供 `to_dict()` 供 GUI 显示。

- `AudioClip`
  - 字段：`clip_id: str`，`file_path: Path`，`category: AudioCategory (Enum: SE/VO/MUSIC)`，`start_frame: int | None`，`duration_frames: int`，`sample_rate: int`
  - 行为：计算起始时间秒数 (`start_time_seconds`)，支持随机起点配置。

- `TrackConfig`
  - 字段：`video_id: str`，`override_original: bool`，`enable_limiter: bool`，`music_random_seed: int | None`，`music_retry_limit: int`，`music_length_mode: LengthMode (Enum: MATCH_VIDEO/FIXED_SECONDS/FIXED_FRAMES)`，`music_length_value: float | int | None`

- `MixSession`
  - 字段：`session_id: str`，`video_clip: VideoClip`，`audio_clips: list[AudioClip]`，`config: TrackConfig`，`target_output: Path`
  - 行为：汇总轨道状态，提供 `requires_black_extension()`、`generate_summary()` 等实用方法。

- `ImportResult`
  - 字段：`videos: list[VideoClip]`，`audios: list[AudioClip]`，`warnings: list[str]`，`errors: list[str]`
  - 用于拖入媒体后的统一反馈。

## 2. 核心模块与函数定义

### 2.1 `dragdrop/file_collector.py`
- `collect_media_from_paths(paths: list[Path]) -> ImportResult`
  - 逻辑：遍历文件/文件夹，递归过滤扩展名（视频：`.mp4/.mov/.mkv` 等，音频：`.wav/.mp3/.flac` 等），生成 `VideoClip`/`AudioClip` 实例。
  - 错误处理：无效路径加入 `ImportResult.errors`；不支持的扩展写入 `warnings`。

### 2.2 `services/media_repository.py`
- `class MediaRepository`
  - `register_import(result: ImportResult) -> None`
  - `pair_audio_with_video(audio_clips: list[AudioClip]) -> dict[str, list[AudioClip]]`
    - 关键逻辑：参考示例代码的命名匹配（去掉前缀 `a1_` 等，大小写不敏感，匹配同名 `video_name.wav`）。
  - `get_session(video_id: str) -> MixSession`
  - `update_session_config(video_id: str, config: TrackConfig) -> None`
  - `list_sessions() -> list[MixSession]`
  - 线程安全：内部使用 `threading.RLock`。

### 2.3 `services/mix_planner.py`
- `class MixPlanner`
  - 依赖：`FFmpegProbeService`、`MediaRepository`
  - `build_plan(session: MixSession) -> MixPlan`
    - 输出结构 `MixPlan`：包含 `input_streams: list[FFmpegInput]`、`filters: list[str]`、`output_args: list[str]`、`needs_black_extension: bool`
    - 核心步骤：
      1. 计算每条音轨的起始时间：`start_seconds = start_frame / fps`（未指定则 0）。
      2. 若 `override_original=False`，保留原视频音轨，添加 `amix` 滤镜参数。
      3. `enable_limiter=True` -> 添加 `alimiter=limit=-0.3dB` 或 `dynaudnorm`，具体参数待验证。
      4. SE/VO 音轨长度超出视频 -> 标记 `needs_black_extension`。
      5. MUSIC 随机起始：
         - 使用 `Random(seed)`；调用 `randint(0, max_offset_frames)`；超过 `music_retry_limit` 仍冲突则回退到 0。
         - `music_length_mode` 若固定 -> 截取对应长度（`atrim`）。

### 2.4 `services/task_executor.py`
- `class TaskExecutor`
  - 依赖：`FFmpegAdapter`、`RichLogger`
  - `submit_plan(plan: MixPlan, session: MixSession) -> Future`
  - 内部使用 `ThreadPoolExecutor(max_workers=configured)`；执行时：
    1. 若 `plan.needs_black_extension` 调用 `FFmpegAdapter.generate_black_clip()`。
    2. 拼接临时列表 (`concat`) 后执行最终 `ffmpeg` 命令。
    3. 写入进度回调给 GUI（通过 Qt Signal）。
    4. 捕获异常 -> 输出 ❌ 日志，Future 标记失败。

### 2.5 `services/preview_controller.py`
- `class PreviewController`
  - `preview(session: MixSession, section: PreviewSection) -> None`
    - `PreviewSection` 包含 `start_seconds: float`、`duration_seconds: float`
    - 处理：
      1. 生成临时 `ffmpeg` 命令，仅截取需要区间 (`-ss` + `-t`)。
      2. 调用 `ffplay` 或生成低码率缓存后用 `QMediaPlayer` 预览。
      3. 使用单独线程启动，防止阻塞主线程。
      4. 提供取消接口 `stop_preview()`，终止进程。

### 2.6 `core/ffmpeg_adapter.py`
- `probe_video(path: Path) -> VideoMetadata`
- `probe_audio(path: Path) -> AudioMetadata`
- `generate_black_clip(video: VideoClip, duration_seconds: float) -> Path`
- `build_mix_command(plan: MixPlan, output_path: Path) -> list[str]`
- `run_command(command: list[str]) -> FFmpegResult`
  - 命令执行统一通过 `subprocess.Popen`，Windows 下设置 `CREATE_NO_WINDOW`。

### 2.7 `core/config_manager.py`
- `load_config(base_path: Path) -> AppConfig`
- `save_config(config: AppConfig) -> None`
- `resolve_runtime_path(relative: Path) -> Path`
  - 兼容 Nuitka 打包路径，优先使用 `sys._MEIPASS`。

### 2.8 `core/logger.py`
- 基于 `rich` 的 `Console`，提供：
  - `log_success(message: str)` -> ✅
  - `log_warning(message: str)` -> ⚠️
  - `log_error(message: str)` -> ❌（必要时启动 ANSI 背景色）
  - `summary(stats: RunStats)`

## 3. 算法与流程详解

### 3.1 自动配对算法（伪代码）

```
// 参考示例代码中的去前缀逻辑
normalize(name: str) -> str:
    lower = name.lower()
    for prefix in ["a1_", "a2_", "a3_", "a4_"]:
        if lower.startswith(prefix):
            lower = lower[len(prefix):]
    return Path(lower).stem

pair_audio_with_video():
    mapping = defaultdict(list)
    for audio in audio_clips:
        base = normalize(audio.file_path.name)
        for video in video_clips:
            if normalize(video.file_path.name) == base:
                mapping[video.clip_id].append(audio)
                break
    return mapping
```

### 3.2 MixPlan 生成伪代码

```
build_plan(session):
    video = session.video_clip
    audio_tracks = session.audio_clips
    config = session.config

    plan = MixPlan()
    plan.add_input(video.file_path)

    if config.override_original is False:
        plan.add_input(video.file_path, stream="audio")

    for audio in audio_tracks:
        offset_sec = (audio.start_frame or 0) / video.fps
        plan.add_input(audio.file_path, seek=offset_sec)
        plan.add_filter(f"[a{audio.clip_id}]adelay={offset_sec*1000}|{offset_sec*1000}")

    if config.enable_limiter:
        plan.add_filter("alimiter=limit=-0.3")

    if plan.total_audio_duration(SE+VO) > video.duration:
        plan.needs_black_extension = True

    plan.output_args = ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    return plan
```

### 3.3 Preview 流程

1. GUI 点击“预览”按钮后发送信号。
2. `PreviewController` 创建 `PreviewSection`（默认 10 秒，可配置）。
3. 构造命令：`ffplay -hide_banner -autoexit -ss {start} -t {duration} <temp_mix>`。
4. 如果用户设置随机音乐起点，预览调用 `MixPlanner` 的快速模式，仅对 Music 轨道应用抽样结果。
5. 预览结束后释放临时文件。

## 4. 错误处理与日志策略

- 拖入阶段：
  - 不存在路径 -> `❌` 并提示忽略。
  - 文件夹为空 -> `⚠️` 提示。
  - 不支持扩展 -> `⚠️`。

- FFmpeg 命令失败 -> 捕获 `CalledProcessError` 或非零返回码，写入详细 stderr 日志。

- 预览失败 -> GUI 弹窗 (QMessageBox) 指出错误，同时在控制台记录。

- 全局异常 -> `rich` Traceback，并写入 `logs/app_{timestamp}.log`。

## 5. GUI 信号与线程模型

- `MainWindow` 发出信号：
  - `mediaImported(ImportResult)`
  - `sessionSelected(str)`
  - `previewRequested(str, PreviewSection)`
  - `mixStarted(str)` / `mixCompleted(str, MixStatus)`

- `TaskExecutor` 在后台线程执行，使用 `QtCore.QThreadPool` 或自定义 `QThread` + `pyqtSignal` 反馈进度。

- `PreviewController` 独立线程，避免阻塞主线程，必要时使用 `QProcess`。

## 6. 配置与持久化

- `config.ini` 示例段：
  - `[general]` 默认输出目录、线程数
  - `[preview]` 默认持续时间、最大重试
  - `[music]` 默认随机种子策略

- 应用启动时加载配置，GUI 初始化控件默认值；关闭时记录用户最新设置。

## 7. 单元测试建议

- `tests/test_pairing.py`：验证各种命名情况下的音频匹配。
- `tests/test_mix_plan.py`：检查不同配置生成的 FFmpeg 参数。
- `tests/test_preview_controller.py`：在不启动真实 ffplay 的情况下模拟命令构造。
- 使用 `pytest` + `pytest-qt` 进行 GUI 交互测试（可选）。

## 8. 主要伪代码（主流程）

```
main():
    app = QApplication
    repo = MediaRepository()
    planner = MixPlanner(repo=repo, probe_service=FFmpegProbeService())
    executor = TaskExecutor(ffmpeg_adapter=FFmpegAdapter())
    previewer = PreviewController(ffmpeg_adapter=FFmpegAdapter())

    window = MainWindow(repo=repo, planner=planner, executor=executor, previewer=previewer)
    window.show()
    app.exec()

MainWindow.on_drop(paths):
    result = collect_media_from_paths(paths)
    repo.register_import(result)
    auto_pairs = repo.pair_audio_with_video(result.audios)
    update_ui_with_pairs(auto_pairs)

MainWindow.on_mix_clicked(video_id):
    session = repo.get_session(video_id)
    plan = planner.build_plan(session)
    executor.submit_plan(plan, session)

MainWindow.on_preview_clicked(video_id):
    section = build_preview_section_from_ui()
    previewer.preview(session=repo.get_session(video_id), section=section)
```


