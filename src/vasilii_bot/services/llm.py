import json
import logging
import re
from datetime import date
from typing import Any, Protocol

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from ..config import Settings
from .bio_facts import apply_life_facts_from_raw_text
from ..models import BioField, FinanceCategorySet, VoiceAnalysis
from ..utils.dates import MONTH_ALIASES
from .prompts import (
    load_prompt,
    render_report_prompt,
    report_system_prompt,
    voice_system_prompt,
)

logger = logging.getLogger(__name__)

OPENAI_COMPAT_BASE_URLS = {
    "mashagpt": "https://api.mashagpt.ru/v1",
    "bothub": "https://openai.bothub.chat/v1",
    "proxyapi": "https://openai.api.proxyapi.ru/v1",
    "openai": None,
}


class LLMError(RuntimeError):
    pass


class LLMService(Protocol):
    async def analyze_voice(
        self,
        transcript: str,
        categories: FinanceCategorySet,
        current_date: date,
    ) -> VoiceAnalysis:
        pass

    async def summarize(self, title: str, source_text: str, period: str = "weekly") -> str:
        pass


class AnthropicLLM:
    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for parsing and reports")
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
        self.model = settings.anthropic_model

    async def analyze_voice(
        self,
        transcript: str,
        categories: FinanceCategorySet,
        current_date: date,
    ) -> VoiceAnalysis:
        prompt = self._build_analysis_prompt(transcript, categories, current_date)
        content = await self._complete_voice(prompt, max_tokens=1800)
        payload = _extract_json(content)
        if not payload.get("entry_date"):
            payload["entry_date"] = current_date.isoformat()
        payload["raw_text"] = transcript
        payload = _prepare_voice_payload(payload, current_date=current_date)
        try:
            return _normalize_bio_fields(VoiceAnalysis.model_validate(payload))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bad LLM payload: %s", payload)
            raise LLMError(f"LLM returned invalid payload: {exc}") from exc

    async def summarize(self, title: str, source_text: str, period: str = "weekly") -> str:
        prompt = render_report_prompt(period, title, source_text)
        max_tokens = 900 if period == "daily" else 1200
        return await self._complete_report(prompt, max_tokens=max_tokens)

    async def _complete_voice(self, prompt: str, max_tokens: int) -> str:
        return await self._complete(prompt, max_tokens=max_tokens, system=voice_system_prompt())

    async def _complete_report(self, prompt: str, max_tokens: int) -> str:
        return await self._complete(prompt, max_tokens=max_tokens, system=report_system_prompt())

    async def _complete(self, prompt: str, max_tokens: int, *, system: str) -> str:
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"LLM request failed: {exc}") from exc

        parts: list[str] = []
        for block in message.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        output = "\n".join(parts).strip()
        if not output:
            raise LLMError("LLM returned empty response")
        return output

    @staticmethod
    def _build_analysis_prompt(
        transcript: str,
        categories: FinanceCategorySet,
        current_date: date,
    ) -> str:
        return f"""current_date: {current_date.isoformat()}

Доступные категории расходов:
{json.dumps(categories.expense, ensure_ascii=False)}

Доступные категории доходов:
{json.dumps(categories.income, ensure_ascii=False)}

Расшифровка голосового сообщения:
{transcript}
"""


