"""Small cached waveform previews; decode audio only and never modify the media."""
from functools import lru_cache
from pathlib import Path
import math
import re
import subprocess
import threading

_decode_slots = threading.BoundedSemaphore(2)


@lru_cache(maxsize=24)
def _decode(path: str, mtime: int, size: int, ffmpeg: str, start: float, duration: float | None):
    # Seek before decoding: close zoom reads only the visible audio interval,
    # retaining millisecond detail even when the source spans many hours.
    frame_size = 4096 if duration is None else max(128, min(4096, 2 ** math.ceil(math.log2(max(1, duration * 10)))))
    command = [ffmpeg, "-v", "error"]
    if start:
        command += ["-ss", str(start)]
    command += ["-i", path]
    if duration is not None:
        command += ["-t", str(duration)]
    command += ["-vn", "-af",
                f"aformat=channel_layouts=mono,asetnsamples=n={frame_size},astats=metadata=1:reset=1,"
                "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-", "-f", "null", "-"]
    with _decode_slots:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=True)
    frames = []
    at = 0.0
    for line in result.stdout.splitlines():
        if "pts_time:" in line:
            match = re.search(r"pts_time:([\d.eE+-]+)", line)
            if match:
                at = float(match.group(1))
        elif line.startswith("lavfi.astats.Overall.Peak_level="):
            db = float(line.split("=", 1)[1])
            frames.append((at, min(1.0, 10 ** (db / 20)) if math.isfinite(db) else 0.0))
    if not frames:
        return {"peaks": [], "duration": 0}
    interval = frames[-1][0] - frames[-2][0] if len(frames) > 1 else .1
    decoded_duration = frames[-1][0] + interval
    if duration is not None:
        decoded_duration = min(duration, decoded_duration)
    bins = min(1200, len(frames))
    peaks = [0.0] * bins
    for at, value in frames:
        i = min(bins - 1, int(at / max(decoded_duration, .001) * bins))
        peaks[i] = max(peaks[i], value)
    return {"peaks": [round(p, 4) for p in peaks], "duration": round(decoded_duration, 3)}


def read_waveform(path: Path, ffmpeg: str, start: float = 0, duration: float | None = None):
    if not math.isfinite(start) or start < 0 or (duration is not None and (not math.isfinite(duration) or duration <= 0)):
        raise ValueError("Invalid waveform interval")
    stat = path.stat()
    return _decode(str(path.resolve()), stat.st_mtime_ns, stat.st_size, ffmpeg, start, duration)
