# GUI 音视频混合工具高阶设计 (HLD)

## 1. 系统架构概览
- **前端 GUI 层**：基于 PySide6/Tkinter (待确认) 构建现代化桌面界面，负责媒体拖放、轨道排列、参数配置与状态反馈。
- **业务服务层**：封装媒体管理、轨道调度、混流配置生成、任务队列管理等核心逻辑。
- **基础设施层**：提供 FFmpeg 调用封装、配置读写、日志与统计汇总、UV 环境依赖管理。
- **数据持久层**：通过 `config.ini`、项目工作目录和临时缓存文件保存用户设置、混流结果与中间状态。

```
GUI 层 (View/Controller)
   │
   ├── 事件调度/命令模式（含可选预览按钮）
   │
业务服务层 (Model & Service)
   │
   ├── 媒体仓库 (MediaRepository)
   ├── 混流计划器 (MixPlanner)
   ├── 任务执行器 (JobExecutor)
   ├── 预览控制器 (PreviewController)
   │
基础设施层
   ├── FFmpegAdapter
   ├── ConfigManager
   ├── RichLogger
   └── StatsAggregator
```

## 2. 模块划分
- `gui/`
  - `main_window.py`：主窗口、拖放、轨道面板布局与信号。
  - `widgets/`：自定义控件，如轨道列表、音频片段编辑器。
- `dragdrop/`：封装文件/文件夹拖入解析逻辑，支持批量导入与过滤。
- `services/`
  - `media_repository.py`：维护视频/音频实体、轨道状态。
  - `mix_planner.py`：根据轨道、设置生成 FFmpeg 命令计划。
  - `task_executor.py`：执行混流任务，更新进度。
- `core/`
  - `ffmpeg_adapter.py`：封装命令构建、Limiter/覆盖原音等选项。
  - `config_manager.py`：负责 `config.ini` 读写，兼容打包路径。
  - `logger.py`：基于 `rich` 的统一日志与统计输出。
- `models/`
  - 定义 `VideoClip`、`AudioClip`、`MixSession`、`TrackConfig` 等数据类。
- `tests/`
  - 针对 mix 逻辑、配置解析、轨道合并的单元测试。
- `resources/`
  - 图标、默认配置、样式文件。

- GUI：采用 PySide6 (Qt6) 构建现代界面与拖放交互。
- 类型与数据结构：Python 3.11 dataclass、typing、Enum。
- 并发：`concurrent.futures.ThreadPoolExecutor` 或 `asyncio` 调度 FFmpeg。
- 配置：`configparser` 处理 `config.ini`。
- 日志与输出：`rich` 控制台渲染，配合 ANSI（备选）。
- 视频处理：系统 FFmpeg，可选引入 `ffmpeg-python` 作为命令生成辅助。

## 4. 高层数据流
1. 用户通过 GUI 拖入单个文件或整个文件夹，`DragDrop` 模块解析媒体并将符合条件的视频/音频批量导入，`MediaRepository` 创建/更新对应数据实体。
2. `MediaRepository` 参考既有示例代码的匹配策略（文件名去前缀/后缀等规则）自动为视频匹配音频文件，可在 GUI 中调整；用户随后配置轨道属性（起始帧/秒、Limiter、覆盖原声、Music 长度或随机起点）。
3. `MixPlanner` 根据当前 `MixSession` 生成执行计划：包括需要黑屏补帧、音频延迟、Limiter 参数等。
4. `TaskExecutor` 调用 `FFmpegAdapter` 逐个执行计划，实时更新 GUI 进度与控制台日志；如用户点击“预览”按钮，则 `PreviewController` 异步触发预览流程。
5. 执行过程中 `RichLogger` 收集事件，作业结束后 `StatsAggregator` 输出汇总，并留待用户按 Enter 退出。
6. GUI 根据任务状态更新界面，允许用户导出日志或重新发起混流。

## 5. 关键交互说明
- 视频与音频面板相互联动：选择某个视频时，右侧展示对应音频轨道与配置。
- Music 轨道可手动输入起始时间或选择“随机起始”，具体随机逻辑由 `MixPlanner` 根据视频长度与音乐长度计算。
- 当 SE/VO 音频时长超过视频结束时，`MixPlanner` 指示生成黑屏片段并通过 concat 拼接。
- Limiter 开关直接影响 FFmpeg `alimiter` 或 `dynaudnorm` 等滤镜参数。
- GUI 中提供预览命令区，供高级用户查看生成的 FFmpeg 命令，并提供“预览”按钮（默认关闭）；拖入文件夹时显示导入统计与自动匹配结果提示。

- Music 随机起始逻辑允许多次重试并支持种子配置，详细策略将在 LLD 中描述。
- FFmpeg 使用系统 PATH 版本，不内置二进制；需检测环境并提示用户。
- 单个项目不支持批量导出多组方案。
- 预览机制以按钮形式可选触发，默认不执行；`PreviewController` 控制预览时长、重试次数与随机种子，尽量减少对主任务的影响。