class OpenAICompatibleLLM:
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if not api_key:
            raise LLMError("API key is required for OpenAI-compatible LLM provider")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**client_kwargs)
        self.model = model

    async def analyze_voice(
        self,
        transcript: str,
        categories: FinanceCategorySet,
        current_date: date,
    ) -> VoiceAnalysis:
        prompt = AnthropicLLM._build_analysis_prompt(transcript, categories, current_date)
        content = await self._complete_voice(prompt, max_tokens=1800)
        payload = _extract_json(content)
        if not payload.get("entry_date"):
            payload["entry_date"] = current_date.isoformat()
        payload["raw_text"] = transcript
        payload = _prepare_voice_payload(payload, current_date=current_date)
        try:
            return _normalize_bio_fields(VoiceAnalysis.model_validate(payload))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bad LLM payload: %s", payload)
            raise LLMError(f"LLM returned invalid payload: {exc}") from exc

    async def summarize(self, title: str, source_text: str, period: str = "weekly") -> str:
        prompt = render_report_prompt(period, title, source_text)
        max_tokens = 900 if period == "daily" else 1200
        return await self._complete_report(prompt, max_tokens=max_tokens)

    async def _complete_voice(self, prompt: str, max_tokens: int) -> str:
        return await self._complete(prompt, max_tokens=max_tokens, system=voice_system_prompt())

    async def _complete_report(self, prompt: str, max_tokens: int) -> str:
        return await self._complete(prompt, max_tokens=max_tokens, system=report_system_prompt())

    async def _complete(self, prompt: str, max_tokens: int, *, system: str) -> str:
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"OpenAI-compatible LLM request failed: {exc}") from exc

        message = completion.choices[0].message
        output = (message.content or "").strip()
        if not output:
            raise LLMError("LLM returned empty response")
        return output


def create_llm_service(settings: Settings, model: str | None = None) -> LLMService:
    from ..llm_models import normalize_model_id

    provider = settings.llm_provider
    resolved_model = normalize_model_id(model or settings.llm_model)
    if provider == "anthropic":
        return AnthropicLLM(settings)

    if provider == "custom":
        api_key = settings.llm_api_key
        base_url = settings.llm_base_url
    elif provider == "mashagpt":
        api_key = settings.llm_api_key or settings.mashagpt_api_key or settings.openai_api_key
        base_url = settings.llm_base_url or OPENAI_COMPAT_BASE_URLS["mashagpt"]
    elif provider == "bothub":
        api_key = settings.llm_api_key or settings.bothub_api_key or settings.openai_api_key
        base_url = settings.llm_base_url or OPENAI_COMPAT_BASE_URLS["bothub"]
    elif provider == "proxyapi":
        api_key = settings.llm_api_key or settings.proxyapi_api_key
        base_url = settings.llm_base_url or OPENAI_COMPAT_BASE_URLS["proxyapi"]
    elif provider == "openai":
        api_key = settings.llm_api_key or settings.openai_api_key
        base_url = settings.llm_base_url or settings.openai_base_url
    else:
        raise LLMError(f"Unsupported LLM provider: {provider}")

    if not api_key:
        raise LLMError(f"Missing API key for LLM provider: {provider}")

    return OpenAICompatibleLLM(
        api_key=api_key.get_secret_value(),
        model=resolved_model,
        base_url=base_url,
    )


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return json.loads(cleaned)

    fenced = re.search(r"```(?:json)?\s*(\{.*?})\s*```", cleaned, flags=re.S)
    if fenced:
        return json.loads(fenced.group(1))

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("LLM response does not contain JSON")
    return json.loads(cleaned[start : end + 1])


FINANCE_ENTRY_KEYS = {"direction", "amount", "category", "description"}


def _prepare_voice_payload(
    payload: dict[str, Any],
    current_date: date | None = None,
) -> dict[str, Any]:
    repaired = dict(payload)
    if repaired.get("date_precision") not in {"day", "month"}:
        repaired["date_precision"] = "day"
    _apply_date_precision(repaired, current_date)
    finance = _normalize_finance_entries(repaired.get("finance"))
    bio_payload = repaired.get("bio")
    if not isinstance(bio_payload, dict):
        bio_payload = {}

    clean_bio: dict[str, list[str]] = {}
    for field in BioField:
        raw_items = bio_payload.get(field.value) or []
        if isinstance(raw_items, str):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            raw_items = [raw_items]

        clean_items: list[str] = []
        for item in raw_items:
            if isinstance(item, str):
                value = item.strip()
                if value:
                    clean_items.append(value)
                continue

            if isinstance(item, dict):
                if _is_finance_entry_dict(item):
                    finance.append(_finance_entry_from_dict(item))
                bio_text = _bio_text_from_dict(item)
                if bio_text:
                    clean_items.append(bio_text)
                continue

            if item is not None:
                clean_items.append(str(item).strip())

        clean_bio[field.value] = _dedupe([item for item in clean_items if item])

    enriched_bio = _enrich_bio_money_items(clean_bio, finance)
    raw_text = str(repaired.get("raw_text") or "")
    enriched_bio, finance = apply_life_facts_from_raw_text(enriched_bio, finance, raw_text)
    repaired["bio"] = enriched_bio
    repaired["finance"] = finance
    repaired["transfers"] = _normalize_transfers(repaired.get("transfers"))
    return repaired


