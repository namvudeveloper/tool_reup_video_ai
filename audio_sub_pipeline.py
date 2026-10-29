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
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Tự động nạp thư viện từ môi trường ảo .venv (hỗ trợ cả macOS & Windows)
_project_root = Path(__file__).resolve().parent
for _vbase in (_project_root / ".venv" / "lib", _project_root / ".venv" / "Lib"):
    if _vbase.is_dir():
        for _sp in _vbase.glob("**/site-packages"):
            if _sp.is_dir() and str(_sp) not in sys.path:
                sys.path.insert(0, str(_sp))

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
    - Nếu có NVIDIA GPU (CUDA): tự động kiểm tra compute_type mà card hỗ trợ (float16 / int8_float16 / int8_float32 / int8 / float32)
    - Nếu trên macOS hoặc CPU: dùng device='cpu', compute_type='int8', model='medium'
    """
    device = device_pref.lower().strip()
    has_cuda = False
    supported_cuda_types = set()

    if device in ("auto", "cuda"):
        try:
            import ctranslate2

            cuda_count = ctranslate2.get_cuda_device_count()
            has_cuda = cuda_count > 0
            if has_cuda:
                supported_cuda_types = set(ctranslate2.get_supported_compute_types("cuda"))
        except Exception:
            try:
                import torch

                has_cuda = torch.cuda.is_available()
            except Exception:
                has_cuda = False

        # Trên Windows, CTranslate2 CUDA yêu cầu phải có cublas64_12.dll trong hệ thống
        if has_cuda and sys.platform == "win32":
            try:
                import ctypes

                ctypes.WinDLL("cublas64_12.dll")
            except Exception:
                has_cuda = False

    if device == "cuda" and not has_cuda:
        print("[CẢNH BÁO] Bạn chọn 'cuda' nhưng máy không có GPU NVIDIA CUDA -> Tự động chuyển sang 'cpu'.")
        device = "cpu"
    elif device == "auto":
        device = "cuda" if has_cuda else "cpu"

    if device == "cuda":
        compute_type = "int8"
        for candidate in ("float16", "int8_float16", "int8_float32", "int8", "float32"):
            if candidate in supported_cuda_types:
                compute_type = candidate
                break
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

    # WAV đã được FFmpeg chuẩn hóa 16 kHz mono PCM16. Đọc trực tiếp để tránh
    # phụ thuộc av.open(metadata_errors=...), vốn không có ở một số bản PyAV.
    import numpy as np

    with wave.open(str(in_audio), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getframerate() != 16000 or wav.getsampwidth() != 2:
            raise RuntimeError("Audio đầu vào Whisper phải là WAV mono 16 kHz PCM16.")
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0

    def _run_whisper(dev: str, ctype: str) -> List[srt.Subtitle]:
        mdl = WhisperModel(
            actual_model,
            device=dev,
            compute_type=ctype,
            cpu_threads=cpu_threads if dev == "cpu" else 0,
        )
        print(f"  ⏳ Đang nhận diện lời thoại tiếng Trung trên {dev.upper()} ({ctype}, language='zh', VAD filter bật)...")
        segs, _ = mdl.transcribe(
            samples,
            language="zh",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        subs: List[srt.Subtitle] = []
        idx_local = 1
        for seg in segs:
            text = (seg.text or "").strip()
            if not text:
                continue
            start_td = datetime.timedelta(seconds=max(0.0, float(seg.start)))
            end_td = datetime.timedelta(seconds=max(float(seg.start) + 0.2, float(seg.end)))
            subs.append(
                srt.Subtitle(
                    index=idx_local,
                    start=start_td,
                    end=end_td,
                    content=text,
                )
            )
            print(
                f"    [{idx_local:03d}] {srt.timedelta_to_srt_timestamp(start_td)} --> "
                f"{srt.timedelta_to_srt_timestamp(end_td)} | {text}"
            )
            idx_local += 1
        return subs

    try:
        subtitles = _run_whisper(actual_device, compute_type)
    except Exception as cuda_exc:
        if actual_device != "cpu":
            print(
                f"  ⚠️ Không thể chạy Whisper trên CUDA ({cuda_exc}) -> Tự động chuyển sang CPU (int8)..."
            )
            subtitles = _run_whisper("cpu", "int8")
        else:
            raise

    srt_content = srt.compose(subtitles)
    out_srt.write_text(srt_content, encoding="utf-8")
    print(f"  ✅ Hoàn tất nhận diện {len(subtitles)} câu thoại tiếng Trung -> {out_srt.name}")
    return str(out_srt)


# ==============================================================================
# BƯỚC 3: DỊCH PHỤ ĐỀ TIẾNG TRUNG SANG TIẾNG VIỆT (DEEP-TRANSLATOR)
# ==============================================================================
def _google_gtx_translate(text: str, source: str = "zh-CN", target: str = "vi") -> str:
    """Dịch văn bản qua cổng JSON GTX của Google (ổn định, nhanh và không bị lỗi TooManyRequests của trang /m)."""
    import urllib.parse
    import urllib.request

    text = (text or "").strip()
    if not text:
        return ""
    url = "https://translate.googleapis.com/translate_a/single"
    params = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": source,
            "tl": target,
            "dt": "t",
            "q": text,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=params,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not data or not data[0]:
        return ""
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


def translate_srt(
    input_srt_zh: str,
    output_srt_vi: str,
    batch_size: int = 20,
    sleep_sec: float = 0.15,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """
    Bước 3: Đọc file .srt tiếng Trung bằng thư viện `srt`, dịch nội dung từ 'zh-CN'
    sang 'vi', giữ nguyên 100% mốc thời gian (Index, Start, End).
    Ưu tiên cổng GTX JSON ổn định, tự động dịch từng câu nếu gộp cụm bị lệch dòng.
    """
    _require_srt()
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        GoogleTranslator = None  # type: ignore[assignment]

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

    translator = GoogleTranslator(source="zh-CN", target="vi") if GoogleTranslator else None
    translated_subs: List[srt.Subtitle] = []

    def _translate_text(q: str) -> str:
        for attempt in range(3):
            try:
                return _google_gtx_translate(q, source="zh-CN", target="vi")
            except Exception:
                if translator is not None:
                    try:
                        return translator.translate(q) or ""
                    except Exception:
                        pass
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(
            "Dịch vụ Google đang giới hạn hoặc từ chối yêu cầu dịch. "
            "Phụ đề tiếng Trung đã được lưu; hãy thử lại sau hoặc dùng bảng sửa phụ đề thủ công."
        )

    # Xử lý theo từng cụm (batch) để tăng tốc độ và giảm số lần gọi API
    for start_idx in range(0, total, batch_size):
        batch = subtitles[start_idx : start_idx + batch_size]
        batch_texts = [sub.content.replace("\n", " ").strip() for sub in batch]

        joined_result = _translate_text("\n".join(batch_texts))
        time.sleep(sleep_sec)
        translated_batch = [line.strip() for line in (joined_result or "").splitlines() if line.strip()]

        # Nếu Google gộp dòng khiến số dòng trả về khác số câu trong batch -> dịch từng câu một để khớp 100% timeline
        if len(translated_batch) != len(batch):
            translated_batch = []
            for single_txt in batch_texts:
                vi_one = _translate_text(single_txt).replace("\n", " ").strip()
                translated_batch.append(vi_one or single_txt)
                time.sleep(0.05)

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
        if progress_callback:
            progress_callback(len(translated_subs), total)

    out_srt.write_text(srt.compose(translated_subs), encoding="utf-8")
    print(f"  ✅ Đã lưu file phụ đề tiếng Việt hoàn chỉnh: {out_srt.name}")
    return str(out_srt)


# ==============================================================================
# BƯỚC 4: TEXT-TO-SPEECH TIẾNG VIỆT KHỚP TIMELINE (EDGE-TTS + FFMPEG)
# ==============================================================================
def _google_tts_fallback(text: str, out_mp3: Path) -> bool:
    """Dự phòng tạo giọng đọc tiếng Việt qua Google TTS nếu Edge-TTS bị ngắt kết nối ở 1 câu."""
    import urllib.parse
    import urllib.request

    try:
        q = (text or "").strip()[:200]
        if not q:
            return False
        url = "https://translate.google.com/translate_tts?" + urllib.parse.urlencode(
            {"ie": "UTF-8", "tl": "vi", "client": "tw-ob", "q": q}
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if data and len(data) > 100:
            out_mp3.write_bytes(data)
            return True
    except Exception:
        pass
    return False


async def _synthesize_edge_tts_segment(
    text: str,
    out_mp3: Path,
    voice: str,
    retries: int = 4,
) -> bool:
    """Render 1 câu thoại tiếng Việt ra file MP3 bằng Microsoft Edge Neural TTS (kèm dự phòng Google TTS)."""
    import edge_tts

    clean = re.sub(r"[\x00-\x1f]+", " ", text or "").strip()
    if not clean or not any(ch.isalnum() for ch in clean):
        return False

    for attempt in range(1, retries + 1):
        try:
            communicate = edge_tts.Communicate(text=clean, voice=voice)
            await communicate.save(str(out_mp3))
            if out_mp3.is_file() and out_mp3.stat().st_size > 100:
                return True
        except Exception as exc:
            if attempt == retries:
                print(f"    [CẢNH BÁO] Edge-TTS lỗi câu '{clean[:30]}...' ({exc}) -> Chuyển sang TTS dự phòng...")
                return await asyncio.to_thread(_google_tts_fallback, clean, out_mp3)
            await asyncio.sleep(0.6 * attempt)
    return False


def generate_tts_from_srt(
    input_srt_vi: str,
    output_audio_vi: str,
    voice: str = "vi-VN-NamMinhNeural",
    total_video_duration: float = 0.0,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
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

        # 1. Chạy bất đồng bộ đa luồng (Semaphore 6) tạo file mp3 cho từng câu phụ đề siêu tốc
        async def _render_all_segments() -> List[Tuple[int, srt.Subtitle, Optional[Path]]]:
            sem = asyncio.Semaphore(6)
            done_counter = 0

            async def _worker(idx: int, sub: srt.Subtitle) -> Tuple[int, srt.Subtitle, Optional[Path]]:
                clean_line = " ".join(sub.content.splitlines()).strip()
                if not clean_line or not any(ch.isalnum() for ch in clean_line):
                    return (idx, sub, None)
                seg_mp3 = temp_dir / f"seg_{idx:04d}.mp3"
                async with sem:
                    ok = await _synthesize_edge_tts_segment(clean_line, seg_mp3, voice)
                if not ok:
                    print(f"    ⚠️ Bỏ qua câu {idx}/{total} không có âm thanh: {clean_line[:50]}")
                    return (idx, sub, None)
                print(f"    🎙️ Đã tạo voice [{idx:03d}/{total:03d}]: {clean_line[:55]}")
                nonlocal done_counter
                done_counter += 1
                if progress_callback:
                    try:
                        progress_callback(done_counter, total, clean_line[:45])
                    except Exception:
                        pass
                return (idx, sub, seg_mp3)

            tasks = [_worker(idx, sub) for idx, sub in enumerate(subtitles, start=1)]
            results = await asyncio.gather(*tasks)
            return list(results)

        rendered_items = asyncio.run(_render_all_segments())

        # 2. Trộn từng đoạn vào đúng mốc thời gian. Ghi nối tiếp sẽ đẩy những câu
        # dài sang sau và có thể cắt mất lời ở cuối video.
        print("  🔗 Đang đồng bộ hóa âm thanh thuyết minh khớp 100% với mốc thời gian phụ đề...")
        import numpy as np

        initial_samples = int(round(max(0.0, total_video_duration) * sample_rate))
        timeline = np.zeros(initial_samples, dtype=np.float32)
        for i, (idx, sub, seg_mp3) in enumerate(rendered_items):
            if seg_mp3 is None:
                continue
            if not seg_mp3.is_file():
                raise RuntimeError(f"Thiếu file giọng đọc cho câu {idx}/{total}.")

            start_sec = sub.start.total_seconds()
            end_sec = sub.end.total_seconds()

            # Khoảng thời gian tối đa cho phép trước khi câu tiếp theo bắt đầu.
            if i + 1 < len(rendered_items):
                next_start_sec = rendered_items[i + 1][1].start.total_seconds()
                max_slot_sec = max(0.3, next_start_sec - start_sec - 0.05)
            else:
                max_slot_sec = max(0.3, end_sec - start_sec)
            if total_video_duration > 0:
                max_slot_sec = min(max_slot_sec, max(0.0, total_video_duration - start_sec))
            if max_slot_sec <= 0: max_slot_sec = max(0.5, end_sec - start_sec)
            if max_slot_sec <= 0: max_slot_sec = max(0.5, end_sec - start_sec)
            if max_slot_sec <= 0: max_slot_sec = max(0.5, end_sec - start_sec)

            target_start_sample = max(0, int(round(start_sec * sample_rate)))
            tts_dur = _probe_duration(ffprobe_bin, str(seg_mp3))
            if tts_dur <= 0:
                raise RuntimeError(f"Không đọc được thời lượng giọng đọc câu {idx}/{total}.")
            af_filters = []

            # Tăng tốc vừa phải khi lời dài; phần dư sẽ được trộn thay vì bị cắt.
            if tts_dur > max_slot_sec:
                speed_ratio = min(1.75, tts_dur / max_slot_sec)
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
            converted = subprocess.run(cmd_conv, capture_output=True, text=True, check=False)
            if converted.returncode != 0 or not seg_wav.is_file():
                raise RuntimeError(
                    f"Không chuyển được giọng đọc câu {idx}/{total}: {converted.stderr.strip()}"
                )

            with wave.open(str(seg_wav), "rb") as seg_in:
                frames = seg_in.readframes(seg_in.getnframes())
            audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
            end_sample = target_start_sample + len(audio)
            if total_video_duration > 0 and end_sample > initial_samples and False:
                raise RuntimeError(
                    f"Câu {idx}/{total} đọc tràn khỏi cuối video. "
                    "Hãy rút ngắn câu này trước khi tạo thuyết minh."
                )
            if end_sample > len(timeline):
                timeline = np.pad(timeline, (0, end_sample - len(timeline)))
            if i + 1 < len(rendered_items) and end_sample > int(next_start_sec * sample_rate):
                print(f"    ⚠️ Câu {idx}/{total} dài hơn khoảng trống; giọng đọc có thể chồng câu sau.")
            timeline[target_start_sample:end_sample] += audio

        peak = float(np.max(np.abs(timeline))) if len(timeline) else 0.0
        if peak > 0.98:
            timeline *= 0.98 / peak
        with wave.open(str(master_wav), "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(sample_rate)
            wav_out.writeframes((timeline * 32767.0).astype("<i2").tobytes())

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


def _probe_video_resolution(ffprobe_bin: str, video_path: str) -> Tuple[int, int]:
    """Lấy chiều rộng x chiều cao của video để căn chỉnh phụ đề CapCut và vùng làm mờ."""
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        data = json.loads(res.stdout or "{}")
        streams = data.get("streams") or []
        if streams:
            w = int(streams[0].get("width") or 1920)
            h = int(streams[0].get("height") or 1080)
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return 1920, 1080


def _sec_to_ass_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_capcut_ass(
    srt_path: str,
    out_ass_path: str,
    width: int = 1920,
    height: int = 1080,
    blur_cfg: Optional[Dict[str, Any]] = None,
    style_cfg: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Tạo file phụ đề .ASS chuẩn phong cách CapCut (chữ đậm, viền đen dày hoặc hộp nền đen mờ)
    và tự động căn vị trí đè chính giữa vùng làm mờ chữ Trung Quốc.
    """
    style = style_cfg or {}
    color_name = str(style.get("color", "yellow") or "yellow").lower()
    color_map = {
        "yellow": "&H0014E0FD",  # Vàng rực kiểu CapCut (#FDE014)
        "white": "&H00FFFFFF",   # Trắng tinh (#FFFFFF)
        "cyan": "&H00FFFF38",    # Xanh Cyan nổi bật (#38FFFF)
        "green": "&H004ADE80",   # Xanh lá sáng (#80DE4A)
    }
    primary_color = color_map.get(color_name, "&H0014E0FD")
    font_size = int(float(style.get("font_size", 52) or 52))
    scaled_font_size = max(22, int(round(font_size * (height / 1080.0))))

    use_box = bool(style.get("box", True))
    border_style = 3 if use_box else 1
    back_color = "&H66000000" if use_box else "&H80000000"
    outline_color = "&H66000000" if use_box else "&H00000000"
    outline_w = max(2, int(round(4 * (height / 1080.0))))
    shadow_w = 0 if use_box else max(1, int(round(2 * (height / 1080.0))))

    y_pct = 86.0
    h_pct = 10.0
    if isinstance(blur_cfg, dict) and str(blur_cfg.get("mode", "delogo")).lower() != "off":
        y_pct = float(blur_cfg.get("y_pct", 86.0) or 86.0)
        h_pct = float(blur_cfg.get("h_pct", 10.0) or 10.0)
    if style.get("pos_y_pct") is not None:
        try:
            center_bottom_pct = 100.0 - float(style["pos_y_pct"])
        except Exception:
            center_bottom_pct = max(4.0, 100.0 - (y_pct + h_pct * 0.62))
    else:
        center_bottom_pct = max(4.0, 100.0 - (y_pct + h_pct * 0.62))

    margin_v = max(18, int(round(height * (center_bottom_pct / 100.0))))
    margin_lr = max(30, int(round(width * 0.06)))

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: CapCut,Arial,{scaled_font_size},{primary_color},&H000000FF,{outline_color},{back_color},"
        f"-1,0,0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},2,{margin_lr},{margin_lr},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    raw_srt = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\n\s*\n", raw_srt.replace("\r\n", "\n").strip())
    events: List[str] = []

    def _parse_ts(ts_str: str) -> float:
        clean = ts_str.strip().replace(",", ".")
        parts = clean.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return 0.0

    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        ts_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if ts_idx == -1:
            continue
        ts_parts = lines[ts_idx].split("-->")
        start_sec = _parse_ts(ts_parts[0])
        end_sec = _parse_ts(ts_parts[1].split()[0])
        if end_sec <= start_sec:
            end_sec = start_sec + 1.5
        text_body = " ".join(lines[ts_idx + 1 :]).strip()
        if not text_body:
            continue
        safe_text = text_body.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        safe_text = text_body.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        if style.get("pos_x_pct") is not None and style.get("pos_y_pct") is not None:
            try:
                px = int(round(width * (float(style["pos_x_pct"]) / 100.0)))
                py = int(round(height * (float(style["pos_y_pct"]) / 100.0)))
                safe_text = f"{{\\an5\\pos({px},{py})}}{safe_text}"
            except Exception:
                pass
        events.append(f"Dialogue: 0,{_sec_to_ass_ts(start_sec)},{_sec_to_ass_ts(end_sec)},CapCut,,0,0,0,,{safe_text}")

    out_p = Path(out_ass_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return str(out_p)


def mux_dubbed_video(
    input_video: str,
    input_audio_vi: Optional[str],
    input_srt_vi: Optional[str],
    output_video_path: str,
    original_audio_volume: float = 0.12,
    tts_audio_volume: float = 1.0,
    blur_sub_cfg: Optional[Dict[str, Any]] = None,
    burn_sub_cfg: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Ghép Video hoàn chỉnh chuẩn CapCut:
    1. Làm mờ / che vùng chữ Trung Quốc trên khung hình (nếu bật blur_sub_cfg)
    2. In cứng (Hardsub) phụ đề Tiếng Việt kiểu CapCut đè lên vùng làm mờ (nếu bật burn_sub_cfg)
    3. Trộn luồng âm thanh Thuyết Minh .MP3 đã có + tiếng nền gốc theo tỷ lệ âm lượng tùy chỉnh.
    """
    ffmpeg_bin, ffprobe_bin = _find_ffmpeg()
    in_vid = Path(input_video).resolve()
    out_vid = Path(output_video_path).resolve()
    out_vid.parent.mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parent

    has_tts_audio = bool(input_audio_vi and Path(input_audio_vi).is_file())
    has_srt = bool(input_srt_vi and Path(input_srt_vi).is_file())

    width, height = _probe_video_resolution(ffprobe_bin, str(in_vid))
    vf_parts: List[str] = []

    if isinstance(blur_sub_cfg, dict) and str(blur_sub_cfg.get("mode", "off")).lower() != "off":
        try:
            from core.processor import build_blur_sub_filter

            blur_vf = build_blur_sub_filter(width, height, blur_sub_cfg)
            if blur_vf:
                vf_parts.append(blur_vf)
        except Exception as exc:
            print(f"  ⚠️ Không thể tạo bộ lọc làm mờ chữ Trung: {exc}")

    burn_enabled = bool(burn_sub_cfg.get("enabled", True)) if isinstance(burn_sub_cfg, dict) else False
    if burn_enabled and has_srt and input_srt_vi:
        try:
            ass_file = project_root / "output" / "subtitles" / "capcut_active_burn.ass"
            generate_capcut_ass(
                str(input_srt_vi),
                str(ass_file),
                width=width,
                height=height,
                blur_cfg=blur_sub_cfg,
                style_cfg=burn_sub_cfg,
            )
            ass_rel_posix = ass_file.resolve().relative_to(project_root).as_posix()
            vf_parts.append(f"ass='{ass_rel_posix}'")
        except Exception as exc:
            print(f"  ⚠️ Không thể tạo phụ đề ASS kiểu CapCut: {exc}")

    need_reencode_video = len(vf_parts) > 0
    v_codec_args = (
        ["-vf", ",".join(vf_parts), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        if need_reencode_video
        else ["-c:v", "copy"]
    )

    print(f"\n[XUẤT VIDEO CAPCUT] 🎬 Đang kết xuất video hoàn chỉnh ➔ {out_vid.name}...")
    cmd: List[str] = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(in_vid),
    ]

    if has_tts_audio and input_audio_vi:
        cmd.extend(["-i", str(Path(input_audio_vi).resolve())])
    if has_srt and input_srt_vi and not burn_enabled:
        cmd.extend(["-i", str(Path(input_srt_vi).resolve())])

    if has_tts_audio:
        cmd.extend(
            [
                "-filter_complex",
                f"[0:a]volume={original_audio_volume:.2f}[bg];[1:a]volume={tts_audio_volume:.2f}[tts];[bg][tts]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]",
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
            ]
        )
    else:
        cmd.extend(["-map", "0:v:0", "-map", "0:a?"])
        if abs(original_audio_volume - 1.0) > 0.01:
            cmd.extend(["-af", f"volume={original_audio_volume:.2f}"])

    if has_srt and not burn_enabled:
        srt_input_idx = 2 if has_tts_audio else 1
        cmd.extend(["-map", f"{srt_input_idx}:s:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=vie"])

    cmd.extend(v_codec_args)
    cmd.extend(["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_vid)])

    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root), check=False)
    if res.returncode != 0:
        cmd_fb: List[str] = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(in_vid),
        ]
        if has_tts_audio and input_audio_vi:
            cmd_fb.extend(["-i", str(Path(input_audio_vi).resolve()), "-map", "0:v:0", "-map", "1:a:0"])
        else:
            cmd_fb.extend(["-map", "0:v:0", "-map", "0:a?"])
        cmd_fb.extend(v_codec_args)
        cmd_fb.extend(["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_vid)])
        res_fb = subprocess.run(cmd_fb, capture_output=True, text=True, cwd=str(project_root), check=False)
        if res_fb.returncode != 0:
            raise RuntimeError(f"Lỗi xuất video CapCut: {res_fb.stderr or res.stderr}")

    print(f"  ✅ Đã xuất video hoàn chỉnh: {out_vid}")
    return str(out_vid)


def _mux_dubbed_video_legacy(
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
        f"[0:a]volume={original_audio_volume:.2f}[bg];[1:a]volume=1.0[tts];[bg][tts]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]",
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
