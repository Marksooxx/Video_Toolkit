# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

# --- 配置区 ---
# Changed SCRIPT_NAME to reflect the new behavior (mixing instead of replacing)
SCRIPT_NAME = "Mix_Original_And_Prefixed_Audios"
SCRIPT_VERSION = "1.0.0" # Initial version for this specific logic
MAX_WORKERS = os.cpu_count() or 4
INPUT_AUDIO_DIR = "~audio"  # Folder name in current directory
OUTPUT_MIX_DIR = "~mix"   # Folder name in current directory
DEFAULT_ENCODING = 'utf-8'

# --- 日志配置 (仅控制台 INFO) ---
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
    logging.warning(f"コンソールストリームエンコーディングを自動設定できませんでした: {e}。ご使用の環境がUTF-8をサポートしていることを確認してください。")
if not root_logger.hasHandlers():
    root_logger.addHandler(console_handler)


# --- 核心函数 (run_command, run_ffprobe, run_ffmpeg_command, find_and_mix_audio 保持不变) ---

def run_command(cmd, command_name="外部コマンド"):
    """汎用関数、外部コマンドを実行し出力をキャプチャする。"""
    logging.debug(f"{command_name} コマンドを実行中: {' '.join(cmd)}")
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding=DEFAULT_ENCODING, errors='replace', creationflags=creationflags
        )
        stdout, stderr = process.communicate()
        return_code = process.poll()

        if stdout: logging.debug(f"{command_name} 標準出力:\n{stdout.strip()}")
        if stderr:
            stderr_strip = stderr.strip()
            logging.debug(f"{command_name} 標準エラー出力:\n{stderr_strip}")
            if return_code != 0:
                 logging.error(f"{command_name} からのエラー出力 (標準エラー出力):\n{stderr_strip}")

        if return_code != 0:
            logging.error(f"{command_name} コマンドの実行に失敗しました。リターンコード: {return_code}")
        else:
            logging.debug(f"{command_name} コマンドは正常に実行されました。")
        return return_code, stdout, stderr
    except FileNotFoundError:
        logging.error(f"{command_name} コマンド '{cmd[0]}' が見つかりません。FFmpeg/FFprobeがシステムのPATHに設定されていることを確認してください。")
        return None, None, None
    except Exception as e:
        logging.error(f"{command_name} の実行中に不明な例外が発生しました: {e}")
        logging.error(traceback.format_exc())
        return None, None, None

def run_ffprobe(input_file, show_entries, stream_type='v', stream_index=0, format_option='default=noprint_wrappers=1:nokey=1'):
    """使用 ffprobe 获取媒体文件信息。"""
    cmd = ['ffprobe', '-v', 'error', '-select_streams', f'{stream_type}:{stream_index}',
           '-show_entries', show_entries, '-of', format_option, input_file]
    return_code, stdout, stderr = run_command(cmd, "ffprobe")
    if return_code == 0 and stdout is not None:
        return stdout.strip()
    else:
        # Log warning only if ffprobe actually failed, not just empty output
        if return_code != 0 or stderr:
             logging.warning(f"ffprobeが '{input_file}' の '{show_entries}' の取得に失敗しました。")
        return None # Return None for failure or empty output

def run_ffmpeg_command(command_list):
    """执行 ffmpeg 命令，返回 True 表示成功，False 表示失败。"""
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y'] + command_list
    return_code, _, _ = run_command(cmd, "ffmpeg")
    return return_code == 0

