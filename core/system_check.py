import glob
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from core.logger import log_error, log_info, log_success, log_warn


def get_os_name() -> str:
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        return "macOS"
    elif sys_name == "windows":
        return "Windows"
    return platform.system()


def _candidate_bin_dirs(project_root: Path) -> list[Path]:
    """Trả về danh sách các thư mục có thể chứa ffmpeg/ffprobe trên cả Windows và macOS."""
    dirs = [
        project_root / "bin",
        project_root / "ffmpeg" / "bin",
    ]
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        dirs.extend(
            [
                Path("/opt/homebrew/bin"),
                Path("/usr/local/bin"),
                Path.home() / "bin",
            ]
        )
    elif sys_name == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        user_profile = os.environ.get("USERPROFILE", "")
        if local_app_data:
            winget_links = Path(local_app_data) / "Microsoft" / "WinGet" / "Links"
            dirs.append(winget_links)
            # Tìm trong thư mục cài đặt của WinGet
            winget_pkgs = glob.glob(
                os.path.join(
                    local_app_data,
                    "Microsoft",
                    "WinGet",
                    "Packages",
                    "*FFmpeg*",
                    "**",
                    "bin",
                ),
                recursive=True,
            )
            dirs.extend(Path(p) for p in winget_pkgs)
        if user_profile:
            dirs.append(Path(user_profile) / "scoop" / "shims")
        dirs.extend(
            [
                Path("C:/ffmpeg/bin"),
                Path("C:/ProgramData/chocolatey/bin"),
                Path("C:/Program Files/ffmpeg/bin"),
            ]
        )
    return dirs


def find_ffmpeg_binaries(project_root: Path) -> Tuple[Optional[str], Optional[str]]:
    """Tìm đường dẫn thực thi của ffmpeg và ffprobe trên macOS & Windows."""
    is_win = platform.system().lower() == "windows"
    ffmpeg_name = "ffmpeg.exe" if is_win else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if is_win else "ffprobe"

    # Bổ sung các đường dẫn phổ biến vào biến môi trường PATH của tiến trình hiện tại
    extra_dirs = [str(d) for d in _candidate_bin_dirs(project_root) if d.exists()]
    if extra_dirs:
        os.environ["PATH"] = os.pathsep.join(extra_dirs) + os.pathsep + os.environ.get("PATH", "")

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if not ffmpeg_path:
        for d in _candidate_bin_dirs(project_root):
            candidate = d / ffmpeg_name
            if candidate.is_file():
                ffmpeg_path = str(candidate)
                break

    if not ffprobe_path:
        for d in _candidate_bin_dirs(project_root):
            candidate = d / ffprobe_name
            if candidate.is_file():
                ffprobe_path = str(candidate)
                break

    return ffmpeg_path, ffprobe_path


