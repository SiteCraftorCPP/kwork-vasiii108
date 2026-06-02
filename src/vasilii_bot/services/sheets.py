import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from gspread import Spreadsheet, Worksheet
from gspread.exceptions import WorksheetNotFound
from gspread.utils import rowcol_to_a1
from rapidfuzz import fuzz, process

from ..config import Settings
from ..models import (
    ACCOUNT_TRANSFER_AMOUNT_COL,
    BIO_FIELD_COLUMNS,
    AccountTransfer,
    FinanceCategorySet,
    FinanceDirection,
    FinanceEntry,
    UserProfile,
    VoiceAnalysis,
)
from ..utils.dates import MONTH_NAMES_NOMINATIVE, month_matches, month_sheet_name, year_sheet_name
from ..utils.text import (
    MONTH_SHEET_TITLE_RE,
    YEAR_SHEET_TITLE_RE,
    append_amount_formula,
    append_signed_amount_formula,
    build_day_marker_runs,
    compact_spaces,
    day_segment_match,
    format_bio_description,
    format_money_description,
    has_day_segment,
    merge_day_segments,
    normalize_account_name,
    parse_day_segments,
    strip_final_dot,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsError(RuntimeError):
    pass


@dataclass(frozen=True)
class MoneyTable:
    direction: FinanceDirection
    header_row: int
    amount_col: int
    description_col: int
    category_col: int
    start_row: int
    end_row: int


@dataclass(frozen=True)
class MoneyLayout:
    worksheet_title: str
    tables: dict[FinanceDirection, MoneyTable]


class GoogleSheetsService:
    def __init__(self, settings: Settings):
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_service_account_file,
            scopes=SCOPES,
        )
        self.client = gspread.authorize(credentials)
        self.api = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self.drive_api = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.bio_template_id = settings.bio_template_id
        self.money_template_id = settings.money_template_id

    async def verify_access(self, spreadsheet_id: str) -> str:
        return await asyncio.to_thread(self._verify_access_sync, spreadsheet_id)

    def _verify_access_sync(self, spreadsheet_id: str) -> str:
        spreadsheet = self.client.open_by_key(spreadsheet_id)
        return spreadsheet.title

    async def create_student_copies(
        self,
        google_email: str,
        bio_template_id: str,
        money_template_id: str,
        title_suffix: str,
    ) -> tuple[str, str]:
        return await asyncio.to_thread(
            self._create_student_copies_sync,
            google_email,
            bio_template_id,
            money_template_id,
            title_suffix,
        )

    def _create_student_copies_sync(
        self,
        google_email: str,
        bio_template_id: str,
        money_template_id: str,
        title_suffix: str,
    ) -> tuple[str, str]:
        bio_id = self._copy_spreadsheet(
            template_id=bio_template_id,
            title=f"Биография - {title_suffix}",
            google_email=google_email,
        )
        money_id = self._copy_spreadsheet(
            template_id=money_template_id,
            title=f"Деньги - {title_suffix}",
            google_email=google_email,
        )
        return bio_id, money_id

    def _copy_spreadsheet(self, template_id: str, title: str, google_email: str) -> str:
        try:
            copied = (
                self.drive_api.files()
                .copy(
                    fileId=template_id,
                    body={"name": title},
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            if "storageQuotaExceeded" in str(exc):
                raise SheetsError(
                    "Google не дал service account создать копию шаблона: "
                    "Drive storage quota exceeded. Такой аккаунт может работать "
                    "с уже расшаренными таблицами, но не может владеть новыми "
                    "копиями в My Drive. Создайте копии шаблонов вручную и "
                    "подключите их через /link_bio и /link_money, либо нужен "
                    "OAuth владельца Google Drive или Shared Drive."
                ) from exc
            raise

        file_id = copied["id"]
        self.drive_api.permissions().create(
            fileId=file_id,
            body={
                "type": "user",
                "role": "writer",
                "emailAddress": google_email,
            },
            sendNotificationEmail=False,
            supportsAllDrives=True,
        ).execute()
        return file_id

    async def get_money_categories(
        self,
        spreadsheet_id: str,
        target_date: date,
    ) -> FinanceCategorySet:
        return await asyncio.to_thread(self._get_money_categories_sync, spreadsheet_id, target_date)

    def _get_money_categories_sync(
        self,
        spreadsheet_id: str,
        target_date: date,
    ) -> FinanceCategorySet:
        spreadsheet = self.client.open_by_key(spreadsheet_id)
        worksheet = self._get_month_worksheet(spreadsheet, target_date)
        layout = self._detect_money_layout(worksheet)
        values = worksheet.get_all_values()
        return FinanceCategorySet(
            income=self._categories_for_table(values, layout.tables[FinanceDirection.income]),
            expense=self._categories_for_table(values, layout.tables[FinanceDirection.expense]),
        )

    async def append_analysis(self, profile: UserProfile, analysis: VoiceAnalysis) -> list[str]:
        return await asyncio.to_thread(self._append_analysis_sync, profile, analysis)

    def _append_analysis_sync(self, profile: UserProfile, analysis: VoiceAnalysis) -> list[str]:
        written: list[str] = []
        if analysis.has_bio:
            if not profile.bio_sheet_id:
                raise SheetsError(
                    "Не подключена таблица биографии. Используйте /link_bio <ссылка>."
                )
            count = self._append_bio_sync(profile.bio_sheet_id, analysis)
            written.append(f"биография: {count} полей")

        if analysis.finance:
            if not profile.money_sheet_id:
                raise SheetsError("Не подключена таблица денег. Используйте /link_money <ссылка>.")
            count = self._append_finance_sync(
                profile.money_sheet_id,
                analysis.entry_date,
                analysis.finance,
            )
            written.append(f"финансы: {count} операций")

        if analysis.transfers:
            if not profile.money_sheet_id:
                raise SheetsError("Не подключена таблица денег. Используйте /link_money <ссылка>.")
            count = self._append_transfers_sync(
                profile.money_sheet_id,
                analysis.entry_date,
                analysis.transfers,
            )
            written.append(f"переводы: {count}")

        return written

    def _append_bio_sync(self, spreadsheet_id: str, analysis: VoiceAnalysis) -> int:
        spreadsheet = self.client.open_by_key(spreadsheet_id)
        worksheet = self._get_year_worksheet(spreadsheet, analysis.entry_date)
        month_row = self._find_bio_month_row(worksheet, analysis.entry_date.month)

        count = 0
        for field, items in analysis.bio.items():
            if not items:
                continue
            column = BIO_FIELD_COLUMNS[field]
            marker = _bio_entry_marker(analysis)
            if analysis.date_precision == "month":
                self._append_rich_day_cell(
                    spreadsheet_id=spreadsheet_id,
                    worksheet=worksheet,
                    row=month_row,
                    column=column,
                    marker=marker,
                    items=items,
                )
            else:
                self._update_description_cell(
                    spreadsheet_id=spreadsheet_id,
                    worksheet=worksheet,
                    row=month_row,
                    column=column,
                    marker=marker,
                    items=items,
                    money_layout=False,
                )
            count += 1
        return count

    def _append_finance_sync(
        self,
        spreadsheet_id: str,
        target_date: date,
        entries: list[FinanceEntry],
    ) -> int:
        spreadsheet = self.client.open_by_key(spreadsheet_id)
        worksheet = self._get_month_worksheet(spreadsheet, target_date)
        layout = self._detect_money_layout(worksheet)
        values = worksheet.get_all_values()

        amount_updates: dict[str, str] = {}
        description_updates: dict[tuple[int, int], list[tuple[int, str]]] = {}
        for entry in entries:
            table = layout.tables[entry.direction]
            category_row = self._find_category_row(values, table, entry.category)

            amount_a1 = rowcol_to_a1(category_row, table.amount_col)
            existing_amount = amount_updates.get(amount_a1)
            if existing_amount is None:
                existing_amount = self._get_formula_value(spreadsheet, worksheet, amount_a1)
            amount_updates[amount_a1] = append_amount_formula(existing_amount, entry.amount)

            description_key = (category_row, table.description_col)
            day = entry.day or target_date.day
            description_updates.setdefault(description_key, []).append((day, entry.description))

        if amount_updates:
            worksheet.batch_update(
                [
                    {
                        "range": amount_a1,
                        "values": [[formula]],
                    }
                    for amount_a1, formula in amount_updates.items()
                ],
                raw=False,
            )

        for (row, column), day_items in description_updates.items():
            self._update_description_cell(
                spreadsheet_id=spreadsheet_id,
                worksheet=worksheet,
                row=row,
                column=column,
                day_items=day_items,
                money_layout=True,
            )

        return len(entries)

    def _append_transfers_sync(
        self,
        spreadsheet_id: str,
        target_date: date,
        transfers: list[AccountTransfer],
    ) -> int:
        spreadsheet = self.client.open_by_key(spreadsheet_id)
        worksheet = self._get_month_worksheet(spreadsheet, target_date)
        values = worksheet.get_all_values()

        amount_updates: dict[str, str] = {}
        for transfer in transfers:
            from_row = self._find_account_row(values, transfer.from_account)
            to_row = self._find_account_row(values, transfer.to_account)
            for row, delta in ((from_row, -transfer.amount), (to_row, transfer.amount)):
                amount_a1 = rowcol_to_a1(row, ACCOUNT_TRANSFER_AMOUNT_COL)
                existing_amount = amount_updates.get(amount_a1)
                if existing_amount is None:
                    existing_amount = self._get_formula_value(spreadsheet, worksheet, amount_a1)
                amount_updates[amount_a1] = append_signed_amount_formula(
                    existing_amount,
                    delta,
                )

        if amount_updates:
            worksheet.batch_update(
                [
                    {"range": amount_a1, "values": [[formula]]}
                    for amount_a1, formula in amount_updates.items()
                ],
                raw=False,
            )
        return len(transfers)

    @staticmethod
    def _find_account_row(values: list[list[str]], account_name: str) -> int:
        target = normalize_account_name(account_name)
        choices: dict[str, int] = {}
        labels: dict[str, str] = {}
        for row in range(1, len(values) + 1):
            for col in range(1, 4):
                value = _value_at(values, row, col)
                if not value:
                    continue
                normalized = normalize_account_name(value)
                if normalized:
                    choices[normalized] = row
                    labels[normalized] = value

        if target in choices:
            return choices[target]

        match = process.extractOne(target, list(choices), scorer=fuzz.WRatio)
        if match and match[1] >= 75:
            return choices[match[0]]

        available = ", ".join(labels.values())
        raise SheetsError(
            f"Счёт '{account_name}' не найден. Доступно: {available or 'нет счетов в таблице'}"
        )

    def _get_year_worksheet(self, spreadsheet: Spreadsheet, target_date: date) -> Worksheet:
        title = year_sheet_name(target_date)
        try:
            return spreadsheet.worksheet(title)
        except WorksheetNotFound:
            return self._duplicate_period_sheet(
                spreadsheet,
                new_title=title,
                template_id=self.bio_template_id,
                kind="year",
            )

    def _get_month_worksheet(self, spreadsheet: Spreadsheet, target_date: date) -> Worksheet:
        title = month_sheet_name(target_date)
        try:
            return spreadsheet.worksheet(title)
        except WorksheetNotFound:
            return self._duplicate_period_sheet(
                spreadsheet,
                new_title=title,
                template_id=self.money_template_id,
                kind="month",
            )

    def _duplicate_period_sheet(
        self,
        spreadsheet: Spreadsheet,
        new_title: str,
        template_id: str | None,
        kind: Literal["month", "year"],
    ) -> Worksheet:
        source_sheet_id = self._resolve_template_sheet_id(template_id, kind)
        if source_sheet_id is None:
            source_sheet_id = self._resolve_local_template_sheet_id(spreadsheet, kind)
        body = {
            "requests": [
                {
                    "duplicateSheet": {
                        "sourceSheetId": source_sheet_id,
                        "newSheetName": new_title,
                    }
                }
            ]
        }
        self.api.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet.id,
            body=body,
        ).execute()
        return spreadsheet.worksheet(new_title)

    def _resolve_template_sheet_id(
        self,
        template_id: str | None,
        kind: Literal["month", "year"],
    ) -> int | None:
        if not template_id:
            return None
        try:
            template = self.client.open_by_key(template_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Template spreadsheet %s is unavailable: %s", template_id, exc)
            return None
        worksheet = _pick_template_worksheet(template.worksheets(), kind)
        return worksheet.id if worksheet else None

    @staticmethod
    def _resolve_local_template_sheet_id(
        spreadsheet: Spreadsheet,
        kind: Literal["month", "year"],
    ) -> int:
        worksheet = _pick_template_worksheet(spreadsheet.worksheets(), kind)
        if worksheet:
            return worksheet.id
        return spreadsheet.worksheets()[0].id

    @staticmethod
    def _find_bio_month_row(worksheet: Worksheet, month: int) -> int:
        values = worksheet.col_values(1)
        for row_index, value in enumerate(values, start=1):
            if month_matches(value, month):
                return row_index
        raise SheetsError(f"В листе {worksheet.title} не найден месяц {month}")

    def _update_description_cell(
        self,
        spreadsheet_id: str,
        worksheet: Worksheet,
        row: int,
        column: int,
        *,
        day_items: list[tuple[int, str]] | None = None,
        marker: str | None = None,
        items: list[str] | None = None,
        money_layout: bool = False,
    ) -> None:
        a1 = rowcol_to_a1(row, column)
        cell_data = self._get_cell_data(spreadsheet_id, worksheet.title, a1)
        existing_text = _cell_string_value(cell_data)
        existing_runs = list(cell_data.get("textFormatRuns") or [])

        if marker and not marker.isdigit():
            new_text, runs = _append_rich_day_text(existing_text, existing_runs, marker, items or [])
        else:
            segments = parse_day_segments(existing_text, money_layout=money_layout)
            if day_items:
                for day, description in day_items:
                    segments = merge_day_segments(segments, day, [description])
            elif marker and marker.isdigit() and items:
                segments = merge_day_segments(segments, int(marker), items)
            new_text = (
                format_money_description(segments)
                if money_layout
                else format_bio_description(segments)
            )
            runs = build_day_marker_runs(new_text) if new_text else []

        self._write_description_cell(
            spreadsheet_id=spreadsheet_id,
            worksheet=worksheet,
            row=row,
            column=column,
            new_text=new_text,
            runs=runs,
        )

    def _append_rich_day_cell(
        self,
        spreadsheet_id: str,
        worksheet: Worksheet,
        row: int,
        column: int,
        marker: str,
        items: list[str],
    ) -> None:
        a1 = rowcol_to_a1(row, column)
        cell_data = self._get_cell_data(spreadsheet_id, worksheet.title, a1)
        existing_text = _cell_string_value(cell_data)
        existing_runs = list(cell_data.get("textFormatRuns") or [])
        new_text, runs = _append_rich_day_text(existing_text, existing_runs, marker, items)
        self._write_description_cell(
            spreadsheet_id=spreadsheet_id,
            worksheet=worksheet,
            row=row,
            column=column,
            new_text=new_text,
            runs=runs,
        )

    def _write_description_cell(
        self,
        spreadsheet_id: str,
        worksheet: Worksheet,
        row: int,
        column: int,
        new_text: str,
        runs: list[dict[str, Any]],
    ) -> None:
        request = {
            "requests": [
                {
                    "updateCells": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": row - 1,
                            "endRowIndex": row,
                            "startColumnIndex": column - 1,
                            "endColumnIndex": column,
                        },
                        "rows": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {"stringValue": new_text},
                                        "textFormatRuns": runs,
                                    }
                                ]
                            }
                        ],
                        "fields": "userEnteredValue,textFormatRuns",
                    }
                }
            ]
        }
        if not new_text:
            return
        self.api.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request).execute()

    def _get_cell_data(self, spreadsheet_id: str, worksheet_title: str, a1: str) -> dict[str, Any]:
        range_name = f"'{worksheet_title}'!{a1}"
        result = (
            self.api.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                ranges=[range_name],
                includeGridData=True,
                fields="sheets(data(rowData(values(userEnteredValue,textFormatRuns))))",
            )
            .execute()
        )
        try:
            return result["sheets"][0]["data"][0]["rowData"][0]["values"][0]
        except (KeyError, IndexError):
            return {}

    @staticmethod
    def _detect_money_layout(worksheet: Worksheet) -> MoneyLayout:
        values = worksheet.get_all_values()
        for row_index, row in enumerate(values, start=1):
            normalized = [_norm(cell) for cell in row]
            amount_cols = [index + 1 for index, cell in enumerate(normalized) if cell == "сумма"]
            if len(amount_cols) < 2:
                continue

            tables: dict[FinanceDirection, MoneyTable] = {}
            for position, amount_col in enumerate(amount_cols):
                if position + 1 < len(amount_cols):
                    next_amount_col = amount_cols[position + 1]
                else:
                    next_amount_col = len(row) + 1

                description_col = _find_header_col(
                    normalized,
                    "описание",
                    amount_col,
                    next_amount_col,
                )
                category_col = _find_header_col(
                    normalized,
                    "категория",
                    amount_col,
                    next_amount_col,
                )
                if not description_col or not category_col:
                    continue

                label = _nearest_block_label(values, row_index, amount_col, category_col)
                if "доход" in label:
                    direction = FinanceDirection.income
                elif "расход" in label:
                    direction = FinanceDirection.expense
                else:
                    direction = (
                        FinanceDirection.expense if position == 0 else FinanceDirection.income
                    )

                tables[direction] = MoneyTable(
                    direction=direction,
                    header_row=row_index,
                    amount_col=amount_col,
                    description_col=description_col,
                    category_col=category_col,
                    start_row=row_index + 1,
                    end_row=len(values),
                )

            if FinanceDirection.income in tables and FinanceDirection.expense in tables:
                return MoneyLayout(worksheet_title=worksheet.title, tables=tables)

        raise SheetsError(f"На листе {worksheet.title} не найдены таблицы расходов/доходов")

    @staticmethod
    def _categories_for_table(values: list[list[str]], table: MoneyTable) -> list[str]:
        categories: list[str] = []
        for row in range(table.start_row, table.end_row + 1):
            value = _value_at(values, row, table.category_col)
            if value and value not in categories:
                categories.append(value)
        return categories

    @staticmethod
    def _find_category_row(values: list[list[str]], table: MoneyTable, requested: str) -> int:
        choices: dict[str, int] = {}
        normalized_to_original: dict[str, str] = {}
        for row in range(table.start_row, table.end_row + 1):
            value = _value_at(values, row, table.category_col)
            if not value:
                continue
            normalized = _category_norm(value)
            choices[normalized] = row
            normalized_to_original[normalized] = value

        requested_norm = _category_norm(requested)
        if requested_norm in choices:
            return choices[requested_norm]

        match = process.extractOne(requested_norm, list(choices), scorer=fuzz.WRatio)
        if match and match[1] >= 78:
            logger.info(
                "Matched category %r to %r with score %s",
                requested,
                normalized_to_original[match[0]],
                match[1],
            )
            return choices[match[0]]

        available = ", ".join(normalized_to_original.values())
        raise SheetsError(f"Категория '{requested}' не найдена. Доступно: {available}")

    @staticmethod
    def _get_formula_value(spreadsheet: Spreadsheet, worksheet: Worksheet, a1: str) -> str:
        range_name = f"'{worksheet.title}'!{a1}"
        result = spreadsheet.values_get(range_name, params={"valueRenderOption": "FORMULA"})
        values = result.get("values") or []
        if not values or not values[0]:
            return ""
        return str(values[0][0])

    @staticmethod
    def _get_display_value(worksheet: Worksheet, a1: str) -> str:
        values = worksheet.get(a1)
        if not values or not values[0]:
            return ""
        return str(values[0][0])

    async def collect_report_source(self, profile: UserProfile, target_date: date) -> str:
        return await asyncio.to_thread(self._collect_report_source_sync, profile, target_date)

    def _collect_report_source_sync(self, profile: UserProfile, target_date: date) -> str:
        chunks: list[str] = []
        if profile.bio_sheet_id:
            try:
                spreadsheet = self.client.open_by_key(profile.bio_sheet_id)
                worksheet = self._get_year_worksheet(spreadsheet, target_date)
                row = self._find_bio_month_row(worksheet, target_date.month)
                values = worksheet.row_values(row)
                chunks.append(f"Биография {worksheet.title}, месяц {target_date.month}: {values}")
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"Биография недоступна: {exc}")

        if profile.money_sheet_id:
            try:
                spreadsheet = self.client.open_by_key(profile.money_sheet_id)
                worksheet = self._get_month_worksheet(spreadsheet, target_date)
                values = worksheet.get_all_values()
                chunks.append(f"Финансы {worksheet.title}: {values[-16:]}")
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"Финансы недоступны: {exc}")

        return "\n\n".join(chunks)


