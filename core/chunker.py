import concurrent.futures
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.processor import probe_media_info
from core.video_url import normalize_video_url

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".ts", ".m4v"}


def natural_sort_key(text: str) -> List[Any]:
    """
    Khóa sắp xếp tự nhiên giúp 'Tap 2.mp4' luôn đứng trước 'Tap 10.mp4'.
    """
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", str(text))]


def format_hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def format_human_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs} giờ {mins:02d} phút"
    elif mins > 0:
        return f"{mins} phút {secs:02d} giây"
    return f"{secs} giây"


def probe_item_metadata(ffprobe_path: str, path_or_url: str, cookies_browser: str = "") -> Dict[str, Any]:
    """
    Đọc nhanh thông tin thời lượng và dung lượng của 1 file video (hoặc link Bilibili/YouTube online).
    Nếu là link Bilibili dài 36 tiếng hoặc playlist nhiều tập, tự động lấy thời lượng thực tế qua yt-dlp.
    """
    path_or_url = normalize_video_url(path_or_url)
    p = Path(path_or_url)
    if p.is_file():
        dur, has_audio = probe_media_info(ffprobe_path, p)
        size_bytes = p.stat().st_size
        return {
            "id": f"file::{p.resolve().as_posix()}",
            "name": p.name,
            "source": str(p.resolve()),
            "is_local": True,
            "duration": round(dur, 2),
            "duration_hms": format_hms(dur),
            "size_mb": round(size_bytes / (1024 * 1024), 1),
            "has_audio": has_audio,
        }
    else:
        title = path_or_url.split("/")[-1][:48] or path_or_url
        dur = 0.0
        try:
            from core.bilibili_bypass import fetch_bilibili_pages, is_bilibili_url

            if is_bilibili_url(path_or_url):
                bili_info = fetch_bilibili_pages(path_or_url)
                title = bili_info["title"]
                dur = float(bili_info["total_duration"])
            else:
                import yt_dlp

                def _extract_with_opts(use_cookies: bool):
                    ydl_opts: Dict[str, Any] = {
                        "quiet": True,
                        "no_warnings": True,
                        "skip_download": True,
                        "extract_flat": "in_playlist",
                    }
                    if use_cookies and cookies_browser:
                        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        return ydl.extract_info(path_or_url, download=False)

                try:
                    info = _extract_with_opts(use_cookies=bool(cookies_browser))
                except Exception as cookie_exc:
                    if cookies_browser and "cookie database" in str(cookie_exc).lower():
                        info = _extract_with_opts(use_cookies=False)
                    else:
                        raise

                if info:
                    title = str(info.get("title") or title)
                    if info.get("duration"):
                        dur = float(info["duration"])
                    elif info.get("entries"):
                        entries = list(info["entries"])
                        total_d = sum(float(e.get("duration") or 0.0) for e in entries if e)
                        if total_d > 0:
                            dur = total_d
        except Exception as exc:
            detail = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()
            raise RuntimeError(
                f"Không đọc được video từ link: {path_or_url}. "
                f"Chi tiết: {detail}"
            ) from exc
        if dur <= 0:
            raise RuntimeError(
                f"Không xác định được thời lượng video từ link: {path_or_url}. "
                "Hãy kiểm tra link hoặc dùng file video trên máy."
            )

        return {
            "id": f"url::{path_or_url}",
            "name": title,
            "source": path_or_url,
            "is_local": False,
            "duration": round(dur, 2),
            "duration_hms": f"{format_hms(dur)} (Link)",
            "size_mb": 0.0,
            "has_audio": True,
        }


def probe_multiple_items(ffprobe_path: str, sources: List[str], cookies_browser: str = "") -> List[Dict[str, Any]]:
    """Đo thời lượng song song nhiều file video cùng lúc (cực nhanh kể cả khi kéo thả 50-100 tập)."""
    if not sources:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda s: probe_item_metadata(ffprobe_path, s, cookies_browser), sources))
    return results


