import difflib
import re

SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)|^([a-zA-Z0-9-_]{20,})$")
DAY_SEGMENT_BOUNDARY = r"(^|\n|\. )"
DAY_SEGMENT_START_RE = re.compile(rf"{DAY_SEGMENT_BOUNDARY}(\d{{1,2}})\s*•", re.IGNORECASE)
MONEY_DAY_MARKER_RE = re.compile(r"(?:^| )(\d{1,2}) •")
BIO_NEXT_DAY_RE = re.compile(r"(?:\n|\. )\d{1,2}\s*•")
MONEY_INLINE_DAY_MARKER_RE = re.compile(r"\s*\d{1,2}\s*•\s*")
MONTH_SHEET_TITLE_RE = re.compile(r"^\d{2}\.\d{4}$")
YEAR_SHEET_TITLE_RE = re.compile(r"^\d{4}$")
TEMPLATE_SHEET_TITLE_RE = re.compile(r"^(?:шаблон|template|blank|пустой)$", re.IGNORECASE)


def day_segment_pattern(marker: str) -> str:
    return rf"{DAY_SEGMENT_BOUNDARY}({re.escape(str(marker))})\s*•"


def day_segment_match(text: str, marker: str) -> re.Match[str] | None:
    return re.search(day_segment_pattern(marker), text, flags=re.IGNORECASE)


def has_day_segment(text: str, marker: str) -> bool:
    return day_segment_match(text, marker) is not None


def parse_spreadsheet_id(value: str) -> str | None:
    match = SPREADSHEET_ID_RE.search(value.strip())
    if not match:
        return None
    return match.group(1) or match.group(2)


def compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_final_dot(value: str) -> str:
    return value.rstrip().removesuffix(".").rstrip()


def join_day_items(day: int, items: list[str]) -> str:
    clean_items = [strip_final_dot(compact_spaces(item)) for item in items if compact_spaces(item)]
    return f"{day} • {' • '.join(clean_items)}."


def append_day_sentence(existing: str, day: int, items: list[str], separator: str = "\n") -> str:
    new_items = [strip_final_dot(compact_spaces(item)) for item in items if compact_spaces(item)]
    if not new_items:
        return existing

    text = compact_spaces(existing)
    if not text:
        return join_day_items(day, new_items)

    if has_day_segment(text, str(day)):
        return f"{strip_final_dot(text)} • {' • '.join(new_items)}."

    return f"{strip_final_dot(text)}.{separator}{join_day_items(day, new_items)}"


def amount_to_formula_part(amount: float) -> str:
    if amount.is_integer():
        return str(int(amount))
    return str(amount).replace(",", ".")


def sanitize_money_description(value: str) -> str:
    """Strip accidental day markers from finance description text."""
    cleaned = MONEY_INLINE_DAY_MARKER_RE.sub(" ", compact_spaces(value))
    return compact_spaces(cleaned)


def parse_day_segments(text: str, *, money_layout: bool = False) -> dict[int, list[str]]:
    if money_layout:
        return parse_money_day_segments(text)

    base = compact_spaces(text).strip().removesuffix(".")
    if not base:
        return {}

    matches = list(DAY_SEGMENT_START_RE.finditer(base))
    if not matches:
        return {}

    segments: dict[int, list[str]] = {}
    for index, match in enumerate(matches):
        day = int(match.group(2))
        start = match.end()
        tail = base[start:]
        next_match = BIO_NEXT_DAY_RE.search(tail)
        chunk_end = start + next_match.start() if next_match else len(base)
        chunk = base[start:chunk_end]
        items = [
            strip_final_dot(item.strip())
            for item in chunk.split("•")
            if compact_spaces(item)
        ]
        if items:
            segments.setdefault(day, []).extend(items)
    return segments


