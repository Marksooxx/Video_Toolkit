### 低级设计文档 (LLD) - 视频帧截取工具

#### 1. 核心逻辑与步骤

1.  **启动程序**：执行 `main()` 函数。
2.  **获取输入**：调用 `get_user_input()` 函数，获取用户输入的视频文件路径和帧范围字符串。
3.  **验证路径**：检查输入的文件路径是否存在。
4.  **获取帧率**：调用 `get_video_frame_rate()` 函数，使用 `ffmpeg.probe` 获取视频的平均帧率。这是后续计算的关键。
5.  **解析范围**：调用 `parse_frame_range()` 函数，解析帧范围字符串，返回开始帧号和结束帧号。
6.  **生成输出路径**：调用 `generate_output_path()` 函数，根据输入路径和范围字符串创建输出文件的完整路径。
7.  **执行处理**：调用 `process_video()` 函数，并传入所有参数。
8.  **处理视频**：
    *   在 `process_video()` 内部，根据帧率和帧号计算出 `开始时间` (秒) 和 `持续时间` (秒)。
    *   构建 `ffmpeg-python` 命令，使用 `-ss` (seek to start time) 和 `-t` (duration) 参数进行截取。
    *   关键：在输出节点设置 `c='copy'` 或 `c:v='copy', c:a='copy'` 来启用流复制。
    *   使用 `try...except` 块执行 `ffmpeg.run()` 并捕获可能的 `ffmpeg.Error`。
9.  **反馈结果**：向用户打印成功或失败的消息。

#### 2. 清晰的函数定义列表

*   **`get_user_input() -> tuple[str, str]`**
    *   **功能**: 提示用户输入视频文件路径和帧范围。
    *   **参数**: 无。
    *   **返回值**: `(file_path, range_str)` 的元组。

*   **`get_video_frame_rate(file_path: str) -> float`**
    *   **功能**: 使用 `ffmpeg.probe` 读取并返回视频的平均帧率。
    *   **参数**: `file_path` - 视频文件路径。
    *   **返回值**: 视频的帧率 (浮点数)。如果无法获取，则抛出异常。

*   **`parse_frame_range(range_str: str) -> tuple[int, int | None]`**
    *   **功能**: 解析如 "10f-20f", "0-end" 等格式的字符串。
    *   **参数**: `range_str` - 用户输入的范围字符串。
    *   **返回值**: `(start_frame, end_frame)` 的元组。如果范围是到结尾，`end_frame` 为 `None`。解析失败则抛出 `ValueError`。

*   **`generate_output_path(file_path: str, range_str: str) -> str`**
    *   **功能**: 根据原文件路径和范围字符串生成输出文件路径。
    *   **参数**: `file_path`, `range_str`。
    *   **返回值**: 输出文件的完整路径字符串。

*   **`process_video(input_path: str, output_path: str, start_frame: int, end_frame: int | None, frame_rate: float)`**
    *   **功能**: 计算时间戳并执行FFmpeg流复制截取命令。
    *   **参数**: 输入/输出路径，开始/结束帧号，以及视频帧率。
    *   **返回值**: 无。执行失败则抛出 `ffmpeg.Error`。

*   **`main()`**
    *   **功能**: 主函数，协调所有步骤的执行。
    *   **参数**: 无。
    *   **返回值**: 无。

#### 3. 数据结构
*   本项目不涉及复杂的数据结构，主要使用Python内置类型如 `str`, `int`, `float`, `tuple`。

#### 4. 算法逻辑
*   **帧范围解析**: 使用正则表达式 `^(\d+)f?-(\d+f?|end)$` 匹配和提取帧范围字符串中的数字和 "end" 关键字。
*   **时间戳转换**:
    *   `start_time = start_frame / frame_rate`
    *   如果 `end_frame` 存在, `duration = (end_frame - start_frame) / frame_rate`。
    *   如果 `end_frame` 为 `None`，则不设置 `duration`，FFmpeg会一直处理到文件结尾。

#### 5. 错误处理
*   **文件未找到**: 在 `main` 函数中，使用 `os.path.exists()` 检查文件是否存在。
*   **解析错误**: `parse_frame_range` 在输入格式不匹配时抛出 `ValueError`，由 `main` 函数捕获并向用户显示。
*   **FFmpeg错误**: `process_video` 中的 `ffmpeg.run()` 调用被包裹在 `try...except ffmpeg.Error as e:` 块中。如果出错，将 `e.stderr` 解码后显示给用户，这对于调试非常有用。

#### 6. 主要逻辑的伪代码

```python
import ffmpeg
import os
import re

# ... (其他函数定义) ...

def main():
    try:
        # 1. 获取输入
        input_path, range_str = get_user_input()

        # 2. 验证路径
        if not os.path.exists(input_path):
            print(f"错误：文件 '{input_path}' 不存在。")
            return

        # 3. 获取帧率
        frame_rate = get_video_frame_rate(input_path)

        # 4. 解析范围
        start_frame, end_frame = parse_frame_range(range_str)

        # 5. 生成输出路径
        output_path = generate_output_path(input_path, range_str)

        # 6. 执行处理
        print("开始处理...")
        process_video(input_path, output_path, start_frame, end_frame, frame_rate)
        print(f"处理完成！文件已保存至: {output_path}")

    except ValueError as e:
        print(f"输入错误: {e}")
    except ffmpeg.Error as e:
        print("FFmpeg 执行失败:")
        # stderr 包含来自 ffmpeg 的原始错误信息
        print(e.stderr.decode('utf-8'))
    except Exception as e:
        print(f"发生未知错误: {e}")

```