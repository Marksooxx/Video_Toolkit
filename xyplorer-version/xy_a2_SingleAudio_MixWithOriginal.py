# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse

# --- 配置区 ---
SCRIPT_NAME = "xy_SingleAudio_MixWithOriginal"
SCRIPT_VERSION = "1.0.0"
MAX_WORKERS = os.cpu_count() or 4
OUTPUT_MIX_DIR = "~mix"   # Folder name in current directory
DEFAULT_ENCODING = 'utf-8'
VIDEO_EXTENSIONS = ['.mp4', '.mov', '.mkv', '.avi', '.flv'] # Supported video formats

# --- 日志配置 ---
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
log_formatter = logging.Formatter(f'[{SCRIPT_NAME} v{SCRIPT_VERSION}] [%(levelname)s] %(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_formatter)
try:
    if hasattr(console_handler.stream, 'reconfigure'):
        console_handler.stream.reconfigure(encoding=DEFAULT_ENCODING, errors='replace')
except Exception as e:
    logging.warning(f"无法自动配置控制台流编码: {e}。请确保您的环境支持UTF-8。")
if not root_logger.hasHandlers():
    root_logger.addHandler(console_handler)

# --- 核心函数 ---

def run_command(cmd, command_name="外部命令"):
    """执行外部命令并捕获其输出的通用函数。"""
    logging.debug(f"正在执行 {command_name} 命令: {' '.join(cmd)}")
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding=DEFAULT_ENCODING, errors='replace', creationflags=creationflags
        )
        stdout, stderr = process.communicate()
        return_code = process.poll()

        if stdout: logging.debug(f"{command_name} 标准输出:\n{stdout.strip()}")
        if stderr: logging.debug(f"{command_name} 标准错误输出:\n{stderr.strip()}")

        if return_code != 0:
            logging.error(f"{command_name} 命令执行失败，返回码: {return_code}")
            if stderr and not stdout:
                logging.error(f"错误详情 (标准错误输出): {stderr.strip()}")
            elif stderr:
                 logging.error(f"(更详细的错误信息可能在DEBUG日志中)")
        else:
            logging.debug(f"{command_name} 命令执行成功。")
        return return_code, stdout, stderr
    except FileNotFoundError:
        logging.error(f"{command_name} 命令 '{cmd[0]}' 未找到。请确保 FFmpeg/FFprobe 已安装并配置在系统PATH中。")
        return None, None, None
    except Exception as e:
        logging.error(f"执行 {command_name} 时发生未知异常: {e}")
        logging.error(traceback.format_exc())
        return None, None, None

def run_ffprobe(input_file, show_entries, stream_type='v', stream_index=0, format_option='default=noprint_wrappers=1:nokey=1'):
    """使用 ffprobe 获取媒体文件信息。"""
    cmd = ['ffprobe', '-v', 'error', '-select_streams', f'{stream_type}:{stream_index}',
           '-show_entries', show_entries, '-of', format_option, input_file]
    return_code, stdout, stderr = run_command(cmd, "ffprobe")
    return stdout.strip() if return_code == 0 and stdout is not None else None

def run_ffmpeg_command(command_list):
    """执行 ffmpeg 命令，返回 True 表示成功，False 表示失败。"""
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y'] + command_list
    return_code, _, _ = run_command(cmd, "ffmpeg")
    return return_code == 0

def find_corresponding_video(audio_file_path):
    """根据音频文件路径，在上一级目录查找对应的视频文件。"""
    audio_filename = os.path.basename(audio_file_path)
    audio_name_no_ext = os.path.splitext(audio_filename)[0]
    search_dir = os.path.dirname(os.path.dirname(os.path.abspath(audio_file_path)))
    
    logging.debug(f"正在目录 '{search_dir}' 中为音频 '{audio_filename}' 查找视频...")
    for entry in os.listdir(search_dir):
        entry_path = os.path.join(search_dir, entry)
        if os.path.isfile(entry_path):
            video_name_no_ext, video_ext = os.path.splitext(entry)
            if video_ext.lower() in VIDEO_EXTENSIONS and video_name_no_ext in audio_name_no_ext:
                logging.info(f"为音频 '{audio_filename}' 找到匹配的视频: '{entry}'")
                return entry_path
    logging.warning(f"在 '{search_dir}' 中未找到与音频 '{audio_filename}' 匹配的视频文件。")
    return None