def _append_bio_rich_text(
    existing_text: str,
    existing_runs: list[dict[str, Any]],
    day: int | str,
    items: list[str],
) -> tuple[str, list[dict[str, Any]]]:
    return _append_rich_day_text(existing_text, existing_runs, str(day), items)


def _append_rich_day_text(
    existing_text: str,
    existing_runs: list[dict[str, Any]],
    marker: str,
    items: list[str],
    separator: str = "\n",
) -> tuple[str, list[dict[str, Any]]]:
    clean_marker = compact_spaces(marker)
    clean_items = _dedupe_items([
        strip_final_dot(compact_spaces(item))
        for item in items
        if compact_spaces(item)
    ])
    if not clean_marker or not clean_items:
        return existing_text, existing_runs

    base = existing_text.rstrip()
    runs = _sanitize_runs(existing_runs, len(base))
    if not base.strip():
        new_text = _join_marker_items(clean_marker, clean_items)
        return new_text, [
            {"startIndex": 0, "format": {"bold": True}},
            {"startIndex": len(clean_marker), "format": {"bold": False}},
        ]

    if _has_day_segment(base, clean_marker):
        existing_items = _day_segment_item_keys(base, clean_marker)
        new_items = [item for item in clean_items if _item_key(item) not in existing_items]
        new_text = f"{strip_final_dot(base)} • {' • '.join(new_items)}." if new_items else base
        return new_text, _sanitize_runs(existing_runs, len(new_text))

    prefix = f"{strip_final_dot(base)}.{separator}"
    new_segment = _join_marker_items(clean_marker, clean_items)
    day_start = len(prefix)
    new_text = f"{prefix}{new_segment}"
    runs.extend(
        [
            {"startIndex": day_start, "format": {"bold": True}},
            {"startIndex": day_start + len(clean_marker), "format": {"bold": False}},
        ]
    )
    return new_text, runs


