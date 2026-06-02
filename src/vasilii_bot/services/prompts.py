from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

REPORT_PROMPT_CATALOG: dict[str, tuple[str, str]] = {
    "report_system": ("reports/system.txt", "Системный (отчёты)"),
    "report_daily": ("reports/daily.txt", "Ежедневный отчёт"),
    "report_weekly": ("reports/weekly.txt", "Еженедельный отчёт"),
    "report_monthly": ("reports/monthly.txt", "Ежемесячный отчёт"),
}

VOICE_PROMPT_CATALOG: dict[str, tuple[str, str]] = {
    "voice_analysis": ("voice_analysis.txt", "Разбор голоса (био/деньги)"),
}

PROMPT_CATALOG: dict[str, tuple[str, str]] = {
    **REPORT_PROMPT_CATALOG,
    **VOICE_PROMPT_CATALOG,
}

REPORT_PERIOD_TO_KEY = {
    "daily": "report_daily",
    "weekly": "report_weekly",
    "monthly": "report_monthly",
}

_LEGACY_REPORT_FILES = {
    "report_daily": "report_daily.txt",
    "report_weekly": "report_weekly.txt",
    "report_monthly": "report_monthly.txt",
}

REPORT_PLACEHOLDERS = ("{title}", "{source_text}")
DEFAULT_REPORT_SYSTEM = (
    "Ты составляешь краткие отчёты на русском языке по данным из таблиц биографии и финансов."
)


def load_prompt(name: str) -> str:
    path = _prompts_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def voice_system_prompt() -> str:
    return load_prompt_by_key("voice_analysis")


def report_system_prompt() -> str:
    try:
        return load_prompt("reports/system.txt")
    except FileNotFoundError:
        return DEFAULT_REPORT_SYSTEM


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
    filename = prompt_filename(prompt_key)
    path = _prompts_dir() / filename
    if path.exists():
        return load_prompt(filename)
    legacy = _LEGACY_REPORT_FILES.get(prompt_key)
    if legacy:
        legacy_path = _prompts_dir() / legacy
        if legacy_path.exists():
            return legacy_path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"Prompt file not found: {path}")


def save_prompt_by_key(prompt_key: str, content: str) -> list[str]:
    if prompt_key not in PROMPT_CATALOG:
        raise KeyError(f"Unknown prompt key: {prompt_key}")
    warnings = validate_prompt_content(prompt_key, content)
    save_prompt_file(prompt_filename(prompt_key), content)
    return warnings


def validate_prompt_content(prompt_key: str, content: str) -> list[str]:
    warnings: list[str] = []
    if prompt_key in REPORT_PERIOD_TO_KEY.values():
        for placeholder in REPORT_PLACEHOLDERS:
            if placeholder not in content:
                warnings.append(f"нет плейсхолдера {placeholder}")
    return warnings


def preview_prompt(content: str, limit: int = 700) -> str:
    if len(content) <= limit:
        return content
    return content[: limit - 3] + "..."


def edit_hint(prompt_key: str) -> str:
    if prompt_key == "report_system":
        return "Системный промпт для всех отчётов (день/неделя/месяц). Отправьте новый текст."
    if prompt_key.startswith("report_"):
        return (
            "Шаблон отчёта. Отправьте новый текст одним сообщением.\n"
            "Обязательные подстановки: {title} и {source_text}."
        )
    return "Отправьте новый текст промпта разбора голоса одним сообщением."


def render_report_prompt(period: str, title: str, source_text: str) -> str:
    prompt_key = REPORT_PERIOD_TO_KEY.get(period, "report_weekly")
    template = load_prompt_by_key(prompt_key)
    return template.format(title=title, source_text=source_text)


def is_report_prompt_key(prompt_key: str) -> bool:
    return prompt_key in REPORT_PROMPT_CATALOG


def _prompts_dir() -> Path:
    return _PROMPTS_DIR
