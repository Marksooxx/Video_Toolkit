import ffmpeg
import os
import re
import sys

def get_user_input() -> tuple[str, str]:
    """
    提示用户输入视频文件路径和帧范围。

    返回:
        一个包含 (文件路径, 帧范围字符串) 的元组。
    """
    file_path = input("動画ファイルのパスを入力してください: ").strip()
    # 清除路径两端的引号(单引号或双引号)
    if (file_path.startswith('"') and file_path.endswith('"')) or \
       (file_path.startswith("'") and file_path.endswith("'")):
        file_path = file_path[1:-1]

    range_str = input("フレーム範囲を入力してください (例: 10f-20f, 10f-end, 0-end): ").strip()
    return file_path, range_str

def generate_output_path(file_path: str, range_str: str) -> str:
    """
    根据原文件路径和范围字符串生成输出文件路径。
    """
    safe_range_str = range_str.replace(":", "-")
    base, ext = os.path.splitext(file_path)
    return f"{base}_{safe_range_str}_fast{ext}"

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


def process_video_fast(input_path: str, output_path: str, start_frame: int, end_frame: int | None, props: dict):
    """
    使用流复制模式进行快速视频截取(仅适用于全I帧视频)。
    """
    frame_rate = props['frame_rate']

    # 修正1帧误差:用户通常指第N帧(从1开始),而时间戳计算基于0索引
    if start_frame > 0:
        start_time = (start_frame - 1) / frame_rate
    else:
        start_time = 0

    # 为了精确剪辑,使用输出 -ss
    input_stream = ffmpeg.input(input_path)

    output_options = {
        'ss': start_time,
        'vcodec': 'copy',  # 流复制,不重新编码
        'acodec': 'copy'   # 音频也直接复制
    }

    # 如果有结束帧,计算结束时间戳
    if end_frame is not None:
        output_options['to'] = end_frame / frame_rate

    # 创建输出流
    output_stream = ffmpeg.output(input_stream, output_path, **output_options)

    # 执行命令
    print(f"ストリームコピーモードで高速抽出中... (再エンコードなし)")
    output_stream.run(overwrite_output=True, quiet=True)


def main():
    """
    主函数,协调所有步骤的执行。
    """
    try:
        input_path, range_str = get_user_input()

        if not os.path.exists(input_path):
            print(f"エラー: ファイル '{input_path}' が見つかりません。", file=sys.stderr)
            return

        print("動画情報を取得中...")
        properties = get_video_properties(input_path)
        print(f"動画情報: フレームレート={properties['frame_rate']:.2f} fps")

        start_frame, end_frame = parse_frame_range(range_str)

        output_path = generate_output_path(input_path, range_str)

        print(f"\n⚠️  注意: このスクリプトはストリームコピーモードを使用します(再エンコードなし)")
        print(f"   全Iフレーム動画のみ、フレーム単位の正確な抽出が保証されます！")
        print(f"   動画が全Iフレームでない場合は、frame_extractor.py を使用してください\n")

        print(f"第 {start_frame} フレームから {'最後まで' if end_frame is None else '第 ' + str(end_frame) + ' フレームまで'} 正確に抽出します...")
        process_video_fast(input_path, output_path, start_frame, end_frame, properties)

        print("\n処理完了！")
        print(f"ファイルを保存しました: {output_path}")
        print(f"\nヒント: 出力動画を確認して、抽出位置が正確かどうか確認してください。")

    except (ValueError, RuntimeError) as e:
        print(f"\nエラー: {e}", file=sys.stderr)
    except ffmpeg.Error as e:
        print("\nFFmpeg の実行に失敗しました:", file=sys.stderr)
        print(e.stderr.decode('utf-8'), file=sys.stderr)
    except Exception as e:
        print(f"\n予期しないエラーが発生しました: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
