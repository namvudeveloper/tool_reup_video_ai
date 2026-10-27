import re
from urllib.parse import urlsplit, urlunsplit


def normalize_video_url(value: str) -> str:
    """Remove Bilibili's locale prefix, which current yt-dlp treats as generic HTML."""
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.hostname not in {"bilibili.com", "www.bilibili.com"}:
        return value
    path = re.sub(r"^/[a-z]{2}(?:-Hans)?(?=/video/BV[0-9A-Za-z]+(?:/|$))", "", parsed.path)
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
