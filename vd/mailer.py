from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import make_msgid


class SendError(Exception):
    pass


def send(mail_cfg: dict, subject: str, html: str, text: str) -> str:
    """Отправляет письмо. Возвращает Message-ID; считается отправленным, только если сервер принял адресата."""
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
