from vasilii_bot.keyboards import (
    confirmation_keyboard,
    prompts_hub_keyboard,
    report_prompts_menu_keyboard,
    settings_menu_keyboard,
)


def _button_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_keyboard_both_tables() -> None:
    texts = _button_texts(confirmation_keyboard("abc", has_bio=True, has_finance=True))
    assert "✅ В обе" in texts
    assert "Возраст тела" in texts
    assert "Возраст души" in texts
    assert "Только био" not in texts
    assert "Верно" not in texts


def test_keyboard_bio_only() -> None:
    texts = _button_texts(confirmation_keyboard("abc", has_bio=True, has_finance=False))
    assert texts.count("✅ Возраст тела") == 1
    assert "В обе" not in texts
    assert "Возраст души" not in texts


def test_keyboard_money_only() -> None:
    texts = _button_texts(confirmation_keyboard("abc", has_bio=False, has_finance=True))
    assert texts.count("✅ Возраст души") == 1
    assert "В обе" not in texts
    assert "Возраст тела" not in texts


def test_prompts_hub_separates_reports_and_voice() -> None:
    callbacks = [
        button.callback_data
        for row in prompts_hub_keyboard().inline_keyboard
        for button in row
    ]
    assert "report_prompts_menu" in callbacks
    assert "prompt_edit:voice_analysis" in callbacks


def test_report_prompts_menu_lists_report_keys() -> None:
    callbacks = [
        button.callback_data
        for row in report_prompts_menu_keyboard().inline_keyboard
        for button in row
    ]
    assert "prompt_edit:report_daily" in callbacks
    assert "prompt_edit:voice_analysis" not in callbacks


def test_settings_menu_has_daily_report_button() -> None:
    texts = _button_texts(settings_menu_keyboard())
    assert "📊 Ежедневный отчёт" in texts
    callbacks = [
        button.callback_data
        for row in settings_menu_keyboard().inline_keyboard
        for button in row
    ]
    assert "report_daily" in callbacks
