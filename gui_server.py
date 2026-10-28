import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.chunker import (
    VIDEO_EXTENSIONS,
    build_target_chunks,
    format_hms,
    format_human_duration,
    natural_sort_key,
    probe_item_metadata,
    probe_multiple_items,
    resolve_dropped_file_on_disk,
)
from core.processor import (
    _build_filters,
    _encoder_args,
    _get_effective_anti_copyright_params,
    probe_media_info,
)
from core.system_check import check_disk_space, find_ffmpeg_binaries, get_os_name, select_video_encoder

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_UI_DIR = PROJECT_ROOT / "web_ui"
RAW_DIR = PROJECT_ROOT / "raw"
UPLOAD_CACHE_DIR = PROJECT_ROOT / "raw" / "dropped_chunks"
PROCESSED_DIR = PROJECT_ROOT / "temp_processed"
OUTPUT_DIR = PROJECT_ROOT / "output"
SRT_WORK_DIR = PROJECT_ROOT / "output" / "subtitles"
CONFIG_PATH = PROJECT_ROOT / "config.json"


# ==============================================================================
# BỘ ĐỌC / GHI FILE PHỤ ĐỀ .SRT THUẦN PYTHON (KHÔNG CẦN THƯ VIỆN NGOÀI)
# ==============================================================================
def parse_srt_text(raw_srt: str) -> List[Dict[str, Any]]:
    """Đọc nội dung file .srt thành danh sách các dòng phụ đề để hiển thị lên bảng sửa."""
    text = (raw_srt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    blocks = re.split(r"\n\s*\n", text)
    cues: List[Dict[str, Any]] = []
    for idx, block in enumerate(blocks, start=1):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        # Tìm dòng chứa mốc thời gian '00:00:01,000 --> 00:00:04,000'
        ts_line_idx = -1
        for i, ln in enumerate(lines):
            if "-->" in ln:
                ts_line_idx = i
                break
        if ts_line_idx == -1:
            continue
        parts = lines[ts_line_idx].split("-->")
        start_ts = parts[0].strip()
        end_ts = parts[1].strip().split(" ")[0]
        content_lines = lines[ts_line_idx + 1 :]
        cues.append(
            {
                "index": len(cues) + 1,
                "start": start_ts,
                "end": end_ts,
                "text": "\n".join(content_lines),
            }
        )
    return cues


def compose_srt_text(cues: List[Dict[str, Any]]) -> str:
    """Ghép danh sách các câu phụ đề đã sửa trên bảng thành chuẩn định dạng .SRT quốc tế."""
    out_blocks: List[str] = []
    idx = 1
    for c in cues:
        text = str(c.get("vi_text") if "vi_text" in c else c.get("text", "")).strip()
        if not text:
            continue
        start_ts = str(c.get("start", "00:00:00,000")).strip()
        end_ts = str(c.get("end", "00:00:03,000")).strip()
        out_blocks.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}")
        idx += 1
    return "\n\n".join(out_blocks) + ("\n" if out_blocks else "")


class PipelineState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ffmpeg_path, self.ffprobe_path = find_ffmpeg_binaries(PROJECT_ROOT)
        self.os_name = get_os_name()
        self.enc_info = (
            select_video_encoder(self.ffmpeg_path, "auto")
            if self.ffmpeg_path
            else {"encoder": "libx264", "label": "Chưa cài FFmpeg"}
        )
        self.recent_folders: List[Path] = [PROJECT_ROOT, OUTPUT_DIR]

        # Danh sách tập phim hiện tại trên giao diện
        self.items: List[Dict[str, Any]] = []
        self.project_name: str = "Phim_Cat_15_Phut"
        # Mặc định 0.25 giờ = 15 phút / phần theo yêu cầu của người dùng
        self.target_hours: float = 0.25
        self.chunk_mode: str = "target_duration"  # 'target_duration' | 'single'
        # Danh sách các chunk_index được người dùng tích chọn (ví dụ 10 phần đầu: [1..10])
        self.selected_chunks: List[int] = []
        self.settings: Dict[str, Any] = {
            "resolution": "1920x1080",
            "fps": 30,
            "video_bitrate": "8M",
            "gpu_acceleration": "auto",
            "trim_start_sec": 0.0,
            "trim_end_sec": 0.0,
            "anti_copyright": {
                "enabled": True,
                "level": "hardcore",
                "zoom_factor": 1.045,
                "brightness": 0.02,
                "contrast": 1.05,
                "saturation": 1.07,
                "speed_factor": 1.04,
                "flip_horizontal": False,
                "pitch_shift": 1.0,
            },
            "audio_normalize": True,
            "clean_temp_after_done": True,
            "cookies_from_browser": "",
            "whisper_model": "small",
            "blur_sub": {
                "mode": "delogo",
                "y_pct": 86.0,
                "h_pct": 10.0,
                "w_pct": 82.0,
            },
        }

        # Trạng thái bảng sửa Phụ đề (.SRT) thủ công & Lồng tiếng
        self.srt_rows: List[Dict[str, Any]] = []
        self.active_srt_path: str = ""
        self.active_video_for_srt: str = ""
        self.srt_status_msg: str = "Chờ video từ Bước 3 hoặc chọn video có sẵn trên máy."

        # Trạng thái chạy ngầm
        self.is_running: bool = False
        self.stop_requested: bool = False
        self.current_proc: Optional[subprocess.Popen] = None
        self.status_phase: str = "Sẵn sàng"
        self.current_chunk_idx: int = 0
        self.total_chunks: int = 0
        self.current_ep_idx: int = 0
        self.total_eps: int = 0
        self.current_ep_pct: float = 0.0
        self.overall_pct: float = 0.0
        self.logs: List[str] = []
        self.finished_outputs: List[Dict[str, Any]] = []
        self.error_message: str = ""
        self.started_at: float = 0.0
        self._load_existing_outputs()

    def _load_existing_outputs(self) -> None:
        if not OUTPUT_DIR.is_dir():
            return
        mp4s = sorted(
            (p for p in OUTPUT_DIR.glob("*.mp4") if p.is_file() and not p.name.endswith("_Lồng_Tiếng_Việt.mp4")),
            key=lambda p: natural_sort_key(p.name),
        )
        for idx, p in enumerate(mp4s, start=1):
            size_gb = p.stat().st_size / (1024**3)
            size_mb = p.stat().st_size / (1024**2)
            size_label = f"{size_gb:.2f} GB" if size_gb >= 1.0 else f"{size_mb:.1f} MB"
            self.finished_outputs.append(
                {
                    "chunk_index": idx,
                    "name": p.name,
                    "path": str(p.resolve()),
                    "duration_hms": "00:15:00",
                    "duration_human": "Đã xuất sẵn",
                    "size_label": size_label,
                }
            )
        if self.finished_outputs:
            self.active_video_for_srt = self.finished_outputs[-1]["path"]
            self.srt_status_msg = f"Sẵn sàng tách phụ đề từ: {Path(self.active_video_for_srt).name}"

    def add_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        with self.lock:
            self.logs.append(line)
            if len(self.logs) > 250:
                self.logs = self.logs[-250:]
        print(line, flush=True)


STATE = PipelineState()