def find_and_mix_audio(video_name, audio_dir, temp_dir):
    """查找匹配的音频文件并混合成单个临时文件"""
    matching_audios = []
    suffix_to_match = f"{video_name}.wav"
    abs_audio_dir = os.path.abspath(audio_dir) # Ensure absolute path
    try:
        if not os.path.isdir(abs_audio_dir):
             logging.error(f"音声ディレクトリが存在しません: '{abs_audio_dir}'")
             return None, None
        for filename in os.listdir(abs_audio_dir):
            if filename.lower().endswith(suffix_to_match.lower()) and os.path.isfile(os.path.join(abs_audio_dir, filename)):
                 matching_audios.append(os.path.abspath(os.path.join(abs_audio_dir, filename)))
    except Exception as e:
        logging.error(f"'{abs_audio_dir}' で音声ファイルを検索中にエラーが発生しました: {e}")
        return None, None

    if not matching_audios:
        # Changed to INFO level as it's a normal case
        logging.info(f"'{video_name}' に対して、名前が '{suffix_to_match}' で終わる音声ファイルが見つかりませんでした。")
        return None, None # Indicate skipped

    logging.info(f"{len(matching_audios)} 個の外部音声ファイルが見つかりました: {', '.join([os.path.basename(f) for f in matching_audios])}")

    if len(matching_audios) == 1:
        logging.info("外部音声ファイルは1つだけなので、プリミックスは不要です。")
        return matching_audios[0], None # Return original path, no temp file to clean

    temp_combined_audio_file = os.path.abspath(os.path.join(temp_dir, f"temp_combined_{video_name}_{int(time.time())}.wav"))
    mix_cmd = []
    filter_complex_parts = []
    map_output = "[a_mix]"

    for i, audio_path in enumerate(matching_audios):
        mix_cmd.extend(['-i', audio_path])
        filter_complex_parts.append(f"[{i}:a]")

    # --- amix 音量标准化配置 ---
    # normalize=0: 禁用音量标准化。直接混合所有音轨，保留原始音量。如果混合后音量过大，可能会导致削波失真 (clipping)。
    # normalize=1 (默认): 启用音量标准化。FFmpeg会自动调整每个音轨的音量，以防止混合后的总音量超过削波阈值，这通常会导致整体音量降低。
    filter_complex_str = "".join(filter_complex_parts) + f"amix=inputs={len(matching_audios)}:duration=longest:normalize=0{map_output}"
    mix_cmd.extend(['-filter_complex', filter_complex_str])
    mix_cmd.extend(['-map', map_output])
    mix_cmd.extend(['-c:a', 'pcm_s16le', temp_combined_audio_file]) # Output intermediate WAV

    logging.info("複数の外部音声ファイルを1つの一時的な音声トラックにプリミックスしています...")
    logging.debug(f"プリミックス音声コマンド: {' '.join(['ffmpeg'] + mix_cmd)}")
    if run_ffmpeg_command(mix_cmd):
        logging.info(f"外部音声を一時ファイルに正常にプリミックスしました: {temp_combined_audio_file}")
        return temp_combined_audio_file, temp_combined_audio_file # Return path of temp file, and itself to be cleaned
    else:
        logging.error("外部音声ファイルのプリミックスに失敗しました。")
        # Attempt to clean up the potentially partially created file
        if os.path.exists(temp_combined_audio_file):
            try: os.remove(temp_combined_audio_file)
            except OSError: pass
        return None, None


