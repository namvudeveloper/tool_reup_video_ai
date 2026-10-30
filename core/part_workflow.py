"""Create a video's subtitles and narration in one resumable part folder."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class WorkflowStopped(RuntimeError):
    pass


def check_stop(stop_checker: Optional[Callable[[], bool]]) -> None:
    if stop_checker and stop_checker():
        raise WorkflowStopped("Đã dừng theo yêu cầu; các file hoàn tất được giữ lại.")


def safe_name(value: str) -> str:
    return re.sub(r"[^\w-]+", "_", value.strip(), flags=re.UNICODE).strip("_") or "Video"


def part_folder(output_dir: Path, project: str, index: int) -> Path:
    return output_dir / safe_name(project) / f"Phan_{index:02d}"


def _stamp(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _copy(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    temp = target.with_name(target.stem + ".pending" + target.suffix)
    shutil.copy2(source, temp)
    temp.replace(target)


def process_part(
    video: Path,
    folder: Path,
    mode: str = "full",
    model: str = "small",
    voice: str = "vi-VN-NamMinhNeural",
    legacy_subtitles: Optional[Path] = None,
    progress: Optional[Callable[[str, float, str, Dict[str, Any]], None]] = None,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Publish each completed artifact, then run the next stage. Never publish partial files.

    mode=srt stops after translation; mode=mp3 requires an existing Vietnamese SRT;
    mode=full performs all stages; organize only adopts existing local files.
    Existing output and checkpoints survive errors.
    """
    if mode not in {"srt", "mp3", "full", "organize"}:
        raise ValueError("Chế độ không hợp lệ.")
    import audio_sub_pipeline as audio

    check_stop(stop_checker)
    video = Path(video).resolve()
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    work = folder / ".work"
    work.mkdir(exist_ok=True)
    manifest_path = work / "progress.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    target = folder / video.name
    source_stamp = _stamp(video)
    if video != target and (manifest.get("import_source") != source_stamp or not target.is_file()):
        _copy(video, target)
        manifest["import_source"] = source_stamp
    video = target
    check_stop(stop_checker)
    video_key = _stamp(video)
    if manifest.get("video") != video_key:
        manifest = {"import_source": manifest.get("import_source"), "video": video_key}
    _, ffprobe = audio._find_ffmpeg()
    duration = audio._probe_duration(ffprobe, str(video))
    if duration <= 0:
        raise RuntimeError(f"Không đọc được thời lượng video: {video.name}")

    vi = folder / f"{video.stem}.vi.srt"
    zh = work / f"{video.stem}.zh.srt"
    mp3 = folder / f"{video.stem}.thuyet_minh.mp3"
    wav = work / "audio16k.wav"
    record: Dict[str, Any] = {
        "path": str(video), "name": video.name, "folder": str(folder),
        "srt_path": "", "audio_vi": "", "stage": "video", "status": "running", "error": "",
    }

    def report(stage: str, percent: float, message: str) -> None:
        check_stop(stop_checker)
        record["stage"] = stage
        manifest["stage"] = stage
        manifest["status"] = record["status"]
        manifest["error"] = ""
        _write_json(manifest_path, manifest)
        if progress:
            progress(stage, percent, message, dict(record))

    # Adopt subtitles already produced for this exact legacy video. Timestamp and
    # source checkpoint checks prevent picking up an older video's files by name.
    def valid_srt(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            cues = list(audio.srt.parse(path.read_text(encoding="utf-8-sig")))
            return bool(cues) and all(
                cue.content.strip() and 0 <= cue.start.total_seconds() < cue.end.total_seconds()
                and cue.end.total_seconds() <= duration + 2 for cue in cues
            )
        except Exception:
            return False

    def adopt(candidate: Path, dest: Path, key: str) -> None:
        if not manifest.get(key) and candidate.is_file() and candidate.stat().st_mtime >= video.stat().st_mtime and valid_srt(candidate):
            _copy(candidate, dest)
            manifest[key] = {"video": video_key, "model": model}

    if legacy_subtitles:
        adopt(legacy_subtitles / f"{video.stem}.vi.srt", vi, "srt")
        adopt(legacy_subtitles / f"{video.stem}.zh.srt", zh, "transcript")
    if not manifest.get("srt") and valid_srt(vi) and vi.stat().st_mtime >= video.stat().st_mtime:
        manifest["srt"] = {"video": video_key, "model": model}

    try:
        report("video", 100, "Đã có video")
        srt_ready = manifest.get("srt", {}).get("video") == video_key and valid_srt(vi)
        if mode in {"mp3", "organize"} and not srt_ready:
            raise RuntimeError("Chưa có SRT tiếng Việt cho phần này. Hãy chọn Tạo SRT hoặc A → Z trước.")
        if not srt_ready:
            transcript_ready = manifest.get("transcript") == {"video": video_key, "model": model} and valid_srt(zh)
            if not transcript_ready:
                report("transcribe", 0, f"Đang tách âm thanh và khởi tạo Whisper {model}")
                audio.extract_audio(str(video), str(wav))
                check_stop(stop_checker)
                pending = zh.with_name(zh.stem + ".pending.srt")
                audio.transcribe_chinese(
                    str(wav), str(pending), model_size=model,
                    progress_callback=lambda percent, count: report("transcribe", percent, f"Whisper {model}: {percent:.0f}% âm thanh, {count} câu"),
                    stop_checker=stop_checker,
                )
                check_stop(stop_checker)
                if not valid_srt(pending):
                    raise RuntimeError("Whisper chưa nhận diện được câu thoại hợp lệ; hãy kiểm tra âm thanh video.")
                pending.replace(zh)
                manifest["transcript"] = {"video": video_key, "model": model}
                _write_json(manifest_path, manifest)
            report("translate", 0, "Đang dịch SRT sang tiếng Việt")
            pending = vi.with_name(vi.stem + ".pending.srt")
            audio.translate_srt(
                str(zh), str(pending),
                progress_callback=lambda done, total: report("translate", done / max(1, total) * 100, f"Đang dịch: {done}/{total} câu"),
                stop_checker=stop_checker,
            )
            check_stop(stop_checker)
            if not valid_srt(pending):
                raise RuntimeError("SRT dịch chưa hợp lệ; phụ đề tiếng Trung đã được giữ lại.")
            pending.replace(vi)
            manifest["srt"] = {"video": video_key, "model": model}
        record["srt_path"] = str(vi)
        report("srt", 100, "Đã xuất SRT tiếng Việt")
        if mode in {"full", "mp3"}:
            audio_key = {"srt_sha256": _digest(vi), "voice": voice, "video": video_key}
            if manifest.get("audio") != audio_key or not mp3.is_file() or mp3.stat().st_size < 100:
                report("tts", 0, f"Đang tạo MP3 ({voice})")
                pending = mp3.with_name(mp3.stem + ".pending.mp3")
                audio.generate_tts_from_srt(
                    str(vi), str(pending), voice=voice, total_video_duration=duration,
                    progress_callback=lambda done, total, text: report("tts", done / max(1, total) * 100, f"Đang tạo MP3: {done}/{total} câu"),
                    stop_checker=stop_checker,
                )
                check_stop(stop_checker)
                if not pending.is_file() or pending.stat().st_size < 100:
                    raise RuntimeError("MP3 chưa được tạo thành công.")
                pending.replace(mp3)
                manifest["audio"] = audio_key
            record["audio_vi"] = str(mp3)
        elif mp3.is_file() and manifest.get("audio", {}).get("srt_sha256") == _digest(vi):
            record["audio_vi"] = str(mp3)
        record["status"] = "complete"
        report("complete", 100, "Hoàn tất phần này")
        return record
    except Exception as exc:
        record.update(status="stopped" if isinstance(exc, WorkflowStopped) else "error", error=str(exc))
        manifest.update(stage=record["stage"], status=record["status"], error=str(exc))
        _write_json(manifest_path, manifest)
        if progress:
            progress(record["stage"], 0, str(exc), dict(record))
        raise
    finally:
        wav.unlink(missing_ok=True)
        for pending in [*folder.glob("*.pending.*"), *work.glob("*.pending.*")]:
            pending.unlink(missing_ok=True)
