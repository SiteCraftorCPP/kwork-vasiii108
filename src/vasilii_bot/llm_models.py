from typing import Literal

ModelChoice = Literal["haiku", "sonnet"]

MODEL_CHOICES: dict[ModelChoice, tuple[str, str]] = {
    "haiku": ("anthropic/claude-haiku-4-5", "Haiku 4.5"),
    "sonnet": ("anthropic/claude-sonnet-4-5", "Sonnet 4.5"),
}

DEFAULT_MODEL_CHOICE: ModelChoice = "sonnet"


def model_id_for_choice(choice: ModelChoice) -> str:
    return MODEL_CHOICES[choice][0]


def label_for_model_id(model_id: str) -> str:
    for _choice, (mid, label) in MODEL_CHOICES.items():
        if mid == model_id:
            return label
    return model_id.rsplit("/", 1)[-1]


def choice_for_model_id(model_id: str) -> ModelChoice | None:
    for choice, (mid, _label) in MODEL_CHOICES.items():
        if mid == model_id:
            return choice
    return None
