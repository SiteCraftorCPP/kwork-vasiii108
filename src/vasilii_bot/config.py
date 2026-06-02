from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["anthropic", "mashagpt", "bothub", "proxyapi", "openai", "custom"]
TranscriptionProvider = Literal["mashagpt", "bothub", "proxyapi", "openai", "custom"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr = Field(alias="BOT_TOKEN")

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514", alias="ANTHROPIC_MODEL")

    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    mashagpt_api_key: SecretStr | None = Field(default=None, alias="MASHAGPT_API_KEY")
    bothub_api_key: SecretStr | None = Field(default=None, alias="BOTHUB_API_KEY")
    proxyapi_api_key: SecretStr | None = Field(default=None, alias="PROXYAPI_API_KEY")

    llm_provider: LLMProvider = Field(default="mashagpt", alias="LLM_PROVIDER")
    llm_api_key: SecretStr | None = Field(default=None, alias="LLM_API_KEY")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_model: str = Field(default="anthropic/claude-sonnet-4-5", alias="LLM_MODEL")

    transcription_provider: TranscriptionProvider = Field(
        default="mashagpt",
        alias="TRANSCRIPTION_PROVIDER",
    )
    transcription_api_key: SecretStr | None = Field(default=None, alias="TRANSCRIPTION_API_KEY")
    transcription_base_url: str | None = Field(default=None, alias="TRANSCRIPTION_BASE_URL")
    transcription_model: str = Field(default="whisper-1", alias="TRANSCRIPTION_MODEL")

    # Backward-compatible alias from the first project draft.
    openai_transcription_model: str | None = Field(default=None, alias="OPENAI_TRANSCRIPTION_MODEL")

    google_service_account_file: Path = Field(alias="GOOGLE_SERVICE_ACCOUNT_FILE")
    bio_template_id: str | None = Field(default=None, alias="BIO_TEMPLATE_ID")
    money_template_id: str | None = Field(default=None, alias="MONEY_TEMPLATE_ID")
    default_bio_sheet_id: str | None = Field(default=None, alias="DEFAULT_BIO_SHEET_ID")
    default_money_sheet_id: str | None = Field(default=None, alias="DEFAULT_MONEY_SHEET_ID")
    database_path: Path = Field(default=Path("./data/bot.sqlite3"), alias="DATABASE_PATH")

    timezone: str = Field(default="Europe/Minsk", alias="TIMEZONE")
    max_voice_seconds: int = Field(default=120, alias="MAX_VOICE_SECONDS")
    report_hour: int = Field(default=9, alias="REPORT_HOUR")
    report_minute: int = Field(default=0, alias="REPORT_MINUTE")
    enable_weekly_reports: bool = Field(default=True, alias="ENABLE_WEEKLY_REPORTS")
    enable_monthly_reports: bool = Field(default=True, alias="ENABLE_MONTHLY_REPORTS")
    delete_webhook_on_start: bool = Field(default=True, alias="DELETE_WEBHOOK_ON_START")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("max_voice_seconds")
    @classmethod
    def validate_voice_limit(cls, value: int) -> int:
        if value < 10 or value > 600:
            raise ValueError("MAX_VOICE_SECONDS must be between 10 and 600")
        return value

    @field_validator("report_hour")
    @classmethod
    def validate_report_hour(cls, value: int) -> int:
        if value < 0 or value > 23:
            raise ValueError("REPORT_HOUR must be between 0 and 23")
        return value

    @field_validator("report_minute")
    @classmethod
    def validate_report_minute(cls, value: int) -> int:
        if value < 0 or value > 59:
            raise ValueError("REPORT_MINUTE must be between 0 and 59")
        return value


def load_settings() -> Settings:
    return Settings()
