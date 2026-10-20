import json
from datetime import datetime
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import quote
from unittest import mock

import main
from tests.fixtures import JABKA_HTML, NOW, POST_TEXTS, tg_page, tg_post
from vd import digest, mailer
from vd.llm import LMStudioClient
from vd.models import Item, SourceResult, Verdict
from vd.sources import jabka, telegram
from vd.store import Store

PROJECT = Path(__file__).resolve().parent.parent


def fake_results(fail_jabka=False):
    channel = "nodatanojobs"
    posts = [tg_post(channel, 100 + i, POST_TEXTS[k], NOW)
             for i, k in enumerate(["vk", "aihr", "junior", "digest", "nofmt", "vv_product"])]
    tg_items = telegram.parse_page(tg_page(channel, posts), channel)
    other = "careerstation_analyst"
    cs_items = telegram.parse_page(tg_page(other, [tg_post(other, 7, POST_TEXTS["vv_product"], NOW),
                                                    tg_post(other, 140, POST_TEXTS["weekly"], NOW)]), other)
    res = [
        SourceResult(source=f"tg:{channel}", items=tg_items, new_bookmark="105"),
        SourceResult(source=f"tg:{other}", items=cs_items, new_bookmark="7"),
        SourceResult(source="tg:HR_CATExpert", items=[], new_bookmark="257"),
    ]
    if fail_jabka:
        res.append(SourceResult(source="site:jabka", error="ConnectionError: timeout"))
    else:
        res.append(SourceResult(source="site:jabka", items=jabka.parse_page(JABKA_HTML), new_bookmark="x"))
    return res


class LLMBannerTests(unittest.TestCase):
    BANNER = "Локальная модель была недоступна"

    def test_no_banner_when_llm_switched_off_on_purpose(self):
        _, html, _ = digest.build([], {}, {}, {"llm_used": False, "llm_failed": False, "llm_off": True})
        self.assertNotIn(self.BANNER, html)

    def test_banner_when_llm_wanted_but_unavailable(self):
        _, html, _ = digest.build([], {}, {}, {"llm_used": False, "llm_failed": False, "llm_off": False})
        self.assertIn(self.BANNER, html)


class SourceStatsTests(unittest.TestCase):
    def test_empty_source_and_nothing_found_are_said_in_words(self):
        found = Item(source="tg:c", kind="telegram", external_id="1", url="u", text="t")
        verdicts = [Verdict(item=found, is_vacancy=True, title="Продуктовый аналитик", bucket="main")]
        read = {"tg:a": 0, "tg:b": 5, "tg:c": 3}
        _, html, text = digest.build(verdicts, read, {}, {"llm_off": True})
        self.assertIn("новых постов нет", html)        # tg:a — канал молчал
        self.assertIn("подходящих не найдено", html)   # tg:b — посты были, вакансий нет
        for line in ("TG · a: новых постов нет", "TG · b: новых 5, подходящих не найдено", "TG · c: новых 3, в письме 1"):
            self.assertIn(line, text)