def parse_money_day_segments(text: str) -> dict[int, list[str]]:
    base = compact_spaces(text).strip().removesuffix(".")
    if not base:
        return {}

    markers = list(MONEY_DAY_MARKER_RE.finditer(base))
    if not markers:
        return {}

    accepted: list[re.Match[str]] = []
    rejected = False
    for index, match in enumerate(markers):
        if index == 0:
            accepted.append(match)
            continue
        if _reject_money_day_boundary(base, match):
            rejected = True
            continue
        accepted.append(match)

    if rejected:
        first = markers[0]
        day = int(first.group(1))
        content = strip_final_dot(base[first.end() :].strip())
        return {day: [content]} if content else {}

    segments: dict[int, list[str]] = {}
    for index, match in enumerate(accepted):
        day = int(match.group(1))
        start = match.end()
        end = accepted[index + 1].start() if index + 1 < len(accepted) else len(base)
        chunk = base[start:end]
        items = [
            strip_final_dot(item.strip())
            for item in chunk.split("•")
            if compact_spaces(item)
        ]
        if items:
            segments.setdefault(day, []).extend(items)
    return segments


def _reject_money_day_boundary(base: str, match: re.Match[str]) -> bool:
    left = base[: match.start()].rstrip()
    right = base[match.end() :].lstrip()
    prev_item = _last_item_before_money_boundary(left)
    next_item = _first_item_after_money_marker(right)
    if not prev_item or not next_item:
        return False
    return prev_item.casefold() == next_item.casefold()


def _last_item_before_money_boundary(left: str) -> str:
    if "•" not in left:
        return ""
    parts = [strip_final_dot(part.strip()) for part in left.split("•")]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    if parts[0].strip().isdigit():
        parts = parts[1:]
    return parts[-1] if parts else ""


def _first_item_after_money_marker(right: str) -> str:
    head = strip_final_dot(right.split("•", 1)[0].strip())
    if not head:
        return ""
    return head.split()[0]


def merge_day_segments(
    existing: dict[int, list[str]],
    day: int,
    items: list[str],
) -> dict[int, list[str]]:
    merged = {key: list(value) for key, value in existing.items()}
    clean_items = [strip_final_dot(compact_spaces(item)) for item in items if compact_spaces(item)]
    if not clean_items:
        return merged
    bucket = merged.setdefault(day, [])
    seen = {item.casefold() for item in bucket}
    for item in clean_items:
        key = item.casefold()
        if key not in seen:
            bucket.append(item)
            seen.add(key)
    return merged


def format_money_description(segments: dict[int, list[str]]) -> str:
    if not segments:
        return ""
    parts: list[str] = []
    for day in sorted(segments):
        items = segments[day]
        parts.append(f"{day} • {' • '.join(items)}")
    return f"{' '.join(parts)}."


def normalize_money_description_text(text: str) -> str:
    """One line, days ascending, single trailing period (money «Описание»)."""
    base = compact_spaces(text.replace("\n", " ").replace("\r", " ")).strip().removesuffix(".")
    if not base:
        return ""
    segments = parse_money_day_segments(base)
    if segments:
        return format_money_description(segments)
    return f"{base}."


def format_bio_description(segments: dict[int, list[str]]) -> str:
    if not segments:
        return ""
    parts: list[str] = []
    for day in sorted(segments):
        items = segments[day]
        parts.append(f"{day} • {' • '.join(items)}.")
    return "\n".join(parts)


def normalize_bio_description_text(text: str) -> str:
    """Reorder bio day blocks ascending (21, 22, 23) regardless of input order."""
    base = text.replace("\r", "").strip()
    if not base:
        return ""
    segments = parse_day_segments(base, money_layout=False)
    if segments:
        return format_bio_description(segments)
    return base


def build_day_marker_runs(text: str) -> list[dict]:
    runs: list[dict] = []
    for match in DAY_SEGMENT_START_RE.finditer(text):
        day_start = match.start(2)
        day_end = match.end(2)
        runs.append({"startIndex": day_start, "format": {"bold": True}})
        runs.append({"startIndex": day_end, "format": {"bold": False}})
    return _merge_runs(runs)


def extend_day_format_runs(
    old_text: str,
    old_runs: list[dict],
    new_text: str,
) -> list[dict]:
    """Keep formatting of unchanged text; bold day digits only in newly added fragments."""
    old = old_text or ""
    new = new_text or ""
    if not new:
        return []
    if not old.strip():
        return build_day_marker_runs(new)

    sanitized = _sanitize_format_runs(old_runs, len(old))
    matcher = difflib.SequenceMatcher(None, old, new)
    runs: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            runs.extend(_shift_format_runs_slice(sanitized, i1, i2, j1))
        elif tag in {"insert", "replace"}:
            inserted = new[j1:j2]
            runs.extend(_offset_format_runs(build_day_marker_runs(inserted), j1))
    return _merge_runs(runs)


