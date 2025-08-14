# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- 配置区 ---
SCRIPT_NAME = "Add_AudioTracks"
SCRIPT_VERSION = "1.1.0" # Final version incorporating fixes
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
# Ensure handler is added only once
if not root_logger.hasHandlers():
    root_logger.addHandler(console_handler)


# --- 核心函数 ---

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
        if stderr: logging.debug(f"{command_name} 標準エラー出力:\n{stderr.strip()}")

        if return_code != 0:
            logging.error(f"{command_name} コマンドの実行に失敗しました。リターンコード: {return_code}")
            if stderr and not stdout:
                logging.error(f"エラー詳細 (標準エラー出力): {stderr.strip()}")
            elif stderr:
                 logging.error(f"(より詳細なエラー情報はDEBUGログにある可能性があります)")
        else:
            logging.debug(f"{command_name} コマンドは正常に実行されました。")
        return return_code, stdout, stderr
    except FileNotFoundError:
        logging.error(f"{command_name} コマンド '{cmd[0]}' が見つかりません。FFmpeg/FFprobeがシステムのPATHに設定されていることを確認してください。")
        return None
    except Exception as e:
        logging.error(f"{command_name} の実行中に不明な例外が発生しました: {e}")
        logging.error(traceback.format_exc())
        return None

def run_ffprobe(input_file, show_entries, stream_type='v', stream_index=0, format_option='default=noprint_wrappers=1:nokey=1'):
    """使用 ffprobe 获取媒体文件信息。"""
    cmd = ['ffprobe', '-v', 'error', '-select_streams', f'{stream_type}:{stream_index}',
           '-show_entries', show_entries, '-of', format_option, input_file]
    result = run_command(cmd, "ffprobe")
    return result[1].strip() if result is not None and result[0] == 0 else None

def run_ffmpeg_command(command_list):
    """执行 ffmpeg 命令，返回 True 表示成功，False 表示失败。"""
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y'] + command_list
    result = run_command(cmd, "ffmpeg")
    return result is not None and result[0] == 0

