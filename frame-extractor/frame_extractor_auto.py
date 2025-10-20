import ffmpeg
import os
import re
import sys
import subprocess
import tempfile

def get_user_input() -> tuple[str, str, bool]:
    """
    提示用户输入视频文件路径、帧范围和是否保留I帧文件。

    返回:
        一个包含 (文件路径, 帧范围字符串, 是否保留I帧文件) 的元组。
    """
    file_path = input("動画ファイルのパスを入力してください: ").strip()
    # 清除路径两端的引号(单引号或双引号)
    if (file_path.startswith('"') and file_path.endswith('"')) or \
       (file_path.startswith("'") and file_path.endswith("'")):
        file_path = file_path[1:-1]

    range_str = input("フレーム範囲を入力してください (例: 10f-20f, 10f-end, 0-end): ").strip()

    keep_iframe = input("変換した全Iフレーム中間ファイルを保持しますか? (y/n, デフォルト n): ").lower().strip()
    keep_iframe_bool = keep_iframe == 'y'

    return file_path, range_str, keep_iframe_bool

def generate_output_path(file_path: str, range_str: str) -> str:
    """
    根据原文件路径和范围字符串生成输出文件路径。
    """
    safe_range_str = range_str.replace(":", "-")
    base, ext = os.path.splitext(file_path)
    return f"{base}_{safe_range_str}_auto{ext}"

def generate_iframe_path(file_path: str) -> str:
    """
    生成全I帧中间文件的路径。
    """
    base, ext = os.path.splitext(file_path)
    return f"{base}_allIframe{ext}"

def parse_frame_range(range_str: str) -> tuple[int, int | None]:
    """
    解析如 "10f-20f", "0-end" 等格式的字符串。
    """
    if range_str.lower() == "0-end":
        return 0, None

    match = re.match(r'^(\d+)f?-(\d+f?|end)$', range_str, re.IGNORECASE)

    if not match:
        raise ValueError(f"フレーム範囲の形式が無効です: '{range_str}'。有効な形式: '10f-20f' または '10f-end'")

    start_frame = int(match.group(1))
    end_str = match.group(2)

    if end_str.lower() == 'end':
        end_frame = None
    else:
        end_frame = int(end_str.replace('f', ''))

    if end_frame is not None and start_frame >= end_frame:
        raise ValueError(f"開始フレーム ({start_frame}) は終了フレーム ({end_frame}) より小さくなければなりません。")

    return start_frame, end_frame

