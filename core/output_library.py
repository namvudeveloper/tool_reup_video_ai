"""Read the output library from disk without changing files or probing media."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable

VIDEO = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
INTERNAL = {"subtitles", "temp", "temp_processed", "raw"}


def natural_key(name: str):
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", name)]


def scan_output_library(root: Path, live_records: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    root = Path(root).resolve()
    live = {str(Path(r["path"]).resolve()): r for r in live_records if r.get("path")}
    projects: Dict[str, Dict[str, Any]] = {}

    def safe(path: Path) -> bool:
        try:
            return path.resolve().is_relative_to(root)
        except (OSError, ValueError):
            return False

    def files_in(folder: Path):
        try:
            return sorted((p for p in folder.iterdir() if p.is_file() and safe(p)
                           and not p.name.startswith(".") and ".pending" not in p.stem),
                          key=lambda p: natural_key(p.name))
        except OSError:
            return []

    def project(key: str, name: str, folder: Path):
        if key not in projects:
            projects[key] = {"id": key, "name": name, "folder": str(folder), "parts": []}
        return projects[key]

    def part(proj, folder: Path, files, index: int, video: Path | None = None):
        videos = [p for p in files if p.suffix.lower() in VIDEO]
        if video is None:
            originals = [p for p in videos if not re.search(r"(?:CapCut|Lồng_Tiếng|Long_Tieng)", p.stem, re.I)]
            video = next(iter(originals or videos), None)
        stem = video.stem if video else folder.name

        def choose(candidates):
            return next((p for p in candidates if p.is_file() and safe(p)), None)

        vi = choose([folder / f"{stem}.vi.srt", folder / f"{stem}.srt",
                     root / "subtitles" / f"{stem}.vi.srt"])
        if not vi:
            vi = next((p for p in files if p.suffix.lower() == ".srt" and not p.name.endswith(".zh.srt")), None)
        audio = choose([folder / f"{stem}.thuyet_minh.mp3", folder / f"{stem}.vi_thuyet_minh.mp3",
                        folder / f"{stem}.mp3", root / f"{stem}.vi_thuyet_minh.mp3"])
        if not audio and folder != root:
            audio = next((p for p in files if p.suffix.lower() in {".mp3", ".wav", ".m4a"}), None)
        try:
            checkpoint_path = folder / ".work/progress.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if safe(checkpoint_path) else {}
        except (OSError, ValueError):
            checkpoint = {}
        active = live.get(str(video.resolve()) if video else "", {})
        status = active.get("status") if active.get("status") in {"running", "error", "stopped"} else checkpoint.get("status")
        if status == "running" and active.get("status") != "running":
            status = "stopped"
        if status not in {"running", "error", "stopped"}:
            status = "complete" if video and vi and audio else "partial" if video or vi or audio else "empty"
        total_bytes = 0
        modified = 0.0
        for file in set(files) | {p for p in (vi, audio) if p}:
            try:
                stat = file.stat()
                total_bytes += stat.st_size
                modified = max(modified, stat.st_mtime)
            except OSError:
                pass
        ident = str(folder.relative_to(root)) if folder != root else f"legacy:{stem}"
        proj["parts"].append({
            "id": ident, "chunk_index": index, "name": f"Phần {index:02d}", "file_name": stem,
            "folder": str(folder), "path": str(video.resolve()) if video else "",
            "srt_path": str(vi.resolve()) if vi else "", "audio_vi": str(audio.resolve()) if audio else "",
            "status": status, "stage": active.get("stage", checkpoint.get("stage", "video")),
            "error": active.get("error", checkpoint.get("error", "")), "size_bytes": total_bytes,
            "modified_at": modified, "duration_human": active.get("duration_human", ""),
            "files": [{"name": p.name, "path": str(p.resolve()), "type": p.suffix.lstrip(".").lower()} for p in files],
        })

    if root.is_dir():
        # Empty project directories are meaningful: show them without invented parts.
        for folder in sorted(root.iterdir(), key=lambda p: natural_key(p.name)):
            if not folder.is_dir() or folder.name.startswith(".") or folder.name in INTERNAL or not safe(folder):
                continue
            proj = project(folder.name, folder.name, folder)
            subfolders = sorted((p for p in folder.iterdir() if p.is_dir() and safe(p)
                                 and not p.name.startswith(".") and p.name not in INTERNAL), key=lambda p: natural_key(p.name))
            for i, subfolder in enumerate(subfolders, 1):
                match = re.search(r"(?:phan|phần|part)[ _-]*(\d+)", subfolder.name, re.I)
                part(proj, subfolder, files_in(subfolder), int(match.group(1)) if match else i)
            direct = files_in(folder)
            if any(p.suffix.lower() in VIDEO for p in direct):
                part(proj, folder, direct, len(proj["parts"]) + 1)

        grouped_names = {Path(p["path"]).name for pr in projects.values() for p in pr["parts"] if p["path"]}
        for file in files_in(root):
            if file.suffix.lower() not in VIDEO or file.name in grouped_names:
                continue
            match = re.search(r"^(.*?)_Phan_(\d+)$", file.stem, re.I)
            name = match.group(1) if match else "Chưa phân nhóm"
            proj = project(name, name, root / name if (root / name).is_dir() else root)
            part(proj, root, [file], int(match.group(2)) if match else len(proj["parts"]) + 1, video=file)

    rows = list(projects.values())
    for proj in rows:
        proj["parts"].sort(key=lambda p: (p["chunk_index"], natural_key(p["file_name"])))
        proj["part_count"] = len(proj["parts"])
        proj["complete_count"] = sum(p["status"] == "complete" for p in proj["parts"])
        proj["error_count"] = sum(p["status"] == "error" for p in proj["parts"])
        proj["size_bytes"] = sum(p["size_bytes"] for p in proj["parts"])
        proj["modified_at"] = max((p["modified_at"] for p in proj["parts"]), default=0)
    rows.sort(key=lambda p: (-p["modified_at"], natural_key(p["name"])))
    return {"root": str(root), "projects": rows, "summary": {
        "projects": len(rows), "parts": sum(p["part_count"] for p in rows),
        "complete": sum(p["complete_count"] for p in rows),
        "size_bytes": sum(p["size_bytes"] for p in rows),
    }}
