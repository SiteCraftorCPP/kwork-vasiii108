import asyncio
import html
import logging
import re
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .config import Settings, load_settings
from .keyboards import (
    confirmation_keyboard,
    model_selection_keyboard,
    prompt_edit_keyboard,
    prompts_menu_keyboard,
    settings_menu_keyboard,
)
from .llm_models import label_for_model_id, model_id_for_choice
from .models import (
    BIO_FIELD_LABELS,
    FinanceCategorySet,
    FinanceDirection,
    PendingEntry,
    VoiceAnalysis,
)
from .services.llm import LLMError
from .services.llm_factory import LLMServiceFactory
from .services.manual_parse import parse_manual_correction
from .services.prompts import (
    PROMPT_CATALOG,
    edit_hint,
    load_prompt_by_key,
    preview_prompt,
    prompt_filename,
    prompt_label,
    save_prompt_by_key,
)
from .services.reports import send_user_report, setup_report_scheduler
from .services.sheets import GoogleSheetsService, SheetsError
from .services.transcriber import Transcriber, TranscriptionError, create_transcriber
from .storage import Storage
from .utils.dates import MONTH_NAMES_NOMINATIVE, today_in_timezone
from .utils.text import parse_spreadsheet_id

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def start_handler(message: Message, settings: Settings, app_storage: Storage) -> None:
    profile = await app_storage.ensure_user(message.chat.id)
    if settings.default_bio_sheet_id and not profile.bio_sheet_id:
        profile = await app_storage.set_bio_sheet(message.chat.id, settings.default_bio_sheet_id)
    if settings.default_money_sheet_id and not profile.money_sheet_id:
        await app_storage.set_money_sheet(message.chat.id, settings.default_money_sheet_id)

    await message.answer(
        "Бот готов принимать голосовые и текстовые записи.\n\n"
        "Подключение таблиц:\n"
        "/create_sheets your@gmail.com - создать личные копии шаблонов\n"
        "/link_bio ссылка-на-таблицу-биографии\n"
        "/link_money ссылка-на-таблицу-денег\n\n"
        "После голосового сообщения я покажу распределение и дождусь подтверждения.\n"
        "/report — ежедневный отчёт по таблицам.\n"
        "/model — модель Haiku / Sonnet 4.5.\n"
        "/prompts — редактировать промпты отчётов и разбора.",
        reply_markup=settings_menu_keyboard(),
    )


@router.message(Command("link_bio"))
async def link_bio_handler(
    message: Message,
    command: CommandObject,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
) -> None:
    await _link_sheet(message, command, app_storage, sheets_service, kind="bio")


@router.message(Command("link_money"))
async def link_money_handler(
    message: Message,
    command: CommandObject,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
) -> None:
    await _link_sheet(message, command, app_storage, sheets_service, kind="money")


@router.message(Command("status"))
async def status_handler(message: Message, app_storage: Storage) -> None:
    profile = await app_storage.ensure_user(message.chat.id)
    await message.answer(
        "Статус подключения:\n"
        f"Биография: {'подключена' if profile.bio_sheet_id else 'не подключена'}\n"
        f"Деньги: {'подключена' if profile.money_sheet_id else 'не подключена'}"
    )


