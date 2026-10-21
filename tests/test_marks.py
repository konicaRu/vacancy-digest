import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from vd.marks import mark_link, parse_marks
from vd.store import Store

# так выглядит CSV таблицы ответов Google Формы (живая выгрузка 20.10.2026)
SHEET_CSV = ("Отметка времени,id\n"
             "20.10.2026 15:54:58,vd-test-click\n"
             "20.10.2026 15:55:09,vd-20261020-am-7\n"
             "20.10.2026 16:05:03, vd-20261020-am-2 \n"
             "20.10.2026 16:06:00,\n"
             "20.10.2026 16:07:00,vd-20261020-pm-3 · Продуктовый аналитик · Авито\n"
             "20.10.2026 16:08:00,vd-test-preview-1 · Тест\n"
             # «Разобрал группу»: одна строка — все номера группы и их названия
             '20.10.2026 16:09:00,"vd-20261020-am-7,8 · Разобрано · jabka.work: 7. Аналитик А; 8. Аналитик Б"\n')


class ParseMarksTests(unittest.TestCase):
    def test_codes_and_statuses_from_sheet_csv(self):
        self.assertEqual(parse_marks(SHEET_CSV), {
            "vd-20261020-am-7": "applied",   # откликнулся раньше, чем разобрал группу — отклик важнее
            "vd-20261020-am-8": "reviewed",
            "vd-20261020-am-2": "applied",
            "vd-20261020-pm-3": "applied",
        })

    def test_empty_sheet(self):
        self.assertEqual(parse_marks("Отметка времени,id\n"), {})


class MarkLinkTests(unittest.TestCase):
    def test_link_carries_code_and_readable_label(self):
        cfg = {"form_url": "https://f/formResponse", "form_field": "entry.1"}
        link = mark_link(cfg, "vd-20261020-am-7", "Продуктовый аналитик · Авито")
        self.assertTrue(link.startswith("https://f/formResponse?entry.1=vd-20261020-am-7%20%C2%B7%20"))
        self.assertTrue(link.endswith("&submit=Submit"))
        # то, что попадёт в таблицу, читается обратно в тот же код
        value = parse_qs(urlparse(link).query)["entry.1"][0]
        self.assertEqual(parse_marks(f"t,id\nx,{value}\n"), {"vd-20261020-am-7": "applied"})


class StoreMarksTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "s.sqlite")
        rows = [{"dedup_key": f"k{i}", "title": f"Аналитик {i}", "company": "Авито", "url": f"u{i}",
                 "source": "site:jabka", "bucket": "main", "code": f"vd-20261020-am-{i}"} for i in (1, 2, 3)]
        self.store.commit_after_send({}, [], rows)

    def test_pending_then_marked_after_send(self):
        pending = self.store.pending_marks({"vd-20261020-am-2": "applied", "vd-20261020-am-3": "reviewed",
                                            "vd-чужой": "applied"})
        self.assertEqual([(r["title"], r["status"]) for r in pending],
                         [("Аналитик 2", "applied"), ("Аналитик 3", "reviewed")])
        self.store.commit_after_send({}, [], [], marks={r["code"]: r["status"] for r in pending})
        status = dict(self.store.conn.execute("SELECT code, status FROM ledger").fetchall())
        self.assertEqual(status["vd-20261020-am-3"], "reviewed")
        self.assertEqual(self.store.pending_marks({"vd-20261020-am-2": "applied"}), [])  # второй раз не показываем

    def test_marked_never_come_back(self):
        self.store.commit_after_send({}, [], [], marks={"vd-20261020-am-1": "applied", "vd-20261020-am-2": "reviewed"})
        old = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
        self.store.conn.execute("UPDATE ledger SET reported_at=?", (old,))
        keys = {r["dedup_key"] for r in self.store.recent_ledger(30)}
        self.assertEqual(keys, {"k1", "k2"})  # k3 забыт через 30 дней; отмеченные — помним всегда

    def test_reissued_vacancy_gets_new_code(self):
        # вакансию прислали снова через 30+ дней — отметка по новому коду должна сработать
        self.store.commit_after_send({}, [], [{"dedup_key": "k1", "title": "Аналитик 1", "company": "Авито",
                                               "url": "u1", "source": "site:jabka", "bucket": "main",
                                               "code": "vd-20261125-am-4"}])
        self.assertEqual([r["title"] for r in self.store.pending_marks({"vd-20261125-am-4": "applied"})],
                         ["Аналитик 1"])

    def test_stats_show_applied_and_reviewed(self):
        self.store.commit_after_send({}, [], [], marks={"vd-20261020-am-1": "applied", "vd-20261020-am-2": "reviewed"})
        stats = {(s, b): n for s, b, n in self.store.source_stats(30)}
        self.assertEqual(stats[("site:jabka", "main")], 3)
        self.assertEqual(stats[("site:jabka", "откликнулся")], 1)
        self.assertEqual(stats[("site:jabka", "разобрано")], 1)

    def test_resend_codes(self):
        self.assertEqual(parse_marks("t,id\nx,vd-20261021-am2-3 · Аналитик\n"), {"vd-20261021-am2-3": "applied"})

    def test_old_database_gets_code_column(self):
        path = Path(tempfile.mkdtemp()) / "old.sqlite"
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE ledger (dedup_key TEXT PRIMARY KEY, title TEXT, company TEXT, url TEXT, "
                  "source TEXT, bucket TEXT, reported_at TEXT NOT NULL, status TEXT DEFAULT 'new')")
        c.commit()
        c.close()
        Store(path).pending_marks({"x": "applied"})  # не падает: колонка code добавлена


if __name__ == "__main__":
    unittest.main()
