from typing import Literal

ModelChoice = Literal["haiku", "sonnet"]

MODEL_CHOICES: dict[ModelChoice, tuple[str, str]] = {
    "haiku": ("anthropic/claude-haiku-4-5", "Haiku 4.5"),
    "sonnet": ("anthropic/claude-sonnet-4-5", "Sonnet 4.5"),
}

# Старые slug 4.6 (ProxyAPI / .env) → актуальные 4.5 для кнопок и запросов.
LEGACY_MODEL_ALIASES: dict[str, str] = {
    "anthropic/claude-sonnet-4-6": MODEL_CHOICES["sonnet"][0],
    "anthropic/claude-haiku-4-6": MODEL_CHOICES["haiku"][0],
    "claude-sonnet-4-6": MODEL_CHOICES["sonnet"][0],
    "claude-haiku-4-6": MODEL_CHOICES["haiku"][0],
}

DEFAULT_MODEL_CHOICE: ModelChoice = "sonnet"

_LEGACY_BY_FOLD: dict[str, str] = {
    key.casefold(): value for key, value in LEGACY_MODEL_ALIASES.items()
}


def normalize_model_id(model_id: str) -> str:
    value = model_id.strip()
    if not value:
        return MODEL_CHOICES[DEFAULT_MODEL_CHOICE][0]
    if value in LEGACY_MODEL_ALIASES:
        return LEGACY_MODEL_ALIASES[value]
    folded = value.casefold()
    if folded in _LEGACY_BY_FOLD:
        return _LEGACY_BY_FOLD[folded]
    if "4-6" in folded or "4.6" in folded:
        if "haiku" in folded:
            return MODEL_CHOICES["haiku"][0]
        if "sonnet" in folded:
            return MODEL_CHOICES["sonnet"][0]
    return value


def model_id_for_choice(choice: ModelChoice) -> str:
    return MODEL_CHOICES[choice][0]


def label_for_model_id(model_id: str) -> str:
    """Человекочитаемое имя для сообщения бота (никогда slug с 4-6)."""
    resolved = normalize_model_id(model_id)
    for _choice, (mid, label) in MODEL_CHOICES.items():
        if mid == resolved:
            return label
    tail = resolved.rsplit("/", 1)[-1].casefold()
    if "haiku" in tail:
        return MODEL_CHOICES["haiku"][1]
    if "sonnet" in tail:
        return MODEL_CHOICES["sonnet"][1]
    return MODEL_CHOICES[DEFAULT_MODEL_CHOICE][1]


def choice_for_model_id(model_id: str) -> ModelChoice | None:
    resolved = normalize_model_id(model_id)
    for choice, (mid, _label) in MODEL_CHOICES.items():
        if mid == resolved:
            return choice
    return None
