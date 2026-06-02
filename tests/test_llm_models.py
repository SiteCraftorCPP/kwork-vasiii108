from vasilii_bot.config import Settings
from vasilii_bot.keyboards import model_selection_keyboard
from vasilii_bot.llm_models import (
    MODEL_CHOICES,
    choice_for_model_id,
    label_for_model_id,
    model_id_for_choice,
    normalize_model_id,
)


def test_model_choices_are_haiku_and_sonnet_45_only() -> None:
    labels = [label for _id, label in MODEL_CHOICES.values()]
    ids = [mid for mid, _label in MODEL_CHOICES.values()]
    assert labels == ["Haiku 4.5", "Sonnet 4.5"]
    assert all("4-5" in mid for mid in ids)
    assert all("4-6" not in mid for mid in ids)


def test_normalize_model_id_maps_legacy_46_to_45() -> None:
    assert normalize_model_id("anthropic/claude-sonnet-4-6") == model_id_for_choice("sonnet")
    assert normalize_model_id("anthropic/claude-haiku-4-6") == model_id_for_choice("haiku")


def test_label_and_choice_for_legacy_sonnet_46() -> None:
    legacy = "anthropic/claude-sonnet-4-6"
    assert label_for_model_id(legacy) == "Sonnet 4.5"
    assert choice_for_model_id(legacy) == "sonnet"


def test_label_for_bare_slug_sonnet_46() -> None:
    """Как в Telegram до миграции: claude-sonnet-4-6 без префикса."""
    assert label_for_model_id("claude-sonnet-4-6") == "Sonnet 4.5"
    assert "4-6" not in label_for_model_id("claude-sonnet-4-6")
    assert "4.6" not in label_for_model_id("claude-sonnet-4-6")


def test_model_selection_keyboard_shows_45_labels() -> None:
    kb = model_selection_keyboard("anthropic/claude-sonnet-4-6")
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "✓ Sonnet 4.5" in texts
    assert "Haiku 4.5" in texts
    assert not any("4.6" in t or "4-6" in t for t in texts)


def test_settings_normalize_llm_model_from_env(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")
    settings = Settings()
    assert settings.llm_model == model_id_for_choice("sonnet")
