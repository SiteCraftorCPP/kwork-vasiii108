from datetime import date

from vasilii_bot.models import BioField, VoiceAnalysis
from vasilii_bot.services.llm import _normalize_bio_fields, _prepare_voice_payload


def test_normalize_bio_fields_moves_positive_relations_to_water() -> None:
    analysis = VoiceAnalysis(
        entry_date=date(2026, 5, 27),
        raw_text="погулял с женой позвонил отцу",
        bio={
            BioField.earth_relations: ["погулял с женой", "позвонил отцу"],
        },
    )

    result = _normalize_bio_fields(analysis)

    assert BioField.earth_relations not in result.bio
    assert result.bio[BioField.water_relations] == ["погулял с женой", "позвонил отцу"]


def test_normalize_bio_fields_keeps_negative_relations_in_earth() -> None:
    analysis = VoiceAnalysis(
        entry_date=date(2026, 5, 27),
        raw_text="поругался с женой",
        bio={
            BioField.earth_relations: ["поругался с женой"],
        },
    )

    result = _normalize_bio_fields(analysis)

    assert result.bio[BioField.earth_relations] == ["поругался с женой"]
    assert BioField.water_relations not in result.bio


def test_prepare_voice_payload_repairs_finance_object_inside_bio() -> None:
    payload = {
        "entry_date": "2026-05-27",
        "bio": {
            "earth_body": ["поцарапал ногу"],
            "water_work": [
                {
                    "direction": "income",
                    "amount": 50000,
                    "category": "Другое",
                    "description": "заработал",
                }
            ],
        },
        "finance": [],
        "raw_text": "Заработал 50 тысяч и поцарапал ногу.",
    }

    result = _prepare_voice_payload(payload)

    assert result["bio"]["water_work"] == ["заработал 50 000 ₽"]
    assert result["finance"] == [
        {
            "direction": "income",
            "amount": 50000,
            "category": "Другое",
            "description": "заработал",
        }
    ]
    VoiceAnalysis.model_validate(result)


def test_prepare_voice_payload_drops_zero_amount_finance_entries() -> None:
    payload = {
        "entry_date": "2026-05-27",
        "bio": {
            "water_relations": ["позвонил отцу", "позвонил отцу"],
        },
        "finance": [
            {
                "direction": "income",
                "amount": 50000,
                "category": "Источник 1",
                "description": "заработал",
            },
            {
                "direction": "expense",
                "amount": 0,
                "category": "Другое",
                "description": "позвонил отцу",
            },
        ],
        "raw_text": "заработал 50 тысяч источник 1 потом позвонил отцу",
    }

    result = _prepare_voice_payload(payload)

    assert result["bio"]["water_relations"] == ["позвонил отцу"]
    assert result["finance"] == [
        {
            "direction": "income",
            "amount": 50000,
            "category": "Источник 1",
            "description": "заработал",
        }
    ]
    VoiceAnalysis.model_validate(result)


def test_prepare_voice_payload_defaults_date_precision_to_day() -> None:
    payload = {
        "entry_date": "2026-05-27",
        "bio": {"water_work": ["заработал"]},
        "finance": [],
    }

    result = _prepare_voice_payload(payload)

    assert result["date_precision"] == "day"
    VoiceAnalysis.model_validate(result)


def test_prepare_voice_payload_infers_month_precision_from_text() -> None:
    payload = {
        "entry_date": "2026-05-27",
        "bio": {"water_work": ["пошёл в школу"]},
        "finance": [],
        "raw_text": "1980 год, май, пошёл в школу.",
    }

    result = _prepare_voice_payload(payload)

    assert result["entry_date"] == "1980-05-01"
    assert result["date_precision"] == "month"
    VoiceAnalysis.model_validate(result)


def test_prepare_voice_payload_keeps_month_precision_for_historical_year() -> None:
    payload = {
        "entry_date": "2026-05-27",
        "date_precision": "day",
        "bio": {"water_work": ["пошёл в школу"]},
        "finance": [],
        "raw_text": "1980 год, май, пошёл в школу.",
    }

    result = _prepare_voice_payload(payload, current_date=date(2026, 5, 27))

    assert result["entry_date"] == "1980-05-01"
    assert result["date_precision"] == "month"
    VoiceAnalysis.model_validate(result)


def test_prepare_voice_payload_resets_month_precision_without_historical_year() -> None:
    payload = {
        "entry_date": "2026-05-01",
        "date_precision": "month",
        "bio": {"water_work": ["заработал"]},
        "finance": [
            {
                "direction": "income",
                "amount": 50000,
                "category": "Источник 1",
                "description": "заработал",
            }
        ],
        "raw_text": "заработал 50 тысяч источник 1",
    }

    result = _prepare_voice_payload(payload, current_date=date(2026, 5, 27))

    assert result["entry_date"] == "2026-05-27"
    assert result["date_precision"] == "day"
    assert result["bio"]["water_work"] == ["заработал 50 000 ₽"]
    VoiceAnalysis.model_validate(result)


def test_prepare_voice_payload_resets_first_day_for_current_month_without_day() -> None:
    payload = {
        "entry_date": "2026-05-01",
        "date_precision": "day",
        "bio": {"water_work": ["заработал"]},
        "finance": [],
        "raw_text": "май, заработал",
    }

    result = _prepare_voice_payload(payload, current_date=date(2026, 5, 27))

    assert result["entry_date"] == "2026-05-27"
    assert result["date_precision"] == "day"
    VoiceAnalysis.model_validate(result)


def test_prepare_voice_payload_keeps_day_precision_when_day_is_named() -> None:
    payload = {
        "entry_date": "1980-05-15",
        "bio": {"water_work": ["пошёл в школу"]},
        "finance": [],
        "raw_text": "15 мая 1980 года пошёл в школу.",
    }

    result = _prepare_voice_payload(payload)

    assert result["entry_date"] == "1980-05-15"
    assert result["date_precision"] == "day"
    VoiceAnalysis.model_validate(result)
