from vasilii_bot.services.prompts import (
    REPORT_PROMPT_CATALOG,
    VOICE_PROMPT_CATALOG,
    load_prompt_by_key,
    render_report_prompt,
    report_system_prompt,
    save_prompt_by_key,
    validate_prompt_content,
    voice_system_prompt,
)

def test_validate_report_prompt_requires_placeholders() -> None:
    warnings = validate_prompt_content("report_daily", "текст без подстановок")
    assert len(warnings) == 2
    assert any("{title}" in warning for warning in warnings)


def test_save_and_load_prompt_by_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "vasilii_bot.services.prompts._PROMPTS_DIR",
        tmp_path,
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "daily.txt").write_text(
        "old {title} {source_text}",
        encoding="utf-8",
    )
    save_prompt_by_key("report_daily", "new {title}\n{source_text}")
    assert load_prompt_by_key("report_daily") == "new {title}\n{source_text}"


def test_report_and_voice_prompts_are_separate_catalogs() -> None:
    assert "report_daily" in REPORT_PROMPT_CATALOG
    assert "voice_analysis" in VOICE_PROMPT_CATALOG
    assert "voice_analysis" not in REPORT_PROMPT_CATALOG


def test_render_report_prompt_uses_report_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("vasilii_bot.services.prompts._PROMPTS_DIR", tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "daily.txt").write_text("T:{title}\nD:{source_text}", encoding="utf-8")
    (reports_dir / "system.txt").write_text("report-system", encoding="utf-8")
    (tmp_path / "voice_analysis.txt").write_text("voice-system", encoding="utf-8")
    rendered = render_report_prompt("daily", "Title", "Data")
    assert rendered == "T:Title\nD:Data"
    assert report_system_prompt() == "report-system"
    assert voice_system_prompt() != report_system_prompt()