def _get_srt_target() -> str:
    """Choose an existing video, preferring the output linked to the subtitle editor."""
    candidates = [STATE.active_video_for_srt]
    candidates.extend(out.get("path", "") for out in reversed(STATE.finished_outputs))
    candidates.extend(item.get("source", "") for item in STATE.items if item.get("is_local"))
    if OUTPUT_DIR.is_dir():
        recent_mp4s = sorted(
            (p for p in OUTPUT_DIR.glob("*.mp4") if p.is_file() and not p.name.endswith("_Lồng_Tiếng_Việt.mp4")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(str(p.resolve()) for p in recent_mp4s)
    return next((str(path) for path in candidates if path and Path(path).is_file()), "")


def _list_available_preview_videos() -> List[Dict[str, str]]:
    """Liệt kê tất cả các file video có thể xem trước (trong output/ và file gốc trên máy)."""
    seen = set()
    videos: List[Dict[str, str]] = []

    if OUTPUT_DIR.is_dir():
        out_files = sorted(
            (p for p in OUTPUT_DIR.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in out_files:
            rp = str(p.resolve())
            if rp not in seen:
                seen.add(rp)
                size_mb = p.stat().st_size / (1024 * 1024)
                tag = "🗣️ Đã Lồng Tiếng" if p.name.endswith("_Lồng_Tiếng_Việt.mp4") else "📦 Đã Xuất (output/)"
                videos.append(
                    {
                        "path": rp,
                        "name": p.name,
                        "label": f"[{tag}] {p.name} ({size_mb:.1f} MB)",
                    }
                )

    for it in STATE.items:
        if it.get("is_local"):
            src = str(it.get("source", ""))
            p = Path(src)
            if p.is_file():
                rp = str(p.resolve())
                if rp not in seen:
                    seen.add(rp)
                    size_mb = p.stat().st_size / (1024 * 1024)
                    videos.append(
                        {
                            "path": rp,
                            "name": p.name,
                            "label": f"[📂 File Gốc] {p.name} ({size_mb:.1f} MB)",
                        }
                    )
    return videos


def _list_available_tts_audios() -> List[Dict[str, str]]:
    """Liệt kê tất cả các file .mp3/.wav thuyết minh đã tạo trong output/ (ưu tiên khớp tên video đang chọn)."""
    audios: List[Dict[str, str]] = []
    if not OUTPUT_DIR.is_dir():
        return audios
    active_vid = _get_srt_target()
    active_stem = Path(active_vid).stem.lower() if active_vid else ""

    files = [
        p for p in OUTPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in (".mp3", ".wav", ".m4a")
    ]

    def _sort_key(p: Path) -> Tuple[int, float]:
        name_low = p.name.lower()
        is_match = 1 if (active_stem and (active_stem in name_low or name_low.split(".")[0] in active_stem)) else 0
        return (is_match, p.stat().st_mtime)

    for p in sorted(files, key=_sort_key, reverse=True):
        rp = str(p.resolve())
        size_mb = p.stat().st_size / (1024 * 1024)
        audios.append(
            {
                "path": rp,
                "name": p.name,
                "label": f"🔊 {p.name} ({size_mb:.1f} MB)",
            }
        )
    return audios


def _native_pick_audio_file() -> Optional[str]:
    """Mở hộp thoại chọn file .mp3 / .wav thuyết minh có sẵn trên máy."""
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        script = (
            'tell application "SystemUIServer"\n'
            "activate\n"
            'set theFile to choose file with prompt "Chọn file âm thanh thuyết minh (.mp3 / .wav):"\n'
            "return POSIX path of theFile\n"
            "end tell"
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    elif sys_name == "windows":
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.OpenFileDialog; "
            "$f.Title = 'Chọn file âm thanh thuyết minh (.mp3 / .wav)'; "
            "$f.Filter = 'Audio Files (*.mp3;*.wav;*.m4a)|*.mp3;*.wav;*.m4a|All Files (*.*)|*.*'; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $f.FileName }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    return None


def _native_pick_files() -> List[str]:
    """Mở cửa sổ chọn nhiều file gốc của macOS (Finder) hoặc Windows (Explorer)."""
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        script = (
            'tell application "SystemUIServer"\n'
            "activate\n"
            'set theFiles to choose file with prompt "Chọn các tập video cần ghép (Giữ phím Command hoặc Shift để chọn nhiều tập):" '
            'of type {"public.movie", "public.mpeg-4", "com.apple.quicktime-movie", "org.matroska.mkv"} '
            "with multiple selections allowed\n"
            "set outText to \"\"\n"
            "repeat with aFile in theFiles\n"
            "set outText to outText & (POSIX path of aFile) & linefeed\n"
            "end repeat\n"
            "return outText\n"
            "end tell"
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            paths = [p.strip() for p in res.stdout.splitlines() if p.strip()]
            paths.sort(key=lambda p: natural_sort_key(Path(p).name))
            return paths
        return []
    elif sys_name == "windows":
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.OpenFileDialog; "
            "$f.Title = 'Chọn các tập video cần ghép (Giữ Ctrl hoặc Shift để chọn nhiều tập)'; "
            "$f.Filter = 'Video Files (*.mp4;*.mkv;*.mov;*.avi;*.ts;*.webm)|*.mp4;*.mkv;*.mov;*.avi;*.ts;*.webm|All Files (*.*)|*.*'; "
            "$f.Multiselect = $true; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $f.FileNames -join \"`n\" }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            paths = [p.strip() for p in res.stdout.splitlines() if p.strip()]
            paths.sort(key=lambda p: natural_sort_key(Path(p).name))
            return paths
        return []
    return []


def _native_pick_srt_file() -> Optional[str]:
    """Mở cửa sổ chọn file phụ đề .srt trên máy Mac hoặc Windows để sửa thủ công."""
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        script = (
            'tell application "SystemUIServer"\n'
            "activate\n"
            'set theFile to choose file with prompt "Chọn file phụ đề (.srt) cần sửa:"\n'
            "return POSIX path of theFile\n"
            "end tell"
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    elif sys_name == "windows":
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.OpenFileDialog; "
            "$f.Title = 'Chọn file phụ đề (.srt) cần sửa'; "
            "$f.Filter = 'Subtitle Files (*.srt)|*.srt|All Files (*.*)|*.*'; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $f.FileName }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    return None


def _native_pick_folder() -> List[str]:
    """Mở cửa sổ chọn nguyên thư mục chứa các tập phim trên macOS hoặc Windows."""
    sys_name = platform.system().lower()
    folder_path: Optional[Path] = None

    if sys_name == "darwin":
        script = (
            'tell application "SystemUIServer"\n'
            "activate\n"
            'set theFolder to choose folder with prompt "Chọn thư mục chứa các tập video:"\n'
            "return POSIX path of theFolder\n"
            "end tell"
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            folder_path = Path(res.stdout.strip())
    elif sys_name == "windows":
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description = 'Chọn thư mục chứa các tập video cần ghép'; "
            "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $d.SelectedPath }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            folder_path = Path(res.stdout.strip())

    if folder_path and folder_path.is_dir():
        STATE.recent_folders.insert(0, folder_path)
        files = [
            str(p.resolve())
            for p in folder_path.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ]
        files.sort(key=lambda p: natural_sort_key(Path(p).name))
        return files
    return []


def _open_folder_in_os(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        subprocess.Popen(["open", str(folder)])
    elif sys_name == "windows":
        subprocess.Popen(["explorer", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def _run_pipeline_worker() -> None:
    """Luồng chạy ngầm xử lý chỉ các Phần (Chunks) đã được người dùng tích chọn (ví dụ 10 phần đầu của 15 phút)."""
    try:
        ac_params = _get_effective_anti_copyright_params(STATE.settings)
        speed = ac_params["speed_factor"]
        plan = build_target_chunks(
            items=STATE.items,
            project_name=STATE.project_name,
            target_hours=STATE.target_hours,
            chunk_mode=STATE.chunk_mode,
            trim_start_sec=float(STATE.settings.get("trim_start_sec", 0.0)),
            trim_end_sec=float(STATE.settings.get("trim_end_sec", 0.0)),
            speed_factor=speed,
        )
        all_chunks = plan["chunks"]
        if not all_chunks:
            STATE.add_log("⚠️ Không có tập video nào trong danh sách để xử lý!")
            return

        # Lọc theo danh sách các Phần được tích chọn (selected_chunks)
        selected_set = set(STATE.selected_chunks or [])
        if selected_set:
            chunks = [c for c in all_chunks if c["chunk_index"] in selected_set]
        else:
            chunks = all_chunks

        if not chunks:
            STATE.add_log("⚠️ Bạn chưa tích chọn Phần cắt nào để xuất! Hãy tích chọn ít nhất 1 phần.")
            return

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        total_eps = sum(len(c["items"]) for c in chunks)
        total_chunks = len(chunks)
        with STATE.lock:
            STATE.total_chunks = total_chunks
            STATE.total_eps = total_eps
            STATE.finished_outputs = []
            STATE.error_message = ""
            STATE.started_at = time.time()

        STATE.add_log(
            f"🚀 Bắt đầu cắt & xử lý {total_chunks}/{len(all_chunks)} Phần đã chọn "
            f"(Tổng cộng {total_eps} đoạn | Mức cắt: {round(STATE.target_hours * 60)} phút/phần)"
        )
        STATE.add_log(
            f"⚡ Tăng tốc phần cứng: {STATE.enc_info['label']} | Chế độ Lách YouTube: {ac_params['level'].upper()}"
        )

        trim_start = float(STATE.settings.get("trim_start_sec", 0.0) or 0.0)
        trim_end = float(STATE.settings.get("trim_end_sec", 0.0) or 0.0)
        bitrate = str(STATE.settings.get("video_bitrate", "8M") or "8M")
        encoder = STATE.enc_info["encoder"]

        global_ep_counter = 0

        for run_idx, chunk in enumerate(chunks, start=1):
            if STATE.stop_requested:
                break

            c_idx = chunk["chunk_index"]
            out_filename = chunk["output_name"]
            chunk_items = chunk["items"]
            chunk_norm_files: List[Path] = []

            with STATE.lock:
                STATE.current_chunk_idx = c_idx
                STATE.status_phase = f"Đang xử lý Phần {c_idx} ({run_idx}/{total_chunks} phần đã chọn) ➔ {out_filename}"

            STATE.add_log(
                f"━━━ 📦 PHẦN {c_idx} ({run_idx}/{total_chunks}): Thời lượng {chunk['total_human']} ➔ {out_filename} ━━━"
            )

            for ep in chunk_items:
                if STATE.stop_requested:
                    break

                global_ep_counter += 1
                with STATE.lock:
                    STATE.current_ep_idx = global_ep_counter
                    STATE.current_ep_pct = 0.0

                source_str = ep["source"]
                is_local = ep.get("is_local", True)
                slice_start = float(ep.get("slice_start_sec", 0.0) or 0.0)
                slice_dur = float(ep.get("slice_duration_sec", 0.0) or 0.0)
                used_remote_slice = False

                if is_local and Path(source_str).is_file():
                    in_file = Path(source_str)
                else:
                    STATE.status_phase = f"[Phần {c_idx}] Đang tải đoạn {global_ep_counter}/{total_eps}"
                    STATE.add_log(f"⬇️ [Đoạn {global_ep_counter}/{total_eps}] Đang tải: {ep['name']}")
                    from core.downloader import download_all_videos

                    def _dl_progress(pct: float, ep_num: int = global_ep_counter) -> None:
                        p_val = round(min(100.0, max(0.0, pct)), 1)
                        with STATE.lock:
                            STATE.current_ep_pct = p_val
                            base = ((ep_num - 1) / max(1, total_eps)) * 92.0
                            step = (p_val / 100.0) * (40.0 / max(1, total_eps))
                            STATE.overall_pct = min(99.0, round(base + step, 1))

                    dl_list = download_all_videos(
                        links=[source_str],
                        raw_dir=RAW_DIR / f"c{c_idx:03d}_ep{global_ep_counter:03d}",
                        project_root=PROJECT_ROOT,
                        ffmpeg_path=STATE.ffmpeg_path,
                        settings=STATE.settings,
                        slice_range=(slice_start, slice_dur) if slice_dur > 0 else None,
                        progress_callback=_dl_progress,
                    )
                    in_file = dl_list[0]
                    used_remote_slice = True

                norm_file = PROCESSED_DIR / f"norm_c{c_idx:03d}_ep{global_ep_counter:03d}.mp4"
                if norm_file.is_file() and norm_file.stat().st_size > 100_000:
                    STATE.add_log(
                        f"✅ [Đoạn {global_ep_counter}/{total_eps}] Đã chuẩn hóa sẵn ({in_file.name}) ➔ Dùng lại ngay."
                    )
                    chunk_norm_files.append(norm_file)
                    with STATE.lock:
                        STATE.current_ep_pct = 100.0
                        STATE.overall_pct = round((global_ep_counter / total_eps) * 92.0, 1)
                    continue

                STATE.status_phase = (
                    f"[Phần {c_idx}] Đang xử lý đoạn {global_ep_counter}/{total_eps}: {ep['name']}"
                )
                STATE.add_log(
                    f"🎬 [Đoạn {global_ep_counter}/{total_eps}] Cắt & Lách bản quyền: {ep['name']}"
                )

                duration, has_audio = probe_media_info(STATE.ffprobe_path, in_file)
                if not used_remote_slice and slice_dur > 0:
                    actual_start = slice_start
                    keep_duration = slice_dur
                else:
                    actual_start = 0.0
                    keep_duration = duration
                    if duration > (trim_start + trim_end + 2.0):
                        actual_start = trim_start
                        keep_duration = duration - trim_start - trim_end

                expected_out_dur = max(1.0, keep_duration / speed if speed > 0 else keep_duration)
                vf_chain, af_chain = _build_filters(STATE.settings, has_audio)

                def _build_cmd(active_enc: str) -> List[str]:
                    cmd = [
                        STATE.ffmpeg_path,
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-progress",
                        "pipe:1",
                        "-nostats",
                    ]
                    if actual_start > 0:
                        cmd.extend(["-ss", f"{actual_start:.3f}"])
                    cmd.extend(["-i", str(in_file)])
                    if not has_audio:
                        cmd.extend(
                            [
                                "-f",
                                "lavfi",
                                "-i",
                                "anullsrc=channel_layout=stereo:sample_rate=48000",
                            ]
                        )
                    if keep_duration > 0 and (actual_start > 0 or trim_end > 0 or slice_dur > 0):
                        cmd.extend(["-t", f"{keep_duration:.3f}"])
                    if has_audio:
                        cmd.extend(["-map", "0:v:0", "-map", "0:a:0"])
                    else:
                        cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-shortest"])

                    cmd.extend(["-vf", vf_chain, "-af", af_chain])
                    cmd.extend(_encoder_args(active_enc, bitrate, scramble_gop=ac_params["scramble_gop"]))
                    cmd.extend(
                        [
                            "-video_track_timescale",
                            "90000",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                            "-ar",
                            "48000",
                            "-ac",
                            "2",
                            "-map_metadata",
                            "-1",
                            "-map_chapters",
                            "-1",
                            "-movflags",
                            "+faststart",
                            str(norm_file),
                        ]
                    )
                    return cmd

                rc = _run_gui_ffmpeg(_build_cmd(encoder), expected_out_dur, global_ep_counter, total_eps)
                if rc != 0 and not STATE.stop_requested and encoder != "libx264":
                    STATE.add_log("⚠️ Chuyển sang chế độ CPU (libx264) cho đoạn này...")
                    rc = _run_gui_ffmpeg(
                        _build_cmd("libx264"), expected_out_dur, global_ep_counter, total_eps
                    )

                if STATE.stop_requested:
                    if norm_file.exists():
                        norm_file.unlink(missing_ok=True)
                    break

                if rc != 0 or not norm_file.is_file():
                    raise RuntimeError(f"Không thể xử lý đoạn {ep['name']} (Mã lỗi {rc})")

                chunk_norm_files.append(norm_file)
                size_mb = norm_file.stat().st_size / (1024 * 1024)
                STATE.add_log(
                    f"✅ [Đoạn {global_ep_counter}/{total_eps}] Hoàn tất chuẩn hóa ({size_mb:.1f} MB)"
                )

            if STATE.stop_requested:
                break

            final_out = OUTPUT_DIR / out_filename
            if len(chunk_norm_files) == 1:
                shutil.copy2(chunk_norm_files[0], final_out)
            else:
                concat_txt = PROCESSED_DIR / f"concat_chunk_{c_idx:03d}.txt"
                lines = []
                for nf in chunk_norm_files:
                    esc = nf.resolve().as_posix().replace("'", "'\\''")
                    lines.append(f"file '{esc}'")
                concat_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

                STATE.status_phase = f"Đang ghép nối Phần {c_idx} ➔ {out_filename}"
                STATE.add_log(f"🔗 Đang ghép nối {len(chunk_norm_files)} đoạn thành {out_filename}...")

                concat_cmd = [
                    STATE.ffmpeg_path,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_txt),
                    "-c",
                    "copy",
                    "-map_metadata",
                    "-1",
                    "-movflags",
                    "+faststart",
                    str(final_out),
                ]
                rc = _run_gui_ffmpeg(
                    concat_cmd,
                    max(1.0, float(chunk["total_duration"])),
                    global_ep_counter,
                    total_eps,
                    is_concat=True,
                )
                if rc != 0 or not final_out.is_file():
                    raise RuntimeError(f"Ghép nối Phần {c_idx} ({out_filename}) thất bại!")
                concat_txt.unlink(missing_ok=True)

            out_dur, _ = probe_media_info(STATE.ffprobe_path, final_out)
            out_size_gb = final_out.stat().st_size / (1024**3)
            out_size_mb = final_out.stat().st_size / (1024**2)
            size_label = f"{out_size_gb:.2f} GB" if out_size_gb >= 1.0 else f"{out_size_mb:.1f} MB"

            with STATE.lock:
                STATE.finished_outputs.append(
                    {
                        "chunk_index": c_idx,
                        "name": out_filename,
                        "path": str(final_out),
                        "duration_hms": format_hms(out_dur),
                        "duration_human": format_human_duration(out_dur),
                        "size_label": size_label,
                    }
                )
                STATE.active_video_for_srt = str(final_out)

            STATE.add_log(
                f"🎉 [HOÀN TẤT PHẦN {c_idx}] Đã xuất: output/{out_filename} "
                f"({format_human_duration(out_dur)} | {size_label})"
            )

            if bool(STATE.settings.get("clean_temp_after_done", True)):
                for nf in chunk_norm_files:
                    nf.unlink(missing_ok=True)

        if STATE.stop_requested:
            STATE.status_phase = "Đã tạm dừng (Có thể bấm Bắt Đầu để chạy tiếp)"
            STATE.add_log("⏹ Đã tạm dừng theo yêu cầu.")
        else:
            if bool(STATE.settings.get("clean_temp_after_done", True)):
                shutil.rmtree(PROCESSED_DIR, ignore_errors=True)
                shutil.rmtree(UPLOAD_CACHE_DIR, ignore_errors=True)
            with STATE.lock:
                STATE.overall_pct = 100.0
                STATE.current_ep_pct = 100.0
                STATE.status_phase = f"🎉 HOÀN THÀNH {total_chunks} PHẦN ĐÃ CHỌN!"
            STATE.add_log(f"🏆 [HOÀN THÀNH] Đã xuất xong {total_chunks} phần vào thư mục output/!")

    except Exception as exc:
        with STATE.lock:
            STATE.error_message = str(exc)
            STATE.status_phase = f"❌ Có lỗi xảy ra: {exc}"
        STATE.add_log(f"❌ [LỖI] {exc}")
    finally:
        with STATE.lock:
            STATE.is_running = False
            STATE.current_proc = None


def _run_gui_ffmpeg(
    cmd: List[str],
    expected_duration: float,
    ep_idx: int,
    total_eps: int,
    is_concat: bool = False,
) -> int:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    with STATE.lock:
        STATE.current_proc = proc

    total_us = max(1, int(expected_duration * 1_000_000))
    if proc.stdout:
        for line in proc.stdout:
            if STATE.stop_requested:
                proc.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                val_str = line.split("=", 1)[1].strip()
                if val_str.isdigit():
                    cur_us = min(int(val_str), total_us)
                    ep_pct = round((cur_us / total_us) * 100.0, 1)
                    with STATE.lock:
                        STATE.current_ep_pct = ep_pct
                        if not is_concat:
                            base = ((ep_idx - 1) / max(1, total_eps)) * 92.0
                            step = (ep_pct / 100.0) * (92.0 / max(1, total_eps))
                            STATE.overall_pct = min(99.0, round(base + step, 1))
                        else:
                            STATE.overall_pct = min(99.5, round(92.0 + (ep_pct * 0.08), 1))
    return proc.wait()


class GuiRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _stream_video_file(self, video_path: Path) -> None:
        if not video_path.is_file():
            self.send_error(404, "Video not found")
            return

        file_size = video_path.stat().st_size
        ext = video_path.suffix.lower()
        mime_map = {
            ".mp4": "video/mp4",
            ".m4v": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
        }
        content_type = mime_map.get(ext, "video/mp4")

        range_header = self.headers.get("Range")
        start = 0
        end = file_size - 1
        status_code = 200

        if range_header and range_header.startswith("bytes="):
            try:
                range_spec = range_header.split("=", 1)[1].strip()
                parts = range_spec.split("-", 1)
                if parts[0]:
                    start = int(parts[0])
                if len(parts) > 1 and parts[1]:
                    end = min(file_size - 1, int(parts[1]))
                if 0 <= start <= end < file_size:
                    status_code = 206
            except Exception:
                start = 0
                end = file_size - 1
                status_code = 200

        chunk_len = max(0, end - start + 1)
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            if status_code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(chunk_len))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            with open(video_path, "rb") as f:
                f.seek(start)
                remaining = chunk_len
                buf_size = 256 * 1024
                while remaining > 0:
                    data = f.read(min(buf_size, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            index_file = WEB_UI_DIR / "index.html"
            content = index_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/api/video-stream":
            qs = urllib.parse.parse_qs(parsed.query)
            req_path = (qs.get("path", [""])[0] or "").strip()
            target = Path(req_path) if req_path else Path(_get_srt_target())
            self._stream_video_file(target)
            return

        if path == "/api/system":
            free_gb = check_disk_space(PROJECT_ROOT, min_recommended_gb=50.0)
            plan = self._compute_plan()
            self._send_json(
                {
                    "os": STATE.os_name,
                    "arch": platform.machine(),
                    "gpu_label": STATE.enc_info["label"],
                    "free_gb": round(free_gb, 1),
                    "project_name": STATE.project_name,
                    "target_hours": STATE.target_hours,
                    "chunk_mode": STATE.chunk_mode,
                    "selected_chunks": STATE.selected_chunks,
                    "settings": STATE.settings,
                    "plan": plan,
                    "srt_rows": STATE.srt_rows,
                    "active_srt_path": STATE.active_srt_path,
                    "active_video_for_srt": _get_srt_target(),
                    "available_videos": _list_available_preview_videos(),
                    "available_audios": _list_available_tts_audios(),
                    "finished_outputs": STATE.finished_outputs,
                    "srt_status_msg": STATE.srt_status_msg,
                }
            )
            return

        if path == "/api/status":
            with STATE.lock:
                elapsed = int(time.time() - STATE.started_at) if STATE.is_running and STATE.started_at else 0
                self._send_json(
                    {
                        "is_running": STATE.is_running,
                        "status_phase": STATE.status_phase,
                        "current_chunk_idx": STATE.current_chunk_idx,
                        "total_chunks": STATE.total_chunks,
                        "current_ep_idx": STATE.current_ep_idx,
                        "total_eps": STATE.total_eps,
                        "current_ep_pct": STATE.current_ep_pct,
                        "overall_pct": STATE.overall_pct,
                        "elapsed_hms": format_hms(elapsed),
                        "logs": STATE.logs[-60:],
                        "finished_outputs": STATE.finished_outputs,
                        "active_video_for_srt": _get_srt_target(),
                        "available_videos": _list_available_preview_videos(),
                    "available_audios": _list_available_tts_audios(),
                        "error_message": STATE.error_message,
                        "srt_status_msg": STATE.srt_status_msg,
                    }
                )
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/upload-chunk":
            filename = urllib.parse.unquote(self.headers.get("X-File-Name", "video.mp4"))
            offset = int(self.headers.get("X-Chunk-Offset", "0"))
            is_last = self.headers.get("X-Chunk-Last", "0") == "1"
            length = int(self.headers.get("Content-Length", "0"))
            chunk_bytes = self.rfile.read(length)

            UPLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            safe_name = os.path.basename(filename)
            target_path = UPLOAD_CACHE_DIR / safe_name

            mode = "wb" if offset == 0 else "ab"
            with open(target_path, mode) as f:
                f.write(chunk_bytes)

            if is_last:
                meta = probe_item_metadata(STATE.ffprobe_path, str(target_path))
                with STATE.lock:
                    existing_ids = {it["id"] for it in STATE.items}
                    if meta["id"] not in existing_ids:
                        STATE.items.append(meta)
                return self._send_current_plan(reset_selection=True)

            self._send_json({"ok": True, "offset": offset + length})
            return

        body = self._read_json_body()

        if path == "/api/pick-files":
            chosen = _native_pick_files()
            if chosen:
                new_metas = probe_multiple_items(STATE.ffprobe_path, chosen)
                with STATE.lock:
                    existing_ids = {it["id"] for it in STATE.items}
                    for m in new_metas:
                        if m["id"] not in existing_ids:
                            STATE.items.append(m)
                            existing_ids.add(m["id"])
            return self._send_current_plan(reset_selection=True)

        if path == "/api/pick-folder":
            chosen = _native_pick_folder()
            if chosen:
                new_metas = probe_multiple_items(STATE.ffprobe_path, chosen)
                with STATE.lock:
                    existing_ids = {it["id"] for it in STATE.items}
                    for m in new_metas:
                        if m["id"] not in existing_ids:
                            STATE.items.append(m)
                            existing_ids.add(m["id"])
            return self._send_current_plan(reset_selection=True)

        if path == "/api/resolve-dropped":
            dropped_list = body.get("files", [])
            resolved_paths: List[str] = []
            unresolved_indices: List[int] = []

            for idx, info in enumerate(dropped_list):
                fname = str(info.get("name", ""))
                fsize = int(info.get("size", 0) or 0)
                full_path = str(info.get("path", "") or "").strip()

                if full_path and Path(full_path).is_file():
                    resolved_paths.append(str(Path(full_path).resolve()))
                    continue

                found = resolve_dropped_file_on_disk(fname, fsize, STATE.recent_folders)
                if found is not None:
                    resolved_paths.append(str(found))
                else:
                    unresolved_indices.append(idx)

            if resolved_paths:
                resolved_paths.sort(key=lambda p: natural_sort_key(Path(p).name))
                new_metas = probe_multiple_items(STATE.ffprobe_path, resolved_paths)
                with STATE.lock:
                    existing_ids = {it["id"] for it in STATE.items}
                    for m in new_metas:
                        if m["id"] not in existing_ids:
                            STATE.items.append(m)
                            existing_ids.add(m["id"])

            plan = self._compute_plan(reset_selection=True)
            self._send_json(
                {
                    "ok": True,
                    "unresolved_indices": unresolved_indices,
                    "plan": plan,
                    "selected_chunks": STATE.selected_chunks,
                }
            )
            return

        if path == "/api/add-links":
            raw_links = body.get("links", [])
            valid_links = [str(x).strip() for x in raw_links if str(x).strip()]
            try:
                new_metas = probe_multiple_items(
                    STATE.ffprobe_path, valid_links, str(STATE.settings.get("cookies_from_browser", ""))
                )
            except Exception as exc:
                self._send_json({"ok": False, "message": str(exc)}, status=400)
                return
            with STATE.lock:
                new_ids = {m["id"] for m in new_metas}
                # Xóa bản cache cũ nếu dán lại cùng link để luôn cập nhật đúng thời lượng thật (ví dụ 2 tiếng)
                STATE.items = [it for it in STATE.items if it["id"] not in new_ids]
                for m in new_metas:
                    STATE.items.append(m)
            return self._send_current_plan(reset_selection=True)

        if path == "/api/update-config":
            reset_sel = False
            with STATE.lock:
                if "project_name" in body:
                    STATE.project_name = str(body["project_name"]).strip() or "Phim_Cat_15_Phut"
                if "target_hours" in body:
                    new_th = float(body["target_hours"] or 0.25)
                    if abs(new_th - STATE.target_hours) > 1e-4:
                        STATE.target_hours = new_th
                        reset_sel = True
                if "chunk_mode" in body:
                    new_cm = str(body["chunk_mode"])
                    if new_cm != STATE.chunk_mode:
                        STATE.chunk_mode = new_cm
                        reset_sel = True
                if "selected_chunks" in body and isinstance(body["selected_chunks"], list):
                    STATE.selected_chunks = [int(x) for x in body["selected_chunks"]]
                if "settings" in body and isinstance(body["settings"], dict):
                    for k, v in body["settings"].items():
                        if k == "anti_copyright" and isinstance(v, dict):
                            STATE.settings["anti_copyright"].update(v)
                        elif k == "blur_sub" and isinstance(v, dict):
                            STATE.settings.setdefault("blur_sub", {}).update(v)
                        else:
                            STATE.settings[k] = v
            return self._send_current_plan(reset_selection=reset_sel)

        if path == "/api/blur-video-now":
            target_vid = str(body.get("path", "") or _get_srt_target()).strip()
            if (not target_vid or not Path(target_vid).is_file()) and not locals().get("only_mp3", False):
                self._send_json({"ok": False, "message": "Chưa có video nào đang được chọn để làm mờ chữ Trung Quốc!"})
                return
            blur_cfg = body.get("blur_sub") or STATE.settings.get("blur_sub") or {}
            mode_str = str(blur_cfg.get("mode", "delogo") or "delogo").lower()
            if mode_str in ("off", "none", ""):
                mode_str = "delogo"
                blur_cfg = dict(blur_cfg, mode="delogo")

            from core.processor import _parse_resolution, build_blur_sub_filter

            in_p = Path(target_vid).resolve()
            out_p = OUTPUT_DIR / f"{in_p.stem}_Mo_Sub_Trung.mp4"
            # Đo kích thước thực của video đầu vào
            vid_w, vid_h = _parse_resolution(str(STATE.settings.get("resolution", "1920x1080")))
            try:
                if STATE.ffprobe_path:
                    res_probe = subprocess.run(
                        [
                            STATE.ffprobe_path,
                            "-v",
                            "error",
                            "-select_streams",
                            "v:0",
                            "-show_entries",
                            "stream=width,height",
                            "-of",
                            "json",
                            str(in_p),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    pdata = json.loads(res_probe.stdout or "{}")
                    st_list = pdata.get("streams") or []
                    if st_list:
                        vid_w = int(st_list[0].get("width") or vid_w)
                        vid_h = int(st_list[0].get("height") or vid_h)
            except Exception:
                pass

            flt = build_blur_sub_filter(vid_w, vid_h, blur_cfg)
            if not flt:
                self._send_json({"ok": False, "message": "Hãy chọn chế độ làm mờ chữ Trung Quốc trước!"})
                return

            STATE.add_log(f"🌫️ Đang làm mờ chữ Trung Quốc trên video: {in_p.name} ➔ {out_p.name}...")
            cmd_blur = [
                STATE.ffmpeg_path,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(in_p),
                "-vf",
                flt,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(out_p),
            ]
            res_b = subprocess.run(cmd_blur, capture_output=True, text=True, check=False)
            if res_b.returncode != 0 or not out_p.is_file():
                self._send_json({"ok": False, "message": f"Làm mờ chữ thất bại: {res_b.stderr}"})
                return

            with STATE.lock:
                STATE.active_video_for_srt = str(out_p.resolve())
                STATE.srt_status_msg = f"✅ Đã làm mờ chữ Trung Quốc xong: {out_p.name}"
            STATE.add_log(f"✅ Đã xuất video làm mờ chữ Trung Quốc: {out_p.name}")
            self._send_json(
                {
                    "ok": True,
                    "blurred_video": str(out_p.resolve()),
                    "active_video_for_srt": str(out_p.resolve()),
                    "available_videos": _list_available_preview_videos(),
                    "available_audios": _list_available_tts_audios(),
                    "message": f"🎉 Đã làm mờ chữ Trung Quốc thành công: {out_p.name}",
                }
            )
            return

        if path == "/api/set-active-video":
            vid_path = str(body.get("path", "") or "").strip()
            if vid_path and Path(vid_path).is_file():
                resolved_vid = Path(vid_path).resolve()
                stem = resolved_vid.stem.replace("_Lồng_Tiếng_Việt", "")
                vi_candidate = SRT_WORK_DIR / f"{stem}.vi.srt"
                zh_candidate = SRT_WORK_DIR / f"{stem}.zh.srt"
                with STATE.lock:
                    STATE.active_video_for_srt = str(resolved_vid)
                    if vi_candidate.is_file() and vi_candidate.stat().st_size > 10:
                        vi_cues = parse_srt_text(vi_candidate.read_text(encoding="utf-8-sig", errors="replace"))
                        zh_map_local: Dict[int, str] = {}
                        if zh_candidate.is_file():
                            for zc in parse_srt_text(zh_candidate.read_text(encoding="utf-8-sig", errors="replace")):
                                zh_map_local[zc["index"]] = zc["text"]
                        STATE.srt_rows = [
                            {
                                "index": c["index"],
                                "start": c["start"],
                                "end": c["end"],
                                "zh_text": zh_map_local.get(c["index"], ""),
                                "vi_text": c["text"],
                            }
                            for c in vi_cues
                        ]
                        STATE.active_srt_path = str(vi_candidate)
                        STATE.srt_status_msg = f"🎬 Đang xem & chỉnh phụ đề cho: {resolved_vid.name} ({len(STATE.srt_rows)} câu)"
                    else:
                        STATE.srt_status_msg = f"🎬 Đang xem trước video: {resolved_vid.name}"
            self._send_json(
                {
                    "ok": True,
                    "active_video_for_srt": _get_srt_target(),
                    "available_videos": _list_available_preview_videos(),
                    "available_audios": _list_available_tts_audios(),
                    "srt_rows": STATE.srt_rows,
                    "active_srt_path": STATE.active_srt_path,
                    "srt_status_msg": STATE.srt_status_msg,
                }
            )
            return

        if path == "/api/reorder":
            action = body.get("action", "")
            index = int(body.get("index", -1))
            with STATE.lock:
                if action == "sort_natural":
                    STATE.items.sort(key=lambda it: natural_sort_key(it["name"]))
                elif action == "clear_all":
                    STATE.items.clear()
                    STATE.selected_chunks.clear()
                elif action == "remove" and 0 <= index < len(STATE.items):
                    STATE.items.pop(index)
                elif action == "move_up" and 0 < index < len(STATE.items):
                    STATE.items[index - 1], STATE.items[index] = (
                        STATE.items[index],
                        STATE.items[index - 1],
                    )
                elif action == "move_down" and 0 <= index < len(STATE.items) - 1:
                    STATE.items[index + 1], STATE.items[index] = (
                        STATE.items[index],
                        STATE.items[index + 1],
                    )
            return self._send_current_plan(reset_selection=True)

        # ================== API BẢNG SỬA PHỤ ĐỀ (.SRT) THỦ CÔNG & LỒNG TIẾNG ==================
        if path == "/api/srt/pick-file":
            chosen_srt = _native_pick_srt_file()
            if chosen_srt and Path(chosen_srt).is_file():
                raw_text = Path(chosen_srt).read_text(encoding="utf-8-sig", errors="replace")
                cues = parse_srt_text(raw_text)
                # Kiểm tra nếu có file .zh.srt cùng tên để nạp song ngữ đối chiếu
                zh_candidate = Path(chosen_srt).with_suffix("").with_suffix(".zh.srt")
                zh_map: Dict[int, str] = {}
                if zh_candidate.is_file():
                    for zc in parse_srt_text(zh_candidate.read_text(encoding="utf-8-sig", errors="replace")):
                        zh_map[zc["index"]] = zc["text"]

                rows = []
                for c in cues:
                    rows.append(
                        {
                            "index": c["index"],
                            "start": c["start"],
                            "end": c["end"],
                            "zh_text": zh_map.get(c["index"], ""),
                            "vi_text": c["text"],
                        }
                    )
                with STATE.lock:
                    STATE.srt_rows = rows
                    STATE.active_srt_path = str(Path(chosen_srt).resolve())
                    STATE.srt_status_msg = f"Đã mở file: {Path(chosen_srt).name} ({len(rows)} câu)"
            self._send_json(
                {
                    "ok": True,
                    "srt_rows": STATE.srt_rows,
                    "active_srt_path": STATE.active_srt_path,
                    "srt_status_msg": STATE.srt_status_msg,
                }
            )
            return

        if path == "/api/srt/save":
            rows = body.get("srt_rows", [])
            custom_path = str(body.get("srt_path", "") or STATE.active_srt_path).strip()
            if not custom_path:
                custom_path = str(SRT_WORK_DIR / "phu_de_da_sua.vi.srt")
            target_p = Path(custom_path)
            target_p.parent.mkdir(parents=True, exist_ok=True)

            srt_text = compose_srt_text(rows)
            target_p.write_text(srt_text, encoding="utf-8")

            with STATE.lock:
                STATE.srt_rows = rows
                STATE.active_srt_path = str(target_p.resolve())
                STATE.srt_status_msg = f"✅ Đã lưu {len(rows)} câu phụ đề vào: {target_p.name}"
            STATE.add_log(f"💾 Đã lưu bản sửa phụ đề thủ công: {target_p}")
            self._send_json(
                {
                    "ok": True,
                    "active_srt_path": STATE.active_srt_path,
                    "srt_status_msg": STATE.srt_status_msg,
                }
            )
            return

        if path == "/api/srt/auto-transcribe":
            # Tự động chạy Bước 1 -> Bước 2 -> Bước 3 từ video để nạp lên bảng cho người dùng sửa
            video_src = _get_srt_target()

            if not video_src or not Path(video_src).is_file():
                self._send_json(
                    {
                        "ok": False,
                        "message": "Hãy chọn hoặc xuất ít nhất 1 file video trên máy trước khi tách phụ đề tự động (hoặc bấm '📂 Mở File .SRT Có Sẵn' để sửa).",
                    }
                )
                return

            try:
                import importlib
                import audio_sub_pipeline

                importlib.reload(audio_sub_pipeline)
                from audio_sub_pipeline import extract_audio, transcribe_chinese, translate_srt

                def set_srt_phase(message: str) -> None:
                    with STATE.lock:
                        STATE.srt_status_msg = message
                    STATE.add_log(message)

                SRT_WORK_DIR.mkdir(parents=True, exist_ok=True)
                vpath = Path(video_src).resolve()
                stem = vpath.stem
                wav_16k = SRT_WORK_DIR / f"{stem}_temp16k.wav"
                zh_srt = SRT_WORK_DIR / f"{stem}.zh.srt"
                vi_srt = SRT_WORK_DIR / f"{stem}.vi.srt"

                reuse_zh = (
                    not bool(body.get("force_retranscribe"))
                    and zh_srt.is_file()
                    and zh_srt.stat().st_size > 20
                    and zh_srt.stat().st_mtime >= vpath.stat().st_mtime
                )
                if reuse_zh:
                    set_srt_phase("🎙️ Dùng lại phụ đề tiếng Trung vừa nhận diện xong...")
                else:
                    set_srt_phase(f"🎵 Đang tách âm thanh từ {vpath.name}...")
                    extract_audio(str(vpath), str(wav_16k))
                    whisper_model = str(STATE.settings.get("whisper_model", "small") or "small")
                    if whisper_model not in {"base", "small", "medium"}:
                        whisper_model = "small"
                    set_srt_phase(f"🎙️ Đang tải/khởi tạo Whisper {whisper_model} và nhận diện tiếng Trung. Lần đầu cần tải mô hình...")
                    transcribe_chinese(str(wav_16k), str(zh_srt), model_size=whisper_model)
                set_srt_phase("🌐 Đã nhận diện xong, đang dịch phụ đề sang Tiếng Việt...")
                translate_srt(
                    str(zh_srt), str(vi_srt),
                    progress_callback=lambda done, total: set_srt_phase(f"🌐 Đang dịch phụ đề sang Tiếng Việt: {done}/{total} câu"),
                )
                wav_16k.unlink(missing_ok=True)

                zh_cues = parse_srt_text(zh_srt.read_text(encoding="utf-8-sig"))
                vi_cues = parse_srt_text(vi_srt.read_text(encoding="utf-8-sig"))
                zh_map = {c["index"]: c["text"] for c in zh_cues}

                rows = [
                    {
                        "index": c["index"],
                        "start": c["start"],
                        "end": c["end"],
                        "zh_text": zh_map.get(c["index"], ""),
                        "vi_text": c["text"],
                    }
                    for c in vi_cues
                ]
                with STATE.lock:
                    STATE.srt_rows = rows
                    STATE.active_srt_path = str(vi_srt)
                    STATE.active_video_for_srt = str(vpath)
                    STATE.srt_status_msg = f"✅ Đã dịch xong {len(rows)} câu! Hãy kiểm tra và sửa câu sai bên dưới."
                self._send_json(
                    {
                        "ok": True,
                        "srt_rows": STATE.srt_rows,
                        "active_srt_path": STATE.active_srt_path,
                        "srt_status_msg": STATE.srt_status_msg,
                    }
                )
            except Exception as exc:
                with STATE.lock:
                    STATE.srt_status_msg = f"❌ Tách/dịch phụ đề thất bại: {exc}"
                self._send_json({"ok": False, "message": str(exc)})
            return

        if path == "/api/srt/pick-audio":
            chosen_audio = _native_pick_audio_file()
            if chosen_audio and Path(chosen_audio).is_file():
                src_p = Path(chosen_audio).resolve()
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                if src_p.parent != OUTPUT_DIR.resolve():
                    dst_p = OUTPUT_DIR / src_p.name
                    try:
                        shutil.copy2(src_p, dst_p)
                        src_p = dst_p.resolve()
                    except Exception:
                        pass
                self._send_json(
                    {
                        "ok": True,
                        "audio_vi": str(src_p),
                        "available_audios": _list_available_tts_audios(),
                        "message": f"🔊 Đã chọn file thuyết minh: {src_p.name}",
                    }
                )
            else:
                self._send_json({"ok": False, "message": "Chưa chọn file âm thanh nào."})
            return

        if path == "/api/srt/export-capcut-video":
            # Xuất Video Hoàn Chỉnh Kiểu CapCut từ:
            # 1) Video đang chọn + 2) Vùng làm mờ chữ Trung + 3) Hardsub Tiếng Việt kiểu CapCut + 4) File .mp3 thuyết minh đã có sẵn!
            rows = body.get("srt_rows", STATE.srt_rows)
            target_vid = str(body.get("video_path", "") or _get_srt_target()).strip()
            if (not target_vid or not Path(target_vid).is_file()) and not locals().get("only_mp3", False):
                self._send_json({"ok": False, "message": "Chưa có video để xuất! Hãy chọn video trên trình Xem Trước hoặc hoàn tất Bước 3."})
                return

            SRT_WORK_DIR.mkdir(parents=True, exist_ok=True)
            srt_file = Path(STATE.active_srt_path or (SRT_WORK_DIR / f"{Path(target_vid).stem}.vi.srt"))
            if isinstance(rows, list) and len(rows) > 0:
                srt_file.parent.mkdir(parents=True, exist_ok=True)
                srt_file.write_text(compose_srt_text(rows), encoding="utf-8")
                with STATE.lock:
                    STATE.srt_rows = rows
                    STATE.active_srt_path = str(srt_file.resolve())

            req_audio = str(body.get("audio_path", "") or "").strip()
            if not req_audio or not Path(req_audio).is_file():
                avail_audios = _list_available_tts_audios()
                if avail_audios:
                    req_audio = avail_audios[0]["path"]

            blur_cfg = body.get("blur_sub") if isinstance(body.get("blur_sub"), dict) else STATE.settings.get("blur_sub", {})
            burn_cfg = body.get("burn_sub") if isinstance(body.get("burn_sub"), dict) else {"enabled": True, "color": "yellow", "font_size": 52, "box": True}
            orig_vol = float(body.get("original_vol", 0.12) if body.get("original_vol") is not None else 0.12)
            tts_vol = float(body.get("tts_vol", 1.0) if body.get("tts_vol") is not None else 1.0)

            try:
                import importlib
                import audio_sub_pipeline

                importlib.reload(audio_sub_pipeline)
                from audio_sub_pipeline import _probe_duration, generate_tts_from_srt, mux_dubbed_video

                # Nếu người dùng chưa có file .mp3 nào nhưng bấm Xuất luôn và có sub Tiếng Việt -> tự tạo .mp3
                if (not req_audio or not Path(req_audio).is_file()) and srt_file.is_file():
                    voice = str(body.get("voice", "vi-VN-NamMinhNeural"))
                    auto_mp3 = OUTPUT_DIR / f"{Path(target_vid).stem}.vi_thuyet_minh.mp3"
                    STATE.add_log(f"🗣️ Chưa có file .mp3 sẵn, đang tự động tạo thuyết minh ({voice})...")
                    video_duration = _probe_duration(STATE.ffprobe_path, str(target_vid)) if STATE.ffprobe_path else 0.0
                    def _on_tts_prog_auto(done_c: int, total_c: int, snippet: str) -> None:
                        pct = int(round((done_c / max(1, total_c)) * 100))
                        with STATE.lock:
                            STATE.srt_status_msg = f"🗣️ Đang tạo file .MP3 thuyết minh: {done_c}/{total_c} câu ({pct}%) — {snippet}"

                    generate_tts_from_srt(
                        str(srt_file),
                        str(auto_mp3),
                        voice=voice,
                        total_video_duration=video_duration,
                        progress_callback=_on_tts_prog_auto,
                    )
                    req_audio = str(auto_mp3.resolve())

                base_stem = Path(target_vid).stem
                for suffix in ("_CapCut_Hoan_Chinh", "_Lồng_Tiếng_Việt", "_Da_Xoa_Sub_Trung"):
                    if base_stem.endswith(suffix):
                        base_stem = base_stem[: -len(suffix)]
                out_mp4 = OUTPUT_DIR / f"{base_stem}_CapCut_Hoan_Chinh.mp4"

                with STATE.lock:
                    STATE.srt_status_msg = f"🎬 Đang kết xuất video CapCut (Làm mờ chữ Trung + In Sub Việt + Ghép MP3): {out_mp4.name}..."
                STATE.add_log(f"🎬 Đang kết xuất video chuẩn CapCut ➔ {out_mp4.name} (MP3: {Path(req_audio).name if req_audio else 'Không dùng'})...")

                mux_dubbed_video(
                    input_video=str(target_vid),
                    input_audio_vi=req_audio if (req_audio and Path(req_audio).is_file()) else None,
                    input_srt_vi=str(srt_file) if srt_file.is_file() else None,
                    output_video_path=str(out_mp4),
                    original_audio_volume=orig_vol,
                    tts_audio_volume=tts_vol,
                    blur_sub_cfg=blur_cfg,
                    burn_sub_cfg=burn_cfg,
                )

                size_mb = out_mp4.stat().st_size / (1024 * 1024)
                dur_sec = _probe_duration(STATE.ffprobe_path, str(out_mp4)) if STATE.ffprobe_path else 0.0
                with STATE.lock:
                    STATE.active_video_for_srt = str(out_mp4.resolve())
                    STATE.finished_outputs = [
                        f for f in STATE.finished_outputs if f.get("path") != str(out_mp4.resolve())
                    ]
                    STATE.finished_outputs.append(
                        {
                            "index": len(STATE.finished_outputs) + 1,
                            "name": out_mp4.name,
                            "path": str(out_mp4.resolve()),
                            "duration_human": format_hms(dur_sec),
                            "size_label": f"{size_mb:.1f} MB",
                        }
                    )
                    STATE.srt_status_msg = f"🎉 Đã xuất xong Video CapCut Hoàn Chỉnh: {out_mp4.name} ({size_mb:.1f} MB)!"
                STATE.add_log(f"✅ Đã xuất xong Video CapCut Hoàn Chỉnh: {out_mp4.name} ({size_mb:.1f} MB)")

                self._send_json(
                    {
                        "ok": True,
                        "dubbed_video": str(out_mp4.resolve()),
                        "audio_vi": req_audio,
                        "active_video_for_srt": str(out_mp4.resolve()),
                        "available_videos": _list_available_preview_videos(),
                        "available_audios": _list_available_tts_audios(),
                        "finished_outputs": STATE.finished_outputs,
                        "message": f"🎉 Đã xuất xong Video CapCut Hoàn Chỉnh: {out_mp4.name} ({size_mb:.1f} MB)!",
                    }
                )
            except Exception as exc:
                with STATE.lock:
                    STATE.srt_status_msg = f"❌ Lỗi xuất video CapCut: {exc}"
                self._send_json({"ok": False, "message": str(exc)})
            return

        if path == "/api/srt/generate-tts":
            only_mp3 = bool(body.get("only_mp3", False))
            # Lưu bản sub đã sửa thủ công và tạo file thuyết minh .mp3 (+ ghép vào video nếu có)
            rows = body.get("srt_rows", STATE.srt_rows)
            voice = str(body.get("voice", "vi-VN-NamMinhNeural"))
            target_vid = _get_srt_target()
            if (not target_vid or not Path(target_vid).is_file()) and not locals().get("only_mp3", False):
                self._send_json({"ok": False, "message": "Chưa có video để ghép thuyết minh. Hãy xuất xong Bước 3 hoặc chọn file video trên máy."})
                return
            if not isinstance(rows, list) or not any(str(row.get("vi_text", "")).strip() for row in rows if isinstance(row, dict)):
                self._send_json({"ok": False, "message": "Chưa có phụ đề Tiếng Việt. Hãy tách phụ đề từ video hoặc mở file .SRT trước."})
                return
            SRT_WORK_DIR.mkdir(parents=True, exist_ok=True)
            srt_file = Path(STATE.active_srt_path or (SRT_WORK_DIR / "phu_de_da_sua.vi.srt"))
            srt_file.parent.mkdir(parents=True, exist_ok=True)
            srt_file.write_text(compose_srt_text(rows), encoding="utf-8")

            out_mp3 = OUTPUT_DIR / f"{srt_file.stem}_thuyet_minh.mp3"
            try:
                import importlib
                import audio_sub_pipeline

                importlib.reload(audio_sub_pipeline)
                from audio_sub_pipeline import _probe_duration, generate_tts_from_srt, mux_dubbed_video

                STATE.add_log(f"🗣️ Đang tạo Thuyết Minh Tiếng Việt ({voice}) từ bản phụ đề bạn đã sửa...")
                video_duration = (
                    _probe_duration(STATE.ffprobe_path, str(target_vid))
                    if (STATE.ffprobe_path and target_vid and Path(target_vid).is_file())
                    else 0.0
                )

                def _on_tts_prog(done_c: int, total_c: int, snippet: str) -> None:
                    pct = int(round((done_c / max(1, total_c)) * 100))
                    with STATE.lock:
                        STATE.srt_status_msg = f"🗣️ Đang tạo file .MP3 thuyết minh: {done_c}/{total_c} câu ({pct}%) — {snippet}"

                (generate_tts_from_srt if not out_mp3.is_file() or out_mp3.stat().st_mtime < srt_file.stat().st_mtime else (lambda *a, **kw: str(out_mp3)))(
                    str(srt_file),
                    str(out_mp3),
                    voice=voice,
                    total_video_duration=video_duration,
                    progress_callback=_on_tts_prog,
                )
                if False: generate_tts_from_srt(
                    str(srt_file),
                    str(out_mp3),
                    voice=voice,
                    total_video_duration=video_duration,
                    progress_callback=_on_tts_prog,
                )
                if False:
                    pass
                pass
                (generate_tts_from_srt if not out_mp3.is_file() or out_mp3.stat().st_mtime < srt_file.stat().st_mtime else (lambda *a, **kw: str(out_mp3)))(
                    str(srt_file),
                    str(out_mp3),
                    voice=voice,
                    total_video_duration=video_duration,
                    progress_callback=_on_tts_prog,
                )
                if False: generate_tts_from_srt(
                    str(srt_file), str(out_mp3), voice=voice,
                    total_video_duration=video_duration,
                )

                dubbed_mp4 = None
                if not only_mp3:
                    dubbed_mp4 = OUTPUT_DIR / f"{Path(target_vid).stem}_CapCut_Hoan_Chinh.mp4"
                    mux_dubbed_video(
                        str(target_vid),
                        str(out_mp3),
                        str(srt_file),
                        str(dubbed_mp4),
                        blur_sub_cfg=STATE.settings.get("blur_sub", {}),
                        burn_sub_cfg={"enabled": True, "color": "yellow", "font_size": 52, "box": True},
                    )
                    STATE.add_log(f"🎬 Đã ghép Thuyết Minh + Phụ Đề đã sửa vào video: {dubbed_mp4.name}")
                else:
                    STATE.add_log(f"🔊 Đã xuất xong file MP3 thuyết minh: {out_mp3.name}")

                self._send_json(
                    {
                        "ok": True,
                        "audio_vi": str(out_mp3.resolve()),
                        "available_audios": _list_available_tts_audios(),
                        "dubbed_video": str(dubbed_mp4.resolve()) if dubbed_mp4 else None,
                        "message": f"🎉 Đã tạo xong file thuyết minh: {out_mp3.name}"
                        + (f" và video CapCut: {dubbed_mp4.name}" if dubbed_mp4 else ""),
                    }
                )
            except Exception as exc_tts:
                self._send_json({"ok": False, "message": str(exc_tts)})
            return

        if False:
                dubbed_mp4 = OUTPUT_DIR / f"{Path(target_vid).stem}_Lồng_Tiếng_Việt.mp4"
                mux_dubbed_video(str(target_vid), str(out_mp3), str(srt_file), str(dubbed_mp4))
                STATE.add_log(f"🎬 Đã ghép Thuyết Minh + Phụ Đề đã sửa vào video: {dubbed_mp4.name}")

                self._send_json(
                    {
                        "ok": True,
                        "audio_vi": str(out_mp3),
                        "dubbed_video": str(dubbed_mp4) if dubbed_mp4 else None,
                        "message": f"🎉 Đã tạo xong file thuyết minh: {out_mp3.name}"
                        + (f" và video lồng tiếng: {dubbed_mp4.name}" if dubbed_mp4 else ""),
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "message": str(exc)})
            return

        if path == "/api/start":
            with STATE.lock:
                if STATE.is_running:
                    self._send_json({"ok": False, "message": "Đang trong quá trình xử lý!"})
                    return
                if not STATE.items:
                    self._send_json({"ok": False, "message": "Chưa có tập video nào trong danh sách!"})
                    return
                STATE.is_running = True
                STATE.stop_requested = False
                STATE.overall_pct = 0.0
                STATE.current_ep_pct = 0.0

            worker = threading.Thread(target=_run_pipeline_worker, daemon=True)
            worker.start()
            self._send_json({"ok": True})
            return

        if path == "/api/stop":
            with STATE.lock:
                STATE.stop_requested = True
                if STATE.current_proc is not None:
                    try:
                        STATE.current_proc.terminate()
                    except Exception:
                        pass
            self._send_json({"ok": True})
            return

        if path == "/api/open-output":
            _open_folder_in_os(OUTPUT_DIR)
            self._send_json({"ok": True, "path": str(OUTPUT_DIR)})
            return

        self.send_error(404)

    def _compute_plan(self, reset_selection: bool = False) -> Dict[str, Any]:
        ac_params = _get_effective_anti_copyright_params(STATE.settings)
        plan = build_target_chunks(
            items=STATE.items,
            project_name=STATE.project_name,
            target_hours=STATE.target_hours,
            chunk_mode=STATE.chunk_mode,
            trim_start_sec=float(STATE.settings.get("trim_start_sec", 0.0)),
            trim_end_sec=float(STATE.settings.get("trim_end_sec", 0.0)),
            speed_factor=ac_params["speed_factor"],
        )
        chunks = plan.get("chunks", [])
        if reset_selection or not STATE.selected_chunks:
            # Mặc định tự động tích chọn 10 phần đầu tiên (ví dụ Phần 1 -> Phần 10 của mức 15 phút)
            STATE.selected_chunks = [c["chunk_index"] for c in chunks[:10]]
        else:
            valid_ids = {c["chunk_index"] for c in chunks}
            STATE.selected_chunks = [idx for idx in STATE.selected_chunks if idx in valid_ids]
            if not STATE.selected_chunks and chunks:
                STATE.selected_chunks = [c["chunk_index"] for c in chunks[:10]]
        return plan

    def _send_current_plan(self, reset_selection: bool = False) -> None:
        plan = self._compute_plan(reset_selection=reset_selection)
        self._send_json(
            {
                "ok": True,
                "plan": plan,
                "selected_chunks": STATE.selected_chunks,
            }
        )


def start_gui_server(port: int = 8765, open_browser: bool = True) -> None:
    WEB_UI_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SRT_WORK_DIR.mkdir(parents=True, exist_ok=True)

    # Tự động giải phóng tiến trình gui_server cũ trên cổng 8765 (nếu có) để luôn dùng bản code mới nhất
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        try:
            res = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True, check=False)
            for pid_str in (res.stdout or "").splitlines():
                pid = int(pid_str.strip())
                if pid != os.getpid():
                    os.kill(pid, 9)
            time.sleep(0.3)
        except Exception:
            pass
    elif sys_name == "windows":
        try:
            res = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, check=False)
            pids = set()
            target_suffix = f":{port}"
            for line in (res.stdout or "").splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(target_suffix) and parts[3].upper() == "LISTENING":
                    if parts[4].isdigit():
                        pid = int(parts[4])
                        if pid > 0 and pid != os.getpid():
                            pids.add(pid)
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
            if pids:
                time.sleep(0.3)
        except Exception:
            pass

    server: Optional[ThreadingHTTPServer] = None
    actual_port = port
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), GuiRequestHandler)
            actual_port = p
            break
        except OSError:
            continue

    if server is None:
        raise RuntimeError("Không thể khởi tạo cổng giao diện Web cục bộ.")

    url = f"http://127.0.0.1:{actual_port}"
    print("=" * 72)
    print("  🎬 GIAO DIỆN CẮT VIDEO 15 PHÚT / 5 TIẾNG & SỬA PHỤ ĐỀ ĐÃ SẴN SÀNG!")
    print(f"  👉 Địa chỉ giao diện: {url}")
    print("  (Cửa sổ trình duyệt sẽ tự động mở. Không tắt cửa sổ đen này khi đang xuất video)")
    print("=" * 72)

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã đóng giao diện.")
        server.server_close()


if __name__ == "__main__":
    no_browser = "--no-browser" in sys.argv
    start_gui_server(open_browser=not no_browser)