class ApplyLinkTests(unittest.TestCase):
    def test_vacancies_numbered_and_reply_link_prefilled(self):
        def v(title, bucket, i):
            item = Item(source="site:jabka", kind="site", external_id=str(i), url=f"https://jabka.work/jobs/{i}", text=title)
            return Verdict(item=item, is_vacancy=True, title=title, bucket=bucket)
        verdicts = [v("Аналитик А", "unknown_format", 1), v("Аналитик Б", "main", 2), v("Аналитик В", "main", 3)]
        marked = [{"code": "vd-20261019-pm-4", "title": "Аналитик Авито", "company": "Авито", "status": "applied"},
                  {"code": "vd-20261019-pm-5", "title": "Аналитик X", "company": None, "status": "reviewed"}]
        subject, html, text = digest.build(verdicts, {"site:jabka": 3}, {}, {"llm_off": True},
                                           tag="vd-20261020-am", mark_link=lambda c, label: f"https://form?id={c}",
                                           marked=marked)
        # сквозная нумерация: сначала «Подходят», потом «Формат не указан»
        self.assertEqual([(x.title, x.num) for x in verdicts], [("Аналитик А", 3), ("Аналитик Б", 1), ("Аналитик В", 2)])
        self.assertIn("1. Аналитик Б", text)
        self.assertIn("3. Аналитик А", text)
        self.assertIn('href="https://form?id=vd-20261020-am-1"', html)  # «Откликнулся» под вакансией №1
        self.assertIn("Откликнулся", html)
        self.assertIn("Отмечено откликов: 1", html)
        self.assertIn("Аналитик Авито", html)
        self.assertIn("разобрано: 1", html)

    def test_grouped_by_source_with_review_group_link(self):
        def v(title, bucket, source, via=None):
            item = Item(source=source, kind="site", external_id=title, url=f"https://x/{title}", text=title, via=via)
            return Verdict(item=item, is_vacancy=True, title=title, bucket=bucket)
        verdicts = [v("J-уточнить", "unknown_format", "site:jabka"), v("J-подходит", "main", "site:jabka"),
                    v("C-1", "main", "tg:careerstation_analyst"),
                    v("C-2 из подборки", "main", "tg:careerstation_pm", via="tg:careerstation_analyst")]
        calls = []

        def link(code, label):
            calls.append((code, label))
            return f"https://form?id={code}"
        _, html, text = digest.build(verdicts, {}, {}, {"llm_off": True}, tag="vd-20261020-am", mark_link=link)
        # группы: сначала источник, где больше подходящих; вакансия из подборки — в группе канала-подборки
        self.assertEqual([(x.title, x.num) for x in verdicts],
                         [("J-уточнить", 4), ("J-подходит", 3), ("C-1", 1), ("C-2 из подборки", 2)])
        self.assertLess(html.index("TG · careerstation_analyst"), html.index("jabka.work"))
        self.assertIn("== TG · careerstation_analyst (2) ==", text)
        self.assertIn("== jabka.work (2) ==", text)
        # под группой — «Разобрал группу»: одна строка в таблице со всеми номерами и названиями
        self.assertIn(("vd-20261020-am-1,2", "Разобрано · TG · careerstation_analyst: 1. C-1; 2. C-2 из подборки"), calls)
        self.assertIn("Разобрал группу (2)", html)

    def test_huge_group_label_is_shortened(self):
        long = "Очень длинное название вакансии продуктового аналитика " * 2
        verdicts = [Verdict(item=Item(source="site:jabka", kind="site", external_id=str(i), url="u", text="t"),
                            is_vacancy=True, title=f"{long}{i}", bucket="main") for i in range(60)]
        labels = []
        digest.build(verdicts, {}, {}, {"llm_off": True}, tag="vd-20261020-am",
                     mark_link=lambda c, label: labels.append(label) or "u")
        group = [lab for lab in labels if lab.startswith("Разобрано")][0]
        self.assertLess(len(quote(group)), 6000)  # ссылка не разрастается
        self.assertIn("и ещё", group)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy(PROJECT / "config.yaml", self.tmp / "config.yaml")
        (self.tmp / "secrets.env").write_text("EMAIL_USER=me@example.com\nEMAIL_APP_PASSWORD=abcd efgh\n", encoding="utf-8")
        self.marks_csv = "Отметка времени,id\n"
        self.patches = [mock.patch.object(main, "ROOT", self.tmp)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, *argv, results=None, send=None, at=None):
        args = main.argparse.Namespace(dry_run="--dry-run" in argv, force="--force" in argv,
                                       no_llm=True, stats=False)
        def offline_fetch(url):
            if "docs.google.com/spreadsheets" in url and self.marks_csv is not None:
                return self.marks_csv
            raise ConnectionError("нет сети в тестах")

        with mock.patch.object(main, "_now", return_value=at or datetime.now()),              mock.patch.object(main, "collect_all", return_value=results or fake_results()), \
             mock.patch.object(main, "make_fetcher", return_value=offline_fetch), \
             mock.patch.object(mailer, "send", side_effect=send or (lambda *a, **k: "<id@x>")) as m:
            code = main.run(args)
        return code, m

    def test_applied_link_mark_and_confirmation(self):
        code, m = self.run_main()
        html = m.call_args.args[2]
        store = Store(self.tmp / "data" / "state.sqlite")
        row = store.conn.execute("SELECT code, title FROM ledger WHERE code LIKE '%-1'").fetchone()
        mark_code, title = row
        self.assertRegex(mark_code, r"^vd-\d{8}-(am|pm)-1$")
        # под вакансией — ссылка на форму с её кодом
        self.assertIn(f"formResponse?entry.536851866={mark_code}%20%C2%B7%20", html)  # код · название
        self.assertIn("Откликнулся", html)
        # я нажал ссылку → код появился в таблице → пробный прогон показывает, но не меняет
        self.marks_csv = f"Отметка времени,id\n20.10.2026 16:00:00,{mark_code}\n"
        _, m2 = self.run_main("--force", "--dry-run")
        self.assertEqual(store.conn.execute("SELECT status FROM ledger WHERE code=?", (mark_code,)).fetchone()[0], "new")
        # настоящий прогон: подтверждение в письме и статус applied
        _, m3 = self.run_main("--force")
        self.assertIn("Отмечено откликов: 1", m3.call_args.args[2])
        self.assertIn(title, m3.call_args.args[2])
        self.assertEqual(store.conn.execute("SELECT status FROM ledger WHERE code=?", (mark_code,)).fetchone()[0], "applied")
        # следующий выпуск уже не повторяет подтверждение
        _, m4 = self.run_main("--force")
        self.assertNotIn("Отмечено откликов", m4.call_args.args[2])

    def test_marks_sheet_unavailable_is_flagged_not_fatal(self):
        self.marks_csv = None  # таблица не открылась
        code, m = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Отметки откликов", m.call_args.args[2])

    def test_dry_run_changes_nothing(self):
        code, m = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        m.assert_not_called()
        store = Store(self.tmp / "data" / "state.sqlite")
        self.assertIsNone(store.get_bookmark("tg:nodatanojobs"))
        html = next((self.tmp / "out").glob("digest_*.html")).read_text(encoding="utf-8")
        self.assertIn("VK Видео", html)
        self.assertIn("формат не указан", html)    # вакансия без формата — в письме (оранжевая карточка)
        self.assertNotIn("MAXLINE", html)          # junior отсеян
        self.assertNotIn("Подборка актуальных", html)

    def test_send_commits_state_and_second_run_skips(self):
        at = datetime(2026, 10, 20, 9, 30)
        code, m = self.run_main(at=at)
        self.assertEqual(code, 0)
        m.assert_called_once()
        subject = m.call_args.args[1]
        self.assertIn("подходят", subject)
        store = Store(self.tmp / "data" / "state.sqlite")
        self.assertEqual(store.get_bookmark("tg:nodatanojobs"), "105")
        self.assertTrue(store.is_seen("tg:nodatanojobs", "100"))
        self.assertTrue(store.sent_in_slot(at))
        # второй запуск в тот же выпуск — без письма
        code2, m2 = self.run_main(at=at.replace(hour=11))
        self.assertEqual(code2, 0)
        m2.assert_not_called()
        # --force: всё уже было отправлено → только «новых нет»
        code3, m3 = self.run_main("--force", at=at.replace(hour=12))
        self.assertIn("новых нет", m3.call_args.args[1])

    def test_morning_and_evening_issues(self):
        day = datetime(2026, 10, 20)
        sent = lambda h, m=0, d=day: self.run_main(at=d.replace(hour=h, minute=m))[1]
        first = sent(9, 30)
        self.assertIn("20.10 утро", first.call_args.args[1])
        sent(12).assert_not_called()                     # утро уже было
        evening = sent(17, 5)                            # вечерний выпуск — только новое после утра
        self.assertIn("20.10 вечер", evening.call_args.args[1])
        self.assertIn("новых нет", evening.call_args.args[1])
        sent(18).assert_not_called()                     # вечер уже был
        self.assertIn("21.10 утро", sent(9, 10, datetime(2026, 10, 21)).call_args.args[1])
        # коды вакансий — по выпуску: утреннее письмо 20.10 → vd-20261020-am-N
        store = Store(self.tmp / "data" / "state.sqlite")
        codes = [r[0] for r in store.conn.execute("SELECT code FROM ledger")]
        self.assertTrue(codes and all(c.startswith("vd-20261020-am-") for c in codes))

    def test_failed_send_keeps_state(self):
        def boom(*a, **k):
            raise mailer.SendError("auth failed")
        code, _ = self.run_main(send=boom)
        self.assertEqual(code, 1)
        store = Store(self.tmp / "data" / "state.sqlite")
        self.assertIsNone(store.get_bookmark("tg:nodatanojobs"))
        self.assertFalse(store.is_seen("tg:nodatanojobs", "100"))
        self.assertFalse(store.sent_in_slot(datetime.now()))

    def test_failed_source_flagged_and_bookmark_kept(self):
        code, m = self.run_main(results=fake_results(fail_jabka=True))
        subject, html = m.call_args.args[1], m.call_args.args[2]
        self.assertIn("не прочитано источников: 1", subject)
        self.assertIn("Не удалось прочитать", html)
        store = Store(self.tmp / "data" / "state.sqlite")
        self.assertIsNone(store.get_bookmark("site:jabka"))
        self.assertEqual(store.get_bookmark("tg:nodatanojobs"), "105")