def process_audio_task(audio_file):
    """
    处理单个音频文件的任务 (与原视频音频混合)。
    输出时长为视频和新音频中较长者。
    返回 'success', 'skipped', or 'failed'。
    """
    task_id = os.path.basename(audio_file)
    logging.info(f"--- [任务 {task_id}] 开始处理 (模式: 音频混合) ---")
    
    abs_audio_file = os.path.abspath(audio_file)
    video_file = find_corresponding_video(abs_audio_file)

    if not video_file:
        logging.warning(f"[任务 {task_id}] 跳过 - 未找到对应的视频文件。")
        return 'skipped'

    abs_video_file = os.path.abspath(video_file)
    video_task_id = os.path.basename(video_file)
    video_name_no_ext = os.path.splitext(video_task_id)[0]
    
    output_dir = os.path.abspath(OUTPUT_MIX_DIR)
    output_file = os.path.join(output_dir, video_task_id)

    temp_black_video, temp_concat_video, list_file_path = None, None, None
    status_to_return = 'failed'

    try:
        logging.info(f"[任务 {task_id}] 开始获取媒体信息...")
        video_duration_str = run_ffprobe(abs_video_file, 'format=duration')
        new_audio_duration_str = run_ffprobe(abs_audio_file, 'format=duration')
        original_audio_exists = run_ffprobe(abs_video_file, 'format=duration', stream_type='a') is not None

        if not original_audio_exists:
            logging.warning(f"[任务 {task_id}] 原始视频不含音轨，将执行替换操作而非混合。")

        if video_duration_str is None or new_audio_duration_str is None:
            logging.error(f"[任务 {task_id}] 无法获取视频或新音频的时长。标记为失败。")
            return status_to_return

        video_duration, new_audio_duration = float(video_duration_str), float(new_audio_duration_str)
        logging.info(f"[任务 {task_id}] 视频时长: {video_duration:.3f}秒, 新音频时长: {new_audio_duration:.3f}秒")

        duration_tolerance = 0.1
        video_input_for_mix = abs_video_file
        final_mix_cmd = []

        if new_audio_duration > video_duration + duration_tolerance:
            duration_diff = new_audio_duration - video_duration
            logging.info(f"[任务 {task_id}] 新音频比视频长约 {duration_diff:.3f}秒，将生成黑场以延长视频。")

            video_width_str, video_height_str, video_fps_str = (run_ffprobe(abs_video_file, 'stream=width', 'v', 0, 'csv=p=0'),
                                                               run_ffprobe(abs_video_file, 'stream=height', 'v', 0, 'csv=p=0'),
                                                               run_ffprobe(abs_video_file, 'stream=r_frame_rate', 'v', 0))

            if not all([video_width_str, video_height_str, video_fps_str]):
                logging.error(f"[任务 {task_id}] 获取视频属性失败。标记为失败。")
                return status_to_return

            video_width, video_height = int(video_width_str), int(video_height_str)
            if '/' in video_fps_str: num, den = map(float, video_fps_str.split('/')); video_fps = num / den if den != 0 else 30
            else: video_fps = float(video_fps_str)

            temp_black_video = os.path.join(output_dir, f"temp_black_{video_name_no_ext}_{int(time.time())}.mp4")
            temp_concat_video = os.path.join(output_dir, f"temp_concat_{video_name_no_ext}_{int(time.time())}.mp4")
            list_file_path = os.path.join(output_dir, f"temp_list_{video_name_no_ext}_{int(time.time())}.txt")

            black_cmd = ['-f', 'lavfi', '-i', f'color=c=black:s={video_width}x{video_height}:d={duration_diff:.6f}', '-r', str(video_fps), '-pix_fmt', 'yuv420p', temp_black_video]
            if not run_ffmpeg_command(black_cmd): return status_to_return

            with open(list_file_path, 'w', encoding='utf-8') as f: f.write(f"file '{abs_video_file.replace('\\', '/')}'\nfile '{temp_black_video.replace('\\', '/')}'\n")
            concat_cmd = ['-f', 'concat', '-safe', '0', '-i', list_file_path, '-c', 'copy', temp_concat_video]
            if not run_ffmpeg_command(concat_cmd): return status_to_return

            video_input_for_mix = temp_concat_video
            logging.info(f"[任务 {task_id}] 视频已成功延长。")

            if original_audio_exists:
                final_mix_cmd = ['-i', video_input_for_mix, '-i', abs_audio_file, '-i', abs_video_file,
                                 '-filter_complex', '[2:a][1:a]amix=inputs=2:duration=longest[a_mix]',
                                 '-map', '0:v:0', '-map', '[a_mix]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', output_file]
            else: # No original audio, so just replace
                final_mix_cmd = ['-i', video_input_for_mix, '-i', abs_audio_file, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', output_file]
        else:
            logging.info(f"[任务 {task_id}] 新音频时长不长于视频。 ")
            if original_audio_exists:
                final_mix_cmd = ['-i', video_input_for_mix, '-i', abs_audio_file,
                                 '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=longest[a_mix]',
                                 '-map', '0:v:0', '-map', '[a_mix]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', output_file]
            else: # No original audio, so just replace
                final_mix_cmd = ['-i', video_input_for_mix, '-i', abs_audio_file, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', output_file]

        logging.info(f"[任务 {task_id}] 开始混合音频...")
        if run_ffmpeg_command(final_mix_cmd):
            final_duration_str = run_ffprobe(output_file, 'format=duration')
            logging.info(f"[任务 {task_id}] ✅ 音频混合成功，已输出到: {output_file} (最终时长: {final_duration_str}秒)")
            status_to_return = 'success'
        else:
            logging.error(f"[任务 {task_id}] ❌ 最终混合失败。")

        return status_to_return

    except Exception as e:
        logging.error(f"[任务 {task_id}] ❌ 处理过程中发生意外错误: {e}")
        logging.error(traceback.format_exc())
        return 'failed'

    finally:
        for f_path in [temp_black_video, temp_concat_video, list_file_path]:
            if f_path and os.path.exists(f_path):
                try: os.remove(f_path); logging.debug(f"[任务 {task_id}] 已删除临时文件: {f_path}")
                except OSError as e: logging.warning(f"[任务 {task_id}] 删除临时文件失败: {f_path}, 错误: {e}")
        logging.info(f"--- [任务 {task_id}] 处理结束 (最终状态: {status_to_return.upper()}) ---")

def main():
    parser = argparse.ArgumentParser(description=f'{SCRIPT_NAME} v{SCRIPT_VERSION} - 接收音频文件，并将其与匹配视频的原始音轨混合。')
    parser.add_argument('files', nargs='*', help='一个或多个要处理的音频文件路径。')
    args = parser.parse_args()

    start_time = time.time()
    logging.info("="*20 + f" {SCRIPT_NAME} v{SCRIPT_VERSION} 开始执行 " + "="*20)
    logging.info("模式: 音频混合。输出时长将是视频和新音频中较长的一个。 ")

    abs_output_mix_dir = os.path.abspath(OUTPUT_MIX_DIR)
    try: os.makedirs(abs_output_mix_dir, exist_ok=True)
    except OSError as e: logging.error(f"创建输出目录失败: {e}。脚本终止。"); return

    audio_files = args.files
    if not audio_files: logging.warning("未提供任何文件进行处理。"); return
    
    total_tasks = len(audio_files)
    logging.info(f"共收到 {total_tasks} 个待处理的音频文件。 ")

    completed_tasks, skipped_tasks, failed_tasks = 0, 0, 0

    logging.info(f"开始使用最多 {MAX_WORKERS} 个线程进行处理...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_audio = {executor.submit(process_audio_task, f): f for f in audio_files}
        for future in as_completed(future_to_audio):
            try:
                status = future.result()
                if status == 'success': completed_tasks += 1
                elif status == 'skipped': skipped_tasks += 1
                else: failed_tasks += 1
            except Exception as e:
                logging.error(f"任务执行时出现未捕获的异常: {e}")
                failed_tasks += 1
            
            processed_count = completed_tasks + skipped_tasks + failed_tasks
            logging.info(f"进度: {processed_count}/{total_tasks} | ✅成功: {completed_tasks} | ⏩跳过: {skipped_tasks} | ❌失败: {failed_tasks}")

    duration = time.time() - start_time
    logging.info("-