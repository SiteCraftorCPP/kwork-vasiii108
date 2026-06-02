"""Heuristics for biography life facts (birth, move, study) without money."""

from __future__ import annotations

import re
from typing import Any

from ..models import BioField
from ..utils.text import compact_spaces

LIFE_FACT_MARKER_RE = re.compile(
    r"\b("
    r"родил(?:ся|ась|ись)|"
    r"переехал|переехала|переехали|"
    r"учил(?:ся|ась)|учился\s+в|училась\s+в|"
    r"окончил(?:а)?|окончил(?:а)?\s+школ|"
    r"пошел\s+в\s+школ|пошла\s+в\s+школ|пошёл\s+в\s+школ|"
    r"вспомнил(?:а)?\s+детств|в\s+детстве|"
    r"узнал(?:а)?\s+новост|"
    r"сменил(?:а)?\s+работ|устроил(?:ся|ась)|уволил(?:ся|ась)|"
    r"родился\s+в|родилась\s+в|родились\s+в"
    r")\b",
    re.IGNORECASE,
)

WORK_LIFE_FACT_RE = re.compile(
    r"\b(учил(?:ся|ась)|сменил(?:а)?\s+работ|устроил(?:ся|ась)|уволил(?:ся|ась)|"
    r"пошел\s+в\s+школ|пошла\s+в\s+школ|пошёл\s+в\s+школ|окончил)\b",
    re.IGNORECASE,
)

AMOUNT_IN_TEXT_RE = re.compile(
    r"\d+\s*(?:руб|₽|тыс|тысяч)|(?:полтор|полтора|две|три|четыре|пять|"
    r"шесть|семь|восемь|девять|десять|двадцать|тридцать|сорок|пятьдесят)\s+тысяч|"
    r"(?:потратил|заплатил|купил|получил|заработал|доход|расход).{0,30}\d{1,5}",
    re.IGNORECASE,
)


def apply_life_facts_from_raw_text(
    bio: dict[str, list[str]],
    finance: list[dict[str, Any]],
    raw_text: str,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    text = compact_spaces(raw_text)
    if not text:
        return bio, finance

    clauses = _extract_life_fact_clauses(text)
    enriched = {field: list(items) for field, items in bio.items()}

    for clause in clauses:
        field = _bio_field_for_life_fact(clause)
        bucket = enriched.setdefault(field.value, [])
        _append_bio_phrase(bucket, clause)

    filtered_finance = [
        entry
        for entry in finance
        if not _finance_entry_is_life_fact(entry, text, clauses)
    ]

    return _relocate_misplaced_life_facts(enriched), filtered_finance


def _relocate_misplaced_life_facts(bio: dict[str, list[str]]) -> dict[str, list[str]]:
    updated = {field: list(items) for field, items in bio.items()}
    for field_name in list(updated):
        for item in list(updated[field_name]):
            if not _is_life_fact_clause(item):
                continue
            target = _bio_field_for_life_fact(item).value
            updated[field_name] = [value for value in updated[field_name] if value != item]
            bucket = updated.setdefault(target, [])
            _append_bio_phrase(bucket, item)
    return {field: items for field, items in updated.items() if items}


def _extract_life_fact_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    for part in re.split(r"(?<=[.!?;])\s+|[,]\s+(?=[А-ЯA-Z])|\s+и\s+", text, flags=re.IGNORECASE):
        chunk = compact_spaces(part)
        if chunk and _is_life_fact_clause(chunk):
            clauses.append(chunk)
    if not clauses and _is_life_fact_clause(text):
        clauses.append(text)
    return clauses


def _is_life_fact_clause(text: str) -> bool:
    if not LIFE_FACT_MARKER_RE.search(text):
        return False
    return not _clause_has_explicit_amount(text)


def _clause_has_explicit_amount(text: str) -> bool:
    return bool(AMOUNT_IN_TEXT_RE.search(text))


def _bio_field_for_life_fact(clause: str) -> BioField:
    if WORK_LIFE_FACT_RE.search(clause):
        return BioField.water_work
    return BioField.water_body


def _finance_entry_is_life_fact(
    entry: dict[str, Any],
    raw_text: str,
    clauses: list[str],
) -> bool:
    description = compact_spaces(str(entry.get("description") or ""))
    category = compact_spaces(str(entry.get("category") or ""))
    combined = f"{description} {category}".casefold()

    if LIFE_FACT_MARKER_RE.search(description) or LIFE_FACT_MARKER_RE.search(category):
        return True

    for clause in clauses:
        clause_key = clause.casefold()
        desc_key = description.casefold()
        if (
            desc_key in clause_key
            or category.casefold() in clause_key
            or clause_key in desc_key
        ) and not _clause_has_explicit_amount(clause):
            return True

    if not _amount_in_text_near_finance_phrase(raw_text, description):
        if description and LIFE_FACT_MARKER_RE.search(raw_text):
            desc_key = description.casefold()
            if any(
                marker in desc_key
                for marker in ("родил", "город", "переех", "учил", "детств", "новост")
            ):
                return True

    return False


def _amount_in_text_near_finance_phrase(raw_text: str, description: str) -> bool:
    if not description:
        return bool(AMOUNT_IN_TEXT_RE.search(raw_text))
    pattern = re.compile(re.escape(description), re.IGNORECASE)
    match = pattern.search(raw_text)
    if not match:
        return bool(AMOUNT_IN_TEXT_RE.search(raw_text))
    window = raw_text[max(0, match.start() - 40) : match.end() + 80]
    return bool(AMOUNT_IN_TEXT_RE.search(window))


def _append_bio_phrase(bucket: list[str], phrase: str) -> None:
    phrase_key = phrase.casefold()
    for index, item in enumerate(bucket):
        item_key = item.casefold()
        if phrase_key == item_key:
            return
        if phrase_key in item_key:
            return
        if item_key in phrase_key:
            bucket[index] = phrase
            return
    bucket.append(phrase)


def _contains_phrase(items: list[str], phrase: str) -> bool:
    key = phrase.casefold()
    return any(key in item.casefold() or item.casefold() in key for item in items)
