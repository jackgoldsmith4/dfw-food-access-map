"""
SQLite connection management and a generic upsert helper.

Every pipeline's "store" step goes through here rather than opening its own
connection, so schema initialization and upsert semantics are identical
across the food-store, population, and housing pipelines.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Sequence

from config import settings
from foodaccess.storage.schema import MIGRATIONS, SCHEMA_SQL

# Tables where a row can be manually edited/deleted through the map UI.
# upsert_records() checks this set before writing so a pipeline re-run never
# overwrites or resurrects a row a human has already corrected.
EDITABLE_TABLES = {"food_stores", "housing_properties"}


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they don't already exist, then apply any column
    migrations. Safe to call every run."""
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        for table, column, coltype in MIGRATIONS:
            existing_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _manually_edited_keys(table: str, key_fields: Sequence[str]) -> set[tuple]:
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(key_fields)} FROM {table} WHERE is_manually_edited = 1"
        ).fetchall()
    return {tuple(row) for row in rows}


def upsert_records(table: str, records: Sequence[dict], key_fields: Sequence[str]) -> int:
    """
    Insert or update a batch of dict records into `table`, keyed on
    `key_fields`. Re-running a pipeline refreshes existing rows instead of
    duplicating them.

    Every record must have the same set of keys. This is intentionally
    generic (rather than one hand-written INSERT per domain) so all three
    pipelines share one tested code path for the actual write.

    For editable tables (food_stores, housing_properties), records whose key
    already belongs to a manually-edited row are dropped before writing —
    a human correction (including a soft delete) always wins over freshly
    fetched source data, and a pipeline can never recreate a row a human
    removed.
    """
    if not records:
        return 0

    if table in EDITABLE_TABLES:
        protected = _manually_edited_keys(table, key_fields)
        if protected:
            records = [r for r in records if tuple(r[k] for k in key_fields) not in protected]
        if not records:
            return 0

    columns = list(records[0].keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in columns if c not in key_fields)
    conflict_clause = ", ".join(key_fields)

    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({conflict_clause}) DO UPDATE SET {update_clause}"
    )

    with get_connection() as conn:
        conn.executemany(sql, records)

    return len(records)