def get_video_properties(file_path: str) -> dict:
    """
    使用 ffmpeg.probe 读取并返回视频的关键属性。

    返回:
        一个包含 frame_rate 的字典。
    """
    try:
        probe = ffmpeg.probe(file_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if video_stream is None:
            raise RuntimeError("ファイルに動画ストリームが見つかりませんでした。")

        # 解析帧率
        frame_rate_str = video_stream['avg_frame_rate']
        if '/' in frame_rate_str:
            num, den = map(int, frame_rate_str.split('/'))
            frame_rate = num / den if den != 0 else 0
        else:
            frame_rate = float(frame_rate_str)

        if frame_rate == 0:
            raise ValueError("動画のフレームレートが0です。")

        properties = {
            'frame_rate': frame_rate
        }
        return properties

    except ffmpeg.Error as e:
        raise RuntimeError(f"ファイルの解析に失敗しました '{file_path}': {e.stderr.decode('utf-8')}")

def check_if_all_iframe(file_path: str) -> bool:
    """
    检查视频是否全部为I帧。

    返回:
        True 如果所有帧都是I帧,否则 False
    """
    print("動画のGOP構造を検出中...")

    try:
        # 使用ffprobe检查前100帧的类型
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'frame=pict_type',
            '-read_intervals', '%+#100',  # 只读取前100帧
            '-of', 'csv=p=0',
            file_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')

        if result.returncode != 0:
            print(f"警告: GOP構造を検出できません。非全Iフレーム動画と仮定します")
            return False

        frame_types = result.stdout.strip().split('\n')

        # 检查是否所有帧都是I帧
        non_i_frames = [ft for ft in frame_types if ft.upper() != 'I']

        if non_i_frames:
            print(f"検出結果: P/Bフレームが見つかりました。通常のGOP構造動画です")
            return False
        else:
            print(f"検出結果: 最初の100フレームが全てIフレームです。全Iフレーム動画の可能性があります")
            return True

    except Exception as e:
        print(f"警告: GOP検出に失敗しました ({e})。非全Iフレーム動画と仮定します")
        return False

def convert_to_all_iframe(input_path: str, output_path: str):
    """
    将视频转换为全I帧格式。
    """
    print(f"\n全Iフレーム形式への変換を開始...")
    print(f"しばらく時間がかかる場合があります。お待ちください...")

    try:
        input_stream = ffmpeg.input(input_path)

        output_options = {
            'vcodec': 'libx264',
            'g': 1,                    # GOP大小为1,每帧都是关键帧
            'crf': 18,                 # 高质量
            'preset': 'medium',
            'acodec': 'copy'           # 音频直接复制
        }

        output_stream = ffmpeg.output(input_stream, output_path, **output_options)
        output_stream.run(overwrite_output=True, quiet=True)

        print(f"✓ 全Iフレーム変換完了！")
        print(f"  中間ファイル: {output_path}")

    except ffmpeg.Error as e:
        raise RuntimeError(f"全Iフレーム変換に失敗しました: {e.stderr.decode('utf-8')}")

def extract_frames_fast(input_path: str, output_path: str, start_frame: int, end_frame: int | None, props: dict):
    """
    使用流复制模式快速截取(适用于全I帧视频)。
    """
    frame_rate = props['frame_rate']

    # 修正1帧误差
    if start_frame > 0:
        start_time = (start_frame - 1) / frame_rate
    else:
        start_time = 0

    input_stream = ffmpeg.input(input_path)

    output_options = {
        'ss': start_time,
        'vcodec': 'copy',
        'acodec': 'copy'
    }

    if end_frame is not None:
        output_options['to'] = end_frame / frame_rate

    output_stream = ffmpeg.output(input_stream, output_path, **output_options)

    print(f"\nフレーム範囲を高速抽出中...")
    output_stream.run(overwrite_output=True, quiet=True)

def main():
    """
    主函数,协调所有步骤的执行。
    """
    iframe_file_created = False
    iframe_file_path = None

    try:
        print("=" * 60)
        print("  フレーム抽出ツール - 自動モード")
        print("  - 動画のGOP構造を自動検出")
        print("  - 最適な処理方法を自動選択")
        print("=" * 60 + "\n")

        input_path, range_str, keep_iframe = get_user_input()

        if not os.path.exists(input_path):
            print(f"エラー: ファイル '{input_path}' が見つかりません。", file=sys.stderr)
            return

        print("\n動画情報を取得中...")
        properties = get_video_properties(input_path)
        print(f"フレームレート: {properties['frame_rate']:.2f} fps")

        start_frame, end_frame = parse_frame_range(range_str)

        # 检查是否为全I帧视频
        is_all_iframe = check_if_all_iframe(input_path)

        if is_all_iframe:
            print("\n✓ 動画は既に全Iフレーム形式です。高速モードで抽出します")
            source_file = input_path
        else:
            print("\n→ 正確な抽出のため、全Iフレーム形式への変換が必要です")
            iframe_file_path = generate_iframe_path(input_path)

            # 检查是否已存在全I帧文件
            if os.path.exists(iframe_file_path):
                use_existing = input(f"\n既存の全Iフレームファイルが見つかりました:\n  {iframe_file_path}\n使用しますか? (y/n, デフォルト y): ").lower().strip()
                if use_existing != 'n':
                    print("既存の全Iフレームファイルを使用します")
                    source_file = iframe_file_path
                else:
                    convert_to_all_iframe(input_path, iframe_file_path)
                    source_file = iframe_file_path
                    iframe_file_created = True
            else:
                convert_to_all_iframe(input_path, iframe_file_path)
                source_file = iframe_file_path
                iframe_file_created = True

        # 生成输出路径并执行快速截取
        output_path = generate_output_path(input_path, range_str)

        print(f"\n第 {start_frame} フレームから {'最後まで' if end_frame is None else '第 ' + str(end_frame) + ' フレームまで'} 抽出します...")
        extract_frames_fast(source_file, output_path, start_frame, end_frame, properties)

        print("\n" + "=" * 60)
        print("  ✓ 処理完了！")
        print("=" * 60)
        print(f"出力ファイル: {output_path}")

        # 处理中间文件
        if iframe_file_created:
            file_size_mb = os.path.getsize(iframe_file_path) / (1024 * 1024)
            print(f"\n中間ファイル: {iframe_file_path}")
            print(f"ファイルサイズ: {file_size_mb:.1f} MB")

            if keep_iframe:
                print("→ 全Iフレーム中間ファイルを保持しました。今後の高速抽出に使用できます")
            else:
                try:
                    os.remove(iframe_file_path)
                    print("→ 全Iフレーム中間ファイルを削除しました")
                except Exception as e:
                    print(f"警告: 中間ファイルを削除できませんでした: {e}")

    except (ValueError, RuntimeError) as e:
        print(f"\nエラー: {e}", file=sys.stderr)
    except ffmpeg.Error as e:
        print("\nFFmpeg の実行に失敗しました:", file=sys.stderr)
        print(e.stderr.decode('utf-8'), file=sys.stderr)
    except KeyboardInterrupt:
        print("\n\n操作がキャンセルされました")
        # 如果创建了中间文件且用户中断,清理中间文件
        if iframe_file_created and iframe_file_path and os.path.exists(iframe_file_path):
            try:
                os.remove(iframe_file_path)
                print(f"中間ファイルをクリーンアップしました: {iframe_file_path}")
            except:
                pass
    except Exception as e:
        print(f"\n予期しないエラーが発生しました: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
