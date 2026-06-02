from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class FinanceDirection(StrEnum):
    income = "income"
    expense = "expense"


class BioField(StrEnum):
    earth_body = "earth_body"
    earth_relations = "earth_relations"
    earth_work = "earth_work"
    water_body = "water_body"
    water_relations = "water_relations"
    water_work = "water_work"


BIO_FIELD_LABELS: dict[BioField, str] = {
    BioField.earth_body: "Земля / Тело",
    BioField.earth_relations: "Земля / Отношения",
    BioField.earth_work: "Земля / Дело",
    BioField.water_body: "Вода / Тело",
    BioField.water_relations: "Вода / Отношения",
    BioField.water_work: "Вода / Дело",
}

ACCOUNT_TRANSFER_AMOUNT_COL = 4

BIO_FIELD_COLUMNS: dict[BioField, int] = {
    BioField.earth_body: 2,
    BioField.earth_relations: 3,
    BioField.earth_work: 4,
    BioField.water_body: 5,
    BioField.water_relations: 6,
    BioField.water_work: 7,
}


class FinanceCategorySet(BaseModel):
    income: list[str] = Field(default_factory=list)
    expense: list[str] = Field(default_factory=list)


class AccountTransfer(BaseModel):
    from_account: str = Field(min_length=1)
    to_account: str = Field(min_length=1)
    amount: float = Field(gt=0)

    @field_validator("from_account", "to_account")
    @classmethod
    def strip_account(cls, value: str) -> str:
        return compact_account_name(value)


def compact_account_name(value: str) -> str:
    return value.strip(" .\n\t")


class FinanceEntry(BaseModel):
    direction: FinanceDirection
    amount: float = Field(gt=0)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    day: int | None = Field(default=None, ge=1, le=31)

    @field_validator("description", "category")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip(" .\n\t")


class VoiceAnalysis(BaseModel):
    entry_date: date
    date_precision: Literal["day", "month"] = "day"
    bio: dict[BioField, list[str]] = Field(default_factory=dict)
    finance: list[FinanceEntry] = Field(default_factory=list)
    transfers: list[AccountTransfer] = Field(default_factory=list)
    raw_text: str = ""

    @field_validator("bio")
    @classmethod
    def strip_bio_items(cls, value: dict[BioField, list[str]]) -> dict[BioField, list[str]]:
        cleaned: dict[BioField, list[str]] = {}
        for field, items in value.items():
            normalized = [item.strip(" .\n\t") for item in items if item and item.strip(" .\n\t")]
            if normalized:
                cleaned[field] = normalized
        return cleaned

    @property
    def has_bio(self) -> bool:
        return any(self.bio.values())

    @property
    def has_finance(self) -> bool:
        return bool(self.finance) or bool(self.transfers)

    @property
    def is_empty(self) -> bool:
        return not self.has_bio and not self.has_finance


class PendingEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    chat_id: int
    analysis: VoiceAnalysis
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class UserProfile(BaseModel):
    chat_id: int
    bio_sheet_id: str | None = None
    money_sheet_id: str | None = None
    timezone: str = "Europe/Minsk"
    llm_model: str | None = None
