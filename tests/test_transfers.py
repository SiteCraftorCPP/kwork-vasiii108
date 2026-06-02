from vasilii_bot.services.sheets import GoogleSheetsService
from vasilii_bot.utils.text import append_signed_amount_formula, normalize_account_name


def test_normalize_account_name() -> None:
    assert normalize_account_name("Банк 1") == "банк1"
    assert normalize_account_name("  Банк 2 ") == "банк2"


def test_append_signed_amount_formula_outgoing() -> None:
    assert append_signed_amount_formula("", -20000) == "=-20000"
    assert append_signed_amount_formula("=1000", -20000) == "=1000-20000"


def test_append_signed_amount_formula_incoming() -> None:
    assert append_signed_amount_formula("", 20000) == "=20000"
    assert append_signed_amount_formula("=1000", 20000) == "=1000+20000"


def test_find_account_row_matches_bank_labels() -> None:
    values = [[""] * 5 for _ in range(30)]
    values[20] = ["", "Банк 1", "0,00 ₽", "p.0,00", ""]
    values[21] = ["", "Банк 2", "0,00 ₽", "p.0,00", ""]
    row = GoogleSheetsService._find_account_row(values, "банк 2")
    assert row == 22
