from datetime import date

from vasilii_bot.bot import _format_confirmation
from vasilii_bot.keyboards import confirmation_keyboard
from vasilii_bot.models import BioField, FinanceDirection, FinanceEntry, VoiceAnalysis


def _button_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_confirmation_text_has_no_vse_verno() -> None:
    analysis = VoiceAnalysis(
        entry_date=date(2026, 6, 1),
        bio={BioField.water_work: ["ездили в Строитель"]},
    )
    text = _format_confirmation(analysis).casefold()
    assert "всё верно" not in text
    assert "все верно" not in text
    assert "проверьте распределение" in text


def test_confirmation_buttons_match_task() -> None:
    bio_only = _button_texts(
        confirmation_keyboard("x", has_bio=True, has_finance=False),
    )
    assert bio_only == ["✅ Возраст тела", "✖️ Исправить", "Отменить"]

    money_only = _button_texts(
        confirmation_keyboard("x", has_bio=False, has_finance=True),
    )
    assert money_only == ["✅ Возраст души", "✖️ Исправить", "Отменить"]

    both = _button_texts(
        confirmation_keyboard("x", has_bio=True, has_finance=True),
    )
    assert "✅ В обе" in both
    assert "Возраст тела" in both
    assert "Возраст души" in both
    assert "Верно" not in both
    assert "только био" not in " ".join(both).casefold()
    assert "только деньги" not in " ".join(both).casefold()