def process_video_task(video_file):
    """
    处理单个视频文件的任务 (混合音频)。
    输出时长为视频和新音频中较长者。
    返回 'success', 'skipped', or 'failed'。
    """
    task_id = os.path.basename(video_file)
    logging.info(f"--- [タスク {task_id}] 処理開始 (モード: オーディオトラック追加/ミックス) ---")
    video_name = os.path.splitext(task_id)[0]
    # Use abspath directly on the configured directory names (relative to CWD)
    audio_file = os.path.abspath(os.path.join(INPUT_AUDIO_DIR, video_name + ".wav")) # Path to NEW audio
    output_file = os.path.abspath(os.path.join(OUTPUT_MIX_DIR, task_id))
    abs_video_file = os.path.abspath(video_file) # Path to ORIGINAL video

    temp_black_video = None
    temp_concat_video = None
    list_file_path = None
    status_to_return = 'failed'

    try:
        logging.debug(f"[タスク {task_id}] ビデオファイル: {abs_video_file}")
        logging.debug(f"[タスク {task_id}] 新規オーディオファイルを検索: {audio_file}") # Path now relative to CWD

        if not os.path.exists(audio_file):
            logging.warning(f"[タスク {task_id}] スキップ - 一致する新しい音声ファイルが見つかりません: {audio_file}")
            status_to_return = 'skipped'
            return status_to_return

        logging.info(f"[タスク {task_id}] 新しい音声が見つかりました。メディア情報の取得を開始します...")

        video_duration_str = run_ffprobe(abs_video_file, 'format=duration')
        new_audio_duration_str = run_ffprobe(audio_file, 'format=duration') # Duration of NEW audio

        if video_duration_str is None or new_audio_duration_str is None:
            logging.error(f"[タスク {task_id}] ビデオまたは新しい音声の長さを取得できませんでした。失敗としてマークします。")
            return status_to_return

        try:
            video_duration = float(video_duration_str)
            new_audio_duration = float(new_audio_duration_str)
            logging.info(f"[タスク {task_id}] ビデオの長さ: {video_duration:.3f}秒, 新しい音声の長さ: {new_audio_duration:.3f}秒")
        except ValueError:
            logging.error(f"[タスク {task_id}] ビデオまたは新しい音声の長さの解析に失敗しました (値: '{video_duration_str}', '{new_audio_duration_str}')。失敗としてマークします。")
            return status_to_return

        duration_tolerance = 0.1
        video_input_for_mix = abs_video_file # Default video input for the final mix command
        final_mix_cmd = []

        # Check if the NEW audio is longer than the ORIGINAL video
        if new_audio_duration > video_duration + duration_tolerance:
            duration_diff = new_audio_duration - video_duration
            logging.info(f"[タスク {task_id}] 新しい音声はビデオより約 {duration_diff:.3f}秒長いため、ビデオを約 {new_audio_duration:.3f}秒に延長するために黒画面を生成します。")

            # --- Black screen generation ---
            video_width_str = run_ffprobe(abs_video_file, 'stream=width', 'v', 0, 'csv=p=0')
            video_height_str = run_ffprobe(abs_video_file, 'stream=height', 'v', 0, 'csv=p=0')
            video_fps_str = run_ffprobe(abs_video_file, 'stream=r_frame_rate', 'v', 0)

            if video_width_str is None or video_height_str is None or video_fps_str is None:
                logging.error(f"[タスク {task_id}] ビデオ属性 (幅/高さ/フレームレート) の取得に失敗しました。黒画面を生成できません。失敗としてマークします。")
                return status_to_return

            try:
                video_width = int(video_width_str)
                video_height = int(video_height_str)
                if video_width <= 0 or video_height <= 0: raise ValueError("幅と高さは正の数でなければなりません")
                if '/' in video_fps_str:
                    num, den = map(float, video_fps_str.split('/'))
                    if den == 0: raise ValueError("フレームレートの分母はゼロであってはなりません")
                    video_fps = num / den
                else: video_fps = float(video_fps_str)
                if video_fps <= 0: raise ValueError("フレームレートは正の数でなければなりません")
            except ValueError as e:
                logging.error(f"[タスク {task_id}] ビデオ属性の解析に失敗しました: {e} (値: W='{video_width_str}', H='{video_height_str}', FPS='{video_fps_str}')。失敗としてマークします。")
                return status_to_return

            logging.debug(f"[タスク {task_id}] ビデオ属性 - 解像度: {video_width}x{video_height}, FPS: {video_fps:.3f}")

            temp_black_video = os.path.abspath(os.path.join(OUTPUT_MIX_DIR, f"temp_black_{video_name}_{int(time.time())}.mp4"))
            temp_concat_video = os.path.abspath(os.path.join(OUTPUT_MIX_DIR, f"temp_concat_{video_name}_{int(time.time())}.mp4"))
            list_file_path = os.path.abspath(os.path.join(OUTPUT_MIX_DIR, f"temp_list_{video_name}_{int(time.time())}.txt"))

            black_cmd = ['-f', 'lavfi', '-i', f'color=c=black:s={video_width}x{video_height}:d={duration_diff:.6f}',
                         '-r', str(video_fps), '-pix_fmt', 'yuv420p', temp_black_video]
            logging.info(f"[タスク {task_id}] 黒画面クリップを生成しています...")
            if not run_ffmpeg_command(black_cmd):
                logging.error(f"[タスク {task_id}] 黒画面の生成に失敗しました。失敗としてマークします。")
                return status_to_return

            try:
                abs_orig_video_path_fmt = abs_video_file.replace('\\', '/')
                abs_black_video_path_fmt = temp_black_video.replace('\\', '/')
                with open(list_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"file '{abs_orig_video_path_fmt}'\n")
                    f.write(f"file '{abs_black_video_path_fmt}'\n")
                logging.debug(f"[タスク {task_id}] リストファイルを作成しました: {list_file_path}")
            except IOError as e:
                logging.error(f"[タスク {task_id}] concatリストファイルの作成に失敗しました: {e}。失敗としてマークします。")
                return status_to_return

            concat_cmd = ['-f', 'concat', '-safe', '0', '-i', list_file_path, '-c', 'copy', temp_concat_video]
            logging.info(f"[タスク {task_id}] 元のビデオと黒画面を結合しています...")
            if not run_ffmpeg_command(concat_cmd):
                logging.error(f"[タスク {task_id}] ビデオの結合に失敗しました。失敗としてマークします。")
                return status_to_return

            video_input_for_mix = temp_concat_video # Use the extended video for mixing
            logging.info(f"[タスク {task_id}] ビデオは正常に約 {new_audio_duration:.3f}秒に延長されました。")

            # --- Final Mix Command (Extended Video) ---
            final_mix_cmd = [
                '-i', video_input_for_mix,    # Input 0 (extended video)
                '-i', audio_file,           # Input 1 (new audio)
                '-i', abs_video_file,       # Input 2 (original video for audio)
                # Mix audio from original video (2:a) and new audio (1:a). duration=longest takes the longer one.
                '-filter_complex', '[2:a][1:a]amix=inputs=2:duration=longest[a_mix]',
                '-map', '0:v:0',            # Map video from extended input (0)
                '-map', '[a_mix]',          # Map the mixed audio output
                '-c:v', 'copy',             # Copy video
                '-c:a', 'aac', '-b:a', '192k', # Encode mixed audio
                output_file
            ]
            logging.debug(f"[タスク {task_id}] Mix コマンド (拡張ビデオ): {' '.join(['ffmpeg'] + final_mix_cmd)}")

        else: # New audio is not longer than original video
            logging.info(f"[タスク {task_id}] 新しい音声の長さはビデオより長くありません ({new_audio_duration:.3f}秒 <= {video_duration:.3f}秒)。出力はビデオの長さ ({video_duration:.3f}秒) になります。")
            # --- Final Mix Command (Original Video) ---
            final_mix_cmd = [
                '-i', video_input_for_mix,    # Input 0 (original video)
                '-i', audio_file,           # Input 1 (new audio)
                # Mix audio from original video (0:a) and new audio (1:a). duration=longest takes the longer one.
                '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=longest[a_mix]',
                '-map', '0:v:0',            # Map video from original input (0)
                '-map', '[a_mix]',          # Map the mixed audio output
                '-c:v', 'copy',             # Copy video
                '-c:a', 'aac', '-b:a', '192k', # Encode mixed audio
                output_file
            ]
            logging.debug(f"[タスク {task_id}] Mix コマンド (オリジナルビデオ): {' '.join(['ffmpeg'] + final_mix_cmd)}")

        logging.info(f"[タスク {task_id}] 音声のミキシングを開始します (長さは長い方に合わせます)...")
        if run_ffmpeg_command(final_mix_cmd):
            final_duration_str = run_ffprobe(output_file, 'format=duration')
            logging.info(f"[タスク {task_id}] 音声のミキシングに成功し、出力しました: {output_file} (最終的な長さ: {final_duration_str}秒)")
            status_to_return = 'success'
        else:
            logging.error(f"[タスク {task_id}] 最終ミキシングに失敗しました。失敗としてマークします。")

        return status_to_return

    except Exception as e:
        logging.error(f"[タスク {task_id}] 処理中に予期せぬエラーが発生しました: {e}")
        logging.error(traceback.format_exc())
        status_to_return = 'failed'
        return status_to_return

    finally:
        # --- Cleanup ---
        files_to_remove = [temp_black_video, temp_concat_video, list_file_path]
        for f_path in files_to_remove:
            if f_path and os.path.exists(f_path):
                try:
                    os.remove(f_path)
                    logging.debug(f"[タスク {task_id}] 一時ファイルを削除しました: {f_path}")
                except OSError as e:
                    logging.warning(f"[タスク {task_id}] 一時ファイルの削除に失敗しました: {f_path}, エラー: {e}")
        logging.info(f"--- [タスク {task_id}] 処理終了 (最終ステータス: {status_to_return.upper()}) ---")

