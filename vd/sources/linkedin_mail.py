"""Уведомления LinkedIn из почты (IMAP, только чтение — письма не помечаются прочитанными).

Два типа элементов:
  linkedin_job  — вакансии из подписки (ссылки /jobs/view/<id>)
  linkedin_post — посты людей, на которых включён колокольчик (ссылки на activity/posts)

Вёрстка писем LinkedIn меняется, поэтому парсер намеренно простой:
ищем ссылки и берём текст вокруг них. После первых реальных писем его стоит подогнать.
"""
from __future__ import annotations

import email
import imaplib
import re
from datetime import date, timedelta
from email.header import decode_header, make_header
from typing import Optional

from bs4 import BeautifulSoup

from ..models import Item, SourceResult

JOB_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)")
POST_RE = re.compile(r"linkedin\.com/(?:comm/)?(?:feed/update/urn:li:activity:(\d+)|posts/[^\s\"'?]*?(\d{15,}))")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def imap_date(d: date) -> str:
    # strftime("%b") на русской Windows даст «окт», IMAP такого не поймёт
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _html_of(msg: email.message.Message) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def _context_text(a, limit: int = 500) -> str:
    """Текст ссылки плюс ближайший блок-родитель (ячейка таблицы письма)."""
    node = a
    for _ in range(4):
        if node.parent is None:
            break
        node = node.parent
        if node.name in ("td", "tr", "table") and len(node.get_text(" ", strip=True)) > 40:
            break
    return node.get_text(" | ", strip=True)[:limit]


def parse_email(subject: str, html: str, uid: str) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    items: dict[str, Item] = {}
    for a in soup.select("a[href]"):
        href = a["href"]
        jm = JOB_RE.search(href)
        if jm:
            job_id = jm.group(1)
            key = f"job:{job_id}"
            if key not in items:
                items[key] = Item(
                    source="linkedin", kind="linkedin_job", external_id=key,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                    text=f"{_context_text(a)}",
                    hint_title=a.get_text(" ", strip=True) or None,
                )
            continue
        pm = POST_RE.search(href)
        if pm:
            post_id = pm.group(1) or pm.group(2)
            key = f"post:{post_id}"
            if key not in items:
                items[key] = Item(
                    source="linkedin", kind="linkedin_post", external_id=key,
                    url=href.split("?")[0],
                    text=f"Тема письма: {subject}\n{_context_text(a, 800)}",
                )
    return list(items.values())


def collect(cfg: dict, mail_cfg: dict, bookmark: Optional[str]) -> SourceResult:
    source = "linkedin"
    last_uid = int(bookmark) if bookmark else None
    since = date.today() - timedelta(days=cfg.get("lookback_days_first_run", 2) if last_uid is None else 14)
    try:
        M = imaplib.IMAP4_SSL(mail_cfg["preset"]["imap"], 993, timeout=30)
        M.login(mail_cfg["user"], mail_cfg["password"])
        M.select("INBOX", readonly=True)
        typ, data = M.uid("search", None, f'(FROM "{cfg.get("from_filter", "linkedin.com")}" SINCE {imap_date(since)})')
        uids = [int(u) for u in (data[0] or b"").split()] if typ == "OK" else []
        if last_uid is not None:
            uids = [u for u in uids if u > last_uid]
        items: list[Item] = []
        for uid in uids:
            typ, msg_data = M.uid("fetch", str(uid), "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            items.extend(parse_email(_decode(msg.get("Subject")), _html_of(msg), str(uid)))
        M.logout()
    except Exception as e:
        return SourceResult(source=source, error=f"{type(e).__name__}: {e}")
    new_bm = str(max(uids)) if uids else bookmark
    return SourceResult(source=source, items=items, new_bookmark=new_bm)