class FakeLMStudio(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"qwen"}]}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLMStudio.requests.append(body)
        answer = {"is_vacancy": True, "title": "Product Analyst", "company": "VK Видео",
                  "role": "product_analyst", "grade": "middle", "remote_from_russia": "yes",
                  "salary": "", "contact": "@hehircatt", "reason": "Продуктовая аналитика, удалёнка по РФ"}
        content = "<think>размышляю</think>" + json.dumps(answer, ensure_ascii=False)
        payload = {"choices": [{"message": {"content": content}}]}
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LLMClientTests(unittest.TestCase):
    def test_request_and_parse(self):
        srv = HTTPServer(("127.0.0.1", 0), FakeLMStudio)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            cfg = {"base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "qwen", "autostart_server": False}
            client = LMStudioClient(cfg, "Продуктовый аналитик")
            self.assertTrue(client.ensure_server())
            item = Item(source="tg:x", kind="telegram", external_id="1", url="u", text="Product Analyst в VK")
            v = client.classify(item)
        finally:
            srv.shutdown()
        self.assertTrue(v.by_llm)
        self.assertEqual((v.company, v.remote_from_russia, v.contact), ("VK Видео", "yes", "@hehircatt"))
        req = FakeLMStudio.requests[-1]
        self.assertEqual(req["model"], "qwen")
        self.assertEqual(req["response_format"]["type"], "json_schema")
        self.assertIn("Продуктовый аналитик", req["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
