import re
from datetime import date
from typing import Literal

from ..models import (
    BIO_FIELD_LABELS,
    AccountTransfer,
    BioField,
    FinanceDirection,
    FinanceEntry,
    VoiceAnalysis,
)
from ..utils.dates import MONTH_NAMES_NOMINATIVE
from ..utils.text import compact_spaces, strip_final_dot

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_FINANCE_LINE_RE = re.compile(
    r"^([+-])\s*([\d\s.,]+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$",
)
_TRANSFER_LINE_RE = re.compile(
    r"^перевод:\s*(.+?)\s*(?:→|->)\s*(.+?)\s*\|\s*([\d\s.,]+)\s*$",
    re.IGNORECASE,
)
_DATE_LINE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_DAY_PREFIX_RE = re.compile(r"^(\d{1,2})\s*•\s*(.+)$")
_SKIP_LINE_PREFIXES = (
    "проверьте распределение",
    "биография",
    "финансы",
    "всё верно",
    "все верно",
)


def parse_manual_correction(text: str, current_date: date) -> VoiceAnalysis | None:
    """Parse user correction text as-is (no LLM, no bio/finance heuristics)."""
    plain = _HTML_TAG_RE.sub("", text)
    plain = plain.replace("&nbsp;", " ")
    lines = [compact_spaces(line) for line in plain.splitlines()]
    lines = [line for line in lines if line and not _should_skip_line(line)]

    entry_date = current_date
    date_precision: Literal["day", "month"] = "day"
    bio: dict[BioField, list[str]] = {}
    finance: list[FinanceEntry] = []
    transfers: list[AccountTransfer] = []

    label_to_field = {label.casefold(): field for field, label in BIO_FIELD_LABELS.items()}

    for line in lines:
        lower = line.casefold()
        if lower.startswith("дата:"):
            date_part = line.split(":", 1)[1].strip()
            if "без дня" in date_part.casefold():
                date_precision = "month"
                for month_num, month_name in MONTH_NAMES_NOMINATIVE.items():
                    if month_name.casefold() in date_part.casefold():
                        entry_date = date(entry_date.year, month_num, 1)
                        break
            else:
                match = _DATE_LINE_RE.search(date_part)
                if match:
                    day, month, year = (int(match.group(i)) for i in range(1, 4))
                    entry_date = date(year, month, day)
            continue

        transfer_match = _TRANSFER_LINE_RE.match(line)
        if transfer_match:
            from_account, to_account, amount_raw = transfer_match.groups()
            amount = _parse_amount(amount_raw)
            if amount is not None:
                transfers.append(
                    AccountTransfer.model_construct(
                        from_account=from_account.strip(),
                        to_account=to_account.strip(),
                        amount=amount,
                    )
                )
            continue

        finance_match = _FINANCE_LINE_RE.match(line)
        if finance_match:
            sign, amount_raw, category, description = finance_match.groups()
            amount = _parse_amount(amount_raw)
            if amount is None:
                continue
            direction = (
                FinanceDirection.income if sign == "+" else FinanceDirection.expense
            )
            description = description.strip()
            day = _extract_day_from_description(description)
            finance.append(
                FinanceEntry.model_construct(
                    direction=direction,
                    amount=amount,
                    category=category.strip(),
                    description=_description_for_manual(description, day),
                    day=day,
                )
            )
            continue

        if ":" in line:
            label, value = line.split(":", 1)
            field = label_to_field.get(label.strip().casefold())
            if field and value.strip():
                items = [
                    strip_final_dot(item.strip())
                    for item in value.split(";")
                    if item.strip()
                ]
                if items:
                    bio[field] = items

    if not bio and not finance and not transfers:
        return None

    return VoiceAnalysis(
        entry_date=entry_date,
        date_precision=date_precision,
        parsed_manually=True,
        bio=bio,
        finance=finance,
        transfers=transfers,
        raw_text=text,
    )


def _should_skip_line(line: str) -> bool:
    lower = line.casefold()
    return any(lower.startswith(prefix) for prefix in _SKIP_LINE_PREFIXES)


def _description_for_manual(description: str, day: int | None) -> str:
    if day is None:
        return strip_final_dot(description)
    match = _DAY_PREFIX_RE.match(description.strip())
    if match:
        return strip_final_dot(match.group(2).strip())
    return strip_final_dot(description)


def _parse_amount(raw: str) -> float | None:
    cleaned = raw.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def _extract_day_from_description(description: str) -> int | None:
    match = _DAY_PREFIX_RE.match(description.strip())
    if not match:
        return None
    day = int(match.group(1))
    if 1 <= day <= 31:
        return day
    return None
