"""Состояние агента в SQLite: закладки, просмотренные элементы, журнал отправленного, запуски.

Всё, что меняет состояние, копится в памяти и записывается одной транзакцией
только после того, как письмо подтверждённо ушло (commit_after_send).
"""
from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from .models import Item

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
    status      TEXT DEFAULT 'new',     -- new / applied (отметка «Откликнулся») / rejected / interview
    code        TEXT                    -- код в письме vd-ГГГГММДД-am|pm-N, по нему приходит отметка
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
CREATE TABLE IF NOT EXISTS pending_bundles (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);
CREATE TABLE IF NOT EXISTS vacancy_entities (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES vacancy_entities(id),
    first_seen TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS publications_entity ON publications(entity_id);
CREATE TABLE IF NOT EXISTS vacancy_deliveries (
    code TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES vacancy_entities(id),
    ledger_key TEXT NOT NULL,
    reported_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    title TEXT, company TEXT
);
CREATE INDEX IF NOT EXISTS deliveries_entity ON vacancy_deliveries(entity_id);
CREATE TABLE IF NOT EXISTS duplicate_suggestions (
    publication_id TEXT NOT NULL REFERENCES publications(id),
    target_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY(publication_id, target_key)
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(SCHEMA)
        # базы, созданные до отметок откликов (20.10.2026), — без колонки code
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(ledger)")}
        if "code" not in cols:
            self.conn.execute("ALTER TABLE ledger ADD COLUMN code TEXT")
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

    def list_pending_bundles(self) -> list[Item]:
        items = []
        for (payload,) in self.conn.execute('SELECT payload FROM pending_bundles ORDER BY rowid'):
            data = json.loads(payload)
            if data.get('published_at'):
                data['published_at'] = datetime.fromisoformat(data['published_at'])
            items.append(Item(**data))
        return items

    def recent_ledger(self, days: int) -> list[dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        # на что откликнулся или что разобрал — не присылаем больше никогда
        rows = self.conn.execute(
            "SELECT dedup_key, title, company, url, source FROM ledger "
            "WHERE reported_at >= ? OR status IN ('applied', 'reviewed')", (since,)).fetchall()
        return [dict(zip(("dedup_key", "title", "company", "url", "source"), r)) for r in rows]

    def pending_marks(self, marks: dict[str, str]) -> list[dict]:
        """Отмеченные в таблице вакансии ({код: applied|reviewed}), статус которых ещё не записан."""
        if not marks:
            return []
        qs = ",".join("?" * len(marks))
        rows = self.conn.execute(
            f"SELECT code, title, company, status FROM ledger WHERE code IN ({qs}) "
            f"UNION ALL SELECT code,title,company,status FROM vacancy_deliveries WHERE code IN ({qs}) "
            "AND code NOT IN (SELECT code FROM ledger WHERE code IS NOT NULL)", tuple(marks) * 2).fetchall()
        out = []
        for code, title, company, status in rows:
            want = marks[code]
            if status == "new" or (status == "reviewed" and want == "applied"):  # отклик важнее «разобрано»
                out.append({"code": code, "title": title, "company": company, "status": want})
        return sorted(out, key=lambda r: (r["status"], r["code"]))

    def duplicate_history(self, marks: Optional[dict[str, str]] = None) -> list[dict]:
        """Архив плюс старый ledger без миграции его ключей, кодов или статусов."""
        from .duplicates import identity
        deliveries = {}
        code_entities = {}
        for code, entity, sent, status in self.conn.execute(
                'SELECT d.code,d.entity_id,d.reported_at,COALESCE(l.status,d.status) '
                'FROM vacancy_deliveries d LEFT JOIN ledger l ON l.code=d.code'):
            code_entities[code] = entity
            status = self._stronger(status, (marks or {}).get(code, 'new'))
            entry = deliveries.setdefault(entity, {'reported_at': sent, 'status': status})
            entry['reported_at'] = max(entry['reported_at'], sent)
            entry['status'] = self._stronger(entry['status'], status)
        history = []
        entity_identities = {}
        for key, entity, first, payload in self.conn.execute('SELECT id,entity_id,first_seen,payload FROM publications'):
            row = json.loads(payload)
            row.update(key=key, entity_id=entity, first_seen=first)
            row.update(deliveries.get(entity, {}))
            history.append(row)
            if row.get('identity'):
                entity_identities.setdefault(entity, set()).add(row['identity'])
        for key, title, company, url, source, sent, status, code in self.conn.execute(
                'SELECT dedup_key,title,company,url,source,reported_at,status,code FROM ledger'):
            entity = code_entities.get(code, self._legacy_entity(key))
            row = dict(key=key, entity_id=entity, title=title or '', company=company,
                                url=url, source=source, first_seen=sent, reported_at=sent,
                                identity=identity(url), text='', grade='unknown',
                                status=self._stronger(status, (marks or {}).get(code, 'new')))
            if entity in deliveries:
                row['status'] = self._stronger(row['status'], deliveries[entity]['status'])
                row['reported_at'] = max(row['reported_at'], deliveries[entity]['reported_at'])
            known_ids = entity_identities.get(entity, set())
            if len(known_ids) == 1:
                row['identity'] = next(iter(known_ids))
            elif len(known_ids) > 1:
                row['ambiguous'] = True
            history.append(row)
        return history

    @staticmethod
    def _stronger(left: str, right: str) -> str:
        ranks = {'new': 0, 'reviewed': 1, 'applied': 2}
        return right if ranks.get(right, 0) > ranks.get(left, 0) else left

    @staticmethod
    def _legacy_entity(key: str) -> str:
        return 'legacy:' + hashlib.sha256(key.encode()).hexdigest()

    def duplicate_observation_count(self) -> int:
        """Только успешные штатные выпуски, явно записанные новым pipeline."""
        return sum(bool(json.loads(stats or '{}').get('duplicates', {}).get('observation'))
                   for (stats,) in self.conn.execute("SELECT stats_json FROM runs WHERE status IN ('sent','empty')"))

    def _archive(self, publications: list[dict], ledger_rows: list[dict], now: str) -> None:
        # Capture old codes before ledger upserts replace them. No legacy row is rewritten.
        for key, title, company, sent, status, code in self.conn.execute(
                'SELECT dedup_key,title,company,reported_at,status,code FROM ledger').fetchall():
            if not code:
                continue
            entity = self._legacy_entity(key)
            self.conn.execute('INSERT OR IGNORE INTO vacancy_entities VALUES (?)', (entity,))
            self.conn.execute('INSERT OR IGNORE INTO vacancy_deliveries VALUES (?,?,?,?,?,?,?)',
                              (code, entity, key, sent, status, title, company))
        for row in publications:
            entity = row['entity_id']
            self.conn.execute('INSERT OR IGNORE INTO vacancy_entities VALUES (?)', (entity,))
            self.conn.execute(
                'INSERT INTO publications VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                'entity_id=excluded.entity_id,payload=excluded.payload',
                (row['key'], entity, row['first_seen'], json.dumps(row, ensure_ascii=False)))
            if row.get('suggestion'):
                self.conn.execute('INSERT OR REPLACE INTO duplicate_suggestions VALUES (?,?,?)',
                                  (row['key'], row['suggestion']['key'], json.dumps(row['suggestion'], ensure_ascii=False)))
        entities = {r['ledger_key']: r['entity_id'] for r in publications}
        for row in ledger_rows:
            if not row.get('code'):
                continue
            entity = entities.get(row['dedup_key'], self._legacy_entity(row['dedup_key']))
            self.conn.execute('INSERT OR IGNORE INTO vacancy_entities VALUES (?)', (entity,))
            self.conn.execute('INSERT OR IGNORE INTO vacancy_deliveries VALUES (?,?,?,?,?,?,?)',
                              (row['code'], entity, row['dedup_key'], now, 'new', row['title'], row.get('company')))

    def sent_in_slot(self, now: datetime, evening_hour: int = 17) -> bool:
        """Уже был выпуск в этот слот: «утро» — до evening_hour, «вечер» — после (по времени старта запуска)."""
        return self.sends_in_slot(now, evening_hour) > 0

    # ---------- журнал запусков ----------
    def start_run(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now()
        cur = self.conn.execute(
            "INSERT INTO runs (run_date, started_at, status) VALUES (?, ?, 'running')",
            (now.date().isoformat(), now.isoformat(timespec="seconds")),
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

    def fail_running(self, error: str) -> None:
        """Запуск упал посреди работы — не оставлять его вечно «running»."""
        self.conn.execute("UPDATE runs SET status='failed', finished_at=?, error=? WHERE status='running'",
                          (datetime.now().isoformat(timespec="seconds"), error))
        self.conn.commit()

    # ---------- запись после отправки ----------
    def commit_after_send(
        self,
        bookmarks: dict[str, str],
        seen: Iterable[tuple[str, str]],
        ledger_rows: Iterable[dict],
        marks: Optional[dict[str, str]] = None,
        pending_bundles: Optional[Iterable[Item]] = None,
        publications: Optional[list[dict]] = None,
    ) -> None:
        ledger_rows = list(ledger_rows)
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:  # одна транзакция
            if publications is not None:
                self._archive(publications, ledger_rows, now)
            if pending_bundles is not None:
                self.conn.execute('DELETE FROM pending_bundles')
                for item in pending_bundles:
                    data = asdict(item)
                    if item.published_at:
                        data['published_at'] = item.published_at.isoformat()
                    self.conn.execute('INSERT OR REPLACE INTO pending_bundles VALUES (?, ?, ?)',
                                      (item.source, item.external_id, json.dumps(data, ensure_ascii=False)))
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
                # прислали повторно (после dedup_days) — новый код и дата, статус отметки сохраняется
                self.conn.execute(
                    "INSERT INTO ledger (dedup_key, title, company, url, source, bucket, reported_at, code) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(dedup_key) DO UPDATE SET url=excluded.url, "
                    "bucket=excluded.bucket, reported_at=excluded.reported_at, code=excluded.code",
                    (r["dedup_key"], r["title"], r.get("company"), r["url"], r["source"], r["bucket"], now,
                     r.get("code")),
                )
            self.conn.executemany("UPDATE ledger SET status=? WHERE code=? AND status IN ('new', 'reviewed')",
                                  [(s, c) for c, s in (marks or {}).items()])
            for code, status in (marks or {}).items():
                if status in ('reviewed', 'applied'):
                    self.conn.execute("UPDATE vacancy_deliveries SET status=? WHERE code=? AND status IN ('new','reviewed')",
                                      (status, code))

    def source_stats(self, days: int = 30) -> list[tuple]:
        """Сколько вакансий каждый источник принёс в дайджест за N дней и сколько из них отмечено
        (для решения, какие каналы держать)."""
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        return self.conn.execute(
            "SELECT source, bucket, COUNT(*) FROM ledger WHERE reported_at >= ? GROUP BY source, bucket "
            "UNION ALL SELECT source, CASE status WHEN 'applied' THEN 'откликнулся' ELSE 'разобрано' END, COUNT(*) "
            "FROM ledger WHERE reported_at >= ? AND status IN ('applied', 'reviewed') GROUP BY source, status "
            "ORDER BY 1", (since, since)
        ).fetchall()

    def sends_in_slot(self, now: datetime, evening_hour: int = 17) -> int:
        """Сколько писем уже ушло в этот выпуск (повторные — через --force)."""
        evening = now.hour >= evening_hour
        rows = self.conn.execute(
            "SELECT started_at FROM runs WHERE run_date=? AND status IN ('sent', 'empty')",
            (now.date().isoformat(),)).fetchall()
        return sum((datetime.fromisoformat(r[0]).hour >= evening_hour) == evening for r in rows)
