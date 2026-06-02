from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

PROMPT_CATALOG: dict[str, tuple[str, str]] = {
    "report_daily": ("report_daily.txt", "Ежедневный отчёт"),
    "report_weekly": ("report_weekly.txt", "Еженедельный отчёт"),
    "report_monthly": ("report_monthly.txt", "Ежемесячный отчёт"),
    "voice_analysis": ("voice_analysis.txt", "Разбор голоса (био/деньги)"),
}

REPORT_PLACEHOLDERS = ("{title}", "{source_text}")


def load_prompt(name: str) -> str:
    path = _prompts_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def save_prompt_file(filename: str, content: str) -> None:
    path = _prompts_dir() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def prompt_label(prompt_key: str) -> str:
    return PROMPT_CATALOG[prompt_key][1]


def prompt_filename(prompt_key: str) -> str:
    if prompt_key not in PROMPT_CATALOG:
        raise KeyError(f"Unknown prompt key: {prompt_key}")
    return PROMPT_CATALOG[prompt_key][0]


def load_prompt_by_key(prompt_key: str) -> str:
    return load_prompt(prompt_filename(prompt_key))


def save_prompt_by_key(prompt_key: str, content: str) -> list[str]:
    if prompt_key not in PROMPT_CATALOG:
        raise KeyError(f"Unknown prompt key: {prompt_key}")
    warnings = validate_prompt_content(prompt_key, content)
    save_prompt_file(prompt_filename(prompt_key), content)
    return warnings


def validate_prompt_content(prompt_key: str, content: str) -> list[str]:
    warnings: list[str] = []
    if prompt_key.startswith("report_"):
        for placeholder in REPORT_PLACEHOLDERS:
            if placeholder not in content:
                warnings.append(f"нет плейсхолдера {placeholder}")
    return warnings


def preview_prompt(content: str, limit: int = 700) -> str:
    if len(content) <= limit:
        return content
    return content[: limit - 3] + "..."


def edit_hint(prompt_key: str) -> str:
    if prompt_key.startswith("report_"):
        return (
            "Отправьте новый текст одним сообщением.\n"
            "Обязательные подстановки: {title} и {source_text}."
        )
    return "Отправьте новый текст промпта одним сообщением."


def render_report_prompt(period: str, title: str, source_text: str) -> str:
    filename = {
        "weekly": "report_weekly.txt",
        "monthly": "report_monthly.txt",
        "daily": "report_daily.txt",
    }.get(period, "report_weekly.txt")
    template = load_prompt(filename)
    return template.format(title=title, source_text=source_text)


def _prompts_dir() -> Path:
    return _PROMPTS_DIR