def _shift_format_runs_slice(
    old_runs: list[dict],
    start: int,
    end: int,
    new_start: int,
) -> list[dict]:
    shifted: list[dict] = []
    for run in old_runs:
        index = run.get("startIndex")
        if not isinstance(index, int) or index < start or index >= end:
            continue
        shifted.append(
            {
                "startIndex": index - start + new_start,
                "format": dict(run.get("format") or {}),
            }
        )
    return shifted


def _offset_format_runs(runs: list[dict], offset: int) -> list[dict]:
    return [
        {
            "startIndex": run["startIndex"] + offset,
            "format": dict(run.get("format") or {}),
        }
        for run in runs
        if isinstance(run.get("startIndex"), int)
    ]


def _sanitize_format_runs(runs: list[dict], text_length: int) -> list[dict]:
    sanitized: list[dict] = []
    for run in runs:
        start = run.get("startIndex")
        fmt = run.get("format")
        if isinstance(start, int) and start < text_length and isinstance(fmt, dict):
            sanitized.append({"startIndex": start, "format": dict(fmt)})
    return sanitized


def _merge_runs(runs: list[dict]) -> list[dict]:
    if not runs:
        return []
    ordered = sorted(runs, key=lambda run: run["startIndex"])
    merged: list[dict] = []
    for run in ordered:
        if merged and merged[-1]["startIndex"] == run["startIndex"]:
            fmt = dict(merged[-1].get("format") or {})
            fmt.update(run.get("format") or {})
            merged[-1] = {"startIndex": run["startIndex"], "format": fmt}
        else:
            merged.append(run)
    return merged


_ZERO_AMOUNT_DISPLAY_RE = re.compile(
    r"^(?:[рp][\s.]*0(?:[,.]0+)?|0(?:[,.]0+)?)(?:\s*₽)?$",
    re.IGNORECASE,
)


def _baseline_for_signed_amount(existing: str) -> str:
    """Пустая ячейка или «р.0,00» в колонке D — как ноль, не как текст для формулы."""
    current = compact_spaces(str(existing or "")).replace("\u00a0", " ").strip()
    if not current:
        return ""
    compact = current.replace(" ", "")
    if compact.startswith("="):
        return compact
    if _ZERO_AMOUNT_DISPLAY_RE.fullmatch(compact):
        return ""
    cleaned = re.sub(r"[^\d,.\-]", "", compact).replace(",", ".")
    if not cleaned:
        return ""
    try:
        if float(cleaned) == 0:
            return ""
    except ValueError:
        pass
    return compact


def append_signed_amount_formula(existing: str, delta: float) -> str:
    if delta == 0:
        return compact_spaces(str(existing or ""))
    part = amount_to_formula_part(abs(delta))
    signed = f"-{part}" if delta < 0 else f"+{part}"
    current = _baseline_for_signed_amount(existing)
    if not current:
        return f"=-{part}" if delta < 0 else f"={part}"
    if current.startswith("="):
        return f"{current}{signed}"
    cleaned = re.sub(r"[^\d,.\-]", "", current).replace(",", ".")
    if not cleaned:
        return f"=-{part}" if delta < 0 else f"={part}"
    return f"={cleaned}{signed}"


def normalize_account_name(value: str) -> str:
    normalized = value.strip().lower().replace("ё", "е")
    return "".join(ch for ch in normalized if ch.isalnum())


def append_amount_formula(existing: str, amount: float) -> str:
    part = amount_to_formula_part(amount)
    current = compact_spaces(str(existing or "")).replace(" ", "").replace("\u00a0", "")
    if not current:
        return f"={part}"
    if current.startswith("="):
        return f"{current}+{part}"

    cleaned = re.sub(r"[^\d,.\-]", "", current).replace(",", ".")
    if not cleaned:
        return f"={part}"
    return f"={cleaned}+{part}"
