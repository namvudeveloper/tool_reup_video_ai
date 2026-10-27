import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.logger import (
    RICH_AVAILABLE,
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    console,
    log_info,
    log_success,
    log_warn,
)


def probe_media_info(ffprobe_path: str, input_file: Path) -> Tuple[float, bool]:
    """
    Lấy thời lượng (giây) và kiểm tra xem video có luồng âm thanh hay không.
    """
    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(input_file),
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        data = json.loads(res.stdout or "{}")
        duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
        streams = data.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        return duration, has_audio
    except Exception:
        return 0.0, True


def _parse_resolution(res_str: str) -> Tuple[int, int]:
    try:
        parts = res_str.lower().replace("*", "x").split("x")
        w = int(parts[0].strip())
        h = int(parts[1].strip())
        return (w - (w % 2), h - (h % 2))
    except Exception:
        return (1920, 1080)


def _get_effective_anti_copyright_params(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trả về bộ thông số lách bản quyền theo Cấp độ (basic | medium | hardcore)
    hoặc thông số tùy chỉnh chi tiết.
    """
    anti_cfg = settings.get("anti_copyright", {}) or {}
    enabled = bool(anti_cfg.get("enabled", True))
    if not enabled:
        return {
            "enabled": False,
            "level": "off",
            "zoom_factor": 1.0,
            "asymmetric_crop": False,
            "micro_rotate_deg": 0.0,
            "brightness": 0.0,
            "contrast": 1.0,
            "saturation": 1.0,
            "gamma_r": 1.0,
            "gamma_g": 1.0,
            "gamma_b": 1.0,
            "hue_shift": 0.0,
            "unsharp": False,
            "film_grain": 0,
            "vignette": False,
            "flip_horizontal": False,
            "speed_factor": 1.0,
            "pitch_shift": 1.0,
            "audio_eq_scrambler": False,
            "audio_stereo_phase": False,
            "audio_pink_noise": False,
            "scramble_gop": False,
        }

    level = str(anti_cfg.get("level", "hardcore")).lower().strip()
    flip_h = bool(anti_cfg.get("flip_horizontal", False))

    if level == "basic":
        return {
            "enabled": True,
            "level": "basic",
            "zoom_factor": float(anti_cfg.get("zoom_factor", 1.02)),
            "asymmetric_crop": False,
            "micro_rotate_deg": 0.0,
            "brightness": float(anti_cfg.get("brightness", 0.015)),
            "contrast": float(anti_cfg.get("contrast", 1.03)),
            "saturation": float(anti_cfg.get("saturation", 1.04)),
            "gamma_r": 1.0,
            "gamma_g": 1.0,
            "gamma_b": 1.0,
            "hue_shift": 0.0,
            "unsharp": False,
            "film_grain": 0,
            "vignette": False,
            "flip_horizontal": flip_h,
            "speed_factor": float(anti_cfg.get("speed_factor", 1.0)),
            "pitch_shift": float(anti_cfg.get("pitch_shift", 1.0)),
            "audio_eq_scrambler": False,
            "audio_stereo_phase": False,
            "audio_pink_noise": False,
            "scramble_gop": False,
        }
    elif level == "medium":
        return {
            "enabled": True,
            "level": "medium",
            "zoom_factor": float(anti_cfg.get("zoom_factor", 1.035)),
            "asymmetric_crop": True,
            "micro_rotate_deg": 0.0,
            "brightness": 0.018,
            "contrast": 1.04,
            "saturation": 1.06,
            "gamma_r": 1.02,
            "gamma_g": 1.0,
            "gamma_b": 0.98,
            "hue_shift": 1.5,
            "unsharp": True,
            "film_grain": 0,
            "vignette": True,
            "flip_horizontal": flip_h,
            "speed_factor": float(anti_cfg.get("speed_factor", 1.03)),
            "pitch_shift": float(anti_cfg.get("pitch_shift", 1.015)),
            "audio_eq_scrambler": True,
            "audio_stereo_phase": True,
            "audio_pink_noise": False,
            "scramble_gop": True,
        }
    else:
        # Chế độ HARDCORE YOUTUBE BYPASS (Mặc định khuyên dùng chống Content ID vID + AudioID)
        return {
            "enabled": True,
            "level": "hardcore",
            "zoom_factor": float(anti_cfg.get("zoom_factor", 1.045)),
            "asymmetric_crop": True,
            "micro_rotate_deg": float(anti_cfg.get("micro_rotate_deg", 0.45)),
            "brightness": 0.02,
            "contrast": 1.05,
            "saturation": 1.07,
            "gamma_r": 1.03,
            "gamma_g": 0.99,
            "gamma_b": 0.97,
            "hue_shift": 2.2,
            "unsharp": True,
            "film_grain": int(anti_cfg.get("film_grain", 2)),
            "vignette": True,
            "flip_horizontal": flip_h,
            "speed_factor": float(anti_cfg.get("speed_factor", 1.04)),
            "pitch_shift": float(anti_cfg.get("pitch_shift", 1.02)),
            "audio_eq_scrambler": True,
            "audio_stereo_phase": True,
            "audio_pink_noise": bool(anti_cfg.get("audio_pink_noise", True)),
            "scramble_gop": True,
        }


def _build_filters(
    settings: Dict[str, Any],
    has_audio: bool,
) -> Tuple[str, str]:
    """
    Xây dựng chuỗi filter hình ảnh (-vf) và âm thanh (-af) chống quét YouTube Content ID
    (Perceptual Frame Hash + Motion Vector + Audio Spectrogram Fingerprinting).
    """
    width, height = _parse_resolution(str(settings.get("resolution", "1920x1080")))
    fps = int(settings.get("fps", 30))
    audio_norm = bool(settings.get("audio_normalize", True))
    p = _get_effective_anti_copyright_params(settings)

    # 1. Chuẩn hóa khung hình gốc về tỉ lệ đích (1920x1080)
    v_filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
        "setsar=1",
    ]

    if p["enabled"]:
        # 2. Xoay nghiêng vi mô (0.45 độ) phá lưới Vector chuyển động và ma trận Macroblock
        rot_deg = p["micro_rotate_deg"]
        if abs(rot_deg) > 0.05:
            v_filters.append(
                f"rotate={rot_deg:.3f}*PI/180:ow={width}:oh={height}:c=black"
            )

        # 3. Cắt lệch tâm bất đối xứng (Asymmetric Crop) + Kéo giãn vi mô lệch trục X/Y
        zoom = p["zoom_factor"]
        if zoom > 1.001:
            if p["asymmetric_crop"]:
                # Cắt lệch trục X và Y khác nhau (X cắt nhiều hơn Y 1.2%) để đổi nhẹ tỉ lệ hình học nội tại
                zx = zoom * 1.012
                zy = zoom
                # Đặt tâm cắt lệch sang trái-trên (0.35 thay vì 0.50 chính giữa) để phá lưới pHash trung tâm
                v_filters.append(
                    f"crop=iw/{zx:.4f}:ih/{zy:.4f}:(iw-ow)*0.36:(ih-oh)*0.38"
                )
            else:
                v_filters.append(
                    f"crop=iw/{zoom:.4f}:ih/{zoom:.4f}:(iw-ow)/2:(ih-oh)/2"
                )
            v_filters.append(f"scale={width}:{height}:flags=lanczos")
            v_filters.append("setsar=1")

        # 4. Biến đổi ma trận màu sắc + lệch kênh RGB Gamma + dịch pha Hue
        v_filters.append(
            f"eq=brightness={p['brightness']:.4f}:contrast={p['contrast']:.4f}:"
            f"saturation={p['saturation']:.4f}:gamma_r={p['gamma_r']:.3f}:"
            f"gamma_g={p['gamma_g']:.3f}:gamma_b={p['gamma_b']:.3f}"
        )
        if abs(p["hue_shift"]) > 0.1:
            v_filters.append(f"hue=h={p['hue_shift']:.2f}")

        # 5. Tăng độ sắc nét viền chi tiết (Unsharp mask) vừa làm phim 3D nét căng vừa đổi hệ số tần số cao DCT
        if p["unsharp"]:
            v_filters.append("unsharp=3:3:0.45:3:3:0.0")

        # 6. Phủ lớp hạt nhiễu vi mô (Temporal Film Grain) làm mỗi khung hình có mã Hash hoàn toàn mới
        if p["film_grain"] > 0:
            strength = min(6, max(1, int(p["film_grain"])))
            v_filters.append(f"noise=alls={strength}:allf=t")

        # 7. Làm tối nhẹ 4 góc khung hình (Cinema Vignette) che dấu vết viền/logo góc
        if p["vignette"]:
            v_filters.append("vignette=PI/10")

        # 8. Lật ngang khung hình (nếu người dùng bật)
        if p["flip_horizontal"]:
            v_filters.append("hflip")

        # 9. Thay đổi tốc độ khung hình theo thời gian thực (Speed Shift)
        speed = p["speed_factor"]
        if abs(speed - 1.0) > 0.004 and 0.5 <= speed <= 2.0:
            v_filters.append(f"setpts=PTS/{speed:.4f}")

    # 10. Ép đồng nhất FPS và định dạng màu chuẩn quốc tế yuv420p
    v_filters.append(f"fps={fps}")
    v_filters.append("format=yuv420p")

    # ================= CHUỖI FILTER ÂM THANH (BYPASS AUDIO CONTENT ID) =================
    a_filters = []
    if has_audio and p["enabled"]:
        speed = p["speed_factor"]
        pitch = p["pitch_shift"]

        # 1. Dịch cao độ (Pitch Shift) + Dịch tốc độ (Tempo) phá vỡ biểu đồ Spectrogram
        if abs(pitch - 1.0) > 0.004 and 0.8 <= pitch <= 1.2:
            a_filters.append(f"asetrate=48000*{pitch:.4f}")
            a_filters.append("aresample=48000")
            comp_tempo = speed / pitch
            if 0.5 <= comp_tempo <= 2.0 and abs(comp_tempo - 1.0) > 0.004:
                a_filters.append(f"atempo={comp_tempo:.4f}")
        elif abs(speed - 1.0) > 0.004 and 0.5 <= speed <= 2.0:
            a_filters.append(f"atempo={speed:.4f}")

        # 2. Cắt lọc dải tần chứa Audio Watermark ẩn & làm lệch các đỉnh phổ nhạc nền (EQ Scrambler)
        if p["audio_eq_scrambler"]:
            a_filters.extend(
                [
                    "highpass=f=70",
                    "lowpass=f=15200",
                    "equalizer=f=320:width_type=q:w=2.0:g=-2.2",
                    "equalizer=f=1150:width_type=q:w=2.0:g=1.8",
                    "equalizer=f=2800:width_type=q:w=2.2:g=-2.5",
                    "equalizer=f=6400:width_type=q:w=1.8:g=2.0",
                ]
            )

        # 3. Mở rộng pha Stereo + Vi phản xạ âm học để làm lệch thuật toán quét Mono của YouTube
        if p["audio_stereo_phase"]:
            a_filters.append("extrastereo=m=1.18")
            a_filters.append("aecho=0.8:0.88:12:0.06")

    if has_audio and audio_norm:
        a_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    a_filters.append("aresample=48000:async=1")
    a_filters.append("aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")

    return ",".join(v_filters), ",".join(a_filters)


def _encoder_args(encoder: str, bitrate: str, scramble_gop: bool = True) -> List[str]:
    """
    Trả về tham số bộ mã hóa phần cứng kèm theo cấu trúc GOP/Keyframe số nguyên tố lẻ (-g 47)
    để phá vỡ nhận diện vị trí cắt cảnh (Scene Cut / I-Frame Fingerprint) của YouTube.
    """
    gop_flags = ["-g", "47"] if scramble_gop else []

    if encoder == "h264_nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-b:v",
            bitrate,
            "-maxrate",
            bitrate,
            "-bufsize",
            "16M",
            "-profile:v",
            "high",
            *gop_flags,
        ]
    elif encoder == "h264_videotoolbox":
        return [
            "-c:v",
            "h264_videotoolbox",
            "-b:v",
            bitrate,
            "-profile:v",
            "high",
            "-allow_sw",
            "1",
            *gop_flags,
        ]
    elif encoder == "h264_amf":
        return [
            "-c:v",
            "h264_amf",
            "-b:v",
            bitrate,
            "-profile:v",
            "high",
            *gop_flags,
        ]
    elif encoder == "h264_qsv":
        return [
            "-c:v",
            "h264_qsv",
            "-b:v",
            bitrate,
            "-profile:v",
            "high",
            *gop_flags,
        ]
    else:
        return [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-maxrate",
            bitrate,
            "-bufsize",
            "16M",
            "-profile:v",
            "high",
            *gop_flags,
        ]


def _run_ffmpeg_with_progress(
    cmd: List[str],
    expected_duration: float,
    task_label: str,
) -> int:
    """Chạy lệnh FFmpeg và hiển thị thanh tiến trình % theo thời gian thực."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    total_us = max(int(expected_duration * 1_000_000), 1)

    if RICH_AVAILABLE and proc.stdout:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold yellow]{task.description}"),
            BarColumn(bar_width=36),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        ) as progress:
            task_id = progress.add_task(task_label, total=total_us)
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    val_str = line.split("=", 1)[1].strip()
                    if val_str.isdigit():
                        current_us = min(int(val_str), total_us)
                        progress.update(task_id, completed=current_us)
                elif line == "progress=end":
                    progress.update(task_id, completed=total_us)
    elif proc.stdout:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                val_str = line.split("=", 1)[1].strip()
                if val_str.isdigit() and expected_duration > 0:
                    pct = min(100.0, (int(val_str) / total_us) * 100.0)
                    print(f"\r  -> {task_label}: {pct:5.1f}%", end="", flush=True)
            elif line == "progress=end":
                print(f"\r  -> {task_label}: 100.0%")

    return proc.wait()