# --- 修改后的 process_video_task 函数 ---
def process_video_task(video_file):
    """
    处理单个视频文件：查找、混合前缀音频，然后将结果与原视频音频混合。
    输出时长为视频和混合后音频中较长者。
    返回 'success', 'skipped', or 'failed'。
    """
    task_id = os.path.basename(video_file)
    logging.info(f"--- [タスク {task_id}] 処理開始 (ミックスモード) ---")
    video_name = os.path.splitext(task_id)[0]

    abs_audio_dir = os.path.abspath(INPUT_AUDIO_DIR)
    abs_mix_dir = os.path.abspath(OUTPUT_MIX_DIR)

    output_file = os.path.join(abs_mix_dir, task_id)
    abs_video_file = os.path.abspath(video_file)

    # --- 变量初始化 ---
    combined_external_audio_path = None # Path to the single track from external audios
    temp_external_audio_to_clean = None # Temp file from external audio mix (if any)
    temp_black_video = None
    temp_concat_video = None
    list_file_path = None
    status_to_return = 'failed'

    try:
        # --- 1. Find and Pre-Mix External Audio ---
        combined_external_audio_path, temp_external_audio_to_clean = find_and_mix_audio(
            video_name, abs_audio_dir, abs_mix_dir # Use output dir for temp files
        )

        if combined_external_audio_path is None:
            # No external audio found or error during pre-mix
            # Logging is handled inside find_and_mix_audio
            # Check if original video has audio, if not, maybe still process?
            # For now, skip if no external audio is successfully prepared.
            logging.warning(f"[タスク {task_id}] 外部音声が見つからないか、準備できませんでした。このビデオをスキップします。")
            status_to_return = 'skipped'
            return status_to_return

        # --- 2. Get Durations ---
        logging.info("ビデオとプリミックスされた外部音声の長さを取得しています...")
        video_duration_str = run_ffprobe(abs_video_file, 'format=duration')
        # Check original video for an audio stream before proceeding
        original_audio_exists = run_ffprobe(abs_video_file, 'format=duration', stream_type='a') is not None
        if original_audio_exists:
             logging.info("元のビデオに音声トラックが検出されました。")
        else:
             logging.warning("元のビデオには音声トラックがないようです。外部音声のみを使用します。")


        external_audio_duration_str = run_ffprobe(combined_external_audio_path, 'format=duration', stream_type='a')

        if video_duration_str is None or external_audio_duration_str is None:
            logging.error(f"ビデオまたはプリミックスされた外部音声の長さを取得できませんでした。失敗としてマークします。")
            return status_to_return

        try:
            video_duration = float(video_duration_str)
            external_audio_duration = float(external_audio_duration_str)
            # Determine the longer duration for potential video extension
            target_duration = max(video_duration, external_audio_duration)
            logging.info(f"ビデオの長さ: {video_duration:.3f}秒, 外部ミックス音声トラックの長さ: {external_audio_duration:.3f}秒")
            logging.info(f"目標出力長は約: {target_duration:.3f}秒")
        except ValueError:
            logging.error(f"ビデオまたは外部音声の長さの解析に失敗しました (値: V='{video_duration_str}', A='{external_audio_duration_str}')。失敗としてマークします。")
            return status_to_return

        # --- 3. Handle Duration Difference (Extend Video if Needed) ---
        duration_tolerance = 0.1
        video_input_for_final_cmd = abs_video_file # Default video input

        # Extend video only if the external audio is significantly longer
        if external_audio_duration > video_duration + duration_tolerance:
            duration_diff = external_audio_duration - video_duration
            logging.info(f"外部ミックス音声トラックはビデオより約 {duration_diff:.3f}秒長いため、ビデオを約 {external_audio_duration:.3f}秒に延長するために黒画面を生成します。")

            # --- Black screen generation ---
            video_width_str = run_ffprobe(abs_video_file, 'stream=width', 'v', 0, 'csv=p=0')
            video_height_str = run_ffprobe(abs_video_file, 'stream=height', 'v', 0, 'csv=p=0')
            video_fps_str = run_ffprobe(abs_video_file, 'stream=r_frame_rate', 'v', 0)

            if video_width_str is None or video_height_str is None or video_fps_str is None:
                logging.error(f"ビデオ属性の取得に失敗しました。黒画面を生成できません。失敗としてマークします。")
                return status_to_return
            try:
                video_width = int(video_width_str); video_height = int(video_height_str)
                if video_width <= 0 or video_height <= 0: raise ValueError("W/H <= 0")
                if '/' in video_fps_str: num, den = map(float, video_fps_str.split('/')); video_fps = num / den if den else 0
                else: video_fps = float(video_fps_str)
                if video_fps <= 0: raise ValueError("FPS <= 0")
            except ValueError as e:
                 logging.error(f"ビデオ属性の解析に失敗しました: {e}。失敗としてマークします。")
                 return status_to_return

            logging.debug(f"ビデオ属性 - 解像度: {video_width}x{video_height}, FPS: {video_fps:.3f}")

            temp_black_video = os.path.join(abs_mix_dir, f"temp_black_{video_name}_{int(time.time())}.mp4")
            temp_concat_video = os.path.join(abs_mix_dir, f"temp_concat_{video_name}_{int(time.time())}.mp4")
            list_file_path = os.path.join(abs_mix_dir, f"temp_list_{video_name}_{int(time.time())}.txt")

            black_cmd = ['-f', 'lavfi', '-i', f'color=c=black:s={video_width}x{video_height}:d={duration_diff:.6f}',
                         '-r', str(video_fps), '-pix_fmt', 'yuv420p', temp_black_video]
            logging.info(f"黒画面クリップを生成しています...")
            if not run_ffmpeg_command(black_cmd):
                logging.error(f"黒画面の生成に失敗しました。失敗としてマークします。")
                return status_to_return

            try:
                abs_orig_video_path_fmt = abs_video_file.replace('\\', '/'); abs_black_video_path_fmt = temp_black_video.replace('\\', '/')
                with open(list_file_path, 'w', encoding='utf-8') as f: f.write(f"file '{abs_orig_video_path_fmt}'\n"); f.write(f"file '{abs_black_video_path_fmt}'\n")
                logging.debug(f"リストファイルを作成しました: {list_file_path}")
            except IOError as e:
                logging.error(f"concatリストファイルの作成に失敗しました: {e}。失敗としてマークします。")
                return status_to_return

            concat_cmd = ['-f', 'concat', '-safe', '0', '-i', list_file_path, '-c', 'copy', temp_concat_video]
            logging.info(f"元のビデオと黒画面を結合しています...")
            if not run_ffmpeg_command(concat_cmd):
                logging.error(f"ビデオの結合に失敗しました。失敗としてマークします。")
                return status_to_return

            video_input_for_final_cmd = temp_concat_video # Use the extended video
            logging.info(f"ビデオは正常に約 {external_audio_duration:.3f}秒に延長されました。")
        else:
            logging.info(f"外部ミックス音声トラックの長さはビデオより長くありません。出力はビデオの長さ ({video_duration:.3f}秒) または外部音声トラックの長さ ({external_audio_duration:.3f}秒) のいずれか長い方になります。")


        # --- 4. Final Merge (Mixing Original Audio and External Audio) ---
        logging.info(f"[タスク {task_id}] 最終ミックス開始: ビデオ + 元の音声 + 外部音声...")
        final_merge_cmd = []

        if original_audio_exists:
            # Mix original audio with the combined external audio
            if video_input_for_final_cmd == temp_concat_video: # Video was extended
                # Inputs: 0=ExtendedVideo, 1=ExternalAudio, 2=OriginalVideo(for audio)
                final_merge_cmd = [
                    '-i', temp_concat_video,             # Input 0: Extended Video
                    '-i', combined_external_audio_path, # Input 1: Combined External Audio
                    '-i', abs_video_file,               # Input 2: Original Video (for audio stream)
                    # Mix Original Audio (from Input 2) and External Audio (from Input 1)
                    '-filter_complex', '[2:a][1:a]amix=inputs=2:duration=longest[a_out]',
                    '-map', '0:v:0',                    # Map video from extended video (Input 0)
                    '-map', '[a_out]',                  # Map the final mixed audio
                    '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '192k',
                    output_file
                ]
                logging.debug(f"最終ミックスコマンド (延長されたビデオ): {' '.join(['ffmpeg'] + final_merge_cmd)}")
            else: # Video was NOT extended
                # Inputs: 0=OriginalVideo, 1=ExternalAudio
                final_merge_cmd = [
                    '-i', abs_video_file,               # Input 0: Original Video (with audio)
                    '-i', combined_external_audio_path, # Input 1: Combined External Audio
                    # Mix Original Audio (from Input 0) and External Audio (from Input 1)
                    '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=longest[a_out]',
                    '-map', '0:v:0',                    # Map video from original video (Input 0)
                    '-map', '[a_out]',                  # Map the final mixed audio
                    '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '192k',
                    output_file
                ]
                logging.debug(f"最終ミックスコマンド (元のビデオ): {' '.join(['ffmpeg'] + final_merge_cmd)}")
        else:
            # Original video has no audio, just use the external audio (like replace)
            logging.warning("元のビデオに音声トラックがないため、外部音声のみを使用してマージします。")
            final_merge_cmd = [
                '-i', video_input_for_final_cmd,     # Input 0: Video (original or extended)
                '-i', combined_external_audio_path, # Input 1: Combined External Audio
                '-map', '0:v:0',                     # Map video from Input 0
                '-map', '1:a:0',                     # Map audio from Input 1 (external only)
                '-c:v', 'copy',
                '-c:a', 'aac', '-b:a', '192k',
                output_file
            ]
            logging.debug(f"最終マージコマンド (外部音声のみ): {' '.join(['ffmpeg'] + final_merge_cmd)}")


        # --- Execute Final Command ---
        if run_ffmpeg_command(final_merge_cmd):
            final_duration_str = run_ffprobe(output_file, 'format=duration')
            logging.info(f"[タスク {task_id}] 音声のミックスに成功し、出力しました: {output_file} (最終的な長さ: {final_duration_str}秒)")
            status_to_return = 'success'
        else:
            logging.error(f"[タスク {task_id}] 最終ミックスに失敗しました。失敗としてマークします。")
            # status_to_return remains 'failed'

        return status_to_return

    except Exception as e:
        logging.error(f"[タスク {task_id}] 処理中に予期せぬエラーが発生しました: {e}")
        logging.error(traceback.format_exc())
        status_to_return = 'failed'
        return status_to_return

    finally:
        # --- 5. Cleanup ---
        logging.debug(f"[タスク {task_id}] 一時ファイルのクリーンアップを開始します...")
        # Ensure temp_external_audio_to_clean is included
        files_to_remove = [temp_external_audio_to_clean, temp_black_video, temp_concat_video, list_file_path]
        for f_path in files_to_remove:
            if f_path and os.path.exists(f_path):
                try:
                    os.remove(f_path)
                    logging.debug(f"[タスク {task_id}] 一時ファイルを削除しました: {f_path}")
                except OSError as e:
                    logging.warning(f"[タスク {task_id}] 一時ファイルの削除に失敗しました: {f_path}, エラー: {e}")
        logging.info(f"--- [タスク {task_id}] 処理終了 (最終ステータス: {status_to_return.upper()}) ---")


