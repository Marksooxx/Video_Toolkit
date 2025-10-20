"""配置管理模块。

负责读取与写入 `config.ini`，并在打包后仍能正确定位配置文件。
"""

from __future__ import annotations

import configparser
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CONFIG_FILE_NAME: str = "config.ini"


@dataclass(slots=True)
class AppConfig:
    """应用运行时配置。"""

    output_directory: Path
    max_workers: int
    preview_duration: float
    preview_retry_limit: int
    music_default_seed: Optional[int]
    music_random_enabled: bool
    music_retry_limit: int
    music_start_offset: float
    video_audio_lead: float
    enable_limiter: bool
    override_original: bool


def _runtime_base_path() -> Path:
    """获取运行时根目录。

    打包后 `sys._MEIPASS` 会指向临时目录。
    """

    if hasattr(sys, "_MEIPASS"):
        base_path = Path(getattr(sys, "_MEIPASS"))
    else:
        base_path = Path(__file__).resolve().parent.parent.parent
    return base_path


def resolve_runtime_path(relative: Path) -> Path:
    """解析相对路径到运行时实际路径。"""

    return _runtime_base_path() / relative


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """加载配置文件。"""

    base_dir: Path = _runtime_base_path()
    target_path: Path = config_path or (base_dir / CONFIG_FILE_NAME)

    parser = configparser.ConfigParser()
    if target_path.exists():
        parser.read(target_path, encoding="utf-8")

    general_section = parser["general"] if "general" in parser else {}
    preview_section = parser["preview"] if "preview" in parser else {}
    music_section = parser["music"] if "music" in parser else {}
    advanced_section = parser["advanced"] if "advanced" in parser else {}

    output_directory = Path(general_section.get("output_directory", "output"))
    max_workers = int(general_section.get("max_workers", "4"))
    preview_duration = float(preview_section.get("duration", "10"))
    preview_retry_limit = int(preview_section.get("retry_limit", "3"))
    music_seed_value = music_section.get("default_seed")
    music_default_seed = int(music_seed_value) if music_seed_value else None
    music_random_enabled = music_section.get("random_enabled", "true").lower() == "true"
    music_retry_limit = int(music_section.get("retry_limit", "3"))
    music_start_offset = float(music_section.get("start_offset", "0"))
    video_audio_lead = float(advanced_section.get("video_audio_lead", "0"))
    enable_limiter = advanced_section.get("enable_limiter", "true").lower() == "true"
    override_original = advanced_section.get("override_original", "false").lower() == "true"

    return AppConfig(
        output_directory=output_directory,
        max_workers=max(1, max_workers),
        preview_duration=max(1.0, preview_duration),
        preview_retry_limit=max(1, preview_retry_limit),
        music_default_seed=music_default_seed,
        music_random_enabled=music_random_enabled,
        music_retry_limit=max(1, music_retry_limit),
        music_start_offset=max(0.0, music_start_offset),
        video_audio_lead=video_audio_lead,
        enable_limiter=enable_limiter,
        override_original=override_original,
    )


def save_config(config: AppConfig, config_path: Optional[Path] = None) -> None:
    """保存配置。"""

    target_path: Path = config_path or (_runtime_base_path() / CONFIG_FILE_NAME)
    parser = configparser.ConfigParser()

    parser["general"] = {
        "output_directory": str(config.output_directory),
        "max_workers": str(config.max_workers),
    }
    parser["preview"] = {
        "duration": str(config.preview_duration),
        "retry_limit": str(config.preview_retry_limit),
    }
    parser["music"] = {}
    if config.music_default_seed is not None:
        parser["music"]["default_seed"] = str(config.music_default_seed)
    parser["music"]["random_enabled"] = "true" if config.music_random_enabled else "false"
    parser["music"]["retry_limit"] = str(config.music_retry_limit)
    parser["music"]["start_offset"] = str(config.music_start_offset)
    parser["advanced"] = {
        "video_audio_lead": str(config.video_audio_lead),
        "enable_limiter": "true" if config.enable_limiter else "false",
        "override_original": "true" if config.override_original else "false",
    }

    with target_path.open("w", encoding="utf-8") as config_file:
        parser.write(config_file)


