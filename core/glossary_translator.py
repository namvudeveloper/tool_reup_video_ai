"""Glossary rules, sentence-aware cue merging, and resilient batch translation helpers."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.part_workflow import check_stop

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GLOSSARY_PATH = PROJECT_ROOT / "custom_glossary.json"

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SENTENCE_END_RE = re.compile(r"[。！？.!?…；;:：\"'”’」』）】\)]$")
_TOKEN_RE_TEMPLATE = r"X\s*GLOSS\s*{idx:04d}\s*X"
_BATCH_MARKER_RE = re.compile(r"(?:^|\n)\s*\[?\s*XQ(\d{3})X\s*\]?\s*[:：\-]?\s*")
_INLINE_MARKER_RE = re.compile(r"\[?\s*XQ(\d{3})X\s*\]?\s*[:：\-]?\s*")

XIANXIA_STARTER_RULES: List[Dict[str, Any]] = [
    {"zh": "师兄", "vi": "sư huynh", "type": "title", "stage": "both"},
    {"zh": "师姐", "vi": "sư tỷ", "type": "title", "stage": "both"},
    {"zh": "师弟", "vi": "sư đệ", "type": "title", "stage": "both"},
    {"zh": "师妹", "vi": "sư muội", "type": "title", "stage": "both"},
    {"zh": "师尊", "vi": "sư tôn", "type": "title", "stage": "both"},
    {"zh": "师父", "vi": "sư phụ", "type": "title", "stage": "both"},
    {"zh": "宗主", "vi": "tông chủ", "type": "title", "stage": "both"},
    {"zh": "长老", "vi": "trưởng lão", "type": "title", "stage": "both"},
    {"zh": "弟子", "vi": "đệ tử", "type": "title", "stage": "both"},
    {"zh": "道友", "vi": "đạo hữu", "type": "title", "stage": "both"},
    {"zh": "前辈", "vi": "tiền bối", "type": "title", "stage": "both"},
    {"zh": "晚辈", "vi": "vãn bối", "type": "title", "stage": "both"},
    {"zh": "在下", "vi": "tại hạ", "type": "title", "stage": "both"},
    {"zh": "阁下", "vi": "các hạ", "type": "title", "stage": "both"},
    {"zh": "灵气", "vi": "linh khí", "type": "term", "stage": "both"},
    {"zh": "灵石", "vi": "linh thạch", "type": "term", "stage": "both"},
    {"zh": "炼气", "vi": "Luyện Khí", "type": "realm", "stage": "both"},
    {"zh": "筑基", "vi": "Trúc Cơ", "type": "realm", "stage": "both"},
    {"zh": "金丹", "vi": "Kim Đan", "type": "realm", "stage": "both"},
    {"zh": "元婴", "vi": "Nguyên Anh", "stage": "realm", "stage": "both"},
    {"zh": "化神", "vi": "Hóa Thần", "type": "realm", "stage": "both"},
    {"zh": "渡劫", "vi": "độ kiếp", "type": "term", "stage": "both"},
    {"zh": "飞剑", "vi": "phi kiếm", "type": "term", "stage": "both"},
    {"zh": "法宝", "vi": "pháp bảo", "type": "term", "stage": "both"},
    {"zh": "功法", "vi": "công pháp", "type": "term", "stage": "both"},
    {"zh": "秘境", "vi": "bí cảnh", "type": "place", "stage": "both"},
]


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _normalize_single_rule(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    stage = str(item.get("stage", "") or "").strip().lower()
    rule_type = str(item.get("type", "term") or "term").strip()
    case_sensitive = bool(item.get("case_sensitive", False))

    zh = str(item.get("zh", "") or "").strip()
    vi = str(item.get("vi", "") or "").strip()
    find = str(item.get("find", item.get("pattern", "")) or "").strip()
    replace = str(item.get("replace", item.get("replacement", "")) or "").strip()

    if not zh and not find:
        src = str(item.get("source", item.get("from", "")) or "").strip()
        dst = str(item.get("target", item.get("to", "")) or "").strip()
        if src and dst:
            if _has_cjk(src) and stage != "post":
                zh, vi = src, dst
            else:
                find, replace = src, dst

    if zh and vi and stage != "post":
        return {"zh": zh, "vi": vi, "type": rule_type, "stage": "both"}

    if find and replace != "":
        return {
            "find": find,
            "replace": replace,
            "type": rule_type,
            "stage": "post",
            "case_sensitive": case_sensitive,
        }
    return None


def normalize_glossary_payload(raw_data: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Normalize arbitrary glossary JSON structures into {'rules': [...]}."""
    rules: List[Dict[str, Any]] = []

    if isinstance(raw_data, list):
        candidates = raw_data
    elif isinstance(raw_data, dict):
        if isinstance(raw_data.get("rules"), list):
            candidates = list(raw_data["rules"])
        elif any(k in raw_data for k in ("zh_terms", "post_fixes", "terms")):
            candidates = []
            for key in ("zh_terms", "terms"):
                mapping = raw_data.get(key)
                if isinstance(mapping, dict):
                    for k, v in mapping.items():
                        candidates.append({"zh": str(k), "vi": str(v), "stage": "both"})
            post_map = raw_data.get("post_fixes")
            if isinstance(post_map, dict):
                for k, v in post_map.items():
                    candidates.append({"find": str(k), "replace": str(v), "stage": "post"})
        else:
            candidates = [
                {"source": str(k), "target": str(v)}
                for k, v in raw_data.items()
                if isinstance(v, (str, int, float))
            ]
    else:
        candidates = []

    for item in candidates:
        norm = _normalize_single_rule(item)
        if norm is not None:
            rules.append(norm)

    merged, _ = merge_glossary_rules([], rules)
    return {"rules": merged}


