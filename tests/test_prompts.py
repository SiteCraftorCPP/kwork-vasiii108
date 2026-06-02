from vasilii_bot.services.prompts import (
    load_prompt_by_key,
    save_prompt_by_key,
    validate_prompt_content,
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
    (tmp_path / "report_daily.txt").write_text(
        "old {title} {source_text}",
        encoding="utf-8",
    )
    save_prompt_by_key("report_daily", "new {title}\n{source_text}")
    assert load_prompt_by_key("report_daily") == "new {title}\n{source_text}"
