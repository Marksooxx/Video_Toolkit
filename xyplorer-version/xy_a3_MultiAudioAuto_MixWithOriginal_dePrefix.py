# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from pathlib import Path

# --- 配置区 ---
SCRIPT_NAME = "xy_MultiAudioAuto_MixWithOriginal_dePrefix"
SCRIPT_VERSION = "1.0.0"
MAX_WORKERS = os.cpu_count() or 4
OUTPUT_MIX_DIR = "~mix"
DEFAULT_ENCODING = 'utf-8'
VIDEO_EXTENSIONS = ['.mp4', '.mov', '.mkv', '.avi', '.flv']

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format=f'[{SCRIPT_NAME} v{SCRIPT_VERSION}] [%(levelname)s] %(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', stream=sys.stdout)

# --- 核心函数 ---
def run_command(cmd, command_name="外部命令"):
    logging.debug(f"正在执行 {command_name} 命令: {' '.join(cmd)}")
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding=DEFAULT_ENCODING, errors='replace', creationflags=creationflags)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logging.error(f"{command_name} 执行失败，返回码: {process.returncode}\n{stderr.strip()}")
        return process.returncode, stdout, stderr
    except FileNotFoundError:
        logging.error(f"命令 '{cmd[0]}' 未找到。请确保 FFmpeg/FFprobe 已安装并配置在系统PATH中。")
        return -1, None, None
    except Exception as e:
        logging.error(f"执行 {command_name} 时发生未知异常: {e}")
        return -1, None, None

def run_ffprobe(input_file, show_entries, stream_type='v', stream_index=0):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', f'{stream_type}:{stream_index}', '-show_entries', show_entries, '-of', 'default=noprint_wrappers=1:nokey=1', input_file]
    ret, out, _ = run_command(cmd, "ffprobe")
    return out.strip() if ret == 0 and out else None

def run_ffmpeg_command(command_list):
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y'] + command_list
    ret, _, _ = run_command(cmd, "ffmpeg")
    return ret == 0

def find_corresponding_video_and_base_name(audio_file_path):
    audio_filename = os.path.basename(audio_file_path)
    search_dir = os.path.dirname(os.path.dirname(os.path.abspath(audio_file_path)))
    
    for entry in os.listdir(search_dir):
        video_name_no_ext, video_ext = os.path.splitext(entry)
        if video_ext.lower() in VIDEO_EXTENSIONS and audio_filename.lower().endswith(f"{video_name_no_ext.lower()}{os.path.splitext(audio_filename)[1].lower()}"):
            logging.info(f"为音频 '{audio_filename}' 找到匹配的视频: '{entry}'")
            return os.path.join(search_dir, entry), video_name_no_ext
            
    logging.warning(f"未找到与 '{audio_filename}' 匹配的视频文件。")
    return None, None

def find_and_premix_audios(base_video_name, initial_audio_path, temp_dir):
    audio_dir = os.path.dirname(initial_audio_path)
    suffix_to_match = f"{base_video_name}.wav"
    matching_audios = {os.path.abspath(initial_audio_path)} # Use a set to avoid duplicates

    for filename in os.listdir(audio_dir):
        if filename.lower().endswith(suffix_to_match.lower()):
            matching_audios.add(os.path.abspath(os.path.join(audio_dir, filename)))

    if not matching_audios:
        logging.warning(f"未找到与基础名 '{base_video_name}' 匹配的音频文件。")
        return None, None

    logging.info(f"找到 {len(matching_audios)} 个相关外部音频文件进行预混合。")

    if len(matching_audios) == 1:
        return list(matching_audios)[0], None

    temp_combined_audio_file = os.path.join(temp_dir, f"temp_premix_{base_video_name}_{int(time.time())}.wav")
    mix_cmd = []
    filter_complex_parts = []
    for i, audio_path in enumerate(matching_audios):
        mix_cmd.extend(['-i', audio_path])
        filter_complex_parts.append(f"[{i}:a]")
    
    filter_complex_str = "".join(filter_complex_parts) + f"amix=inputs={len(matching_audios)}:duration=longest:normalize=0[a_mix]"
    mix_cmd.extend(['-filter_complex', filter_complex_str, '-map', '[a_mix]', '-c:a', 'pcm_s16le', temp_combined_audio_file])

    logging.info("正在将多个外部音频预混合为单个音轨...")
    if run_ffmpeg_command(mix_cmd):
        logging.info(f"外部音频已成功预混合到: {temp_combined_audio_file}")
        return temp_combined_audio_file, temp_combined_audio_file
    else:
        logging.error("预混合外部音频失败。")
        return None, None