# --- 主程序 ---
def main():
    start_time = time.time()
    current_working_dir = Path.cwd().resolve()
    logging.info("="*20 + f" {SCRIPT_NAME} v{SCRIPT_VERSION} 実行開始 " + "="*20)
    logging.info(f"実行ディレクトリ: {current_working_dir}")
    logging.info("モード: オーディオトラック追加/ミックス。出力の長さは、元のビデオと新しい音声のいずれか長い方になります。")

    # Use os.path.abspath directly on folder names (relative to CWD)
    abs_input_audio_dir = os.path.abspath(INPUT_AUDIO_DIR)
    abs_output_mix_dir = os.path.abspath(OUTPUT_MIX_DIR)

    logging.info(f"想定される音声入力ディレクトリ: {abs_input_audio_dir}")
    logging.info(f"想定されるミックス出力ディレクトリ: {abs_output_mix_dir}")

    # Check and create directories
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

    # Find video files in current directory
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

    # --- Threaded Processing ---
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
                    logging.error(f"[タスク {task_id}] 実行中にキャッチされない例外が発生しました: {e}")
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

    # --- Final Summary ---
    logging.info("-" * 60)
    logging.info("すべてのタスク処理の試行が完了しました。")
    end_time = time.time()
    duration = end_time - start_time
    logging.info(f"処理されたビデオファイルの総数: {total_tasks}")
    logging.info(f"正常に完了したタスク数: {completed_tasks}")
    logging.info(f"スキップされたタスク数 (新しい音声なし): {skipped_tasks}")
    logging.info(f"失敗したタスク数: {failed_tasks}")
    logging.info(f"総所要時間: {duration:.2f} 秒 ({time.strftime('%H:%M:%S', time.gmtime(duration))})")

    if failed_tasks > 0: logging.warning("処理に失敗したタスクがあります。詳細については上記のログを確認してください。")
    if skipped_tasks > 0: logging.warning("スキップされたタスクがあります (対応する新しい音声ファイルが見つからなかったため)。")
    if total_tasks > 0 and completed_tasks == total_tasks and failed_tasks == 0 and skipped_tasks == 0:
        logging.info("見つかったすべてのタスクが正常に完了しました！")
    elif completed_tasks > 0 and failed_tasks == 0 and skipped_tasks == 0 :
         logging.info("正常に処理されたすべてのタスクが完了しました！") # In case some were skipped/failed

    logging.info("="*20 + f" {SCRIPT_NAME} v{SCRIPT_VERSION} 実行終了 " + "="*20)

