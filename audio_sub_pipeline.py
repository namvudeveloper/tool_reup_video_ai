#!/usr/bin/env python3
"""
audio_sub_pipeline.py
---------------------
Module độc lập xử lý tự động từ Video gốc (tiếng Trung) sang:
1. Phụ đề gốc tiếng Trung (.zh.srt) bằng Faster-Whisper
2. Phụ đề dịch tiếng Việt (.vi.srt) bằng Deep-Translator (GoogleTranslator)
3. Âm thanh Thuyết minh tiếng Việt (.vi.mp3) khớp chuẩn timeline bằng Edge-TTS + FFmpeg
4. (Tùy chọn) Ghép luôn thuyết minh + phụ đề tiếng Việt vào video thành phẩm (.vi_dubbed.mp4)

Hỗ trợ đa nền tảng: macOS (Apple Silicon / Intel) & Windows (NVIDIA CUDA / CPU).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, List, Optional, Tuple

try:
    import srt
except ImportError:
    srt = None  # Sẽ kiểm tra và thông báo hướng dẫn cài đặt khi gọi hàm xử lý SRT

# Đảm bảo hiển thị tiếng Việt UTF-8 trên cả Windows CMD/PowerShell và macOS Terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.system("chcp 65001 >nul 2>&1")


def _find_ffmpeg() -> Tuple[str, str]:
    """Tự động tìm đường dẫn thực thi của ffmpeg và ffprobe trên macOS & Windows."""
    extra_paths = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path(__file__).resolve().parent / "bin"),
        "C:/ffmpeg/bin",
        "C:/ProgramData/chocolatey/bin",
    ]
    os.environ["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + os.environ.get("PATH", "")

    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    if not ffmpeg_bin or not ffprobe_bin:
        raise RuntimeError(
            "Không tìm thấy FFmpeg / FFprobe trên hệ thống!\n"
            "👉 Trên macOS: brew install ffmpeg\n"
            "👉 Trên Windows: winget install Gyan.FFmpeg"
        )
    return ffmpeg_bin, ffprobe_bin


def _probe_duration(ffprobe_bin: str, media_path: str) -> float:
    """Đo thời lượng (giây) của file audio/video bằng ffprobe."""
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(media_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        data = json.loads(res.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0.0) or 0.0)
    except Exception:
        return 0.0


def _detect_whisper_config(device_pref: str = "auto", model_pref: str = "auto") -> Tuple[str, str, str]:
    """
    Xác định cấu hình tối ưu cho Faster-Whisper:
    - Nếu có NVIDIA GPU (CUDA): dùng device='cuda', compute_type='float16', model='large-v3'
    - Nếu trên macOS hoặc CPU: dùng device='cpu', compute_type='int8', model='medium'
    """
    device = device_pref.lower().strip()
    has_cuda = False

    if device in ("auto", "cuda"):
        try:
            import ctranslate2

            cuda_count = ctranslate2.get_cuda_device_count()
            has_cuda = cuda_count > 0
        except Exception:
            try:
                import torch

                has_cuda = torch.cuda.is_available()
            except Exception:
                has_cuda = False

    if device == "cuda" and not has_cuda:
        print("[CẢNH BÁO] Bạn chọn 'cuda' nhưng máy không có GPU NVIDIA CUDA -> Tự động chuyển sang 'cpu'.")
        device = "cpu"
    elif device == "auto":
        device = "cuda" if has_cuda else "cpu"

    if device == "cuda":
        compute_type = "float16"
        default_model = "large-v3"
    else:
        compute_type = "int8"
        default_model = "medium"

    model_size = default_model if model_pref == "auto" else model_pref
    return device, compute_type, model_size


def _require_srt() -> Any:
    if srt is None:
        raise RuntimeError(
            "Chưa cài đặt thư viện 'srt'.\n"
            "👉 Vui lòng chạy: pip install srt faster-whisper deep-translator edge-tts"
        )
    return srt


# ==============================================================================
# BƯỚC 1: EXTRACT AUDIO (16kHz Mono PCM 16-bit WAV)
# ==============================================================================
def extract_audio(video_path: str, audio_output_path: str) -> str:
    """
    Bước 1: Dùng FFmpeg tách luồng audio từ video_path sang định dạng
    16kHz Mono PCM 16-bit WAV (pcm_s16le) tối ưu nhất cho Faster-Whisper.
    """
    ffmpeg_bin, _ = _find_ffmpeg()
    in_path = Path(video_path).resolve()
    out_path = Path(audio_output_path).resolve()

    if not in_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy video đầu vào: {in_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n[BƯỚC 1/4] 🎵 Đang tách âm thanh 16kHz Mono WAV từ: {in_path.name}")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(in_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 or not out_path.is_file():
        raise RuntimeError(f"Tách âm thanh thất bại: {res.stderr.strip()}")

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ Đã xuất file âm thanh chuẩn Whisper: {out_path.name} ({size_mb:.1f} MB)")
    return str(out_path)


# ==============================================================================
# BƯỚC 2: SPEECH-TO-TEXT TIẾNG TRUNG (FASTER-WHISPER)
# ==============================================================================
def transcribe_chinese(
    audio_path: str,
    output_srt_zh: str,
    device: str = "auto",
    model_size: str = "auto",
) -> str:
    """
    Bước 2: Nhận diện giọng nói tiếng Trung (language='zh') từ file WAV 16kHz
    và xuất ra file phụ đề .srt tiếng Trung chuẩn mốc thời gian.
    """
    _require_srt()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Chưa cài đặt thư viện 'faster-whisper'.\n"
            "👉 Vui lòng chạy: pip install faster-whisper"
        ) from exc

    in_audio = Path(audio_path).resolve()
    out_srt = Path(output_srt_zh).resolve()
    out_srt.parent.mkdir(parents=True, exist_ok=True)

    actual_device, compute_type, actual_model = _detect_whisper_config(device, model_size)
    print(
        f"\n[BƯỚC 2/4] 🎙️ Đang khởi tạo Faster-Whisper "
        f"(Model: {actual_model} | Thiết bị: {actual_device.upper()} | Kiểu tính toán: {compute_type})..."
    )

    cpu_threads = max(4, (os.cpu_count() or 4))
    model = WhisperModel(
        actual_model,
        device=actual_device,
        compute_type=compute_type,
        cpu_threads=cpu_threads if actual_device == "cpu" else 0,
    )

    print("  ⏳ Đang nhận diện lời thoại tiếng Trung (language='zh', VAD filter bật)...")
    segments, info = model.transcribe(
        str(in_audio),
        language="zh",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
    )

    subtitles: List[srt.Subtitle] = []
    idx = 1
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        start_td = datetime.timedelta(seconds=max(0.0, float(seg.start)))
        end_td = datetime.timedelta(seconds=max(float(seg.start) + 0.2, float(seg.end)))
        subtitles.append(
            srt.Subtitle(
                index=idx,
                start=start_td,
                end=end_td,
                content=text,
            )
        )
        print(
            f"    [{idx:03d}] {srt.timedelta_to_srt_timestamp(start_td)} --> "
            f"{srt.timedelta_to_srt_timestamp(end_td)} | {text}"
        )
        idx += 1

    srt_content = srt.compose(subtitles)
    out_srt.write_text(srt_content, encoding="utf-8")
    print(f"  ✅ Hoàn tất nhận diện {len(subtitles)} câu thoại tiếng Trung -> {out_srt.name}")
    return str(out_srt)


# ==============================================================================
# BƯỚC 3: DỊCH PHỤ ĐỀ TIẾNG TRUNG SANG TIẾNG VIỆT (DEEP-TRANSLATOR)
# ==============================================================================
def translate_srt(
    input_srt_zh: str,
    output_srt_vi: str,
    batch_size: int = 15,
    sleep_sec: float = 0.2,
) -> str:
    """
    Bước 3: Đọc file .srt tiếng Trung bằng thư viện `srt`, dịch nội dung từ 'zh-CN'
    sang 'vi' bằng GoogleTranslator, giữ nguyên 100% mốc thời gian (Index, Start, End).
    Có cơ chế chia batch kết hợp fallback từng dòng + retry + sleep(0.2s) chống rate-limit.
    """
    _require_srt()
    try:
        from deep_translator import GoogleTranslator
    except ImportError as exc:
        raise RuntimeError(
            "Chưa cài đặt thư viện 'deep-translator'.\n"
            "👉 Vui lòng chạy: pip install deep-translator"
        ) from exc

    in_srt = Path(input_srt_zh).resolve()
    out_srt = Path(output_srt_vi).resolve()
    out_srt.parent.mkdir(parents=True, exist_ok=True)

    raw_text = in_srt.read_text(encoding="utf-8-sig")
    subtitles = list(srt.parse(raw_text))
    total = len(subtitles)

    print(f"\n[BƯỚC 3/4] 🌐 Đang dịch {total} câu phụ đề từ Tiếng Trung (zh-CN) sang Tiếng Việt (vi)...")
    if total == 0:
        out_srt.write_text("", encoding="utf-8")
        return str(out_srt)

    translator = GoogleTranslator(source="zh-CN", target="vi")
    translated_subs: List[srt.Subtitle] = []

    def _translate_single_with_retry(text: str, retries: int = 3) -> str:
        clean_text = text.strip()
        if not clean_text:
            return ""
        for attempt in range(1, retries + 1):
            try:
                res = translator.translate(clean_text)
                time.sleep(sleep_sec)
                return (res or clean_text).strip()
            except Exception as exc:
                if attempt == retries:
                    print(f"    [CẢNH BÁO] Không dịch được câu '{clean_text}' ({exc}) -> Giữ nguyên gốc.")
                    return clean_text
                time.sleep(sleep_sec * (attempt * 2))
        return clean_text

    # Xử lý theo từng cụm (batch) để tăng tốc độ và giảm số lần gọi API
    for start_idx in range(0, total, batch_size):
        batch = subtitles[start_idx : start_idx + batch_size]
        batch_texts = [sub.content.replace("\n", " ").strip() for sub in batch]

        translated_batch: Optional[List[str]] = None
        try:
            # Ghép bằng ký tự phân tách dòng để dịch 1 lần cho cả batch
            joined_payload = "\n".join(batch_texts)
            joined_result = translator.translate(joined_payload)
            time.sleep(sleep_sec)
            if joined_result:
                split_lines = [line.strip() for line in joined_result.splitlines() if line.strip()]
                if len(split_lines) == len(batch):
                    translated_batch = split_lines
        except Exception:
            translated_batch = None

        # Nếu dịch gộp không khớp số dòng, tự động chuyển sang dịch từng dòng an toàn tuyệt đối
        if translated_batch is None:
            translated_batch = [_translate_single_with_retry(t) for t in batch_texts]

        for sub, vi_text in zip(batch, translated_batch):
            new_sub = srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=vi_text,
            )
            translated_subs.append(new_sub)
            print(
                f"    [{new_sub.index:03d}/{total:03d}] "
                f"{srt.timedelta_to_srt_timestamp(new_sub.start)} | {vi_text}"
            )

    out_srt.write_text(srt.compose(translated_subs), encoding="utf-8")
    print(f"  ✅ Đã lưu file phụ đề tiếng Việt hoàn chỉnh: {out_srt.name}")
    return str(out_srt)


# ==============================================================================
# BƯỚC 4: TEXT-TO-SPEECH TIẾNG VIỆT KHỚP TIMELINE (EDGE-TTS + FFMPEG)
# ==============================================================================
async def _synthesize_edge_tts_segment(
    text: str,
    out_mp3: Path,
    voice: str,
    retries: int = 3,
) -> bool:
    """Render 1 câu thoại tiếng Việt ra file MP3 bằng Microsoft Edge Neural TTS."""
    import edge_tts

    for attempt in range(1, retries + 1):
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice)
            await communicate.save(str(out_mp3))
            if out_mp3.is_file() and out_mp3.stat().st_size > 100:
                return True
        except Exception as exc:
            if attempt == retries:
                print(f"    [CẢNH BÁO] Lỗi tạo giọng đọc cho câu '{text[:30]}...': {exc}")
                return False
            await asyncio.sleep(0.5 * attempt)
    return False


def generate_tts_from_srt(
    input_srt_vi: str,
    output_audio_vi: str,
    voice: str = "vi-VN-NamMinhNeural",
    total_video_duration: float = 0.0,
) -> str:
    """
    Bước 4: Đọc từng câu thoại trong file .srt tiếng Việt, dùng `edge-tts` tạo giọng đọc
    và ghép nối chính xác theo mốc thời gian (timeline/offset) của từng câu phụ đề.
    Tự động điều chỉnh tốc độ câu đọc (atempo) nếu câu dịch dài hơn khung thời gian cho phép
    để không bao giờ bị đè tiếng lên câu tiếp theo.
    """
    _require_srt()
    try:
        import edge_tts  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Chưa cài đặt thư viện 'edge-tts'.\n"
            "👉 Vui lòng chạy: pip install edge-tts"
        ) from exc

    ffmpeg_bin, ffprobe_bin = _find_ffmpeg()
    in_srt = Path(input_srt_vi).resolve()
    out_audio = Path(output_audio_vi).resolve()
    out_audio.parent.mkdir(parents=True, exist_ok=True)

    raw_text = in_srt.read_text(encoding="utf-8-sig")
    subtitles = list(srt.parse(raw_text))
    total = len(subtitles)

    print(
        f"\n[BƯỚC 4/4] 🗣️ Đang tạo Thuyết Minh Tiếng Việt (Giọng: {voice}) cho {total} câu thoại..."
    )

    sample_rate = 24000
    temp_dir = Path(tempfile.mkdtemp(prefix="tts_segments_"))

    try:
        # Tạo file WAV tổng hợp chuẩn 24kHz Mono PCM 16-bit khớp tuyệt đối theo mili-giây
        master_wav = temp_dir / "master_timeline.wav"

        if total == 0:
            dur = max(1.0, total_video_duration)
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r={sample_rate}:cl=mono",
                    "-t",
                    f"{dur:.3f}",
                    str(out_audio),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return str(out_audio)

        # 1. Chạy bất đồng bộ tạo file mp3 cho từng câu phụ đề
        async def _render_all_segments() -> List[Tuple[int, srt.Subtitle, Optional[Path]]]:
            tasks_out: List[Tuple[int, srt.Subtitle, Optional[Path]]] = []
            for idx, sub in enumerate(subtitles, start=1):
                clean_line = " ".join(sub.content.splitlines()).strip()
                if not clean_line:
                    tasks_out.append((idx, sub, None))
                    continue
                seg_mp3 = temp_dir / f"seg_{idx:04d}.mp3"
                ok = await _synthesize_edge_tts_segment(clean_line, seg_mp3, voice)
                print(f"    🎙️ Đã tạo voice [{idx:03d}/{total:03d}]: {clean_line[:55]}")
                tasks_out.append((idx, sub, seg_mp3 if ok else None))
            return tasks_out

        rendered_items = asyncio.run(_render_all_segments())

        # 2. Đưa từng đoạn âm thanh vào đúng mốc thời gian (timeline offset) trên luồng WAV chuẩn
        print("  🔗 Đang đồng bộ hóa âm thanh thuyết minh khớp 100% với mốc thời gian phụ đề...")
        with wave.open(str(master_wav), "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)  # 16-bit PCM (2 bytes / sample)
            wav_out.setframerate(sample_rate)

            current_sample_pos = 0

            for i, (idx, sub, seg_mp3) in enumerate(rendered_items):
                if seg_mp3 is None or not seg_mp3.is_file():
                    continue

                start_sec = sub.start.total_seconds()
                end_sec = sub.end.total_seconds()

                # Khoảng thời gian tối đa cho phép trước khi câu tiếp theo bắt đầu
                if i + 1 < len(rendered_items):
                    next_start_sec = rendered_items[i + 1][1].start.total_seconds()
                    max_slot_sec = max(0.3, next_start_sec - start_sec - 0.05)
                else:
                    max_slot_sec = max(1.0, (end_sec - start_sec) * 1.5)

                target_start_sample = int(round(start_sec * sample_rate))
                if target_start_sample > current_sample_pos:
                    # Chèn khoảng lặng (silence) chính xác tới thời điểm câu thoại bắt đầu
                    silence_samples = target_start_sample - current_sample_pos
                    wav_out.writeframes(b"\x00\x00" * silence_samples)
                    current_sample_pos = target_start_sample

                tts_dur = _probe_duration(ffprobe_bin, str(seg_mp3))
                af_filters = []

                # Nếu câu đọc tiếng Việt dài hơn khoảng thời gian giữa 2 câu, tự tăng tốc nhẹ (tối đa 1.45x)
                if tts_dur > max_slot_sec and max_slot_sec > 0.2:
                    speed_ratio = min(1.45, max(1.02, tts_dur / max_slot_sec))
                    af_filters.append(f"atempo={speed_ratio:.3f}")

                af_filters.append(f"aresample={sample_rate}")
                seg_wav = temp_dir / f"seg_{idx:04d}.wav"

                cmd_conv = [
                    ffmpeg_bin,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(seg_mp3),
                    "-af",
                    ",".join(af_filters),
                    "-ac",
                    "1",
                    "-ar",
                    str(sample_rate),
                    "-acodec",
                    "pcm_s16le",
                    str(seg_wav),
                ]
                subprocess.run(cmd_conv, check=False)

                if seg_wav.is_file():
                    with wave.open(str(seg_wav), "rb") as seg_in:
                        frames = seg_in.readframes(seg_in.getnframes())
                        wav_out.writeframes(frames)
                        current_sample_pos += len(frames) // 2

            # Bù thêm khoảng lặng ở cuối để khớp tổng thời lượng video gốc (nếu có truyền vào)
            if total_video_duration > 0:
                total_target_samples = int(round(total_video_duration * sample_rate))
                if total_target_samples > current_sample_pos:
                    wav_out.writeframes(b"\x00\x00" * (total_target_samples - current_sample_pos))

        # 3. Xuất từ file WAV tổng hợp sang file đích (.mp3 hoặc .wav) kèm chuẩn hóa âm lượng loudnorm
        ext = out_audio.suffix.lower()
        codec_args = (
            ["-c:a", "libmp3lame", "-b:a", "192k"]
            if ext == ".mp3"
            else ["-c:a", "pcm_s16le"]
        )

        cmd_final = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(master_wav),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "44100",
            "-ac",
            "2",
            *codec_args,
            str(out_audio),
        ]
        res = subprocess.run(cmd_final, capture_output=True, text=True, check=False)
        if res.returncode != 0 or not out_audio.is_file():
            raise RuntimeError(f"Không thể xuất file thuyết minh cuối cùng: {res.stderr}")

        size_mb = out_audio.stat().st_size / (1024 * 1024)
        print(f"  ✅ Đã xuất file âm thanh Thuyết Minh Tiếng Việt: {out_audio.name} ({size_mb:.1f} MB)")
        return str(out_audio)

    finally:
        # Tự động dọn dẹp toàn bộ các file mp3/wav nhỏ tạm thời
        shutil.rmtree(temp_dir, ignore_errors=True)


def mux_dubbed_video(
    input_video: str,
    input_audio_vi: str,
    input_srt_vi: str,
    output_video_path: str,
    original_audio_volume: float = 0.12,
) -> str:
    """
    Hàm tiện ích bổ sung: Ghép luồng Thuyết minh tiếng Việt (100% âm lượng)
    trộn cùng âm thanh nền gốc (12% âm lượng) + nhúng phụ đề tiếng Việt vào video MP4.
    """
    ffmpeg_bin, _ = _find_ffmpeg()
    out_vid = Path(output_video_path).resolve()
    out_vid.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n[GHÉP VIDEO THUYẾT MINH] 🎬 Đang trộn Thuyết Minh + Nhạc nền gốc ➔ {out_vid.name}...")
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(Path(input_video).resolve()),
        "-i",
        str(Path(input_audio_vi).resolve()),
        "-i",
        str(Path(input_srt_vi).resolve()),
        "-filter_complex",
        f"[0:a]volume={original_audio_volume:.2f}[bg];[1:a]volume=1.0[tts];[bg][tts]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-map",
        "2:s:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=vie",
        "-movflags",
        "+faststart",
        str(out_vid),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        # Fallback nếu video gốc không có luồng âm thanh
        cmd_no_bg = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(Path(input_video).resolve()),
            "-i",
            str(Path(input_audio_vi).resolve()),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out_vid),
        ]
        subprocess.run(cmd_no_bg, check=True)

    print(f"  ✅ Đã xuất video thuyết minh tiếng Việt: {out_vid}")
    return str(out_vid)


def run_audio_sub_pipeline(
    input_video: str,
    output_dir: str,
    voice: str = "vi-VN-NamMinhNeural",
    device: str = "auto",
    model_size: str = "auto",
    mux_video: bool = False,
    keep_temp: bool = False,
) -> dict:
    """
    Chạy trọn bộ 4 bước từ Video gốc -> Phụ đề tiếng Việt (.srt) & Thuyết minh tiếng Việt (.mp3)
    và tự động dọn dẹp file rác sau khi hoàn tất.
    """
    start_ts = time.time()
    in_video_path = Path(input_video).resolve()
    if not in_video_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file video đầu vào: {in_video_path}")

    out_dir_path = Path(output_dir).resolve()
    out_dir_path.mkdir(parents=True, exist_ok=True)

    stem = in_video_path.stem
    temp_wav_16k = out_dir_path / f"{stem}_temp_16k.wav"
    srt_zh_path = out_dir_path / f"{stem}.zh.srt"
    srt_vi_path = out_dir_path / f"{stem}.vi.srt"
    audio_vi_path = out_dir_path / f"{stem}_thuyet_minh_vi.mp3"

    _, ffprobe_bin = _find_ffmpeg()
    video_duration = _probe_duration(ffprobe_bin, str(in_video_path))

    print("=" * 74)
    print("  🎬 AUDIO & SUBTITLE VIETNAMESE PIPELINE (WHISPER ➔ TRANSLATE ➔ EDGE-TTS)")
    print(f"  📂 Video đầu vào : {in_video_path.name} (Thời lượng: {video_duration:.1f}s)")
    print(f"  📁 Thư mục lưu   : {out_dir_path}")
    print(f"  🗣️ Giọng đọc TTS : {voice}")
    print("=" * 74)

    try:
        # Bước 1: Tách âm thanh WAV 16kHz Mono
        extract_audio(str(in_video_path), str(temp_wav_16k))

        # Bước 2: Nhận diện giọng nói tiếng Trung ra file .zh.srt
        transcribe_chinese(
            audio_path=str(temp_wav_16k),
            output_srt_zh=str(srt_zh_path),
            device=device,
            model_size=model_size,
        )

        # Bước 3: Dịch phụ đề sang tiếng Việt (.vi.srt)
        translate_srt(
            input_srt_zh=str(srt_zh_path),
            output_srt_vi=str(srt_vi_path),
        )

        # Bước 4: Tạo file âm thanh thuyết minh tiếng Việt (.mp3) khớp timeline
        generate_tts_from_srt(
            input_srt_vi=str(srt_vi_path),
            output_audio_vi=str(audio_vi_path),
            voice=voice,
            total_video_duration=video_duration,
        )

        dubbed_video_path = None
        if mux_video:
            dubbed_video_path = out_dir_path / f"{stem}_vi_dubbed.mp4"
            mux_dubbed_video(
                input_video=str(in_video_path),
                input_audio_vi=str(audio_vi_path),
                input_srt_vi=str(srt_vi_path),
                output_video_path=str(dubbed_video_path),
            )

        elapsed = time.time() - start_ts
        print("\n" + "=" * 74)
        print(f"🎉 [HOÀN THÀNH] Xử lý xong sau {elapsed:.1f} giây!")
        print(f"  📄 Phụ đề Tiếng Việt (.srt)   : {srt_vi_path}")
        print(f"  🔊 Voice Thuyết Minh (.mp3)   : {audio_vi_path}")
        if dubbed_video_path:
            print(f"  🎬 Video Đã Lồng Tiếng (.mp4) : {dubbed_video_path}")
        print("=" * 74)

        return {
            "srt_zh": str(srt_zh_path),
            "srt_vi": str(srt_vi_path),
            "audio_vi": str(audio_vi_path),
            "dubbed_video": str(dubbed_video_path) if dubbed_video_path else None,
        }

    finally:
        # Dọn dẹp file âm thanh 16kHz tạm thời
        if not keep_temp and temp_wav_16k.exists():
            temp_wav_16k.unlink(missing_ok=True)
            print("🧹 Đã tự động dọn dẹp file âm thanh tạm (_temp_16k.wav).")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline Tự Động Tạo Phụ Đề Tiếng Việt (.srt) & Thuyết Minh Tiếng Việt (.mp3) Từ Video Gốc"
    )
    parser.add_argument(
        "input_video",
        nargs="?",
        help="Đường dẫn tới file video gốc (tiếng Trung)",
    )
    parser.add_argument(
        "--input-video",
        "-i",
        dest="input_video_flag",
        type=str,
        help="Đường dẫn tới file video gốc (thay thế cho tham số vị trí)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="output_sub_tts",
        help="Thư mục lưu file kết quả (.srt tiếng Việt và .mp3 thuyết minh). Mặc định: output_sub_tts",
    )
    parser.add_argument(
        "--voice",
        "-v",
        type=str,
        default="vi-VN-NamMinhNeural",
        help="Giọng đọc Microsoft Neural (vi-VN-NamMinhNeural [Nam] hoặc vi-VN-HoaiMyNeural [Nữ])",
    )
    parser.add_argument(
        "--device",
        "-d",
        type=str,
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="Thiết bị chạy Whisper: 'auto' (tự nhận CUDA/CPU), 'cuda', hoặc 'cpu'",
    )
    parser.add_argument(
        "--model-size",
        "-m",
        type=str,
        default="auto",
        help="Kích thước model Whisper ('auto', 'large-v3', 'medium', 'small', 'base')",
    )
    parser.add_argument(
        "--mux-video",
        action="store_true",
        help="Ghép luôn file thuyết minh .mp3 và phụ đề .srt vào video gốc để xuất file .mp4 hoàn chỉnh",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Giữ lại file .wav 16kHz trung gian sau khi chạy xong",
    )

    args = parser.parse_args()
    video_path = args.input_video_flag or args.input_video

    if not video_path:
        parser.print_help()
        print("\n💡 Ví dụ cách chạy:")
        print("   python audio_sub_pipeline.py raw/ep_001.mp4 --output-dir output/")
        print("   python audio_sub_pipeline.py -i raw/ep_001.mp4 -o output/ --voice vi-VN-HoaiMyNeural --mux-video")
        return 1

    try:
        run_audio_sub_pipeline(
            input_video=video_path,
            output_dir=args.output_dir,
            voice=args.voice,
            device=args.device,
            model_size=args.model_size,
            mux_video=args.mux_video,
            keep_temp=args.keep_temp,
        )
        return 0
    except KeyboardInterrupt:
        print("\n⚠️ Đã dừng chương trình theo yêu cầu người dùng.")
        return 130
    except Exception as exc:
        print(f"\n❌ [LỖI] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