def process_audio_task(audio_file):
    task_id = os.path.basename(audio_file)
    logging.info(f"--- [任务 {task_id}] 开始处理 (模式: 多音频自动混合) ---")
    
    abs_audio_file = os.path.abspath(audio_file)
    output_dir = os.path.abspath(OUTPUT_MIX_DIR)
    
    video_file, base_video_name = find_corresponding_video_and_base_name(abs_audio_file)
    if not video_file:
        return 'skipped'

    abs_video_file = os.path.abspath(video_file)
    video_task_id = os.path.basename(video_file)
    output_file = os.path.join(output_dir, video_task_id)

    premixed_audio_path, temp_premix_to_clean = None, None
    temp_black_video, temp_concat_video, list_file_path = None, None, None
    status_to_return = 'failed'

    try:
        premixed_audio_path, temp_premix_to_clean = find_and_premix_audios(base_video_name, abs_audio_file, output_dir)
        if not premixed_audio_path:
            logging.error(f"[任务 {task_id}] 预混合音频失败或未找到音频。")
            return 'failed'

        video_duration_str = run_ffprobe(abs_video_file, 'format=duration')
        external_audio_duration_str = run_ffprobe(premixed_audio_path, 'format=duration', 'a')
        original_audio_exists = run_ffprobe(abs_video_file, 'format=duration', 'a') is not None

        if not all([video_duration_str, external_audio_duration_str]):
            logging.error(f"[任务 {task_id}] 无法获取视频或预混合音频的时长。")
            return status_to_return

        video_duration, external_audio_duration = float(video_duration_str), float(external_audio_duration_str)
        logging.info(f"[任务 {task_id}] 视频时长: {video_duration:.3f}s, 外部音频总时长: {external_audio_duration:.3f}s")

        video_input_for_final_cmd = abs_video_file
        if external_audio_duration > video_duration + 0.1:
            duration_diff = external_audio_duration - video_duration
            logging.info(f"[任务 {task_id}] 外部音频比视频长约 {duration_diff:.3f}秒，将生成黑场。")
            
            video_width, video_height, video_fps = (run_ffprobe(abs_video_file, 'stream=width', 'v', 0),
                                                    run_ffprobe(abs_video_file, 'stream=height', 'v', 0),
                                                    run_ffprobe(abs_video_file, 'stream=r_frame_rate', 'v', 0))
            if not all([video_width, video_height, video_fps]): return status_to_return
            if '/' in video_fps: num, den = map(float, video_fps.split('/')); video_fps = num/den if den else 30

            temp_black_video = os.path.join(output_dir, f"temp_black_{base_video_name}.mp4")
            temp_concat_video = os.path.join(output_dir, f"temp_concat_{base_video_name}.mp4")
            list_file_path = os.path.join(output_dir, f"temp_list_{base_video_name}.txt")

            run_ffmpeg_command(['-f', 'lavfi', '-i', f'color=c=black:s={video_width}x{video_height}:d={duration_diff:.6f}', '-r', str(video_fps), '-pix_fmt', 'yuv420p', temp_black_video])
            with open(list_file_path, 'w') as f: f.write(f"file '{abs_video_file.replace('\\', '/')}'\nfile '{temp_black_video.replace('\\', '/')}'\n")
            run_ffmpeg_command(['-f', 'concat', '-safe', '0', '-i', list_file_path, '-c', 'copy', temp_concat_video])
            video_input_for_final_cmd = temp_concat_video

        final_merge_cmd = []
        if original_audio_exists:
            inputs = ['-i', video_input_for_final_cmd, '-i', premixed_audio_path]
            filter_complex = '[0:a][1:a]amix=inputs=2:duration=longest[a_out]'
            maps = ['-map', '0:v:0', '-map', '[a_out]']
            if video_input_for_final_cmd == temp_concat_video: # Video was extended, need original audio
                inputs.append('-i')
                inputs.append(abs_video_file)
                filter_complex = '[2:a][1:a]amix=inputs=2:duration=longest[a_out]'
            final_merge_cmd.extend(inputs)
            final_merge_cmd.extend(['-filter_complex', filter_complex])
            final_merge_cmd.extend(maps)
        else:
            final_merge_cmd.extend(['-i', video_input_for_final_cmd, '-i', premixed_audio_path, '-map', '0:v:0', '-map', '1:a:0'])
        
        final_merge_cmd.extend(['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', output_file])

        logging.info(f"[任务 {task_id}] 开始最终混合...")
        if run_ffmpeg_command(final_merge_cmd):
            logging.info(f"[任务 {task_id}] ✅ 混合成功: {output_file}")
            status_to_return = 'success'
        else:
            logging.error(f"[任务 {task_id}] ❌ 最终混合失败。")

        return status_to_return
    finally:
        for f in [temp_premix_to_clean, temp_black_video, temp_concat_video, list_file_path]:
            if f and os.path.exists(f): os.remove(f)
        logging.info(f"--- [任务 {task_id}] 处理结束 (状态: {status_to_return.upper()}) ---")

