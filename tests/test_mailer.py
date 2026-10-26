"""Отправка письма через curl.exe: Python ходит через VPN (Browsec), а VPN закрывает почтовые порты (26.10.2026),
curl.exe в список VPN не входит и отправляет напрямую."""
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from vd import mailer

CFG = {"user": "me@ya.ru", "password": "app-pass\"x", "to": "me@ya.ru", "subject_prefix": "Вакансии",
       "preset": {"smtp": "smtp.yandex.ru", "smtp_port": 465}}


class CurlSendTests(unittest.TestCase):
    def run_send(self, returncode=0, stderr=""):
        seen = {}

        def fake_run(args, input, capture_output, text, timeout):
            seen["args"], seen["stdin"] = args, input
            seen["message"] = Path(args[args.index("--upload-file") + 1]).read_bytes()
            return subprocess.CompletedProcess(args, returncode, "", stderr)

        with mock.patch.object(mailer, "_curl_path", return_value="C:/Windows/System32/curl.exe"), \
             mock.patch.object(mailer.subprocess, "run", side_effect=fake_run):
            msg_id = mailer.send(CFG, "26.10 вечер: 2 подходят", "<p>письмо</p>", "письмо")
        return msg_id, seen

    def test_sends_through_curl_with_password_on_stdin(self):
        msg_id, seen = self.run_send()
        args = seen["args"]
        self.assertEqual(args[0], "C:/Windows/System32/curl.exe")
        self.assertIn("smtps://smtp.yandex.ru:465", args)
        self.assertEqual(args[args.index("--mail-from") + 1], "me@ya.ru")
        self.assertEqual(args[args.index("--mail-rcpt") + 1], "me@ya.ru")
        self.assertNotIn("app-pass", " ".join(args))          # пароля нет в командной строке (виден в списке процессов)
        self.assertIn('user = "me@ya.ru:app-pass\\"x"', seen["stdin"])  # он в конфиге curl через stdin, кавычка экранирована
        self.assertIn(b"Subject:", seen["message"])
        self.assertTrue(msg_id.startswith("<") and msg_id.endswith("@ya.ru>"))

    def test_wrong_password_is_explained(self):
        with self.assertRaises(mailer.SendError) as e:
            self.run_send(returncode=67, stderr="curl: (67) Login denied")
        self.assertIn("логин/пароль приложения", str(e.exception))

    def test_other_curl_error(self):
        with self.assertRaises(mailer.SendError) as e:
            self.run_send(returncode=28, stderr="curl: (28) Connection timed out")
        self.assertIn("curl", str(e.exception))

    def test_message_file_is_removed(self):
        _, seen = self.run_send()
        files = [a for a in seen["args"] if a.endswith(".eml")]
        self.assertTrue(files and not Path(files[0]).exists())


if __name__ == "__main__":
    unittest.main()
