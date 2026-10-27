import os
import sys

# Đảm bảo đầu ra UTF-8 trên Windows CMD / PowerShell và macOS Terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.system("chcp 65001 >nul 2>&1")

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )
    from rich.table import Table

    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None
    Panel = None
    BarColumn = None
    DownloadColumn = None
    Progress = None
    SpinnerColumn = None
    TaskProgressColumn = None
    TextColumn = None
    TimeElapsedColumn = None
    TimeRemainingColumn = None
    TransferSpeedColumn = None
    Table = None


def print_banner():
    title = "🎬 AUTO VIDEO AGGREGATOR & ANTI-COPYRIGHT PIPELINE"
    subtitle = "Tự động Tải Video Raw • Lách Bản Quyền • Ghép Video Dài (macOS & Windows)"
    if RICH_AVAILABLE:
        console.print(
            Panel.fit(
                f"[bold cyan]{title}[/bold cyan]\n[dim]{subtitle}[/dim]",
                border_style="bright_blue",
                padding=(1, 3),
            )
        )
    else:
        print("=" * 72)
        print(f"  {title}")
        print(f"  {subtitle}")
        print("=" * 72)


def log_info(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[bold blue][INFO][/bold blue] {msg}")
    else:
        print(f"[INFO] {msg}")


def log_step(step_num: int, total_steps: int, title: str):
    if RICH_AVAILABLE:
        console.print(
            f"\n[bold magenta]━━━ [BƯỚC {step_num}/{total_steps}] {title.upper()} ━━━[/bold magenta]"
        )
    else:
        print(f"\n=== [BƯỚC {step_num}/{total_steps}] {title.upper()} ===")


def log_success(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[bold green][THÀNH CÔNG][/bold green] {msg}")
    else:
        print(f"[THÀNH CÔNG] {msg}")


def log_warn(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[bold yellow][CẢNH BÁO][/bold yellow] {msg}")
    else:
        print(f"[CẢNH BÁO] {msg}")


def log_error(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[bold red][LỖI][/bold red] {msg}")
    else:
        print(f"[LỖI] {msg}")
