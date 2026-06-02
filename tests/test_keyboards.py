from vasilii_bot.keyboards import confirmation_keyboard


def _button_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_keyboard_both_tables() -> None:
    texts = _button_texts(confirmation_keyboard("abc", has_bio=True, has_finance=True))
    assert "✅ В обе" in texts
    assert "Возрастела" in texts
    assert "Возраст души" in texts
    assert "Только био" not in texts
    assert "Верно" not in texts


def test_keyboard_bio_only() -> None:
    texts = _button_texts(confirmation_keyboard("abc", has_bio=True, has_finance=False))
    assert texts.count("✅ Возрастела") == 1
    assert "В обе" not in texts
    assert "Возраст души" not in texts


def test_keyboard_money_only() -> None:
    texts = _button_texts(confirmation_keyboard("abc", has_bio=False, has_finance=True))
    assert texts.count("✅ Возраст души") == 1
    assert "В обе" not in texts
    assert "Возрастела" not in texts