def build_target_chunks(
    items: List[Dict[str, Any]],
    project_name: str,
    target_hours: float = 5.0,
    chunk_mode: str = "target_duration",
    trim_start_sec: float = 0.0,
    trim_end_sec: float = 0.0,
    speed_factor: float = 1.0,
) -> Dict[str, Any]:
    """
    Chia danh sách các tập phim thành các Phần (Chunks) dựa theo mục tiêu thời lượng (ví dụ: 5 tiếng / video).
    - chunk_mode == 'single': Gom tất cả các tập thành 1 video tổng hợp duy nhất.
    - chunk_mode == 'target_duration': Tự động ngắt thành từng Phần khi đạt đủ `target_hours` (mặc định 5 tiếng).
    """
    safe_base = "".join(
        c if (c.isalnum() or c in ("_", "-")) else "_" for c in (project_name or "Video_Tong_Hop").strip()
    ).strip("_") or "Video_Tong_Hop"

    # Hỗ trợ cả mức cắt nhỏ như 15 phút (0.25 giờ = 900 giây) hoặc 5 phút (300 giây)
    target_seconds = max(60.0, float(target_hours or 0.25) * 3600.0)
    speed = float(speed_factor or 1.0)
    if speed <= 0:
        speed = 1.0

    # Tính thời lượng hiệu dụng của từng tập sau khi cắt Intro/Outro và đổi tốc độ.
    # Đặc biệt: Nếu 1 video đầu vào siêu dài (ví dụ video Bilibili 36 tiếng > target_seconds 5 tiếng),
    # tự động cắt nhỏ (slice) video đó thành các đoạn con 5 tiếng để xuất ra nhiều Phần!
    enriched_items: List[Dict[str, Any]] = []
    total_effective_seconds = 0.0

    for idx, item in enumerate(items, start=1):
        raw_dur = float(item.get("duration", 0.0) or 0.0)
        base_start = 0.0
        kept_raw_dur = raw_dur
        if raw_dur > (trim_start_sec + trim_end_sec + 2.0):
            base_start = trim_start_sec
            kept_raw_dur = raw_dur - trim_start_sec - trim_end_sec

        eff_dur = kept_raw_dur
        max_raw_slice = target_seconds

        # Nếu chế độ chia theo mục tiêu (ví dụ 15 phút = 900s) và video dài hơn mục tiêu (ví dụ 2 tiếng = 7329s)
        if chunk_mode != "single" and target_hours > 0 and kept_raw_dur > max_raw_slice * 1.05:
            slice_offset = 0.0
            part_num = 1
            while slice_offset < kept_raw_dur - 1.0:
                cur_raw_len = min(max_raw_slice, kept_raw_dur - slice_offset)
                cur_eff_len = cur_raw_len
                sub_copy = dict(item)
                sub_copy["ep_index"] = len(enriched_items) + 1
                sub_copy["name"] = (
                    f"{item['name']} [Phần {part_num:02d}: "
                    f"{format_hms(base_start + slice_offset)} ➔ {format_hms(base_start + slice_offset + cur_raw_len)}]"
                )
                sub_copy["slice_start_sec"] = round(base_start + slice_offset, 2)
                sub_copy["slice_duration_sec"] = round(cur_raw_len, 2)
                sub_copy["effective_duration"] = round(cur_eff_len, 2)
                sub_copy["effective_hms"] = format_hms(cur_eff_len)
                enriched_items.append(sub_copy)
                total_effective_seconds += cur_eff_len
                slice_offset += cur_raw_len
                part_num += 1
        else:
            item_copy = dict(item)
            item_copy["ep_index"] = len(enriched_items) + 1
            item_copy["slice_start_sec"] = round(base_start, 2)
            item_copy["slice_duration_sec"] = round(kept_raw_dur, 2)
            item_copy["effective_duration"] = round(eff_dur, 2)
            item_copy["effective_hms"] = format_hms(eff_dur)
            enriched_items.append(item_copy)
            total_effective_seconds += eff_dur

    chunks: List[Dict[str, Any]] = []

    if not enriched_items:
        pass
    elif chunk_mode == "single" or target_hours <= 0:
        chunks.append(
            {
                "chunk_index": 1,
                "output_name": f"{safe_base}.mp4",
                "episode_count": len(enriched_items),
                "start_ep": 1,
                "end_ep": len(enriched_items),
                "total_duration": round(total_effective_seconds, 2),
                "total_hms": format_hms(total_effective_seconds),
                "total_human": format_human_duration(total_effective_seconds),
                "progress_pct": min(100.0, round((total_effective_seconds / target_seconds) * 100.0, 1)),
                "meets_target": total_effective_seconds >= target_seconds * 0.9,
                "items": enriched_items,
            }
        )
    else:
        current_bucket: List[Dict[str, Any]] = []
        current_dur = 0.0

        for ep in enriched_items:
            ep_dur = ep["effective_duration"]
            current_bucket.append(ep)
            current_dur += ep_dur

            # Ngắt chunk khi tổng thời lượng chạm hoặc vượt mốc mục tiêu (ví dụ >= 5 tiếng)
            if current_dur >= target_seconds:
                c_idx = len(chunks) + 1
                chunks.append(
                    {
                        "chunk_index": c_idx,
                        "output_name": f"{safe_base}_Phan_{c_idx:02d}.mp4",
                        "episode_count": len(current_bucket),
                        "start_ep": current_bucket[0]["ep_index"],
                        "end_ep": current_bucket[-1]["ep_index"],
                        "total_duration": round(current_dur, 2),
                        "total_hms": format_hms(current_dur),
                        "total_human": format_human_duration(current_dur),
                        "progress_pct": min(100.0, round((current_dur / target_seconds) * 100.0, 1)),
                        "meets_target": True,
                        "items": current_bucket,
                    }
                )
                current_bucket = []
                current_dur = 0.0

        # Phần dư còn lại (hoặc khi tổng các tập chưa tới 5 tiếng)
        if current_bucket:
            c_idx = len(chunks) + 1
            out_name = (
                f"{safe_base}.mp4"
                if c_idx == 1
                else f"{safe_base}_Phan_{c_idx:02d}.mp4"
            )
            chunks.append(
                {
                    "chunk_index": c_idx,
                    "output_name": out_name,
                    "episode_count": len(current_bucket),
                    "start_ep": current_bucket[0]["ep_index"],
                    "end_ep": current_bucket[-1]["ep_index"],
                    "total_duration": round(current_dur, 2),
                    "total_hms": format_hms(current_dur),
                    "total_human": format_human_duration(current_dur),
                    "progress_pct": min(100.0, round((current_dur / target_seconds) * 100.0, 1)),
                    "meets_target": current_dur >= target_seconds * 0.9,
                    "items": current_bucket,
                }
            )

    # Tính số tập ước tính cần thêm nếu Chunk cuối chưa đủ mục tiêu 5 tiếng
    avg_ep_dur = (
        (total_effective_seconds / len(enriched_items))
        if enriched_items
        else 900.0
    )
    remaining_for_target = max(0.0, target_seconds - total_effective_seconds)
    est_more_eps = int(round(remaining_for_target / avg_ep_dur)) if avg_ep_dur > 0 and remaining_for_target > 0 else 0

    return {
        "total_episodes": len(enriched_items),
        "total_duration": round(total_effective_seconds, 2),
        "total_hms": format_hms(total_effective_seconds),
        "total_human": format_human_duration(total_effective_seconds),
        "target_hours": target_hours,
        "target_seconds": target_seconds,
        "target_hms": format_hms(target_seconds),
        "overall_target_pct": min(100.0, round((total_effective_seconds / target_seconds) * 100.0, 1)),
        "estimated_more_episodes_needed": est_more_eps,
        "chunks": chunks,
        "items": enriched_items,
    }