def merge_glossary_rules(
    existing_rules: Sequence[Dict[str, Any]],
    incoming_rules: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """Merge rules without duplicates, preferring incoming translations for matching keys."""
    merged: List[Dict[str, Any]] = []
    index_by_key: Dict[Tuple[str, str], int] = {}

    def _rule_key(rule: Dict[str, Any]) -> Tuple[str, str]:
        if rule.get("stage") == "post":
            return ("post", str(rule.get("find", "")).strip().lower())
        return ("both", str(rule.get("zh", "")).strip())

    for raw in existing_rules:
        norm = _normalize_single_rule(raw)
        if not norm:
            continue
        key = _rule_key(norm)
        if key in index_by_key:
            merged[index_by_key[key]] = norm
        else:
            index_by_key[key] = len(merged)
            merged.append(norm)

    added = 0
    for raw in incoming_rules:
        norm = _normalize_single_rule(raw)
        if not norm:
            continue
        key = _rule_key(norm)
        if key in index_by_key:
            merged[index_by_key[key]] = norm
        else:
            index_by_key[key] = len(merged)
            merged.append(norm)
            added += 1

    return merged, added


def load_glossary(path: Optional[Path] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Load and normalize custom_glossary.json; returns empty rules if missing or invalid."""
    target = Path(path) if path is not None else DEFAULT_GLOSSARY_PATH
    if not target.is_file():
        return {"rules": []}
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"rules": []}
    return normalize_glossary_payload(raw)


def save_glossary(data: Any, path: Optional[Path] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Atomically write normalized glossary JSON to disk."""
    target = Path(path) if path is not None else DEFAULT_GLOSSARY_PATH
    normalized = normalize_glossary_payload(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return normalized


def glossary_signature(rules: Sequence[Dict[str, Any]]) -> str:
    payload = json.dumps(list(rules), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def mask_batch_texts(
    texts: Sequence[str],
    rules: Sequence[Dict[str, Any]],
) -> Tuple[List[str], Dict[int, str]]:
    """Pre-replace Chinese glossary terms with Google-safe alphanumeric placeholders."""
    pre_rules = sorted(
        (r for r in rules if r.get("stage") != "post" and r.get("zh") and r.get("vi")),
        key=lambda r: len(str(r["zh"])),
        reverse=True,
    )
    if not pre_rules:
        return list(texts), {}

    term_to_idx: Dict[str, int] = {}
    token_map: Dict[int, str] = {}
    zh_pattern = re.compile("|".join(re.escape(str(r["zh"])) for r in pre_rules))
    zh_to_vi = {str(r["zh"]): str(r["vi"]) for r in pre_rules}

    def _mask_one(text: str) -> str:
        if not text:
            return ""
        parts: List[str] = []
        last = 0
        for match in zh_pattern.finditer(text):
            start, end = match.span()
            matched_zh = match.group(0)
            if matched_zh not in term_to_idx:
                idx = len(term_to_idx)
                term_to_idx[matched_zh] = idx
                token_map[idx] = zh_to_vi[matched_zh]
            idx = term_to_idx[matched_zh]
            parts.append(text[last:start])
            need_left_space = start > 0 and not text[start - 1].isspace()
            need_right_space = end < len(text) and not text[end].isspace()
            token = f"XGLOSS{idx:04d}X"
            parts.append(f"{' ' if need_left_space else ''}{token}{' ' if need_right_space else ''}")
            last = end
        parts.append(text[last:])
        return "".join(parts)

    return [_mask_one(t) for t in texts], token_map


def apply_post_replace(
    text: str,
    token_map: Dict[int, str],
    rules: Sequence[Dict[str, Any]],
) -> str:
    """Apply post-translation Vietnamese replacements, then restore protected glossary tokens."""
    out = text or ""

    post_rules = sorted(
        (r for r in rules if r.get("stage") == "post" and r.get("find")),
        key=lambda r: len(str(r["find"])),
        reverse=True,
    )
    if post_rules:
        patterns: List[str] = []
        rule_lookup: List[Tuple[re.Pattern[str], str]] = []
        for idx, rule in enumerate(post_rules):
            find_str = str(rule["find"])
            rep_str = str(rule.get("replace", ""))
            flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
            if _has_cjk(find_str):
                inner = re.escape(find_str)
            else:
                left_boundary = r"(?<!\w)" if find_str[0].isalnum() or find_str[0] == "_" else ""
                right_boundary = r"(?!\w)" if find_str[-1].isalnum() or find_str[-1] == "_" else ""
                inner = f"{left_boundary}{re.escape(find_str)}{right_boundary}"
            group_name = f"P{idx}"
            # Keep single-pass alternation longest-first while honoring per-rule case sensitivity.
            inline_flag = "(?i:" + inner + ")" if flags & re.IGNORECASE else inner
            patterns.append(f"(?P<{group_name}>{inline_flag})")
            rule_lookup.append((re.compile(inner, flags), rep_str))

        combined = re.compile("|".join(patterns))

        def _replace_match(match: re.Match[str]) -> str:
            last_group = match.lastgroup
            if not last_group:
                return match.group(0)
            r_idx = int(last_group[1:])
            return rule_lookup[r_idx][1]

        out = combined.sub(_replace_match, out)

    if token_map:
        for idx, vi_term in token_map.items():
            pattern = re.compile(_TOKEN_RE_TEMPLATE.format(idx=idx), re.IGNORECASE)
            out = pattern.sub(lambda _m, rep=vi_term: rep, out)

    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r" {2,}", " ", out).strip()
    return out


def apply_glossary_to_rows(
    rows: Sequence[Dict[str, Any]],
    rules: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """Apply post-replace rules to existing SRT editor rows without re-translating."""
    updated: List[Dict[str, Any]] = []
    changed_count = 0
    for row in rows:
        new_row = dict(row)
        orig_vi = str(new_row.get("vi_text", "") or "")
        new_vi = apply_post_replace(orig_vi, {}, rules)
        if new_vi != orig_vi:
            new_row["vi_text"] = new_vi
            changed_count += 1
        updated.append(new_row)
    return updated, changed_count


def _ends_sentence(text: str) -> bool:
    cleaned = (text or "").strip()
    return bool(cleaned and _SENTENCE_END_RE.search(cleaned))


def join_cues_text(cues: Sequence[Any]) -> str:
    """Join adjacent subtitle texts smoothly without inserting spaces inside Chinese."""
    out = ""
    for cue in cues:
        part = (getattr(cue, "content", "") or "").replace("\n", " ").strip()
        if not part:
            continue
        if not out:
            out = part
        elif _has_cjk(out[-1]) and _has_cjk(part[0]):
            out += part
        else:
            out += " " + part
    return out


def group_broken_cues(
    subtitles: Sequence[Any],
    max_gap_sec: float = 0.75,
    max_cues: int = 4,
    max_chars: int = 120,
) -> List[List[Any]]:
    """Group consecutive incomplete Whisper cues into whole sentences for natural translation."""
    groups: List[List[Any]] = []
    current_group: List[Any] = []
    current_chars = 0

    for cue in subtitles:
        text = (getattr(cue, "content", "") or "").replace("\n", " ").strip()
        if not current_group:
            current_group = [cue]
            current_chars = len(text)
            continue

        prev = current_group[-1]
        prev_text = (getattr(prev, "content", "") or "").replace("\n", " ").strip()
        gap = (cue.start - prev.end).total_seconds()
        should_merge = (
            gap <= max_gap_sec
            and not _ends_sentence(prev_text)
            and len(current_group) < max_cues
            and current_chars + len(text) <= max_chars
        )
        if should_merge:
            current_group.append(cue)
            current_chars += len(text)
        else:
            groups.append(current_group)
            current_group = [cue]
            current_chars = len(text)

    if current_group:
        groups.append(current_group)
    return groups


def split_translation_for_cues(vi_text: str, cues: Sequence[Any]) -> Optional[List[str]]:
    """Split a translated sentence across original cues at word boundaries, keeping all non-empty."""
    cleaned = re.sub(r"\s+", " ", (vi_text or "").strip())
    if len(cues) <= 1:
        return [cleaned] if cleaned else None

    words = cleaned.split(" ") if cleaned else []
    n_cues = len(cues)
    if len(words) < n_cues:
        return None

    weights = [
        max(1, len((getattr(c, "content", "") or "").strip()))
        for c in cues
    ]
    total_weight = float(sum(weights))
    total_words = len(words)

    pieces: List[str] = []
    cursor = 0
    cum_weight = 0.0

    for i in range(n_cues - 1):
        cum_weight += weights[i]
        remaining_cues = n_cues - 1 - i
        min_idx = cursor + 1
        max_idx = total_words - remaining_cues
        ideal_idx = round((cum_weight / total_weight) * total_words)
        split_idx = max(min_idx, min(max_idx, ideal_idx))

        # Prefer breaking right after punctuation within +/-2 words of ideal position.
        best_idx = split_idx
        best_dist = 99
        for cand in range(max(min_idx, split_idx - 2), min(max_idx, split_idx + 2) + 1):
            if words[cand - 1][-1:] in {",", ";", ".", "!", "?", "—", "-"}:
                dist = abs(cand - split_idx)
                if dist < best_dist:
                    best_idx = cand
                    best_dist = dist
        pieces.append(" ".join(words[cursor:best_idx]))
        cursor = best_idx

    pieces.append(" ".join(words[cursor:]))
    return pieces


def _sleep_checking_stop(seconds: float, stop_checker: Optional[Callable[[], bool]]) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        check_stop(stop_checker)
        time.sleep(min(0.2, max(0.01, deadline - time.monotonic())))


def _parse_marked_batch(raw_output: str, count: int) -> Optional[List[str]]:
    if count <= 1:
        cleaned = _INLINE_MARKER_RE.sub("", (raw_output or "")).strip()
        return [cleaned] if cleaned else None

    matches = list(_BATCH_MARKER_RE.finditer(raw_output or ""))
    if len(matches) != count:
        matches = list(_INLINE_MARKER_RE.finditer(raw_output or ""))
    if len(matches) != count:
        return None

    parsed: List[str] = []
    for expected_idx, m in enumerate(matches):
        if int(m.group(1)) != expected_idx:
            return None
        start = m.end()
        end = matches[expected_idx + 1].start() if expected_idx + 1 < count else len(raw_output)
        seg = raw_output[start:end].replace("\n", " ").strip()
        if not seg:
            return None
        parsed.append(seg)
    return parsed


def _parse_newline_batch(raw_output: str, count: int) -> Optional[List[str]]:
    lines = [
        _INLINE_MARKER_RE.sub("", line).strip()
        for line in (raw_output or "").splitlines()
    ]
    lines = [line for line in lines if line]
    if len(lines) == count:
        return lines
    return None


def translate_units_resilient(
    units: Sequence[str],
    translate_fn: Callable[[str], str],
    batch_size: int = 20,
    max_chars: int = 2200,
    sleep_sec: float = 0.25,
    stop_checker: Optional[Callable[[], bool]] = None,
    on_batch_done: Optional[Callable[[int, int, List[str]], None]] = None,
) -> List[str]:
    """
    Translate masked text units reliably for long (8h+) videos:
    - Bounded by both item count and character budget to avoid payload truncation
    - Exponential backoff with stop_checker awareness
    - Marker parsing + recursive binary splitting instead of falling straight to 1-by-1
    """
    total = len(units)
    if total == 0:
        return []

    def _call_with_retry(payload: str) -> str:
        delays = (1.0, 2.5, 5.0, 10.0, 20.0)
        last_exc: Optional[Exception] = None
        for attempt, delay in enumerate(delays):
            check_stop(stop_checker)
            try:
                return translate_fn(payload)
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < len(delays):
                    _sleep_checking_stop(delay, stop_checker)
        raise RuntimeError(
            f"Dịch vụ Google đang giới hạn hoặc gián đoạn sau nhiều lần thử ({last_exc}). "
            "Tiến trình đã được lưu tạm để bạn chạy tiếp từ đoạn đang dở."
        )

    def _translate_slice(slice_items: Sequence[str]) -> List[str]:
        check_stop(stop_checker)
        k = len(slice_items)
        if k == 0:
            return []
        if k == 1:
            translated = _call_with_retry(slice_items[0]).replace("\n", " ").strip()
            if sleep_sec > 0:
                _sleep_checking_stop(min(0.15, sleep_sec), stop_checker)
            return [translated or slice_items[0]]

        marked_payload = "\n".join(f"XQ{i:03d}X {txt}" for i, txt in enumerate(slice_items))
        raw_out = _call_with_retry(marked_payload)
        if sleep_sec > 0:
            _sleep_checking_stop(sleep_sec, stop_checker)

        parsed = _parse_marked_batch(raw_out, k)
        if parsed is not None:
            return parsed

        parsed_lines = _parse_newline_batch(raw_out, k)
        if parsed_lines is not None:
            return parsed_lines

        mid = k // 2
        return _translate_slice(slice_items[:mid]) + _translate_slice(slice_items[mid:])

    results: List[str] = []
    idx = 0
    while idx < total:
        check_stop(stop_checker)
        batch_end = idx
        char_budget = 0
        while batch_end < total and (batch_end - idx) < batch_size:
            next_len = len(units[batch_end]) + 10
            if batch_end > idx and (char_budget + next_len) > max_chars:
                break
            char_budget += next_len
            batch_end += 1

        batch_out = _translate_slice(units[idx:batch_end])
        results.extend(batch_out)
        if on_batch_done:
            on_batch_done(idx, batch_end, batch_out)
        idx = batch_end

    return results


def collect_zh_srt_paths(output_dir: Path, active_video: str = "") -> List[Path]:
    """Collect Chinese .zh.srt files in natural order across project output folders."""
    candidates: List[Path] = []
    seen = set()

    def _add(p: Path) -> None:
        if not p.is_file():
            return
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            candidates.append(p.resolve())

    if active_video:
        vp = Path(active_video)
        _add(vp.parent / ".work" / f"{vp.stem}.zh.srt")
        _add(vp.parent / f"{vp.stem}.zh.srt")
        _add(output_dir / "subtitles" / f"{vp.stem}.zh.srt")

    if output_dir.is_dir():
        for p in sorted(output_dir.rglob("*.zh.srt")):
            if ".pending." not in p.name:
                _add(p)
    return candidates


def build_glossary_sample_text(srt_paths: Sequence[Path], max_chars: int = 12000) -> str:
    """Sample unique Chinese subtitle lines evenly across all parts (great for 8h videos)."""
    try:
        import srt as srt_lib
    except ImportError:
        srt_lib = None

    unique_lines: List[str] = []
    seen_lines = set()

    for path in srt_paths:
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        if srt_lib is not None:
            try:
                texts = [c.content.replace("\n", " ").strip() for c in srt_lib.parse(raw)]
            except Exception:
                texts = [ln.strip() for ln in raw.splitlines()]
        else:
            texts = [ln.strip() for ln in raw.splitlines()]

        for line in texts:
            if not line or "-->" in line or line.isdigit() or not _has_cjk(line):
                continue
            if line not in seen_lines:
                seen_lines.add(line)
                unique_lines.append(line)

    if not unique_lines:
        return ""

    total_chars = sum(len(x) + 1 for x in unique_lines)
    if total_chars <= max_chars:
        return "\n".join(unique_lines)

    # Evenly sample across the entire timeline (start -> middle -> end of 8h video).
    sampled: List[str] = []
    used_chars = 0
    step = max(1.0, total_chars / float(max_chars))
    pos = 0.0
    while int(pos) < len(unique_lines) and used_chars < max_chars:
        line = unique_lines[int(pos)]
        if used_chars + len(line) + 1 > max_chars and sampled:
            break
        sampled.append(line)
        used_chars += len(line) + 1
        pos += step
    return "\n".join(sampled)


def build_gemini_glossary_prompt(sample_text: str) -> str:
    return (
        "Bạn là biên tập viên dịch phụ đề phim/hoạt hình Trung Quốc sang tiếng Việt.\n"
        "Hãy đọc mẫu lời thoại tiếng Trung bên dưới (được lấy mẫu từ đầu đến cuối bộ phim) "
        "và trích xuất toàn bộ TÊN NHÂN VẬT, ĐỊA DANH, TÔNG MÔN, CẢNH GIỚI, CHIÊU THỨC, PHÁP BẢO, "
        "và các THUẬT NGỮ RIÊNG lặp lại nhiều lần.\n"
        "Yêu cầu:\n"
        "1. Dịch sang âm Hán Việt chuẩn hoặc tên tiếng Việt tự nhiên thống nhất.\n"
        "2. CHỈ trả về JSON hợp lệ đúng cấu trúc sau, không giải thích thêm:\n"
        '{"rules": [{"zh": "韩立", "vi": "Hàn Lập", "type": "name"}]}\n'
        "Các giá trị type hợp lệ: name, place, title, skill, realm, term.\n\n"
        "--- MẪU LỜI THOẠI TIẾNG TRUNG ---\n"
        f"{sample_text}"
    )


def extract_json_from_text(text: str) -> Any:
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            return json.loads(raw[start : end + 1])
        arr_start = raw.find("[")
        arr_end = raw.rfind("]")
        if arr_start != -1 and arr_end > arr_start:
            return json.loads(raw[arr_start : arr_end + 1])
        raise


def extract_glossary_with_gemini(
    sample_text: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    """Call Gemini API once to extract proper nouns & terminology into glossary rules."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Chưa nhập Gemini API key.")
    if not (sample_text or "").strip():
        raise ValueError("Chưa có phụ đề tiếng Trung (.zh.srt) để quét glossary.")

    clean_model = (model or "gemini-2.5-flash").strip()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(clean_model)}:generateContent?key={urllib.parse.quote(key)}"
    )
    payload = {
        "contents": [{"parts": [{"text": build_gemini_glossary_prompt(sample_text)}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in (401, 403):
            raise RuntimeError("Gemini API key không hợp lệ hoặc chưa có quyền gọi model này.") from exc
        if exc.code == 429:
            raise RuntimeError(
                "Gemini API đang hết hạn mức (429). Hãy thử đổi sang 'gemini-2.5-flash' "
                "hoặc bấm 'Copy Prompt' dán vào Gemini Web 0đ rồi dán JSON lại."
            ) from exc
        if exc.code == 404:
            raise RuntimeError(f"Không tìm thấy model Gemini '{clean_model}'. Hãy chọn model khác.") from exc
        raise RuntimeError(f"Lỗi Gemini API ({exc.code}): {detail[:240]}") from exc
    except Exception as exc:
        raise RuntimeError(f"Không kết nối được Gemini API: {exc}") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini không trả về kết quả hợp lệ (có thể bị chặn bộ lọc an toàn).")
    parts = candidates[0].get("content", {}).get("parts") or []
    raw_text = "".join(str(p.get("text", "")) for p in parts)
    parsed = extract_json_from_text(raw_text)
    normalized = normalize_glossary_payload(parsed)
    return [r for r in normalized["rules"] if r.get("stage") != "post"]
