from datetime import date

from vasilii_bot.models import FinanceDirection, VoiceAnalysis
from vasilii_bot.services.sheets import (
    GoogleSheetsService,
    _append_bio_rich_text,
    _bio_entry_marker,
    _has_day_segment,
    _pick_template_worksheet,
)
from vasilii_bot.utils.text import has_day_segment


class FakeWorksheet:
    title = "05.2026"

    def __init__(self, values: list[list[str]]):
        self._values = values

    def get_all_values(self) -> list[list[str]]:
        return self._values


def test_append_bio_rich_text_new_cell_bolds_day_only() -> None:
    text, runs = _append_bio_rich_text("", [], 24, ["поцарапал руку"])
    assert text == "24 • поцарапал руку."
    assert runs == [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 2, "format": {"bold": False}},
    ]


def test_append_bio_rich_text_same_day_keeps_existing_runs() -> None:
    existing_runs = [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 2, "format": {"bold": False}},
    ]
    text, runs = _append_bio_rich_text(
        "24 • поцарапал руку.",
        existing_runs,
        24,
        ["потерял 3 кг веса"],
    )
    assert text == "24 • поцарапал руку • потерял 3 кг веса."
    assert runs == existing_runs


def test_append_bio_rich_text_same_day_skips_duplicates() -> None:
    existing_runs = [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 2, "format": {"bold": False}},
    ]
    text, runs = _append_bio_rich_text(
        "27 • позвонил своему отцу • погулял с женой.",
        existing_runs,
        27,
        ["позвонил своему отцу", "погулял с женой"],
    )
    assert text == "27 • позвонил своему отцу • погулял с женой."
    assert runs == existing_runs


def test_append_bio_rich_text_same_day_appends_only_new_items() -> None:
    text, _ = _append_bio_rich_text(
        "27 • позвонил своему отцу.",
        [],
        27,
        ["позвонил своему отцу", "погулял с женой"],
    )
    assert text == "27 • позвонил своему отцу • погулял с женой."


def test_append_bio_rich_text_same_day_does_not_rebold_old_text() -> None:
    existing_runs = [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 2, "format": {"bold": False}},
        {"startIndex": 20, "format": {"bold": True}},
        {"startIndex": 22, "format": {"bold": False}},
    ]
    text, runs = _append_bio_rich_text(
        "27 • получение.",
        existing_runs,
        27,
        ["прибыль"],
    )
    assert text == "27 • получение • прибыль."
    assert runs == existing_runs


def test_day_segment_does_not_match_number_inside_same_day_line() -> None:
    text = "1 • Дмитриев 20 • Дмитриев 27 • Нейт • продажа."
    assert _has_day_segment(text, "1") is True
    assert _has_day_segment(text, "20") is False
    assert _has_day_segment(text, "27") is False
    assert has_day_segment(text, "20") is False


def test_append_bio_rich_text_new_day_uses_new_line_and_bolds_day() -> None:
    existing_runs = [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 2, "format": {"bold": False}},
    ]
    text, runs = _append_bio_rich_text(
        "24 • поцарапал руку.",
        existing_runs,
        25,
        ["погулял с женой"],
    )
    assert text == "24 • поцарапал руку.\n25 • погулял с женой."
    assert runs == [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 2, "format": {"bold": False}},
        {"startIndex": 21, "format": {"bold": True}},
        {"startIndex": 23, "format": {"bold": False}},
    ]


def test_append_rich_text_supports_month_marker() -> None:
    text, runs = _append_bio_rich_text("", [], "май", ["пошёл в школу"])
    assert text == "май • пошёл в школу."
    assert runs == [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 3, "format": {"bold": False}},
    ]


def test_bio_entry_marker_uses_month_when_precision_is_month() -> None:
    analysis = VoiceAnalysis(
        entry_date=date(1980, 5, 1),
        date_precision="month",
        bio={},
    )
    assert _bio_entry_marker(analysis) == "май"


def test_detect_money_layout_when_expenses_are_left() -> None:
    values = [
        [""] * 11,
        ["", "Расходы:", "", "", "", "", "", "Доходы:"],
        [""] * 11,
        ["", "Сумма", "Описание", "", "", "Категория", "", "Сумма", "Описание", "", "Категория"],
        ["", "500", "бумага", "", "", "Связи для обучения", "", "", "", "", "Источник 1"],
    ]
    layout = GoogleSheetsService._detect_money_layout(FakeWorksheet(values))
    expense = layout.tables[FinanceDirection.expense]
    income = layout.tables[FinanceDirection.income]

    assert expense.amount_col == 2
    assert expense.description_col == 3
    assert expense.category_col == 6
    assert income.amount_col == 8
    assert income.description_col == 9
    assert income.category_col == 11


def test_pick_template_worksheet_prefers_earliest_month_sheet() -> None:
    class StubWorksheet:
        def __init__(self, title: str, sheet_id: int):
            self.title = title
            self.id = sheet_id

    worksheets = [
        StubWorksheet("Итоги", 1),
        StubWorksheet("06.2026", 2),
        StubWorksheet("01.2026", 3),
    ]
    picked = _pick_template_worksheet(worksheets, "month")
    assert picked is not None
    assert picked.title == "01.2026"


def test_detect_money_layout_when_income_is_left() -> None:
    values = [
        [""] * 10,
        ["", "Доходы:", "", "", "", "", "Расходы:"],
        [""] * 10,
        ["", "Сумма", "Описание", "", "Категория", "", "Сумма", "Описание", "", "Категория"],
        ["", "5000", "продажа", "", "Источник 1", "", "500", "бумага", "", "Еда"],
    ]
    layout = GoogleSheetsService._detect_money_layout(FakeWorksheet(values))
    assert layout.tables[FinanceDirection.income].amount_col == 2
    assert layout.tables[FinanceDirection.expense].amount_col == 7
