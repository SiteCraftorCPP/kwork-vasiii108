import re

SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)|^([a-zA-Z0-9-_]{20,})$")
DAY_SEGMENT_BOUNDARY = r"(^|\n|\. )"
DAY_SEGMENT_START_RE = re.compile(rf"{DAY_SEGMENT_BOUNDARY}(\d{{1,2}})\s*•", re.IGNORECASE)
MONEY_NEXT_DAY_RE = re.compile(r" \d{1,2}\s*•")
BIO_NEXT_DAY_RE = re.compile(r"(?:\n|\. )\d{1,2}\s*•")
MONTH_SHEET_TITLE_RE = re.compile(r"^\d{2}\.\d{4}$")
YEAR_SHEET_TITLE_RE = re.compile(r"^\d{4}$")


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


def parse_day_segments(text: str, *, money_layout: bool = False) -> dict[int, list[str]]:
    base = compact_spaces(text).strip().removesuffix(".")
    if not base:
        return {}

    matches = list(DAY_SEGMENT_START_RE.finditer(base))
    if not matches:
        return {}

    next_day_re = MONEY_NEXT_DAY_RE if money_layout else BIO_NEXT_DAY_RE
    segments: dict[int, list[str]] = {}
    for index, match in enumerate(matches):
        day = int(match.group(2))
        start = match.end()
        tail = base[start:]
        next_match = next_day_re.search(tail)
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


def format_bio_description(segments: dict[int, list[str]]) -> str:
    if not segments:
        return ""
    parts: list[str] = []
    for day in sorted(segments):
        items = segments[day]
        parts.append(f"{day} • {' • '.join(items)}.")
    return "\n".join(parts)


def build_day_marker_runs(text: str) -> list[dict]:
    runs: list[dict] = []
    for match in DAY_SEGMENT_START_RE.finditer(text):
        day_start = match.start(2)
        day_end = match.end(2)
        runs.append({"startIndex": day_start, "format": {"bold": True}})
        runs.append({"startIndex": day_end, "format": {"bold": False}})
    return _merge_runs(runs)


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


def append_signed_amount_formula(existing: str, delta: float) -> str:
    if delta == 0:
        return compact_spaces(str(existing or ""))
    part = amount_to_formula_part(abs(delta))
    signed = f"-{part}" if delta < 0 else f"+{part}"
    current = compact_spaces(str(existing or "")).replace(" ", "").replace("\u00a0", "")
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