def _normalize_transfers(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    entries = value if isinstance(value, list) else [value]
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        amount = entry.get("amount")
        from_account = entry.get("from_account") or entry.get("from")
        to_account = entry.get("to_account") or entry.get("to")
        if not from_account or not to_account or not _amount_is_positive(amount):
            continue
        result.append(
            {
                "from_account": str(from_account).strip(),
                "to_account": str(to_account).strip(),
                "amount": float(amount),
            }
        )
    return result


def _apply_date_precision(payload: dict[str, Any], current_date: date | None) -> None:
    raw_text = str(payload.get("raw_text") or "")
    inferred = _infer_year_month_without_day(raw_text)
    if inferred is not None:
        year, month = inferred
        if current_date is None or year != current_date.year:
            payload["entry_date"] = date(year, month, 1).isoformat()
            payload["date_precision"] = "month"
            return

    if current_date is None:
        return

    parsed_entry_date = _parse_iso_date(payload.get("entry_date"))
    model_used_first_day_for_current_month = (
        parsed_entry_date is not None
        and parsed_entry_date.year == current_date.year
        and parsed_entry_date.month == current_date.month
        and parsed_entry_date.day == 1
        and not _has_explicit_day(raw_text)
        and not _has_relative_date(raw_text)
    )
    if payload.get("date_precision") == "month" or model_used_first_day_for_current_month:
        payload["entry_date"] = current_date.isoformat()
        payload["date_precision"] = "day"


def _infer_year_month_without_day(text: str) -> tuple[int, int] | None:
    normalized = text.casefold().replace("ё", "е")
    year_match = re.search(r"\b(19\d{2}|20\d{2})\s*(?:год[ауе]?|г\.?)?\b", normalized)
    if not year_match:
        return None

    year = int(year_match.group(1))
    month = _find_month_in_text(normalized)
    if month is None or _has_explicit_day_for_month(normalized, month):
        return None
    return year, month


def _find_month_in_text(text: str) -> int | None:
    for month, aliases in MONTH_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in aliases):
            return month
    return None


def _has_explicit_day_for_month(text: str, month: int) -> bool:
    aliases = "|".join(re.escape(alias) for alias in MONTH_ALIASES[month])
    return bool(re.search(rf"\b(?:[1-9]|[12]\d|3[01])\s+(?:{aliases})\b", text))


