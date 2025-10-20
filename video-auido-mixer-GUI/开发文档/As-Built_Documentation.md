# As-Built 文档

## 1. 系统概览
- **项目结构**：遵循模块化分层，源码位于 `src/video_audio_mixer_gui/`，使用 PySide6 构建 GUI，核心服务独立于界面。
- **主要模块**：
  - `gui`：`MainWindow` 与自定义控件负责交互、拖放、快捷键。
  - `services`：媒体仓库、混流计划器、任务执行器、预览控制器。
  - `core`：配置管理、FFmpeg 适配器、日志封装。
  - `models`：数据类（视频、音频、会话、配置等）。
- **运行环境**：Windows 11、Python 3.11.9；FFmpeg 通过系统 PATH 调用；依赖由 `uv` 管理。

## 2. 核心功能实现
### 2.1 媒体导入与匹配
- 拖入视频/音频或文件夹时调用 `collect_media_from_paths()` 解析。
- `MediaRepository._collect_name_variants()` 同时考虑原名、去前缀（a1_/a2_/a3_/a4_）以及去后缀（-mix/_mix/-audio/_audio），实现宽松匹配。
- GUI 中 SE/VO/MUSIC 列表允许手动拖入音频，借助 `add_audio_to_video()` 将素材归类。

### 2.2 音频配置
- 音频表单支持秒/帧双向输入、音源偏移，保存时换算为帧写回仓库。
- 全局参数提供音乐随机开关、重试次数、随机种子、音乐偏移、音频全局延迟等项。
- 所有配置与 `config.ini` 同步，GUI 中变更自动保存。

### 2.3 混流与预览
- `MixPlanner` 构建 `MixPlan`，包括 `atrim`、`adelay`、`amix normalize`，并在 SE/VO 超出视频时生成黑屏延伸。
- `TaskExecutor` 在后台线程执行 FFmpeg，按需生成黑屏并拼接，再输出最终文件。
- `PreviewController` 生成短片后使用 `ffplay -autoexit` 播放，播放结束自动清理临时文件。

### 2.4 GUI 交互
- 左侧 `QTreeWidget` 显示视频编号、名称与 SE/VO/MUSIC 数量，可排序。
- 中间状态栏提示各分类是否匹配；右侧标签页展示音频列表并支持拖放。
- 提供快捷键：`Ctrl+P` 预览、`Ctrl+M` 混流、`Delete` 删除选中。

## 3. 配置与持久化
- `config.ini` 由 `AppConfig` 负责：输出目录、线程数、预览时长、音乐随机配置、音乐偏移、音频全局延迟。
- GUI 启动时加载配置，操作中随时保存。
- 文档方面：`README.md`、`ticket.md`、`As-Built_Documentation.md` 描述当前功能与进度。

## 4. 测试
- 使用 pytest (`uv run pytest`) 运行 `tests/`：
  - `test_media_repository.py`：匹配与参数更新；
  - `test_mix_planner.py`：黑屏延伸、随机音乐、normalize 参数；
  - `test_preview_controller.py`：预览命令与流程。
- `conftest.py` 将 `src` 加入 `sys.path`，确保导入成功。

## 5. 运行流程
1. `uv sync` 安装依赖。
2. `uv run python main.py` 启动 GUI。
3. 拖入视频/音频或文件夹，检查匹配状态与数量。
4. 调整音频参数、全局策略，必要时手动拖入音频。
5. 预览确认后点击“开始混流”，输出文件位于原视频目录并带 `_mix` 后缀。

## 6. 后续建议
- 准备 Nuitka 打包脚本，完善部署说明。
- 扩展用户指南/FAQ，补充命名规范与常见错误与解决方法。
- 根据反馈继续优化状态提示、日志导出等交互细节。