# --- 主程序 (基本不变, 更新脚本名称和描述) ---
def main():
    start_time = time.time()
    logging.info("="*20 + f" {SCRIPT_NAME} v{SCRIPT_VERSION} 実行開始 " + "="*20)
    logging.info("モード: すべてのプレフィックスに一致する音声を検索し、元の音声とミックスしてビデオにマージします。") # Updated description
    logging.info("出力の長さは、元のビデオと外部ミックス音声のいずれか長い方になります。")

    abs_input_audio_dir = os.path.abspath(INPUT_AUDIO_DIR)
    abs_output_mix_dir = os.path.abspath(OUTPUT_MIX_DIR)

    logging.info(f"想定される音声入力ディレクトリ: {abs_input_audio_dir}")
    logging.info(f"想定されるミックス出力ディレクトリ: {abs_output_mix_dir}")

    for dir_path in [abs_input_audio_dir, abs_output_mix_dir]:
        try:
            os.makedirs(dir_path, exist_ok=True)
            logging.info(f"フォルダ '{dir_path}' の準備ができました。")
        except OSError as e:
            logging.error(f"フォルダ '{dir_path}' の作成またはアクセスに失敗しました: {e}。スクリプトを終了します。")
            return
        if not os.path.isdir(dir_path):
             logging.error(f"パス '{dir_path}' は存在しますが、フォルダではありません。スクリプトを終了します。")
             return

    try:
        current_dir = '.'
        video_files = [f for f in os.listdir(current_dir) if f.lower().endswith('.mp4') and os.path.isfile(os.path.join(current_dir, f))]
        if not video_files:
            logging.warning(f"現在のディレクトリ '{os.path.abspath(current_dir)}' にMP4ファイルが見つかりませんでした。スクリプトを終了します。")
            return
        total_tasks = len(video_files)
        logging.info(f"処理対象のMP4ファイルが合計 {total_tasks} 個見つかりました。")
    except Exception as e:
        logging.error(f"MP4ファイルの検索中にエラーが発生しました: {e}。スクリプトを終了します。")
        return

    completed_tasks = 0
    skipped_tasks = 0
    failed_tasks = 0

    logging.info(f"最大 {MAX_WORKERS} 個のスレッドを使用して処理を開始します...")
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_video = {executor.submit(process_video_task, f): f for f in video_files}

            for future in as_completed(future_to_video):
                video_file = future_to_video[future]
                task_id = os.path.basename(video_file)
                status = 'unknown'
                try:
                    status = future.result()
                    if status == 'success': completed_tasks += 1
                    elif status == 'skipped': skipped_tasks += 1
                    else: failed_tasks += 1
                except Exception as e:
                    logging.error(f"[タスク {task_id}] 結果取得時に重大な例外が発生しました: {e}")
                    logging.error(traceback.format_exc())
                    failed_tasks += 1
                    status = 'failed_exception'

                processed_count = completed_tasks + skipped_tasks + failed_tasks
                progress_percent = (processed_count / total_tasks) * 100
                status_display = status.upper() if isinstance(status, str) else '不明'
                logging.info(f"進捗: {processed_count}/{total_tasks} ({progress_percent:.2f}%) | "
                             f"成功: {completed_tasks} | スキップ: {skipped_tasks} | 失敗: {failed_tasks} | "
                             f"完了直後: {task_id} (ステータス: {status_display})")
    except Exception as e:
        logging.error(f"スレッドプールの実行中に重大なエラーが発生しました: {e}")
        logging.error(traceback.format_exc())

    logging.info("-" * 60)
    logging.info("すべてのタスク処理の試行が完了しました。")
    end_time = time.time()
    duration = end_time - start_time
    logging.info(f"検索したビデオファイルの総数: {total_tasks}")
    logging.info(f"正常に完了したタスク数: {completed_tasks}")
    logging.info(f"スキップされたタスク数 (一致する外部音声なし): {skipped_tasks}") # Updated skip reason
    logging.info(f"失敗したタスク数: {failed_tasks}")
    logging.info(f"総所要時間: {duration:.2f} 秒 ({time.strftime('%H:%M:%S', time.gmtime(duration))})")

    if failed_tasks > 0: logging.warning("処理に失敗したタスクがあります。詳細については上記のログを確認してください。")
    if skipped_tasks > 0: logging.warning("スキップされたタスクがあります (一致する外部音声ファイルが見つからなかったため)。")
    if total_tasks > 0 and completed_tasks == total_tasks and failed_tasks == 0 and skipped_tasks == 0:
        logging.info("見つかったすべてのタスクが正常に完了しました！")
    elif completed_tasks > 0 and failed_tasks == 0 and skipped_tasks == 0 :
         logging.info("正常に処理されたすべてのタスクが完了しました！")

    logging.info("="*20 + f" {SCRIPT_NAME} v{SCRIPT_VERSION} 実行終了 " + "="*20)

