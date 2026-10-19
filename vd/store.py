"""Состояние агента в SQLite: закладки, просмотренные элементы, журнал отправленного, запуски.

Всё, что меняет состояние, копится в памяти и записывается одной транзакцией
только после того, как письмо подтверждённо ушло (commit_after_send).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    source      TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seen (
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);
CREATE TABLE IF NOT EXISTS ledger (
    dedup_key   TEXT PRIMARY KEY,
    title       TEXT,
    company     TEXT,
    url         TEXT,
    source      TEXT,
    bucket      TEXT,
    reported_at TEXT NOT NULL,
    status      TEXT DEFAULT 'new'      -- new / applied / rejected / interview — на будущее
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,          -- running / sent / failed / dry-run
    stats_json  TEXT,
    error       TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- чтение ----------
    def get_bookmark(self, source: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM bookmarks WHERE source=?", (source,)).fetchone()
        return row[0] if row else None

    def is_seen(self, source: str, external_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen WHERE source=? AND external_id=?", (source, external_id)
        ).fetchone()
        return row is not None

    def recent_ledger(self, days: int) -> list[dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.conn.execute(
            "SELECT dedup_key, title, company, url, source FROM ledger WHERE reported_at >= ?", (since,)
        ).fetchall()
        return [dict(zip(("dedup_key", "title", "company", "url", "source"), r)) for r in rows]

    def sent_today(self) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM runs WHERE run_date=? AND status IN ('sent', 'empty')", (date.today().isoformat(),)
        ).fetchone()
        return row is not None

    # ---------- журнал запусков ----------
    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (run_date, started_at, status) VALUES (?, ?, 'running')",
            (date.today().isoformat(), datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, status: str, stats: dict, error: Optional[str] = None) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats_json=?, error=? WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), status,
             json.dumps(stats, ensure_ascii=False), error, run_id),
        )
        self.conn.commit()

    # ---------- запись после отправки ----------
    def commit_after_send(
        self,
        bookmarks: dict[str, str],
        seen: Iterable[tuple[str, str]],
        ledger_rows: Iterable[dict],
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:  # одна транзакция
            for source, value in bookmarks.items():
                self.conn.execute(
                    "INSERT INTO bookmarks (source, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(source) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (source, value, now),
                )
            self.conn.executemany(
                "INSERT OR IGNORE INTO seen (source, external_id, first_seen) VALUES (?, ?, ?)",
                [(s, e, now) for s, e in seen],
            )
            for r in ledger_rows:
                self.conn.execute(
                    "INSERT OR IGNORE INTO ledger (dedup_key, title, company, url, source, bucket, reported_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (r["dedup_key"], r["title"], r.get("company"), r["url"], r["source"], r["bucket"], now),
                )

    def source_stats(self, days: int = 30) -> list[tuple]:
        """Сколько вакансий каждый источник принёс в дайджест за N дней (для решения, какие каналы держать)."""
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        return self.conn.execute(
            "SELECT source, bucket, COUNT(*) FROM ledger WHERE reported_at >= ? GROUP BY source, bucket "
            "ORDER BY source", (since,)
        ).fetchall()
