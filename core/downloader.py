import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.logger import (
    RICH_AVAILABLE,
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
    console,
    log_error,
    log_info,
    log_success,
    log_warn,
)


def _is_local_file(link: str, project_root: Path) -> Path | None:
    """Kiểm tra nếu mục trong 'links' là một đường dẫn file video có sẵn trên máy."""
    if link.startswith(("http://", "https://", "www.")):
        return None
    p = Path(link)
    if p.is_file():
        return p.resolve()
    rel = (project_root / link).resolve()
    if rel.is_file():
        return rel
    return None


def download_all_videos(
    links: List[str],
    raw_dir: Path,
    project_root: Path,
    ffmpeg_path: str,
    settings: Dict[str, Any],
    slice_range: Tuple[float, float] | None = None,
) -> List[Path]:
    """
    Bước 1: Tải danh sách video chất lượng cao (1080p/4K) về thư mục raw/
    theo thứ tự ep_001.mp4, ep_002.mp4, ...
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    downloaded_files: List[Path] = []

    max_retries = int(settings.get("max_retries", 3))
    cookies_browser = str(settings.get("cookies_from_browser", "")).strip()

    total = len(links)
    for idx, raw_link in enumerate(links, start=1):
        link = raw_link.strip()
        if not link:
            continue

        ep_prefix = f"ep_{idx:03d}"
        target_mp4 = raw_dir / f"{ep_prefix}.mp4"

        # Nếu tập này đã được tải đầy đủ từ lần chạy trước, sử dụng lại ngay để tiết kiệm thời gian
        if target_mp4.is_file() and target_mp4.stat().st_size > 100_000:
            size_mb = target_mp4.stat().st_size / (1024 * 1024)
            log_info(
                f"[Tập {idx}/{total}] Đã có sẵn file {target_mp4.name} ({size_mb:.1f} MB) -> Bỏ qua tải lại."
            )
            downloaded_files.append(target_mp4)
            continue

        # Kiểm tra nếu người dùng truyền đường dẫn file nội bộ trên máy
        local_src = _is_local_file(link, project_root)
        if local_src is not None:
            log_info(f"[Tập {idx}/{total}] Sao chép video có sẵn trên máy: {local_src.name}")
            shutil.copy2(local_src, target_mp4)
            downloaded_files.append(target_mp4)
            continue

        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError(
                "Chưa cài đặt thư viện 'yt-dlp'. Vui lòng chạy file chay_tool.command (Mac) / chay_tool.bat (Windows) hoặc gõ: pip install -r requirements.txt"
            ) from exc

        log_info(f"[Tập {idx}/{total}] Đang tải: {link}")
        outtmpl = str(raw_dir / f"{ep_prefix}.%(ext)s")

        ydl_opts: Dict[str, Any] = {
            "format": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "ffmpeg_location": str(Path(ffmpeg_path).parent),
            "retries": max_retries,
            "fragment_retries": max_retries,
            "concur_fragments": 4,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        }

        if cookies_browser:
            ydl_opts["cookiesfrombrowser"] = (cookies_browser,)

        if slice_range is not None and slice_range[1] > 0:
            start_s, dur_s = slice_range
            end_s = start_s + dur_s
            try:
                from yt_dlp.utils import download_range_func

                ydl_opts["download_ranges"] = download_range_func(None, [(start_s, end_s)])
            except Exception:
                pass

        if RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(bar_width=36),
                TaskProgressColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False,
            ) as progress:
                task_id = progress.add_task(f"Tập {idx:02d}/{total:02d}", total=100)

                def _progress_hook(d: Dict[str, Any]):
                    status = d.get("status")
                    if status == "downloading":
                        total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        downloaded_bytes = d.get("downloaded_bytes", 0)
                        if total_bytes > 0:
                            progress.update(
                                task_id,
                                total=total_bytes,
                                completed=downloaded_bytes,
                            )
                    elif status == "finished":
                        total_bytes = d.get("total_bytes") or d.get("downloaded_bytes") or 100
                        progress.update(task_id, total=total_bytes, completed=total_bytes)

                ydl_opts["progress_hooks"] = [_progress_hook]
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([link])
                except Exception as exc:
                    log_error(f"Không thể tải tập {idx} ({link}): {exc}")
                    raise
        else:
            def _simple_hook(d: Dict[str, Any]):
                if d.get("status") == "downloading":
                    pct = d.get("_percent_str", "").strip()
                    spd = d.get("_speed_str", "").strip()
                    print(f"\r  -> Đang tải Tập {idx}/{total}: {pct} ({spd})   ", end="", flush=True)
                elif d.get("status") == "finished":
                    print(f"\r  -> Đang tải Tập {idx}/{total}: 100% (Đang đóng gói MP4...)")

            ydl_opts["progress_hooks"] = [_simple_hook]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([link])

        # Tìm file vừa tải xong (đề phòng trường hợp đuôi khác .mp4)
        if target_mp4.is_file():
            downloaded_files.append(target_mp4)
        else:
            matches = sorted(raw_dir.glob(f"{ep_prefix}.*"))
            if matches:
                downloaded_files.append(matches[0])
            else:
                raise FileNotFoundError(f"Tải xong nhưng không tìm thấy file cho tập {idx} tại {raw_dir}")

        size_mb = downloaded_files[-1].stat().st_size / (1024 * 1024)
        log_success(f"[Tập {idx}/{total}] Hoàn tất tải: {downloaded_files[-1].name} ({size_mb:.1f} MB)")

    if not downloaded_files:
        log_warn("Không có video nào được tải về!")

    return downloaded_files
