import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BILI_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

BILI_HEADERS = {
    "User-Agent": BILI_UA,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_YDL_INSTANCE = None


def is_bilibili_url(url: str) -> bool:
    u = (url or "").lower()
    return "bilibili.com/video/" in u or "b23.tv/" in u


def extract_bvid_and_page(url: str) -> Tuple[Optional[str], Optional[int]]:
    """Tách mã BV (ví dụ BV1vt8A61Eao) và số trang (?p=1) từ link Bilibili."""
    m = re.search(r"(BV[0-9A-Za-z]{10})", url, re.IGNORECASE)
    if not m:
        return None, None
    bvid = "BV" + m.group(1)[2:]
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    p_val = None
    if "p" in qs and qs["p"]:
        try:
            p_val = int(qs["p"][0])
        except ValueError:
            p_val = None
    return bvid, p_val


class _SilentLogger:
    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def _get_bilibili_ydl():
    """
    Khởi tạo YoutubeDL tích hợp sẵn Cookie từ Google Chrome (nếu đọc được) và lấy buvid3/buvid4
    hợp lệ từ Bilibili SPI. Trên Windows, khi Chrome đang mở và khóa file SQLite Cookies,
    tự động chuyển sang chế độ không cần Cookie Chrome (dùng buvid3 + try_look=1) để không bị lỗi.
    """
    global _YDL_INSTANCE
    if _YDL_INSTANCE is not None:
        return _YDL_INSTANCE

    import yt_dlp

    base_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "http_headers": BILI_HEADERS,
        "logger": _SilentLogger(),
    }

    chrome_default_mac = Path.home() / "Library/Application Support/Google/Chrome/Default"
    chrome_default_win = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Chrome/User Data/Default"
        if os.environ.get("LOCALAPPDATA")
        else None
    )

    ydl = None
    cookie_source = None
    if chrome_default_mac.is_dir():
        cookie_source = ("chrome", str(chrome_default_mac), None, None)
    elif chrome_default_win and chrome_default_win.is_dir():
        cookie_source = ("chrome", str(chrome_default_win), None, None)

    if cookie_source is not None:
        try:
            opts_with_cookie = dict(base_opts)
            opts_with_cookie["cookiesfrombrowser"] = cookie_source
            candidate = yt_dlp.YoutubeDL(opts_with_cookie)
            # Kiểm tra truy cập cookiejar ngay; nếu Chrome trên Windows đang mở và khóa DB sẽ ném lỗi tại đây
            _ = candidate.cookiejar
            ydl = candidate
        except Exception:
            ydl = None

    if ydl is None:
        ydl = yt_dlp.YoutubeDL(dict(base_opts))

    # Cấp phát buvid3 & buvid4 thật từ API chính thức của Bilibili để vượt kiểm tra 412 / -352
    try:
        import http.cookiejar

        spi_raw = ydl.urlopen("https://api.bilibili.com/x/frontend/finger/spi").read().decode("utf-8")
        spi_data = json.loads(spi_raw).get("data", {})
        for cname, key in (("buvid3", "b_3"), ("buvid4", "b_4")):
            val = spi_data.get(key)
            if val:
                ydl.cookiejar.set_cookie(
                    http.cookiejar.Cookie(
                        0, cname, str(val), None, False,
                        ".bilibili.com", True, True, "/", True,
                        False, None, True, None, None, {}, False,
                    )
                )
    except Exception:
        pass

    _YDL_INSTANCE = ydl
    return ydl


