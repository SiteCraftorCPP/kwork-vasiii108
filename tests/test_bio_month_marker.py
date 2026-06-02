from datetime import date

from vasilii_bot.models import VoiceAnalysis
from vasilii_bot.services.sheets import _append_bio_rich_text, _bio_entry_marker
from vasilii_bot.utils.dates import MONTH_NAMES_NOMINATIVE, bio_month_marker, normalize_bio_marker


def test_bio_month_marker_is_lowercase_for_all_months() -> None:
    for month in range(1, 13):
        marker = bio_month_marker(month)
        assert marker == marker.lower()
        assert marker[0].islower() or not marker[0].isalpha()


def test_normalize_bio_marker_lowercases_known_months() -> None:
    assert normalize_bio_marker("Май") == "май"
    assert normalize_bio_marker("  ИЮНЬ  ") == "июнь"
    assert normalize_bio_marker("24") == "24"


def test_append_bio_rich_text_normalizes_uppercase_month() -> None:
    text, _ = _append_bio_rich_text("", [], "Май", ["пошёл в школу"])
    assert text.startswith("май •")
    assert "Май" not in text


def test_bio_entry_marker_month_precision() -> None:
    analysis = VoiceAnalysis(
        entry_date=date(1980, 5, 1),
        date_precision="month",
        bio={},
    )
    assert _bio_entry_marker(analysis) == bio_month_marker(5)
    assert _bio_entry_marker(analysis) != MONTH_NAMES_NOMINATIVE[5]
