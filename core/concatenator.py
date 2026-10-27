import shutil
from pathlib import Path
from typing import List

from core.logger import log_info, log_success, log_warn
from core.processor import _run_ffmpeg_with_progress, probe_media_info


def _format_duration_hms(seconds: float) -> str:
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def concatenate_videos(
    processed_files: List[Path],
    output_dir: Path,
    project_name: str,
    ffmpeg_path: str,
    ffprobe_path: str,
    raw_dir: Path,
    processed_dir: Path,
    clean_temp: bool = True,
) -> Path:
    """
    Bước 3: Ghép liền mạch toàn bộ các tập đã chuẩn hóa thành 1 video siêu dài duy nhất
    và tự động dọn dẹp file tạm sau khi xuất thành công.
    """
    if not processed_files:
        raise ValueError("Không có tập video nào để ghép nối!")

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(
        c if (c.isalnum() or c in ("_", "-", ".")) else "_" for c in project_name.strip()
    )
    if not safe_name:
        safe_name = "Video_Tong_Hop_Full"
    if not safe_name.lower().endswith(".mp4"):
        safe_name += ".mp4"

    final_output = output_dir / safe_name
    concat_list_path = processed_dir / "concat_list.txt"

    # Tính tổng thời lượng dự kiến và tạo file danh sách ghép nối chuẩn đa nền tảng (Windows + macOS)
    total_duration = 0.0
    lines = []
    for f in processed_files:
        dur, _ = probe_media_info(ffprobe_path, f)
        total_duration += dur
        escaped_path = f.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped_path}'")

    concat_list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    log_info(
        f"Đang nối liền mạch {len(processed_files)} tập -> {final_output.name} "
        f"(Tổng thời lượng dự kiến: {_format_duration_hms(total_duration)})"
    )

    cmd = [
        ffmpeg_path,
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
        str(concat_list_path),
        "-c",
        "copy",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        str(final_output),
    ]

    rc = _run_ffmpeg_with_progress(cmd, total_duration, "Ghép nối thành phẩm")
    if rc != 0 or not final_output.is_file() or final_output.stat().st_size == 0:
        raise RuntimeError("Ghép nối video thất bại! Vui lòng kiểm tra lại dung lượng ổ đĩa.")

    final_dur, _ = probe_media_info(ffprobe_path, final_output)
    final_size_gb = final_output.stat().st_size / (1024**3)
    final_size_mb = final_output.stat().st_size / (1024**2)
    size_str = f"{final_size_gb:.2f} GB" if final_size_gb >= 1.0 else f"{final_size_mb:.1f} MB"

    log_success(
        f"Xuất video thành phẩm hoàn tất: {final_output} "
        f"(Thời lượng: {_format_duration_hms(final_dur)} | Dung lượng: {size_str})"
    )

    if clean_temp:
        log_info("Đang tự động dọn dẹp các file tạm trung gian để giải phóng ổ cứng...")
        for temp_folder in (raw_dir, processed_dir):
            try:
                if temp_folder.exists():
                    shutil.rmtree(temp_folder)
            except Exception as exc:
                log_warn(f"Không thể xóa thư mục tạm {temp_folder.name}: {exc}")
        log_success("Đã dọn sạch thư mục tạm (raw/ & temp_processed/).")

    return final_output