def _bio_entry_marker(analysis: VoiceAnalysis) -> str:
    if analysis.date_precision == "month":
        return MONTH_NAMES_NOMINATIVE[analysis.entry_date.month].lower()
    return str(analysis.entry_date.day)


def _join_marker_items(marker: str, items: list[str]) -> str:
    clean_items = [strip_final_dot(compact_spaces(item)) for item in items if compact_spaces(item)]
    return f"{marker} • {' • '.join(clean_items)}."


def _dedupe_items(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _item_key(item)
        if key and key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _day_segment_item_keys(text: str, marker: str) -> set[str]:
    segment = _day_segment_text(text, marker)
    if segment is None:
        return set()
    return {_item_key(item) for item in segment.split("•") if _item_key(item)}


def _day_segment_text(text: str, marker: str) -> str | None:
    match = _day_segment_match(text, marker)
    if not match:
        return None
    start = match.end()
    next_match = re.search(r"(?:\n|\. )\d+\s*•", text[start:])
    end = start + next_match.start() if next_match else len(text)
    return text[start:end]


def _item_key(value: str) -> str:
    return strip_final_dot(compact_spaces(value)).casefold()


def _sanitize_runs(runs: list[dict[str, Any]], text_length: int) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for run in runs:
        start = run.get("startIndex")
        fmt = run.get("format")
        if isinstance(start, int) and start < text_length and isinstance(fmt, dict):
            sanitized.append({"startIndex": start, "format": fmt})
    return sanitized


def _has_day_segment(text: str, marker: str) -> bool:
    return has_day_segment(text, marker)


def _day_segment_match(text: str, marker: str) -> re.Match[str] | None:
    return day_segment_match(text, marker)


def _pick_template_worksheet(
    worksheets: list[Worksheet],
    kind: Literal["month", "year"],
) -> Worksheet | None:
    if kind == "year":
        matches = [ws for ws in worksheets if YEAR_SHEET_TITLE_RE.fullmatch(ws.title)]
    else:
        matches = [ws for ws in worksheets if MONTH_SHEET_TITLE_RE.fullmatch(ws.title)]

    if not matches:
        return None

    return min(matches, key=_template_sheet_sort_key)


def _template_sheet_sort_key(worksheet: Worksheet) -> tuple[int, str]:
    title = worksheet.title
    if MONTH_SHEET_TITLE_RE.fullmatch(title):
        month, year = title.split(".", 1)
        return (int(year), int(month), title)
    if YEAR_SHEET_TITLE_RE.fullmatch(title):
        return (int(title), 0, title)
    return (0, 0, title)


def _cell_string_value(cell_data: dict[str, Any]) -> str:
    value = cell_data.get("userEnteredValue") or {}
    for key in ("stringValue", "numberValue", "formulaValue"):
        if key in value:
            return str(value[key])
    return ""


def _find_header_col(row: list[str], label: str, start_col: int, end_col: int) -> int | None:
    for col in range(start_col, end_col):
        if col - 1 < len(row) and row[col - 1] == label:
            return col
    return None


def _nearest_block_label(
    values: list[list[str]],
    header_row: int,
    start_col: int,
    end_col: int,
) -> str:
    labels: list[str] = []
    for row in range(max(1, header_row - 5), header_row):
        for col in range(start_col, end_col + 1):
            labels.append(_norm(_value_at(values, row, col)))
    return " ".join(labels)


def _value_at(values: list[list[str]], row: int, col: int) -> str:
    if row < 1 or col < 1:
        return ""
    try:
        return values[row - 1][col - 1].strip()
    except IndexError:
        return ""


def _norm(value: str) -> str:
    return value.strip().lower().replace("ё", "е").replace(":", "")


def _category_norm(value: str) -> str:
    return "".join(ch for ch in _norm(value) if ch.isalnum())