@router.message(Command("create_sheets"))
async def create_sheets_handler(
    message: Message,
    command: CommandObject,
    settings: Settings,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
) -> None:
    if not settings.bio_template_id or not settings.money_template_id:
        await message.answer("В .env не заданы BIO_TEMPLATE_ID и MONEY_TEMPLATE_ID.")
        return

    google_email = (command.args or "").strip()
    if not _looks_like_email(google_email):
        await message.answer("Используйте: /create_sheets your-google-email@gmail.com")
        return

    await message.answer("Создаю личные копии шаблонов и выдаю доступ.")
    title_suffix = f"{message.chat.id}"
    try:
        bio_id, money_id = await sheets_service.create_student_copies(
            google_email=google_email,
            bio_template_id=settings.bio_template_id,
            money_template_id=settings.money_template_id,
            title_suffix=title_suffix,
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не смог создать копии: {html.escape(str(exc))}")
        return

    await app_storage.set_bio_sheet(message.chat.id, bio_id)
    await app_storage.set_money_sheet(message.chat.id, money_id)
    await message.answer(
        "Копии созданы и подключены.\n\n"
        f"Биография: https://docs.google.com/spreadsheets/d/{bio_id}/edit\n"
        f"Деньги: https://docs.google.com/spreadsheets/d/{money_id}/edit"
    )


@router.message(Command("prompts"))
async def prompts_handler(message: Message) -> None:
    await _answer_prompts_menu(message)


@router.callback_query(F.data == "settings_menu")
async def settings_menu_callback(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.answer()
    await callback.message.edit_text(
        "Настройки бота:",
        reply_markup=settings_menu_keyboard(),
    )


@router.callback_query(F.data == "prompts_menu")
async def prompts_menu_callback(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.answer()
    await _edit_prompts_menu(callback.message)


@router.callback_query(F.data == "model_menu")
async def model_menu_callback(
    callback: CallbackQuery,
    settings: Settings,
    app_storage: Storage,
) -> None:
    if not callback.message:
        return
    await callback.answer()
    profile = await app_storage.ensure_user(callback.message.chat.id)
    model_id = profile.llm_model or settings.llm_model
    await callback.message.edit_text(
        f"Модель для разбора записей: <b>{html.escape(label_for_model_id(model_id))}</b>",
        reply_markup=model_selection_keyboard(model_id),
    )


@router.callback_query(F.data.startswith("prompt_edit:"))
async def prompt_edit_callback(callback: CallbackQuery, app_storage: Storage) -> None:
    if not callback.data or not callback.message:
        return
    prompt_key = callback.data.split(":", 1)[1]
    if prompt_key not in PROMPT_CATALOG:
        await callback.answer("Неизвестный промпт.", show_alert=True)
        return

    await app_storage.set_prompt_edit_request(callback.message.chat.id, prompt_key)
    content = load_prompt_by_key(prompt_key)
    await callback.answer("Жду новый текст.")
    await callback.message.edit_text(
        f"<b>{html.escape(prompt_label(prompt_key))}</b>\n\n"
        f"{html.escape(edit_hint(prompt_key))}\n\n"
        f"<b>Сейчас:</b>\n<pre>{html.escape(preview_prompt(content))}</pre>",
        reply_markup=prompt_edit_keyboard(prompt_key),
    )


@router.callback_query(F.data.startswith("prompt_show:"))
async def prompt_show_callback(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        return
    prompt_key = callback.data.split(":", 1)[1]
    if prompt_key not in PROMPT_CATALOG:
        await callback.answer("Неизвестный промпт.", show_alert=True)
        return
    content = load_prompt_by_key(prompt_key)
    await callback.answer()
    if len(content) <= 3500:
        await callback.message.answer(
            f"<b>{html.escape(prompt_label(prompt_key))}</b>\n\n<pre>{html.escape(content)}</pre>"
        )
    else:
        await callback.message.answer_document(
            document=BufferedInputFile(
                content.encode("utf-8"),
                filename=prompt_filename(prompt_key),
            ),
            caption=prompt_label(prompt_key),
        )


@router.callback_query(F.data == "prompt_cancel")
async def prompt_cancel_callback(callback: CallbackQuery, app_storage: Storage) -> None:
    if not callback.message:
        return
    await app_storage.clear_prompt_edit_request(callback.message.chat.id)
    await callback.answer("Отменено.")
    await _edit_prompts_menu(callback.message)


@router.message(Command("model"))
async def model_handler(
    message: Message,
    settings: Settings,
    app_storage: Storage,
) -> None:
    profile = await app_storage.ensure_user(message.chat.id)
    model_id = profile.llm_model or settings.llm_model
    await message.answer(
        f"Модель для разбора записей: <b>{html.escape(label_for_model_id(model_id))}</b>",
        reply_markup=model_selection_keyboard(model_id),
    )


@router.callback_query(F.data.startswith("set_model:"))
async def set_model_callback(
    callback: CallbackQuery,
    settings: Settings,
    app_storage: Storage,
) -> None:
    if not callback.data or not callback.message:
        return
    choice = callback.data.split(":", 1)[1]
    if choice not in {"haiku", "sonnet"}:
        await callback.answer("Неизвестная модель.", show_alert=True)
        return
    model_id = model_id_for_choice(choice)  # type: ignore[arg-type]
    await app_storage.set_llm_model(callback.message.chat.id, model_id)
    await callback.answer(f"Модель: {label_for_model_id(model_id)}")
    await callback.message.edit_text(
        f"Модель для разбора записей: <b>{html.escape(label_for_model_id(model_id))}</b>",
        reply_markup=model_selection_keyboard(model_id),
    )


@router.message(Command("report"))
async def report_handler(
    message: Message,
    bot: Bot,
    settings: Settings,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
    llm_factory: LLMServiceFactory,
) -> None:
    profile = await app_storage.ensure_user(message.chat.id)
    if not profile.bio_sheet_id and not profile.money_sheet_id:
        await message.answer("Сначала подключите таблицы: /link_bio и /link_money.")
        return

    await message.answer("Готовлю ежедневный отчёт.")
    try:
        sent = await send_user_report(
            bot=bot,
            settings=settings,
            profile=profile,
            sheets_service=sheets_service,
            llm_factory=llm_factory,
            period="daily",
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось сформировать отчёт: {html.escape(str(exc))}")
        return

    if not sent:
        await message.answer("Нет данных для отчёта за сегодня.")


@router.message(Command("cancel"))
async def cancel_command_handler(message: Message, app_storage: Storage) -> None:
    pending_id = await app_storage.pop_edit_request(message.chat.id)
    if pending_id:
        await app_storage.delete_pending(pending_id)
    await app_storage.clear_prompt_edit_request(message.chat.id)
    await message.answer("Текущая операция отменена.")


@router.message(F.voice)
async def voice_handler(
    message: Message,
    bot: Bot,
    settings: Settings,
    app_storage: Storage,
    transcriber: Transcriber,
    llm_factory: LLMServiceFactory,
    sheets_service: GoogleSheetsService,
) -> None:
    if not message.voice:
        return
    if message.voice.duration and message.voice.duration > settings.max_voice_seconds:
        await message.answer(
            f"Голосовое длиннее {settings.max_voice_seconds} секунд. Запишите короче."
        )
        return

    await message.answer("Принял, распознаю и раскладываю по таблицам.")
    audio_path = await _download_voice(bot, message)
    try:
        transcript = await transcriber.transcribe(audio_path)
    except TranscriptionError as exc:
        await message.answer(f"Не удалось распознать голос: {html.escape(str(exc))}")
        return
    finally:
        audio_path.unlink(missing_ok=True)

    await _process_free_text(
        message=message,
        text=transcript,
        app_storage=app_storage,
        llm_factory=llm_factory,
        sheets_service=sheets_service,
        settings=settings,
    )


@router.message(F.text & ~F.text.startswith("/"))
async def text_handler(
    message: Message,
    settings: Settings,
    app_storage: Storage,
    llm_factory: LLMServiceFactory,
    sheets_service: GoogleSheetsService,
) -> None:
    if not message.text:
        return

    prompt_key = await app_storage.pop_prompt_edit_request(message.chat.id)
    if prompt_key:
        await _save_prompt_text(message, prompt_key, message.text or "")
        return

    edit_pending_id = await app_storage.pop_edit_request(message.chat.id)
    if edit_pending_id:
        await _process_manual_correction(
            message=message,
            text=message.text,
            app_storage=app_storage,
            settings=settings,
            pending_id=edit_pending_id,
        )
        return

    await _process_free_text(
        message=message,
        text=message.text,
        app_storage=app_storage,
        llm_factory=llm_factory,
        sheets_service=sheets_service,
        settings=settings,
    )


@router.callback_query(F.data.startswith("confirm:"))
@router.callback_query(F.data.startswith("confirm_money:"))
@router.callback_query(F.data.startswith("confirm_bio:"))
async def confirm_callback(
    callback: CallbackQuery,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
) -> None:
    if not callback.data or not callback.message:
        return
    action, pending_id = callback.data.split(":", 1)
    pending = await app_storage.get_pending(pending_id)
    if not pending or pending.chat_id != callback.message.chat.id:
        await callback.answer("Запись уже неактуальна.", show_alert=True)
        return

    analysis = _select_analysis_part(pending.analysis, action)
    if analysis.is_empty:
        await callback.answer("В этой записи нет выбранного типа данных.", show_alert=True)
        return

    profile = await app_storage.ensure_user(callback.message.chat.id)
    try:
        written = await sheets_service.append_analysis(profile, analysis)
    except SheetsError as exc:
        await callback.answer("Не записал в таблицу.", show_alert=True)
        await callback.message.answer(html.escape(str(exc)))
        return

    await app_storage.delete_pending(pending_id)
    await callback.answer("Записано.")
    await callback.message.edit_text(
        "Запись внесена: " + ", ".join(written),
        reply_markup=None,
    )


@router.callback_query(F.data.startswith("edit:"))
async def edit_callback(callback: CallbackQuery, app_storage: Storage) -> None:
    if not callback.data or not callback.message:
        return
    pending_id = callback.data.split(":", 1)[1]
    pending = await app_storage.get_pending(pending_id)
    if not pending or pending.chat_id != callback.message.chat.id:
        await callback.answer("Запись уже неактуальна.", show_alert=True)
        return

    await app_storage.set_edit_request(callback.message.chat.id, pending_id)
    await callback.answer("Жду исправление.")
    await callback.message.answer(
        "Отправьте исправленный текст в том же формате, что в подтверждении "
        "(дата, био, строки +сумма | категория | описание). "
        "Повторный разбор ИИ не делается."
    )


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_callback(callback: CallbackQuery, app_storage: Storage) -> None:
    if not callback.data or not callback.message:
        return
    pending_id = callback.data.split(":", 1)[1]
    await app_storage.delete_pending(pending_id)
    await callback.answer("Отменено.")
    await callback.message.edit_text("Запись отменена.", reply_markup=None)


async def _link_sheet(
    message: Message,
    command: CommandObject,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
    kind: str,
) -> None:
    if not command.args:
        await message.answer("Пришлите ссылку или ID таблицы после команды.")
        return
    spreadsheet_id = parse_spreadsheet_id(command.args)
    if not spreadsheet_id:
        await message.answer("Не понял ссылку на Google Sheets. Пришлите полную ссылку на таблицу.")
        return

    try:
        title = await sheets_service.verify_access(spreadsheet_id)
    except Exception as exc:  # noqa: BLE001
        await message.answer(
            "Не удалось открыть таблицу. Проверьте, что она расшарена на service account.\n"
            f"Ошибка: {html.escape(str(exc))}"
        )
        return

    if kind == "bio":
        await app_storage.set_bio_sheet(message.chat.id, spreadsheet_id)
        label = "биографии"
    else:
        await app_storage.set_money_sheet(message.chat.id, spreadsheet_id)
        label = "денег"
    await message.answer(f"Таблица {label} подключена: {html.escape(title)}")


async def _process_manual_correction(
    message: Message,
    text: str,
    app_storage: Storage,
    settings: Settings,
    pending_id: str,
) -> None:
    profile = await app_storage.ensure_user(message.chat.id)
    current_date = today_in_timezone(profile.timezone or settings.timezone)
    analysis = parse_manual_correction(text, current_date)
    if not analysis or analysis.is_empty:
        await message.answer(
            "Не разобрал исправление. Пришлите текст как в подтверждении:\n"
            "Дата: 01.06.2026\n"
            "Земля / Тело: событие\n"
            "-500 | Категория | описание"
        )
        return

    pending = PendingEntry(
        id=pending_id,
        chat_id=message.chat.id,
        analysis=analysis,
    )
    await app_storage.save_pending(pending)
    await message.answer(
        _format_confirmation(analysis),
        reply_markup=confirmation_keyboard(
            pending.id,
            has_bio=analysis.has_bio,
            has_finance=analysis.has_finance,
        ),
    )


async def _process_free_text(
    message: Message,
    text: str,
    app_storage: Storage,
    llm_factory: LLMServiceFactory,
    sheets_service: GoogleSheetsService,
    settings: Settings,
    pending_id: str | None = None,
) -> None:
    profile = await app_storage.ensure_user(message.chat.id)
    if not profile.bio_sheet_id and not profile.money_sheet_id:
        await message.answer(
            "Сначала подключите хотя бы одну таблицу:\n"
            "/link_bio ссылка\n"
            "/link_money ссылка"
        )
        return

    current_date = today_in_timezone(profile.timezone or settings.timezone)
    categories = FinanceCategorySet()
    if profile.money_sheet_id:
        try:
            categories = await sheets_service.get_money_categories(
                profile.money_sheet_id,
                current_date,
            )
        except SheetsError as exc:
            await message.answer(f"Не смог прочитать категории денег: {html.escape(str(exc))}")
            return

    try:
        analysis = await llm_factory.for_user(profile).analyze_voice(
            text,
            categories,
            current_date,
        )
    except LLMError as exc:
        await message.answer(f"Не удалось разобрать запись: {html.escape(str(exc))}")
        return

    if analysis.is_empty:
        await message.answer(
            "Не нашёл данных для записи. Переформулируйте или отправьте исправление."
        )
        return

    entry_id = pending_id or PendingEntry(chat_id=message.chat.id, analysis=analysis).id
    pending = PendingEntry(
        id=entry_id,
        chat_id=message.chat.id,
        analysis=analysis,
    )
    await app_storage.save_pending(pending)
    await message.answer(
        _format_confirmation(analysis),
        reply_markup=confirmation_keyboard(
            pending.id,
            has_bio=analysis.has_bio,
            has_finance=analysis.has_finance,
        ),
    )


async def _download_voice(bot: Bot, message: Message) -> Path:
    if not message.voice:
        raise TranscriptionError("No voice attachment")
    tmp_dir = Path("tmp/voice")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    audio_path = tmp_dir / f"{message.chat.id}_{message.message_id}.ogg"
    file = await bot.get_file(message.voice.file_id)
    await bot.download_file(file.file_path, destination=audio_path)
    return audio_path


def _format_confirmation(analysis: VoiceAnalysis) -> str:
    lines = [
        f"<b>Дата:</b> {html.escape(_format_analysis_date(analysis))}",
        "",
        "Проверьте распределение:",
    ]

    if analysis.has_bio:
        lines.append("")
        lines.append("<b>Биография</b>")
        for field, items in analysis.bio.items():
            if items:
                label = BIO_FIELD_LABELS[field]
                lines.append(f"{html.escape(label)}: {html.escape('; '.join(items))}")

    if analysis.finance or analysis.transfers:
        lines.append("")
        lines.append("<b>Финансы</b>")
        for entry in analysis.finance:
            sign = "+" if entry.direction == FinanceDirection.income else "-"
            lines.append(
                f"{sign}{entry.amount:g} | {html.escape(entry.category)} | "
                f"{html.escape(entry.description)}"
            )
        for transfer in analysis.transfers:
            lines.append(
                f"Перевод: {html.escape(transfer.from_account)} → "
                f"{html.escape(transfer.to_account)} | {transfer.amount:g}"
            )

    return "\n".join(lines)


def _select_analysis_part(analysis: VoiceAnalysis, action: str) -> VoiceAnalysis:
    if action == "confirm_money":
        return analysis.model_copy(update={"bio": {}})
    if action == "confirm_bio":
        return analysis.model_copy(update={"finance": [], "transfers": []})
    return analysis


def _format_analysis_date(analysis: VoiceAnalysis) -> str:
    if analysis.date_precision == "month":
        month = MONTH_NAMES_NOMINATIVE[analysis.entry_date.month].lower()
        return f"{month} {analysis.entry_date.year} (без дня)"
    return analysis.entry_date.strftime("%d.%m.%Y")


def _looks_like_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


async def _answer_prompts_menu(message: Message) -> None:
    await message.answer(
        "Выберите промпт для редактирования.\n"
        "После выбора отправьте новый текст одним сообщением.",
        reply_markup=prompts_menu_keyboard(),
    )


async def _edit_prompts_menu(message: Message) -> None:
    await message.edit_text(
        "Выберите промпт для редактирования.\n"
        "После выбора отправьте новый текст одним сообщением.",
        reply_markup=prompts_menu_keyboard(),
    )


async def _save_prompt_text(message: Message, prompt_key: str, text: str) -> None:
    clean = text.strip()
    if len(clean) < 20:
        await message.answer("Слишком короткий промпт. Пришлите полный текст.")
        return
    try:
        warnings = save_prompt_by_key(prompt_key, clean)
    except KeyError:
        await message.answer("Неизвестный промпт.")
        return

    note = f"Промпт «{prompt_label(prompt_key)}» сохранён."
    if warnings:
        note += "\nПредупреждение: " + ", ".join(warnings) + "."
    await message.answer(note, reply_markup=prompts_menu_keyboard())


async def _main(settings: Settings) -> None:
    app_storage = Storage(settings.database_path)
    await app_storage.init()

    sheets_service = GoogleSheetsService(settings)
    llm_factory = LLMServiceFactory(settings)
    transcriber = create_transcriber(settings)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    scheduler = setup_report_scheduler(
        bot=bot,
        settings=settings,
        app_storage=app_storage,
        sheets_service=sheets_service,
        llm_factory=llm_factory,
    )
    scheduler.start()

    if settings.delete_webhook_on_start:
        await bot.delete_webhook(drop_pending_updates=False)

    await dp.start_polling(
        bot,
        settings=settings,
        app_storage=app_storage,
        sheets_service=sheets_service,
        llm_factory=llm_factory,
        transcriber=transcriber,
    )


def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    asyncio.run(_main(settings))