def _http_get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if params:
        query_str = urllib.parse.urlencode(params)
        url = f"{url}?{query_str}"
    req = urllib.request.Request(url, headers=BILI_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def fetch_bilibili_pages(url: str) -> Dict[str, Any]:
    """
    Lấy danh sách các tập (pages) và tổng thời lượng thực tế trực tiếp từ API pagelist của Bilibili,
    vượt qua hoàn toàn lỗi 412 / Unable to extract initial state của trang HTML.
    """
    bvid, page_num = extract_bvid_and_page(url)
    if not bvid:
        raise ValueError(f"Link Bilibili không hợp lệ (không tìm thấy mã BV): {url}")

    res = _http_get_json("https://api.bilibili.com/x/player/pagelist", {"bvid": bvid})
    if res.get("code") != 0 or not res.get("data"):
        raise RuntimeError(f"Bilibili pagelist API trả về lỗi: {res.get('message')}")

    pages: List[Dict[str, Any]] = res["data"]
    # Nếu link không chỉ định ?p=... (ví dụ đang xem Tập 1 có ?t=6.8 dài 2 tiếng), mặc định lấy đúng Page 1 đang xem
    target_page = page_num if page_num is not None else 1
    filtered = [p for p in pages if int(p.get("page", 0)) == target_page]
    if filtered:
        pages = filtered

    total_duration = sum(float(p.get("duration", 0) or 0) for p in pages)
    first_part = str(pages[0].get("part") or bvid).strip()
    title = f"{bvid} - {first_part}"

    return {
        "bvid": bvid,
        "title": title,
        "total_duration": total_duration,
        "pages": pages,
    }


def get_bilibili_stream_urls(bvid: str, cid: int) -> Dict[str, Any]:
    """
    Lấy link luồng Video + Audio trực tiếp thông qua BiliBiliIE._download_playinfo (bỏ qua bước cào HTML bị chặn).
    """
    ydl = _get_bilibili_ydl()
    ie = ydl.get_info_extractor("BiliBili")
    play_info = ie._download_playinfo(
        bvid,
        cid,
        headers=BILI_HEADERS,
        query={"try_look": 1},
    )

    if "dash" in play_info and play_info["dash"]:
        videos = list(play_info["dash"].get("video") or [])
        audios = list(play_info["dash"].get("audio") or [])
        # Ưu tiên codec H.264 (codecid=7) và độ phân giải cao nhất (1080p)
        videos.sort(
            key=lambda v: (
                1 if v.get("codecid") == 7 else 0,
                int(v.get("height", 0) or 0),
                int(v.get("bandwidth", 0) or 0),
            ),
            reverse=True,
        )
        audios.sort(key=lambda a: int(a.get("bandwidth", 0) or 0), reverse=True)

        v_url = (videos[0].get("baseUrl") or videos[0].get("base_url")) if videos else None
        a_url = (audios[0].get("baseUrl") or audios[0].get("base_url")) if audios else None
        if v_url:
            return {
                "type": "dash",
                "video_url": v_url,
                "audio_url": a_url,
                "width": videos[0].get("width", 1920),
                "height": videos[0].get("height", 1080),
            }

    if "durl" in play_info and play_info["durl"]:
        durl_item = play_info["durl"][0]
        return {
            "type": "durl",
            "video_url": durl_item.get("url"),
            "audio_url": None,
            "width": 1920,
            "height": 1080,
        }

    raise RuntimeError(f"Không tìm thấy luồng phát hợp lệ cho Bilibili {bvid} (cid={cid})")


def download_bilibili_slice_via_ffmpeg(
    url: str,
    output_mp4: Path,
    ffmpeg_path: str,
    slice_range: Optional[Tuple[float, float]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> Path:
    """
    Tải trực tiếp toàn bộ hoặc chỉ 1 phân đoạn (ví dụ 15 phút: slice_range=(start_sec, dur_sec))
    từ Bilibili bằng FFmpeg HTTP Range Seek.
    """
    info = fetch_bilibili_pages(url)
    bvid = info["bvid"]
    pages = info["pages"]
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    if slice_range is not None and slice_range[1] > 0:
        req_start, req_dur = float(slice_range[0]), float(slice_range[1])
    else:
        req_start, req_dur = 0.0, float(info["total_duration"])

    req_end = req_start + req_dur

    accum_time = 0.0
    segments_to_fetch: List[Dict[str, Any]] = []

    for p in pages:
        p_dur = float(p.get("duration", 0) or 0)
        p_start_global = accum_time
        p_end_global = accum_time + p_dur
        accum_time = p_end_global

        overlap_start = max(req_start, p_start_global)
        overlap_end = min(req_end, p_end_global)
        if overlap_end > overlap_start + 0.5:
            local_offset = overlap_start - p_start_global
            local_length = overlap_end - overlap_start
            segments_to_fetch.append(
                {
                    "cid": int(p["cid"]),
                    "page": int(p.get("page", 1)),
                    "part": str(p.get("part", "")),
                    "ss": round(local_offset, 3),
                    "t": round(local_length, 3),
                }
            )

    if not segments_to_fetch:
        segments_to_fetch.append(
            {
                "cid": int(pages[0]["cid"]),
                "page": 1,
                "part": str(pages[0].get("part", "")),
                "ss": 0.0,
                "t": min(req_dur, float(pages[0].get("duration", 900))),
            }
        )

    headers_str = (
        f"Referer: https://www.bilibili.com/\r\n"
        f"User-Agent: {BILI_UA}\r\n"
    )

    part_files: List[Path] = []
    for idx, seg in enumerate(segments_to_fetch, start=1):
        stream_info = get_bilibili_stream_urls(bvid, seg["cid"])
        v_url = stream_info["video_url"]
        a_url = stream_info["audio_url"]
        seg_out = (
            output_mp4
            if len(segments_to_fetch) == 1
            else output_mp4.parent / f"{output_mp4.stem}_sub{idx:02d}.mp4"
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
        ]

        reconnect_opts = [
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
        ]

        cmd.extend(["-headers", headers_str, *reconnect_opts])
        if seg["ss"] > 0:
            cmd.extend(["-ss", f"{seg['ss']:.3f}"])
        cmd.extend(["-i", v_url])

        if a_url:
            cmd.extend(["-headers", headers_str, *reconnect_opts])
            if seg["ss"] > 0:
                cmd.extend(["-ss", f"{seg['ss']:.3f}"])
            cmd.extend(["-i", a_url])
            cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])

        if seg["t"] > 0:
            cmd.extend(["-t", f"{seg['t']:.3f}"])

        cmd.extend(
            [
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(seg_out),
            ]
        )

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        total_us = max(1, int(seg["t"] * 1_000_000))
        if proc.stdout:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    val = line.split("=", 1)[1].strip()
                    if val.isdigit() and progress_callback:
                        pct = min(100.0, (int(val) / total_us) * 100.0)
                        progress_callback(pct)
        rc = proc.wait()
        if rc != 0 or not seg_out.is_file():
            raise RuntimeError(f"Tải phân đoạn Bilibili thất bại (cid={seg['cid']}, mã lỗi={rc})")
        part_files.append(seg_out)

    if len(part_files) > 1:
        concat_list = output_mp4.parent / f"{output_mp4.stem}_bili_concat.txt"
        lines = [f"file '{pf.resolve().as_posix()}'" for pf in part_files]
        concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(output_mp4),
            ],
            check=True,
        )
        concat_list.unlink(missing_ok=True)
        for pf in part_files:
            pf.unlink(missing_ok=True)

    return output_mp4
