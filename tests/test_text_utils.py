from vasilii_bot.utils.text import (
    append_amount_formula,
    append_day_sentence,
    format_money_description,
    has_day_segment,
    merge_day_segments,
    parse_day_segments,
    parse_spreadsheet_id,
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
    segments = {26: ["пироги"], 6: ["букет"], 16: ["пироги в ресторане"]}
    assert (
        format_money_description(segments)
        == "6 • букет 16 • пироги в ресторане 26 • пироги."
    )


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