def main():
    parser = argparse.ArgumentParser(description=f'{SCRIPT_NAME} v{SCRIPT_VERSION} - 自动查找并混合所有带前缀的音频文件到匹配的视频中。')
    parser.add_argument('files', nargs='*', help='一个或多个要处理的音频文件路径。脚本将自动查找关联文件。')
    args = parser.parse_args()

    if not args.files:
        logging.warning("未提供任何文件。请拖放至少一个音频文件到脚本上。")
        return

    start_time = time.time()
    logging.info(f"共收到 {len(args.files)} 个初始音频文件。将为每个文件触发一次独立的处理流程。")
    os.makedirs(OUTPUT_MIX_DIR, exist_ok=True)

    processed_files = set() # Track processed base names to avoid redundant work
    tasks_to_run = []
    for f in args.files:
        _, base_name = find_corresponding_video_and_base_name(f)
        if base_name and base_name not in processed_files:
            tasks_to_run.append(f)
            processed_files.add(base_name)
        elif not base_name:
             logging.warning(f"无法为 '{f}' 找到视频，跳过。")
        else:
             logging.info(f"'{f}' 的基础视频 '{base_name}' 已在处理队列中，跳过重复项。")

    total_tasks = len(tasks_to_run)
    if not total_tasks: logging.warning("没有有效的、不重复的任务可执行。"); return
    logging.info(f"去重后，将执行 {total_tasks} 个独立的处理任务。")

    completed, skipped, failed = 0, (len(args.files) - total_tasks), 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_audio = {executor.submit(process_audio_task, f): f for f in tasks_to_run}
        for future in as_completed(future_to_audio):
            status = future.result()
            if status == 'success': completed += 1
            elif status == 'skipped': skipped += 1
            else: failed += 1
            logging.info(f"进度: {completed+skipped+failed}/{total_tasks} | ✅成功: {completed} | ⏩跳过: {skipped} | ❌失败: {failed}")

    duration = time.time() - start_time
    logging.info(f"---\n所有任务处理完毕。总耗时: {duration:.2f}s\n总计: ✅成功: {completed}, ⏩跳过: {skipped}, ❌失败: {failed}\n---")

if __name__ == "__main__":
    main()
