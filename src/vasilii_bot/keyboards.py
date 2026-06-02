from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .llm_models import MODEL_CHOICES, choice_for_model_id, model_id_for_choice
from .services.prompts import REPORT_PROMPT_CATALOG


def confirmation_keyboard(
    pending_id: str,
    has_bio: bool = True,
    has_finance: bool = True,
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []

    if has_bio and has_finance:
        keyboard.append(
            [InlineKeyboardButton(text="✅ В обе", callback_data=f"confirm:{pending_id}")]
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="Возраст тела",
                    callback_data=f"confirm_bio:{pending_id}",
                ),
                InlineKeyboardButton(
                    text="Возраст души",
                    callback_data=f"confirm_money:{pending_id}",
                ),
            ]
        )
    elif has_bio:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="✅ Возраст тела",
                    callback_data=f"confirm_bio:{pending_id}",
                )
            ]
        )
    elif has_finance:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="✅ Возраст души",
                    callback_data=f"confirm_money:{pending_id}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(text="✖️ Исправить", callback_data=f"edit:{pending_id}"),
            InlineKeyboardButton(text="Отменить", callback_data=f"cancel:{pending_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def model_selection_keyboard(current_model_id: str) -> InlineKeyboardMarkup:
    current_choice = choice_for_model_id(current_model_id)
    buttons: list[InlineKeyboardButton] = []
    for choice, (_model_id, label) in MODEL_CHOICES.items():
        prefix = "✓ " if choice == current_choice else ""
        buttons.append(
            InlineKeyboardButton(
                text=f"{prefix}{label}",
                callback_data=f"set_model:{choice}",
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Ежедневный отчёт",
                    callback_data="report_daily",
                ),
            ],
            [
                InlineKeyboardButton(text="📝 Промпты", callback_data="prompts_menu"),
                InlineKeyboardButton(text="🤖 Модель", callback_data="model_menu"),
            ],
        ]
    )


def prompts_hub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Промпты отчётов",
                    callback_data="report_prompts_menu",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎙 Промпт разбора голоса",
                    callback_data="prompt_edit:voice_analysis",
                ),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_menu")],
        ]
    )


def report_prompts_menu_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, (_filename, label) in REPORT_PROMPT_CATALOG.items():
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"prompt_edit:{key}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="prompts_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prompts_menu_keyboard() -> InlineKeyboardMarkup:
    """Alias for the prompts hub (reports vs voice)."""
    return prompts_hub_keyboard()


def prompt_edit_keyboard(prompt_key: str) -> InlineKeyboardMarkup:
    back_target = (
        "report_prompts_menu"
        if prompt_key in REPORT_PROMPT_CATALOG
        else "prompts_menu"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 Показать полностью",
                    callback_data=f"prompt_show:{prompt_key}",
                ),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=back_target),
                InlineKeyboardButton(text="✖️ Отмена", callback_data="prompt_cancel"),
            ],
        ]
    )
