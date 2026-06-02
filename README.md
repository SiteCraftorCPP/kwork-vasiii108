# Vasilii Life Finance Bot

Telegram-бот для голосового ведения биографии и финансов с записью в персональные Google Sheets.

## Что реализовано

- Telegram long polling на `aiogram 3`.
- Команды подключения таблиц:
  - `/create_sheets <google email>`
  - `/link_bio <google sheets url or id>`
  - `/link_money <google sheets url or id>`
  - `/status`
  - `/cancel`
- Голосовой pipeline:
	  - скачивание voice из Telegram;
	  - транскрибация через OpenAI-compatible audio API;
	  - разбор русской записи через OpenAI-compatible API или Claude;
  - подтверждение пользователем;
  - запись в Google Sheets.
- Биография:
  - лист по году, например `2026`;
  - строка месяца;
  - запись в 6 полей `ЗЕМЛЯ/ВОДА x Тело/Отношения/Дело`;
  - день в начале записи выделяется жирным через Google Sheets API `textFormatRuns`.
- Финансы:
  - лист по месяцу, например `05.2026`;
  - автоопределение блоков `Расходы` и `Доходы` по заголовкам;
  - сумма дописывается формулой через `+`;
  - описание дописывается в формате `24 • роллы. 25 • ресторан • такси.`;
  - категории берутся из таблицы студента.
- SQLite-хранилище привязок студентов и pending-записей.
- APScheduler для еженедельных и ежемесячных отчётов.
- Команда `/report` для ежедневного отчёта по запросу.
- Команда `/model` — переключение Haiku 4.5 / Sonnet 4.5 (без 4.6).
- Переводы между счетами (Банк 1 → Банк 2) в колонку D листа месяца.
- Промпты LLM и отчётов в папке `prompts/` (можно редактировать без правок кода).
- Автоматическое снятие старого Telegram webhook перед polling-запуском.

## Подготовка Google

1. Создайте Google Cloud service account.
2. Включите Google Sheets API и Google Drive API.
3. Скачайте JSON-ключ на сервер, например `service-account.json`.
4. Дайте service account доступ редактора к шаблонным или пользовательским таблицам.
5. Укажите ID шаблонов в `.env`: `BIO_TEMPLATE_ID` и `MONEY_TEMPLATE_ID`.

Важно: service account у обычных Google-аккаунтов может не иметь Drive storage quota.
В этом случае он открывает и редактирует расшаренные таблицы, но не может сам создавать
копии шаблонов. Тогда студент создаёт копии вручную, даёт service account права редактора
и подключает их командами `/link_bio` и `/link_money`. Полностью автоматическое создание
копий требует OAuth владельца Google Drive или Shared Drive.

## Локальный запуск

```bash
uv sync --dev
cp .env.example .env
```

Заполните `.env`:

```env
BOT_TOKEN=...
PROXYAPI_API_KEY=...
LLM_PROVIDER=proxyapi
LLM_MODEL=anthropic/claude-sonnet-4-5
TRANSCRIPTION_PROVIDER=proxyapi
TRANSCRIPTION_MODEL=whisper-1
GOOGLE_SERVICE_ACCOUNT_FILE=./koc8-bot-d806c14ea1fa.json
BIO_TEMPLATE_ID=...
MONEY_TEMPLATE_ID=...
DEFAULT_BIO_SHEET_ID=...
DEFAULT_MONEY_SHEET_ID=...
```

При `proxyapi` отдельные `LLM_API_KEY` и `TRANSCRIPTION_API_KEY` не нужны — используется `PROXYAPI_API_KEY`.
`BIO_TEMPLATE_ID` и `MONEY_TEMPLATE_ID` уже должны быть в `.env`: без них не работают `/create_sheets` и создание новых листов года/месяца.

`DEFAULT_BIO_SHEET_ID` и `DEFAULT_MONEY_SHEET_ID` используются для тестового режима:
новый Telegram-чат получает эти таблицы автоматически после `/start`. Для каждого
студента в продакшене лучше использовать личные копии через `/link_bio` и `/link_money`.

Поддерживаемые LLM-провайдеры:

- `mashagpt`: OpenAI-compatible API, `https://api.mashagpt.ru/v1`.
- `bothub`: OpenAI-compatible API, `https://openai.bothub.chat/v1`.
- `proxyapi`: OpenAI-compatible API через ProxyAPI, `https://openai.api.proxyapi.ru/v1`.
- `openai`: прямой OpenAI API.
- `anthropic`: прямой Anthropic API.
- `custom`: любой OpenAI-compatible endpoint через `LLM_BASE_URL` и `LLM_API_KEY`.

Для распознавания голосовых:

- `bothub`: OpenAI-compatible `/audio/transcriptions`.
- `mashagpt`: OpenAI-compatible chat API; audio endpoint may be unavailable on account/API.
- `proxyapi`: OpenAI `/audio/transcriptions` через ProxyAPI.
- `openai`: прямой OpenAI API.
- `custom`: любой совместимый endpoint через `TRANSCRIPTION_BASE_URL`.

Запуск:

```bash
uv run vasilii-bot
```

## Промпты

Файлы в `prompts/`:

- `voice_analysis.txt` — разбор голосовых записей.
- `report_daily.txt` — ежедневный отчёт (`/report`).
- `report_weekly.txt` — еженедельный отчёт по расписанию.
- `report_monthly.txt` — ежемесячный отчёт по расписанию.

Редактирование в Telegram: кнопка **📝 Промпты** в `/start` или команда `/prompts`.
Выберите отчёт (день/неделя/месяц) или разбор голоса, затем пришлите новый текст.
Файлы в `prompts/` на диске обновляются сразу, перезапуск не нужен.

## Проверка

```bash
uv run pytest
uv run ruff check .
```

## Деплой на VPS

Минимально:

```bash
apt update
apt install -y curl
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --no-dev
uv run vasilii-bot
```

Для продакшена лучше запускать через `systemd`, передав `.env` рядом с проектом.

## Важное по секретам

Не храните Telegram token, SSH-пароли и API-ключи в коде. Все секреты должны лежать в `.env` или в переменных окружения на сервере.
