from datetime import date

from vasilii_bot.models import BioField, FinanceDirection
from vasilii_bot.services.manual_parse import parse_manual_correction


def test_parse_manual_correction_from_confirmation_format() -> None:
    text = """
    Дата: 21.06.2026
    Проверьте распределение:
    Земля / Тело: усталость
    Финансы
    -500 | Еда | обед
    +1000 | Источник 1 | продажа
    Всё верно?
    """
    analysis = parse_manual_correction(text, date(2026, 6, 1))
    assert analysis is not None
    assert analysis.entry_date == date(2026, 6, 21)
    assert analysis.bio[BioField.earth_body] == ["усталость"]
    assert len(analysis.finance) == 2
    assert analysis.finance[0].direction == FinanceDirection.expense
    assert analysis.finance[1].amount == 1000


def test_parse_manual_correction_with_day_in_description() -> None:
    text = "-300 | Еда | 16 • пироги в ресторане"
    analysis = parse_manual_correction(text, date(2026, 6, 1))
    assert analysis is not None
    assert analysis.finance[0].day == 16
    assert analysis.finance[0].description == "пироги в ресторане"