def resolve_dropped_file_on_disk(
    filename: str,
    filesize: int,
    search_roots: List[Path],
) -> Optional[Path]:
    """
    Khi người dùng Kéo & Thả (Drag & Drop) file từ Finder (Mac) hoặc Explorer (Windows)
    vào giao diện, tìm ngay đường dẫn gốc trên ổ đĩa theo (tên file + kích thước byte chính xác)
    để KHÔNG phải copy lại file hàng GB.
    """
    safe_name = os.path.basename(filename)
    if not safe_name:
        return None

    # 1. Trên macOS: Sử dụng Spotlight index (mdfind) tìm trong 0.02 giây trên toàn bộ ổ cứng!
    if platform.system().lower() == "darwin" and filesize > 0:
        try:
            escaped = safe_name.replace('"', '\\"')
            cmd = ["mdfind", f'kMDItemFSName == "{escaped}" && kMDItemFSSize == {filesize}']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
            for line in (res.stdout or "").splitlines():
                cand = Path(line.strip())
                if cand.is_file() and cand.stat().st_size == filesize:
                    return cand.resolve()
        except Exception:
            pass

    # 2. Quét nhanh các thư mục phổ biến (Downloads, Desktop, Videos, Movies, Project root)
    home = Path.home()
    common_dirs = list(search_roots) + [
        home / "Downloads",
        home / "Desktop",
        home / "Movies",
        home / "Videos",
        home / "Documents",
    ]
    seen = set()
    for folder in common_dirs:
        if not folder or not folder.is_dir():
            continue
        folder_key = str(folder.resolve())
        if folder_key in seen:
            continue
        seen.add(folder_key)

        direct = folder / safe_name
        if direct.is_file() and (filesize <= 0 or direct.stat().st_size == filesize):
            return direct.resolve()

        # Quét sâu tối đa 2 cấp thư mục con trong Downloads/Videos/Movies
        try:
            for sub in folder.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    cand = sub / safe_name
                    if cand.is_file() and (filesize <= 0 or cand.stat().st_size == filesize):
                        return cand.resolve()
        except Exception:
            pass

    return None
