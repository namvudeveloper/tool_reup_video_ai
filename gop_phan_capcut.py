#!/usr/bin/env python3
"""
gop_phan_capcut.py
------------------
Gộp toàn bộ các phần (Phan_01, Phan_02, ...) của 1 bộ phim trong output/<Tên_Phim>/ thành:
  1. <Tên_Phim>_FULL.mp4      : nối không mất chất lượng (stream copy, không render lại)
  2. <Tên_Phim>_FULL.vi.srt   : phụ đề Tiếng Việt gộp, tự cộng dồn mốc thời gian từng phần

Cách dùng:
  .venv\\Scripts\\python.exe gop_phan_capcut.py "output\\Kẻ_Đi_Bộ_Trong_Bóng_Tối"
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_sub_pipeline import _find_ffmpeg  # noqa: E402

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _ts_to_sec(ts: str) -> float:
    m = _TS.search(ts)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def _sec_to_ts(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path: Path) -> List[Tuple[float, float, str]]:
    cues = []
    text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        ts_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if ts_idx < 0:
            continue
        a, b = lines[ts_idx].split("-->", 1)
        body = "\n".join(lines[ts_idx + 1 :]).strip()
        if body:
            cues.append((_ts_to_sec(a), _ts_to_sec(b), body))
    return cues


def probe_duration(ffprobe: str, media: Path) -> float:
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(media)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return float(json.loads(r.stdout or "{}").get("format", {}).get("duration", 0.0) or 0.0)


def collect_parts(film_dir: Path) -> List[Tuple[Path, Path | None]]:
    parts = []
    for d in sorted(p for p in film_dir.iterdir() if p.is_dir() and p.name.lower().startswith("phan_")):
        mp4 = next((f for f in sorted(d.glob("*.mp4")) if "_FULL" not in f.stem), None)
        if not mp4:
            continue
        srt = next(iter(sorted(d.glob("*.vi.srt"))), None)
        parts.append((mp4, srt))
    return parts


def build(film_dir: Path) -> Tuple[Path, Path, List[Tuple[float, float, str]], float]:
    ffmpeg, ffprobe = _find_ffmpeg()
    film_dir = film_dir.resolve()
    parts = collect_parts(film_dir)
    if not parts:
        raise SystemExit(f"Không tìm thấy thư mục Phan_xx nào chứa .mp4 trong {film_dir}")

    name = film_dir.name
    out_mp4 = film_dir / f"{name}_FULL.mp4"
    out_srt = film_dir / f"{name}_FULL.vi.srt"

    # 1) Phụ đề gộp: cộng dồn đúng thời lượng thực của từng phần
    merged: List[Tuple[float, float, str]] = []
    offset = 0.0
    for mp4, srt in parts:
        dur = probe_duration(ffprobe, mp4)
        if srt and srt.is_file():
            for s, e, t in parse_srt(srt):
                s2, e2 = min(s, dur), min(e, dur)
                if e2 > s2:
                    merged.append((s2 + offset, e2 + offset, t))
        print(f"  • {mp4.parent.name}: {dur:.2f}s, offset {offset:.2f}s, srt={'có' if srt else 'KHÔNG'}")
        offset += dur
    total = offset
    out_srt.write_text(
        "\n".join(f"{i}\n{_sec_to_ts(s)} --> {_sec_to_ts(e)}\n{t}\n" for i, (s, e, t) in enumerate(merged, 1)),
        encoding="utf-8",
    )
    print(f"✅ Phụ đề gộp: {out_srt.name} ({len(merged)} câu, {total / 3600:.2f} giờ)")

    # 2) Video gộp không mất chất lượng
    if out_mp4.is_file() and abs(probe_duration(ffprobe, out_mp4) - total) < 2.0:
        print(f"✅ Video gộp đã có sẵn: {out_mp4.name}")
    else:
        list_file = film_dir / "_concat_list.txt"
        list_file.write_text(
            "".join("file '" + str(mp4).replace("\\", "/").replace("'", "'\\''") + "'\n" for mp4, _ in parts),
            encoding="utf-8",
        )
        print(f"🎬 Đang nối {len(parts)} phần thành {out_mp4.name} (stream copy, không render lại)...")
        r = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stats",
             "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", str(out_mp4)],
        )
        list_file.unlink(missing_ok=True)
        if r.returncode != 0 or not out_mp4.is_file():
            raise SystemExit("❌ Nối video thất bại.")
        print(f"✅ Video gộp: {out_mp4.name} ({out_mp4.stat().st_size / 1024**3:.2f} GB, "
              f"{probe_duration(ffprobe, out_mp4) / 3600:.2f} giờ)")
    return out_mp4, out_srt, merged, total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]))
