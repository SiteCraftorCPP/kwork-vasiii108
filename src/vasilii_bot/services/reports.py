import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import Settings
from ..models import UserProfile
from .llm_factory import LLMServiceFactory
from ..services.sheets import GoogleSheetsService
from ..storage import Storage

logger = logging.getLogger(__name__)

REPORT_TITLES = {
    "daily": "Ежедневный отчёт",
    "weekly": "Еженедельный отчёт",
    "monthly": "Ежемесячный отчёт",
}


def setup_report_scheduler(
    bot: Bot,
    settings: Settings,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
    llm_factory: LLMServiceFactory,
) -> AsyncIOScheduler:
    timezone = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=timezone)

    if settings.enable_weekly_reports:
        scheduler.add_job(
            _send_reports,
            trigger="cron",
            day_of_week="mon",
            hour=settings.report_hour,
            minute=settings.report_minute,
            kwargs={
                "bot": bot,
                "settings": settings,
                "app_storage": app_storage,
                "sheets_service": sheets_service,
                "llm_factory": llm_factory,
                "period": "weekly",
            },
            id="weekly_reports",
            replace_existing=True,
        )

    if settings.enable_monthly_reports:
        scheduler.add_job(
            _send_reports,
            trigger="cron",
            day=1,
            hour=settings.report_hour,
            minute=settings.report_minute,
            kwargs={
                "bot": bot,
                "settings": settings,
                "app_storage": app_storage,
                "sheets_service": sheets_service,
                "llm_factory": llm_factory,
                "period": "monthly",
            },
            id="monthly_reports",
            replace_existing=True,
        )

    return scheduler


async def send_user_report(
    bot: Bot,
    settings: Settings,
    profile: UserProfile,
    sheets_service: GoogleSheetsService,
    llm_factory: LLMServiceFactory,
    period: str,
) -> bool:
    if not profile.bio_sheet_id and not profile.money_sheet_id:
        return False

    timezone = ZoneInfo(profile.timezone or settings.timezone)
    today = datetime.now(timezone).date()
    if period == "monthly":
        target_date = today - timedelta(days=1)
    else:
        target_date = today

    title = REPORT_TITLES.get(period, REPORT_TITLES["weekly"])
    source = await sheets_service.collect_report_source(profile, target_date)
    if not source.strip():
        return False

    summary = await llm_factory.for_user(profile).summarize(title, source, period=period)
    await bot.send_message(
        profile.chat_id,
        f"<b>{html.escape(title)}</b>\n\n{html.escape(summary)}",
    )
    return True


async def _send_reports(
    bot: Bot,
    settings: Settings,
    app_storage: Storage,
    sheets_service: GoogleSheetsService,
    llm_factory: LLMServiceFactory,
    period: str,
) -> None:
    users = await app_storage.list_users()
    for profile in users:
        try:
            await send_user_report(
                bot=bot,
                settings=settings,
                profile=profile,
                sheets_service=sheets_service,
                llm_factory=llm_factory,
                period=period,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send %s report to chat %s", period, profile.chat_id)