# --- Script Entry Point ---
if __name__ == "__main__":
    try:
        # --- Dependency Check ---
        logging.info("依存関係 (ffmpeg, ffprobe) を確認しています...")
        try:
            ffmpeg_check = run_command(['ffmpeg', '-version'], 'ffmpeg check')
            ffprobe_check = run_command(['ffprobe', '-version'], 'ffprobe check')
            if ffmpeg_check is None or ffprobe_check is None:
                 logging.critical("エラー：ffmpeg または ffprobe コマンドが見つからないか、実行できません。それらがインストールされ、システムのPATH環境変数に含まれていることを確認してください。スクリプトは続行できません。")
                 sys.exit(1)
            if ffmpeg_check[0] != 0 or ffprobe_check[0] != 0:
                 logging.warning("ffmpeg または ffprobe のバージョン確認コマンドがゼロ以外の終了コードを返しました。潜在的な問題を示している可能性がありますが、スクリプトは続行を試みます。")
            else:
                 logging.info("依存関係の確認に成功しました: ffmpeg および ffprobe が利用可能です。")
        except Exception as check_exc:
             logging.critical(f"依存関係の確認中に予期せぬエラーが発生しました: {check_exc}。スクリプトを終了します。")
             logging.critical(traceback.format_exc())
             sys.exit(1)

        # --- Run Main Logic ---
        main()

    except SystemExit:
        pass # Allow clean exit after logged critical errors
    except Exception as e:
        logging.critical(f"スクリプトのトップレベルでキャッチされない例外が発生しました: {e}")
        logging.critical(traceback.format_exc())
    finally:
        logging.shutdown()
        input("\nスクリプトの実行が完了しました。Enterキーを押して終了します...")