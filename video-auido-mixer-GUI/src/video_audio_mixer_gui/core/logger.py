"""基于 rich 的日志封装模块。

提供统一的控制台输出接口，带有 emoji 与配色方案，以提高可读性。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.theme import Theme


_THEME: Theme = Theme({
    "success": "black on green",
    "warning": "black on yellow",
    "error": "white on red",
    "info": "default on default",
})


@dataclass(slots=True)
class RunStats:
    """运行统计数据模型。"""

    total: int
    success: int
    skipped: int
    failed: int


class RichLogger:
    """rich 控制台日志包装类。"""

    def __init__(self, console: Optional[Console] = None) -> None:
        # 使用 rich 控制台，支持彩色输出
        self._console: Console = console or Console(theme=_THEME)

    def log_success(self, message: str) -> None:
        """输出成功信息。"""

        self._console.print(f"✅ {message}", style="success")

    def log_warning(self, message: str) -> None:
        """输出警告信息。"""

        self._console.print(f"⚠️ {message}", style="warning")

    def log_error(self, message: str) -> None:
        """输出错误信息。"""

        self._console.print(f"❌ {message}", style="error")

    def log_info(self, message: str) -> None:
        """输出普通信息。"""

        self._console.print(f"ℹ️ {message}", style="info")

    def summary(self, stats: RunStats) -> None:
        """输出执行汇总。"""

        summary_text: str = (
            f"总数: {stats.total} | 成功: {stats.success} | "
            f"跳过: {stats.skipped} | 失败: {stats.failed}"
        )
        if stats.failed > 0:
            self._console.print(summary_text, style="error")
        elif stats.skipped > 0:
            self._console.print(summary_text, style="warning")
        else:
            self._console.print(summary_text, style="success")