def process_all_videos(
    raw_files: List[Path],
    processed_dir: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    encoder: str,
    settings: Dict[str, Any],
) -> List[Path]:
    """
    Bước 2: Cắt intro/outro, chuẩn hóa 1920x1080 (30/60fps), lách bản quyền hình ảnh & âm thanh.
    """
    processed_dir.mkdir(parents=True, exist_ok=True)
    processed_files: List[Path] = []

    trim_start = float(settings.get("trim_start_sec", 0.0) or 0.0)
    trim_end = float(settings.get("trim_end_sec", 0.0) or 0.0)
    bitrate = str(settings.get("video_bitrate", "8M") or "8M")
    p = _get_effective_anti_copyright_params(settings)
    speed = p["speed_factor"]

    total = len(raw_files)
    for idx, in_file in enumerate(raw_files, start=1):
        out_file = processed_dir / f"norm_{idx:03d}.mp4"

        if out_file.is_file() and out_file.stat().st_size > 100_000:
            size_mb = out_file.stat().st_size / (1024 * 1024)
            log_info(
                f"[Tập {idx}/{total}] Đã xử lý sẵn {out_file.name} ({size_mb:.1f} MB) -> Bỏ qua."
            )
            processed_files.append(out_file)
            continue

        duration, has_audio = probe_media_info(ffprobe_path, in_file)
        actual_start = 0.0
        keep_duration = duration

        if duration > 0 and (trim_start > 0 or trim_end > 0):
            if duration > (trim_start + trim_end + 2.0):
                actual_start = trim_start
                keep_duration = duration - trim_start - trim_end
            else:
                log_warn(
                    f"[Tập {idx}/{total}] Thời lượng video ({duration:.1f}s) quá ngắn để cắt đầu/cuối ({trim_start}s/{trim_end}s) -> Giữ nguyên thời lượng."
                )

        expected_out_dur = keep_duration / speed if speed > 0 else keep_duration
        vf_chain, af_chain = _build_filters(settings, has_audio)

        def _make_cmd(active_encoder: str) -> List[str]:
            cmd = [
                ffmpeg_path,
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

            if keep_duration > 0 and (actual_start > 0 or trim_end > 0):
                cmd.extend(["-t", f"{keep_duration:.3f}"])

            if has_audio:
                cmd.extend(["-map", "0:v:0", "-map", "0:a:0"])
            else:
                cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-shortest"])

            cmd.extend(["-vf", vf_chain, "-af", af_chain])
            cmd.extend(_encoder_args(active_encoder, bitrate, scramble_gop=p["scramble_gop"]))
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
                    str(out_file),
                ]
            )
            return cmd

        log_info(
            f"[Tập {idx}/{total}] Chuẩn hóa 1080p & Lách bản quyền ({p['level'].upper()}): {in_file.name}"
        )
        rc = _run_ffmpeg_with_progress(
            _make_cmd(encoder),
            expected_out_dur,
            f"Xử lý Tập {idx:02d}/{total:02d}",
        )

        if rc != 0 and encoder != "libx264":
            log_warn(
                f"[Tập {idx}/{total}] GPU encoder ({encoder}) trả về mã lỗi {rc}. Tự động chuyển sang CPU (libx264)..."
            )
            rc = _run_ffmpeg_with_progress(
                _make_cmd("libx264"),
                expected_out_dur,
                f"Xử lý Tập {idx:02d}/{total:02d} (CPU)",
            )

        if rc != 0 or not out_file.is_file():
            raise RuntimeError(f"Xử lý thất bại tại tập {idx}: {in_file.name}")

        size_mb = out_file.stat().st_size / (1024 * 1024)
        log_success(f"[Tập {idx}/{total}] Đã chuẩn hóa xong: {out_file.name} ({size_mb:.1f} MB)")
        processed_files.append(out_file)

    return processed_files
