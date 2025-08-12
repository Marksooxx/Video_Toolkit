#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频颜色通道转换脚本
功能：遍历当前文件夹所有视频文件，应用RGBA→BGRA颜色滤镜
作者：Claude
"""

import os
import subprocess
import tempfile
import shutil
from pathlib import Path

# 支持的视频文件扩展名
VIDEO_EXTENSIONS = {
    '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', 
    '.m4v', '.3gp', '.ts', '.mts', '.m2ts', '.vob', '.mpg', 
    '.mpeg', '.divx', '.xvid', '.asf', '.rm', '.rmvb'
}

def is_video_file(file_path):
    """检查文件是否为视频文件"""
    return file_path.suffix.lower() in VIDEO_EXTENSIONS

def convert_video(input_path, output_path):
    """
    转换单个视频文件
    
    Args:
        input_path (Path): 输入文件路径
        output_path (Path): 输出文件路径
    
    Returns:
        bool: 转换是否成功
    """
    try:
        # 构建ffmpeg命令
        cmd = [
            'ffmpeg',
            '-i', str(input_path),
            # 滤镜链：先转为rgba交换通道，再转为yuv420p以获得最佳兼容性
            '-vf', 'format=rgba,colorchannelmixer=rr=0:rg=0:rb=1:ra=0:gr=0:gg=1:gb=0:ga=0:br=1:bg=0:bb=0:ba=0:ar=0:ag=0:ab=0:aa=1,format=yuv420p',
            '-c:v', 'libx264',  # 指定视频编码器为H.264，提高兼容性
            '-c:a', 'copy',  # 音频直接复制，不重编码
            '-y',  # 覆盖输出文件
            str(output_path)
        ]
        
        print(f"  変換中: {input_path.name}")
        
        # 执行ffmpeg命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        
        if result.returncode == 0:
            print(f"  ✓ 変換成功: {input_path.name}")
            return True
        else:
            print(f"  ✗ 変換失敗: {input_path.name}")
            print(f"    エラーメッセージ: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"  ✗ 変換がタイムアウトしました: {input_path.name}")
        return False
    except Exception as e:
        print(f"  ✗ 変換中に例外が発生しました: {input_path.name} - {str(e)}")
        return False

def process_videos(directory=None):
    """
    处理指定目录下的所有视频文件
    
    Args:
        directory (str, optional): 目录路径，默认为当前目录
    """
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory)
    
    if not directory.exists():
        print(f"✗ ディレクトリが存在しません: {directory}")
        return
    
    print(f"ディレクトリをスキャン中: {directory}")
    
    # 查找所有视频文件
    video_files = [f for f in directory.iterdir() 
                   if f.is_file() and is_video_file(f)]
    
    if not video_files:
        print("動画ファイルが見つかりませんでした")
        return
    
    print(f"{len(video_files)} 個の動画ファイルが見つかりました\n")
    
    success_count = 0
    failed_count = 0
    
    for i, video_file in enumerate(video_files, 1):
        print(f"[{i}/{len(video_files)}] ファイルを処理中: {video_file.name}")
        
        try:
            # 创建临时文件 - 使用原文件名 + _temp
            temp_path = video_file.with_stem(video_file.stem + '_temp')
            
            # 转换视频
            if convert_video(video_file, temp_path):
                # 转换成功，替换原文件
                if temp_path.exists() and temp_path.stat().st_size > 0:
                    # 备份原文件名
                    backup_path = video_file.with_suffix(video_file.suffix + '.backup')
                    
                    # 重命名原文件为备份
                    video_file.rename(backup_path)
                    
                    try:
                        # 将临时文件重命名为原文件名
                        temp_path.rename(video_file)
                        
                        # 删除备份文件
                        backup_path.unlink()
                        
                        print(f"  ✓ ファイルが更新されました: {video_file.name}")
                        success_count += 1
                        
                    except Exception as e:
                        # 如果重命名失败，恢复原文件
                        backup_path.rename(video_file)
                        print(f"  ✗ ファイルの更新に失敗したため、元に戻しました: {video_file.name} - {str(e)}")
                        failed_count += 1
                        
                        # 清理临时文件
                        if temp_path.exists():
                            temp_path.unlink()
                else:
                    print(f"  ✗ 変換後のファイルが無効です: {video_file.name}")
                    failed_count += 1
            else:
                failed_count += 1
                
        except Exception as e:
            print(f"  ✗ ファイルの処理中に例外が発生しました: {video_file.name} - {str(e)}")
            failed_count += 1
            
        finally:
            # 清理可能残留的临时文件
            if 'temp_path' in locals() and temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass
        
        print()  # 添加空行分隔
    
    # 输出处理结果
    print("=" * 50)
    print(f"処理完了！ 成功: {success_count}, 失敗: {failed_count}")
    print("=" * 50)

def main():
    """主函数"""
    print("動画カラーチャンネル変換ツール (RGBA → BGRA)")
    print("=" * 50)
    
    # 获取当前目录
    current_dir = Path.cwd()
    print(f"現在の作業ディレクトリ: {current_dir}")
    print("動画ファイルの処理を開始します...")
    print("-" * 50)
    
    try:
        process_videos()
        print("\nすべてのファイルの処理が完了しました！")
        
    except KeyboardInterrupt:
        print("\n\nユーザーによって操作が中断されました")
        
    except Exception as e:
        print(f"\nプログラムでエラーが発生しました: {str(e)}")
    
    input("\nエンターキーを押して終了します...")

if __name__ == "__main__":
    main()