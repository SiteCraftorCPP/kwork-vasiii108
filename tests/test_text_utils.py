from vasilii_bot.models import FinanceEntry, FinanceDirection
from vasilii_bot.utils.text import (
    append_amount_formula,
    append_day_sentence,
    extend_day_format_runs,
    format_money_description,
    normalize_bio_description_text,
    normalize_money_description_text,
    has_day_segment,
    merge_day_segments,
    parse_day_segments,
    parse_money_day_segments,
    parse_spreadsheet_id,
    sanitize_money_description,
)


def test_parse_spreadsheet_id_from_url() -> None:
    value = "https://docs.google.com/spreadsheets/d/abcDEF_123-456/edit?gid=1"
    assert parse_spreadsheet_id(value) == "abcDEF_123-456"


def test_parse_spreadsheet_id_from_raw_id() -> None:
    assert parse_spreadsheet_id("1K5HhiIkvuLrUXEHPG1jBot6LjLZ5aExHchAwoAHzhO0")


def test_append_day_sentence_same_day() -> None:
    result = append_day_sentence("24 • роллы. 25 • ресторан.", 25, ["такси"])
    assert result == "24 • роллы. 25 • ресторан • такси."


def test_append_day_sentence_new_day() -> None:
    result = append_day_sentence("24 • роллы.", 25, ["ресторан", "такси"])
    assert result == "24 • роллы.\n25 • ресторан • такси."


def test_has_day_segment_ignores_inline_numbers() -> None:
    text = "1 • Дмитриев 20 • Дмитриев 27 • Нейт."
    assert has_day_segment(text, "1") is True
    assert has_day_segment(text, "20") is False


def test_format_money_description_sorted_single_line() -> None:
    segments = {
        26: ["пироги в ресторане"],
        6: ["букет"],
        16: ["пироги в ресторане"],
    }
    assert (
        format_money_description(segments)
        == "6 • букет 16 • пироги в ресторане 26 • пироги в ресторане."
    )


def test_normalize_money_description_merges_multiline_to_one_line() -> None:
    legacy = "6 • букет.\n16 • пироги в ресторане.\n26 • пироги в ресторане."
    assert (
        normalize_money_description_text(legacy)
        == "6 • букет 16 • пироги в ресторане 26 • пироги в ресторане."
    )


def test_normalize_money_description_ensures_trailing_dot() -> None:
    assert normalize_money_description_text("6 • букет") == "6 • букет."


def test_normalize_bio_description_sorts_chaotic_days() -> None:
    chaotic = "23 • третье.\n21 • первое.\n22 • второе."
    assert (
        normalize_bio_description_text(chaotic)
        == "21 • первое.\n22 • второе.\n23 • третье."
    )


def test_money_chaotic_days_sorted_on_format() -> None:
    chaotic = "26 • поздно 6 • рано 16 • середина."
    assert (
        normalize_money_description_text(chaotic)
        == "6 • рано 16 • середина 26 • поздно."
    )


def test_merge_multiple_chaotic_finance_days() -> None:
    segments = {}
    for day, label in ((23, "c"), (21, "a"), (22, "b")):
        segments = merge_day_segments(segments, day, [label])
    assert format_money_description(segments) == "21 • a 22 • b 23 • c."


def test_merge_day_segments_keeps_chronological_order_in_formatter() -> None:
    existing = parse_day_segments("26 • старое", money_layout=True)
    merged = merge_day_segments(existing, 6, ["букет"])
    merged = merge_day_segments(merged, 16, ["пироги в ресторане"])
    assert format_money_description(merged) == "6 • букет 16 • пироги в ресторане 26 • старое."


def test_append_amount_formula_empty_cell() -> None:
    assert append_amount_formula("", 500) == "=500"


def test_append_amount_formula_existing_formula() -> None:
    assert append_amount_formula("=1000+4000", 500) == "=1000+4000+500"


def test_append_amount_formula_existing_currency_value() -> None:
    assert append_amount_formula("1 000,00 ₽", 500) == "=1000.00+500"


def test_parse_money_corrupted_cell_keeps_full_text() -> None:
    text = "1 • Дмитриев 20 • Дмитриев 27 • Нейт • продажа КС-1 Ольге."
    segments = parse_money_day_segments(text)
    assert segments == {
        1: ["Дмитриев 20 • Дмитриев 27 • Нейт • продажа КС-1 Ольге"],
    }


def test_merge_corrupted_money_cell_adds_same_day() -> None:
    text = "1 • Дмитриев 20 • Дмитриев 27 • Нейт • продажа КС-1 Ольге."
    segments = parse_money_day_segments(text)
    merged = merge_day_segments(segments, 1, ["обед"])
    result = format_money_description(merged)
    assert result.startswith("1 • Дмитриев 20 • Дмитриев 27 • Нейт • продажа КС-1 Ольге • обед.")


def test_june_first_empty_money_description() -> None:
    result = format_money_description(merge_day_segments({}, 1, ["обед"]))
    assert result == "1 • обед."


def test_sanitize_money_description_strips_inline_day_markers() -> None:
    assert sanitize_money_description("Дмитриев 20 • Дмитриев") == "Дмитриев Дмитриев"


def test_extend_day_format_runs_does_not_bold_old_money_days() -> None:
    old = "16 • старое 26 • еще."
    new = "6 • новое 16 • старое 26 • еще."
    runs = extend_day_format_runs(old, [], new)
    bold_starts = [
        run["startIndex"]
        for run in runs
        if run.get("format", {}).get("bold") is True
    ]
    assert bold_starts == [new.index("6")]


def test_extend_day_format_runs_preserves_existing_runs() -> None:
    old = "24 • текст."
    old_runs = [
        {"startIndex": 0, "format": {"bold": True}},
        {"startIndex": 2, "format": {"bold": False}},
    ]
    new = "24 • текст.\n25 • новое."
    runs = extend_day_format_runs(old, old_runs, new)
    assert {"startIndex": 0, "format": {"bold": True}} in runs
    assert {"startIndex": 2, "format": {"bold": False}} in runs


def test_finance_entry_sanitizes_description() -> None:
    entry = FinanceEntry(
        direction=FinanceDirection.expense,
        amount=500,
        category="Еда",
        description="20 • роллы",
    )
    assert entry.description == "роллы"
