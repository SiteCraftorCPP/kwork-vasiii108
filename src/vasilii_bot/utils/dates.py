from datetime import date, datetime
from zoneinfo import ZoneInfo

MONTH_NAMES_NOMINATIVE = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

MONTH_ALIASES = {
    1: {"январь", "января"},
    2: {"февраль", "февраля"},
    3: {"март", "марта"},
    4: {"апрель", "апреля"},
    5: {"май", "мая"},
    6: {"июнь", "июня"},
    7: {"июль", "июля"},
    8: {"август", "августа"},
    9: {"сентябрь", "сентября"},
    10: {"октябрь", "октября"},
    11: {"ноябрь", "ноября"},
    12: {"декабрь", "декабря"},
}


def today_in_timezone(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def month_sheet_name(value: date) -> str:
    return f"{value.month:02d}.{value.year}"


def year_sheet_name(value: date) -> str:
    return str(value.year)


def normalize_month_text(value: str) -> str:
    return value.strip().lower().replace("ё", "е")


def month_matches(value: str, month: int) -> bool:
    return normalize_month_text(value) in MONTH_ALIASES[month]