def _test_encoder(ffmpeg_path: str, encoder: str) -> bool:
    """Chạy thử nghiệm 1 khung hình giả lập để chắc chắn GPU encoder hoạt động thực tế."""
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=256x256:d=0.1",
        "-frames:v",
        "1",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        encoder,
        "-f",
        "null",
        "-",
    ]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def select_video_encoder(ffmpeg_path: str, preferred: str = "auto") -> Dict[str, str]:
    """
    Tự động phát hiện và chọn bộ mã hóa video tối ưu (GPU hoặc CPU) cho cả Windows và macOS.
    Trả về dict gồm: {'encoder': tên_encoder, 'label': mô_tả_hiển_thị}
    """
    preferred = (preferred or "auto").lower().strip()
    sys_name = platform.system().lower()

    if preferred in ("cpu", "libx264"):
        return {"encoder": "libx264", "label": "CPU (libx264 chuẩn quốc tế)"}

    # Thứ tự ưu tiên thử nghiệm theo hệ điều hành
    candidates = []
    if preferred != "auto":
        mapping = {
            "nvenc": ("h264_nvenc", "NVIDIA GPU (NVENC)"),
            "h264_nvenc": ("h264_nvenc", "NVIDIA GPU (NVENC)"),
            "videotoolbox": ("h264_videotoolbox", "Apple GPU / Media Engine (VideoToolbox)"),
            "h264_videotoolbox": ("h264_videotoolbox", "Apple GPU / Media Engine (VideoToolbox)"),
            "amf": ("h264_amf", "AMD GPU (AMF)"),
            "h264_amf": ("h264_amf", "AMD GPU (AMF)"),
            "qsv": ("h264_qsv", "Intel GPU (QuickSync)"),
            "h264_qsv": ("h264_qsv", "Intel GPU (QuickSync)"),
        }
        if preferred in mapping:
            candidates.append(mapping[preferred])

    if sys_name == "darwin":
        candidates.append(("h264_videotoolbox", "Apple Silicon / macOS GPU (h264_videotoolbox)"))
    elif sys_name == "windows":
        candidates.extend(
            [
                ("h264_nvenc", "NVIDIA GPU (h264_nvenc - RTX/GTX)"),
                ("h264_amf", "AMD Radeon GPU (h264_amf)"),
                ("h264_qsv", "Intel GPU (h264_qsv)"),
            ]
        )
    else:
        candidates.extend(
            [
                ("h264_nvenc", "NVIDIA GPU (h264_nvenc)"),
                ("h264_qsv", "Intel GPU (h264_qsv)"),
            ]
        )

    for encoder, label in candidates:
        if _test_encoder(ffmpeg_path, encoder):
            return {"encoder": encoder, "label": label}

    return {"encoder": "libx264", "label": "CPU (libx264 - Đa luồng)"}


def check_disk_space(target_dir: Path, min_recommended_gb: float = 50.0) -> float:
    """Kiểm tra dung lượng ổ cứng trống (GB) và cảnh báo nếu dưới mức khuyến nghị."""
    target_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(target_dir)
    free_gb = usage.free / (1024**3)
    if free_gb < min_recommended_gb:
        log_warn(
            f"Ổ đĩa còn trống {free_gb:.1f} GB (Khuyến nghị >= {min_recommended_gb:.0f} GB cho video dài 3-5 tiếng)."
        )
    else:
        log_info(f"Dung lượng ổ đĩa trống: {free_gb:.1f} GB (Đảm bảo an toàn).")
    return free_gb


def verify_environment(project_root: Path, gpu_pref: str = "auto") -> Dict[str, str]:
    """Kiểm tra toàn diện môi trường chạy trên macOS hoặc Windows."""
    os_label = get_os_name()
    arch = platform.machine()
    log_info(f"Hệ điều hành: {os_label} ({arch}) | Python {platform.python_version()}")

    ffmpeg_path, ffprobe_path = find_ffmpeg_binaries(project_root)
    if not ffmpeg_path or not ffprobe_path:
        log_error("Không tìm thấy bộ công cụ xử lý video FFmpeg / FFprobe trên máy!")
        if os_label == "macOS":
            log_info("👉 Cách cài trên macOS: Mở Terminal và chạy lệnh:  brew install ffmpeg")
        else:
            log_info(
                "👉 Cách cài trên Windows: Mở CMD/PowerShell và chạy lệnh:  winget install Gyan.FFmpeg\n"
                "   Hoặc tải file ffmpeg.exe & ffprobe.exe bỏ vào thư mục 'bin/' của tool."
            )
        raise RuntimeError("Thiếu FFmpeg/FFprobe. Vui lòng cài đặt trước khi chạy tool.")

    check_disk_space(project_root)
    enc_info = select_video_encoder(ffmpeg_path, gpu_pref)
    log_success(f"Chế độ tăng tốc phần cứng: {enc_info['label']}")

    return {
        "os": os_label,
        "ffmpeg": ffmpeg_path,
        "ffprobe": ffprobe_path,
        "encoder": enc_info["encoder"],
        "encoder_label": enc_info["label"],
    }
