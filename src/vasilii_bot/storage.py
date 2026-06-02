import asyncio
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from .llm_models import normalize_model_id
from .models import PendingEntry, UserProfile

T = TypeVar("T")


class Storage:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    async def init(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        await self._run(self._init_sync)

    async def _run(self, func: Callable[..., T], *args: object) -> T:
        return await asyncio.to_thread(func, *args)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_sync(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    bio_sheet_id TEXT,
                    money_sheet_id TEXT,
                    timezone TEXT NOT NULL DEFAULT 'Europe/Minsk',
                    llm_model TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS pending_entries (
                    id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_pending_entries_chat_id
                    ON pending_entries(chat_id);

                CREATE TABLE IF NOT EXISTS edit_requests (
                    chat_id INTEGER PRIMARY KEY,
                    pending_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS prompt_edit_requests (
                    chat_id INTEGER PRIMARY KEY,
                    prompt_key TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            try:
                conn.execute("ALTER TABLE users ADD COLUMN llm_model TEXT")
            except sqlite3.OperationalError:
                pass

    async def ensure_user(self, chat_id: int) -> UserProfile:
        return await self._run(self._ensure_user_sync, chat_id)

    def _ensure_user_sync(self, chat_id: int) -> UserProfile:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (chat_id)
                VALUES (?)
                ON CONFLICT(chat_id) DO NOTHING
                """,
                (chat_id,),
            )
            row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row_to_user(row)

    async def set_bio_sheet(self, chat_id: int, sheet_id: str) -> UserProfile:
        return await self._run(self._set_sheet_sync, chat_id, "bio_sheet_id", sheet_id)

    async def set_money_sheet(self, chat_id: int, sheet_id: str) -> UserProfile:
        return await self._run(self._set_sheet_sync, chat_id, "money_sheet_id", sheet_id)

    async def set_llm_model(self, chat_id: int, model_id: str) -> UserProfile:
        return await self._run(self._set_llm_model_sync, chat_id, model_id)

    def _set_llm_model_sync(self, chat_id: int, model_id: str) -> UserProfile:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (chat_id)
                VALUES (?)
                ON CONFLICT(chat_id) DO NOTHING
                """,
                (chat_id,),
            )
            conn.execute(
                """
                UPDATE users
                SET llm_model = ?, updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = ?
                """,
                (normalize_model_id(model_id), chat_id),
            )
            row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row_to_user(row)

    def _set_sheet_sync(self, chat_id: int, column: str, sheet_id: str) -> UserProfile:
        if column not in {"bio_sheet_id", "money_sheet_id"}:
            raise ValueError(f"Unsupported sheet column: {column}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (chat_id)
                VALUES (?)
                ON CONFLICT(chat_id) DO NOTHING
                """,
                (chat_id,),
            )
            conn.execute(
                f"UPDATE users SET {column} = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
                (sheet_id, chat_id),
            )
            row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row_to_user(row)

    async def get_user(self, chat_id: int) -> UserProfile | None:
        return await self._run(self._get_user_sync, chat_id)

    def _get_user_sync(self, chat_id: int) -> UserProfile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row_to_user(row) if row else None

    async def list_users(self) -> list[UserProfile]:
        return await self._run(self._list_users_sync)

    def _list_users_sync(self) -> list[UserProfile]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
        return [self._row_to_user(row) for row in rows]

    async def save_pending(self, pending: PendingEntry) -> None:
        await self._run(self._save_pending_sync, pending)

    def _save_pending_sync(self, pending: PendingEntry) -> None:
        payload_json = json.dumps(pending.to_json_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pending_entries (id, chat_id, payload_json)
                VALUES (?, ?, ?)
                """,
                (pending.id, pending.chat_id, payload_json),
            )

    async def get_pending(self, pending_id: str) -> PendingEntry | None:
        return await self._run(self._get_pending_sync, pending_id)

    def _get_pending_sync(self, pending_id: str) -> PendingEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM pending_entries WHERE id = ?",
                (pending_id,),
            ).fetchone()
        if not row:
            return None
        return PendingEntry.model_validate(json.loads(row["payload_json"]))

    async def delete_pending(self, pending_id: str) -> None:
        await self._run(self._delete_pending_sync, pending_id)

    def _delete_pending_sync(self, pending_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_entries WHERE id = ?", (pending_id,))
            conn.execute("DELETE FROM edit_requests WHERE pending_id = ?", (pending_id,))

    async def set_edit_request(self, chat_id: int, pending_id: str) -> None:
        await self._run(self._set_edit_request_sync, chat_id, pending_id)

    def _set_edit_request_sync(self, chat_id: int, pending_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO edit_requests (chat_id, pending_id)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE
                    SET pending_id = excluded.pending_id,
                        created_at = CURRENT_TIMESTAMP
                """,
                (chat_id, pending_id),
            )

    async def set_prompt_edit_request(self, chat_id: int, prompt_key: str) -> None:
        await self._run(self._set_prompt_edit_request_sync, chat_id, prompt_key)

    def _set_prompt_edit_request_sync(self, chat_id: int, prompt_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_edit_requests (chat_id, prompt_key)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE
                    SET prompt_key = excluded.prompt_key,
                        created_at = CURRENT_TIMESTAMP
                """,
                (chat_id, prompt_key),
            )

    async def pop_prompt_edit_request(self, chat_id: int) -> str | None:
        return await self._run(self._pop_prompt_edit_request_sync, chat_id)

    def _pop_prompt_edit_request_sync(self, chat_id: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT prompt_key FROM prompt_edit_requests WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            conn.execute("DELETE FROM prompt_edit_requests WHERE chat_id = ?", (chat_id,))
        return row["prompt_key"] if row else None

    async def clear_prompt_edit_request(self, chat_id: int) -> None:
        await self._run(self._clear_prompt_edit_request_sync, chat_id)

    def _clear_prompt_edit_request_sync(self, chat_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM prompt_edit_requests WHERE chat_id = ?", (chat_id,))

    async def pop_edit_request(self, chat_id: int) -> str | None:
        return await self._run(self._pop_edit_request_sync, chat_id)

    def _pop_edit_request_sync(self, chat_id: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT pending_id FROM edit_requests WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            conn.execute("DELETE FROM edit_requests WHERE chat_id = ?", (chat_id,))
        return row["pending_id"] if row else None

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserProfile:
        raw_llm = row["llm_model"] if "llm_model" in row.keys() else None
        llm_model = normalize_model_id(raw_llm) if raw_llm else None
        return UserProfile(
            chat_id=row["chat_id"],
            bio_sheet_id=row["bio_sheet_id"],
            money_sheet_id=row["money_sheet_id"],
            timezone=row["timezone"],
            llm_model=llm_model,
        )
