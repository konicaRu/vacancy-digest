import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import main
from tests.fixtures import JABKA_HTML, NOW, POST_TEXTS, tg_page, tg_post
from vd import mailer
from vd.llm import LMStudioClient
from vd.models import Item, SourceResult
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


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy(PROJECT / "config.yaml", self.tmp / "config.yaml")
        (self.tmp / "secrets.env").write_text("EMAIL_USER=me@example.com\nEMAIL_APP_PASSWORD=abcd efgh\n", encoding="utf-8")
        self.patches = [mock.patch.object(main, "ROOT", self.tmp)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, *argv, results=None, send=None):
        args = main.argparse.Namespace(dry_run="--dry-run" in argv, force="--force" in argv,
                                       no_llm=True, stats=False)
        def offline_fetch(url):
            raise ConnectionError("нет сети в тестах")

        with mock.patch.object(main, "collect_all", return_value=results or fake_results()), \
             mock.patch.object(main, "make_fetcher", return_value=offline_fetch), \
             mock.patch.object(mailer, "send", side_effect=send or (lambda *a, **k: "<id@x>")) as m:
            code = main.run(args)
        return code, m

    def test_dry_run_changes_nothing(self):
        code, m = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        m.assert_not_called()
        store = Store(self.tmp / "data" / "state.sqlite")
        self.assertIsNone(store.get_bookmark("tg:nodatanojobs"))
        html = next((self.tmp / "out").glob("digest_*.html")).read_text(encoding="utf-8")
        self.assertIn("VK Видео", html)
        self.assertIn("Формат не указан", html)
        self.assertNotIn("MAXLINE", html)          # junior отсеян
        self.assertNotIn("Подборка актуальных", html)

    def test_send_commits_state_and_second_run_skips(self):
        code, m = self.run_main()
        self.assertEqual(code, 0)
        m.assert_called_once()
        subject = m.call_args.args[1]
        self.assertIn("подходят", subject)
        store = Store(self.tmp / "data" / "state.sqlite")
        self.assertEqual(store.get_bookmark("tg:nodatanojobs"), "105")
        self.assertTrue(store.is_seen("tg:nodatanojobs", "100"))
        self.assertTrue(store.sent_today())
        # второй запуск в тот же день — без письма
        code2, m2 = self.run_main()
        self.assertEqual(code2, 0)
        m2.assert_not_called()
        # --force: всё уже было отправлено → только «новых нет»
        code3, m3 = self.run_main("--force")
        self.assertIn("новых нет", m3.call_args.args[1])

    def test_failed_send_keeps_state(self):
        def boom(*a, **k):
            raise mailer.SendError("auth failed")
        code, _ = self.run_main(send=boom)
        self.assertEqual(code, 1)
        store = Store(self.tmp / "data" / "state.sqlite")
        self.assertIsNone(store.get_bookmark("tg:nodatanojobs"))
        self.assertFalse(store.is_seen("tg:nodatanojobs", "100"))
        self.assertFalse(store.sent_today())

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
