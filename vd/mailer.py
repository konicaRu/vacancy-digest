"""Отправка письма.

Python ходит в интернет через VPN (Browsec: иначе Telegram заблокирован), а VPN закрывает почтовые порты (26.10.2026).
Поэтому на Windows письмо отправляет системный curl.exe — его нет в списке программ VPN, он идёт напрямую.
Пароль передаётся curl через stdin (конфиг), а не в командной строке — её видно в списке процессов.
Без curl.exe (не Windows) — smtplib.
"""
from __future__ import annotations

import os
import smtplib
import subprocess
import tempfile
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Optional


class SendError(Exception):
    pass


def _curl_path() -> Optional[str]:
    path = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "curl.exe"
    return str(path) if path.exists() else None


def _curl_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _send_curl(curl: str, preset: dict, user: str, password: str, to: str, msg: EmailMessage) -> None:
    fd, path = tempfile.mkstemp(suffix=".eml")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(msg.as_bytes())
        args = [curl, "--silent", "--show-error", "--ssl-reqd", "--connect-timeout", "30", "--max-time", "120",
                f"smtps://{preset['smtp']}:{preset['smtp_port']}",
                "--mail-from", user, "--mail-rcpt", to, "--upload-file", path, "--config", "-"]
        r = subprocess.run(args, input=f"user = {_curl_quote(user + ':' + password)}\n",
                           capture_output=True, text=True, timeout=180)
    finally:
        Path(path).unlink(missing_ok=True)
    if r.returncode == 67:
        raise SendError(f"Почта не приняла логин/пароль приложения: {r.stderr.strip()}")
    if r.returncode != 0:
        raise SendError(f"curl (код {r.returncode}): {r.stderr.strip() or 'без описания'}")


def send(mail_cfg: dict, subject: str, html: str, text: str) -> str:
    """Отправляет письмо. Возвращает Message-ID; считается отправленным, только если сервер принял адресата
    (curl возвращает ошибку, если сервер отклонил адресата или само письмо)."""
    user, password = mail_cfg.get("user"), mail_cfg.get("password")
    if not user or not password:
        raise SendError("В secrets.env не заданы EMAIL_USER / EMAIL_APP_PASSWORD")
    msg = EmailMessage()
    msg["Subject"] = f'{mail_cfg.get("subject_prefix", "Вакансии")} {subject}'
    msg["From"] = user
    msg["To"] = mail_cfg["to"]
    msg_id = make_msgid(domain=user.split("@")[-1])
    msg["Message-ID"] = msg_id
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    preset = mail_cfg["preset"]

    curl = _curl_path()
    if curl:
        _send_curl(curl, preset, user, password, mail_cfg["to"], msg)
        return msg_id

    try:
        with smtplib.SMTP_SSL(preset["smtp"], preset["smtp_port"], timeout=60) as smtp:
            smtp.login(user, password)
            refused = smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise SendError(f"Почта не приняла логин/пароль приложения: {e}") from e
    except Exception as e:
        raise SendError(f"{type(e).__name__}: {e}") from e
    if refused:
        raise SendError(f"Сервер отклонил адресатов: {refused}")
    return msg_id