def _has_explicit_day(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    return any(_has_explicit_day_for_month(normalized, month) for month in MONTH_ALIASES)


def _has_relative_date(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    return bool(re.search(r"\b(вчера|позавчера|сегодня|завтра)\b", normalized))


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_finance_entries(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    entries = value if isinstance(value, list) else [value]
    result: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict) and _is_finance_entry_dict(entry):
            normalized = _finance_entry_from_dict(entry)
            if _amount_is_positive(normalized.get("amount")):
                result.append(normalized)
    return result


def _enrich_bio_money_items(
    bio: dict[str, list[str]],
    finance: list[dict[str, Any]],
) -> dict[str, list[str]]:
    enriched = {field: list(items) for field, items in bio.items()}
    for field in (BioField.earth_work.value, BioField.water_work.value):
        items = enriched.get(field, [])
        if not items:
            continue
        enriched[field] = [_enrich_bio_money_item(item, finance) for item in items]
    return enriched


def _enrich_bio_money_item(item: str, finance: list[dict[str, Any]]) -> str:
    if _contains_amount(item):
        return item
    item_key = item.casefold()
    for entry in finance:
        description = str(entry.get("description") or "").strip()
        if not description:
            continue
        description_key = description.casefold()
        if description_key in item_key or item_key in description_key:
            return f"{item} {_format_amount_for_bio(entry['amount'])}"
    return item


def _contains_amount(value: str) -> bool:
    return bool(re.search(r"\d|тыс|тысяч|руб|₽", value.casefold()))


def _format_amount_for_bio(value: Any) -> str:
    amount = float(value)
    if amount.is_integer():
        return f"{int(amount):,}".replace(",", " ") + " ₽"
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _is_finance_entry_dict(value: dict[str, Any]) -> bool:
    return FINANCE_ENTRY_KEYS.issubset(value)


def _finance_entry_from_dict(value: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "direction": value["direction"],
        "amount": value["amount"],
        "category": value["category"],
        "description": value["description"],
    }
    day = value.get("day")
    if isinstance(day, int) and 1 <= day <= 31:
        entry["day"] = day
    elif isinstance(day, str) and day.isdigit():
        parsed_day = int(day)
        if 1 <= parsed_day <= 31:
            entry["day"] = parsed_day
    return entry


def _amount_is_positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _bio_text_from_dict(value: dict[str, Any]) -> str:
    for key in ("text", "description", "value", "title", "name"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


POSITIVE_RELATION_RE = re.compile(
    r"\b("
    r"погулял|погуляла|гулял|гуляла|"
    r"поговорил|поговорила|разговаривал|разговаривала|"
    r"позвонил|позвонила|созвонился|созвонилась|"
    r"встретился|встретилась|пообщался|пообщалась|"
    r"помог|помогла|обнял|обняла|поддержал|поддержала"
    r")\b",
    re.IGNORECASE,
)
NEGATIVE_RELATION_RE = re.compile(
    r"\b("
    r"поругался|поругалась|ругался|ругалась|"
    r"поссорился|поссорилась|ссорился|ссорилась|"
    r"конфликт|обидел|обидела|обиделся|обиделась|"
    r"скандал|злость|претензи"
    r")",
    re.IGNORECASE,
)


def _normalize_bio_fields(analysis: VoiceAnalysis) -> VoiceAnalysis:
    bio = {field: list(items) for field, items in analysis.bio.items()}
    earth_relations = bio.get(BioField.earth_relations, [])
    water_relations = bio.get(BioField.water_relations, [])
    raw_has_negative = bool(NEGATIVE_RELATION_RE.search(analysis.raw_text))

    normalized_earth: list[str] = []
    for item in earth_relations:
        item_is_negative = bool(NEGATIVE_RELATION_RE.search(item))
        item_is_positive = bool(POSITIVE_RELATION_RE.search(item))
        if item_is_positive or (not item_is_negative and not raw_has_negative):
            water_relations.append(item)
        else:
            normalized_earth.append(item)

    normalized_water: list[str] = []
    for item in water_relations:
        if NEGATIVE_RELATION_RE.search(item):
            normalized_earth.append(item)
        else:
            normalized_water.append(item)

    bio[BioField.earth_relations] = normalized_earth
    bio[BioField.water_relations] = normalized_water
    cleaned_bio = {field: _dedupe(items) for field, items in bio.items() if items}
    return analysis.model_copy(update={"bio": cleaned_bio})


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.casefold()
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def normalize_bio_payload(payload: dict[str, Any]) -> dict[BioField, list[str]]:
    result: dict[BioField, list[str]] = {}
    for field in BioField:
        items = payload.get(field.value) or []
        if isinstance(items, str):
            items = [items]
        result[field] = [str(item) for item in items if str(item).strip()]
    return result
