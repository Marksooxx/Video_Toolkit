#!/usr/bin/env python3
# -*- coding: utf-8 -*-"""
视频颜色通道转换脚本 (参数版本)
功能：处理通过命令行参数传入的视频文件，应用RGBA→BGRA颜色滤镜
"""

import os
import sys
import subprocess
import argparse
import logging
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 配置区 ---
SCRIPT_NAME = "xy_RGBA_to_BGRA"
SCRIPT_VERSION = "1.0.0"
MAX_WORKERS = os.cpu_count() or 4
DEFAULT_ENCODING = 'utf-8'

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format=f'[{SCRIPT_NAME} v{SCRIPT_VERSION}] [%(levelname)s] %(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', stream=sys.stdout)

def run_ffmpeg_command(cmd_list):
    """执行FFmpeg命令并处理输出。"""
    logging.debug(f"Executing FFmpeg command: {' '.join(cmd_list)}")
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        result = subprocess.run(
            cmd_list, capture_output=True, text=True, encoding=DEFAULT_ENCODING,
            errors='replace', timeout=600, creationflags=creationflags
        )
        if result.returncode != 0:
            logging.error(f"FFmpeg执行失败。返回码: {result.returncode}")
            logging.error(f"FFmpeg 错误输出:\n{result.stderr.strip()}")
            return False
        return True
    except FileNotFoundError:
        logging.error("错误: 'ffmpeg' 命令未找到。请确保FFmpeg已安装并位于系统PATH中。")
        return False
    except subprocess.TimeoutExpired:
        logging.error("FFmpeg命令执行超时。")
        return False
    except Exception as e:
        logging.error(f"执行FFmpeg时发生未知异常: {e}")
        return False

def process_single_video(video_path):
    """
    转换单个视频文件，并安全地替换它。
    返回 'success', 'failed'。
    """
    task_id = os.path.basename(video_path)
    logging.info(f"--- [任务 {task_id}] 开始处理 ---")
    
    video_file = Path(video_path)
    temp_path = None
    backup_path = None

    try:
        # 创建临时文件路径
        temp_path = video_file.with_stem(video_file.stem + f'_temp_{int(time.time())}')

        # 构建ffmpeg命令
        cmd = [
            'ffmpeg',
            '-i', str(video_file),
            '-vf', 'format=rgba,colorchannelmixer=rr=0:rg=0:rb=1:ra=0:gr=0:gg=1:gb=0:ga=0:br=1:bg=0:bb=0:ba=0:ar=0:ag=0:ab=0:aa=1,format=yuv420p',
            '-c:v', 'libx264',
            '-c:a', 'copy',
            '-y',
            str(temp_path)
        ]
        
        logging.info(f"[任务 {task_id}] 正在转换颜色通道...")
        if not run_ffmpeg_command(cmd):
            logging.error(f"[任务 {task_id}] ❌ 转换失败。")
            return 'failed'

        if not temp_path.exists() or temp_path.stat().st_size == 0:
            logging.error(f"[任务 {task_id}] ❌ 转换后的文件无效或为空。")
            return 'failed'

        # 安全地替换原文件
        logging.info(f"[任务 {task_id}] 转换成功，正在替换原文件...")
        backup_path = video_file.with_suffix(video_file.suffix + '.bak')
        
        # 1. 将原文件重命名为备份
        os.rename(video_file, backup_path)
        
        try:
            # 2. 将临时文件重命名为原文件名
            os.rename(temp_path, video_file)
            # 3. 删除备份
            os.remove(backup_path)
            logging.info(f"[任务 {task_id}] ✅ 文件更新成功。")
            return 'success'
        except Exception as e:
            logging.error(f"[任务 {task_id}] ❌ 替换文件时出错: {e}。正在从备份恢复...", exc_info=True)
            # 如果替换失败，则恢复备份
            if not video_file.exists():
                os.rename(backup_path, video_file)
            return 'failed'

    except Exception as e:
        logging.error(f"[任务 {task_id}] ❌ 处理过程中发生意外错误: {e}", exc_info=True)
        return 'failed'
    finally:
        # 清理临时文件和可能的残留备份
        for p in [temp_path, backup_path]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                    logging.debug(f"[任务 {task_id}] 已清理残留文件: {p}")
                except OSError:
                    pass # 忽略清理错误
        logging.info(f"--- [任务 {task_id}] 处理结束 ---")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description=f'{SCRIPT_NAME} v{SCRIPT_VERSION} - 转换指定视频文件的颜色通道 (RGBA -> BGRA)。')
    parser.add_argument('files', nargs='*', help='一个或多个要处理的视频文件路径。')
    args = parser.parse_args()

    start_time = time.time()
    logging.info("="*20 + f" {SCRIPT_NAME} v{SCRIPT_VERSION} 开始执行 " + "="*20)

    video_files = args.files
    if not video_files:
        logging.warning("没有从命令行参数中接收到任何文件。请拖放文件到脚本上执行。")
        return

    total_tasks = len(video_files)
    logging.info(f"共收到 {total_tasks} 个待处理的视频文件。")

    completed_tasks, failed_tasks = 0, 0

    logging.info(f"开始使用最多 {MAX_WORKERS} 个线程进行处理...")
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_video = {executor.submit(process_single_video, f): f for f in video_files}

            for future in as_completed(future_to_video):
                try:
                    status = future.result()
                    if status == 'success':
                        completed_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    video_file = future_to_video[future]
                    logging.error(f"[任务 {os.path.basename(video_file)}] 执行时出现未捕获的异常: {e}", exc_info=True)
                    failed_tasks += 1
                
                processed_count = completed_tasks + failed_tasks
                progress_percent = (processed_count / total_tasks) * 100
                logging.info(f"进度: {processed_count}/{total_tasks} ({progress_percent:.2f}%) | ✅成功: {completed_tasks} | ❌失败: {failed_tasks}")

    except Exception as e:
        logging.error(f"线程池执行期间发生严重错误: {e}", exc_info=True)

    duration = time.time() - start_time
    logging.info("-