# --- Script Entry Point (保持不变) ---
if __name__ == "__main__":
    try:
        logging.info("依存関係 (ffmpeg, ffprobe) を確認しています...")
        try:
            ffmpeg_check_code, _, _ = run_command(['ffmpeg', '-version'], 'ffmpeg check')
            ffprobe_check_code, _, _ = run_command(['ffprobe', '-version'], 'ffprobe check')
            if ffmpeg_check_code is None or ffprobe_check_code is None:
                 logging.critical("エラー：ffmpeg または ffprobe コマンドが見つからないか、実行できません。それらがインストールされ、システムのPATH環境変数に含まれていることを確認してください。スクリプトは続行できません。")
                 sys.exit(1)
            if ffmpeg_check_code != 0 or ffprobe_check_code != 0:
                 logging.warning("ffmpeg または ffprobe のバージョン確認コマンドがゼロ以外の終了コードを返しました。潜在的な問題を示している可能性がありますが、スクリプトは続行を試みます。")
            else:
                 logging.info("依存関係の確認に成功しました: ffmpeg および ffprobe が利用可能です。")
        except Exception as check_exc:
             logging.critical(f"依存関係の確認中に予期せぬエラーが発生しました: {check_exc}。スクリプトを終了します。")
             logging.critical(traceback.format_exc())
             sys.exit(1)

        main()

    except SystemExit:
        pass
    except Exception as e:
        logging.critical(f"スクリプトのトップレベルでキャッチされない例外が発生しました: {e}")
        logging.critical(traceback.format_exc())
    finally:
        logging.shutdown()
        input("\nスクリプトの実行が完了しました。Enterキーを押して終了します...")