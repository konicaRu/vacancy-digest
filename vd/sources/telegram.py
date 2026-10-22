"""Чтение публичных Telegram-каналов через веб-превью t.me/s/<канал>.

Аккаунт и токены не нужны. Страница отдаёт ~20 последних постов,
более старые — по ссылке ?before=<id>. Закладка = id последнего прочитанного поста.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from bs4 import BeautifulSoup

from ..models import Item, SourceError, SourceResult

log = logging.getLogger(__name__)

BASE = "https://t.me/s/{channel}"


def _text(el) -> str:
    """Текст поста: строки только по <br>, а не по каждому тегу (<b>Senior Data</b> <b>Аналитик</b> — одна строка)."""
    for br in el.find_all("br"):
        br.replace_with("\n")
    lines = (ln.strip() for ln in el.get_text().splitlines())
    # меню канала «Вакансии │ Стажировки │ За рубежом │ Удалёнка │ …» — не текст вакансии («Удалёнка» ≠ формат работы)
    return "\n".join(ln for ln in lines if ln and ln.count("│") < 3)


def parse_page(html: str, channel: str) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[Item] = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        data_post = msg.get("data-post", "")
        try:
            post_id = int(data_post.rsplit("/", 1)[1])
        except (IndexError, ValueError):
            continue
        # основной текст поста (а не цитата из ответа)
        text_el = (msg.select_one(".tgme_widget_message_bubble > .tgme_widget_message_text")
                   or msg.select_one(".tgme_widget_message_text"))
        text = _text(text_el) if text_el else ""
        anchors = [(a["href"], a.get_text(" ", strip=True)) for a in text_el.select("a[href]")] if text_el else []
        links = [h for h, _ in anchors]
        # подборки вида «цитата = вакансия: название, описание, формат, «Откликнуться»» (mtsbankcareer)
        blocks = [(_text(bq), bq.select_one("a[href]")["href"])
                  for bq in (text_el.select("blockquote") if text_el else []) if bq.select_one("a[href]")]
        t = msg.select_one("a.tgme_widget_message_date time[datetime]") or msg.select_one("time[datetime]")
        published = None
        if t is not None:
            try:
                published = datetime.fromisoformat(t["datetime"])
            except ValueError:
                published = None
        items.append(Item(
            source=f"tg:{channel}",
            kind="telegram",
            external_id=str(post_id),
            url=f"https://t.me/{channel}/{post_id}",
            text=text,
            published_at=published,
            links=links,
            anchors=anchors,
            blocks=blocks,
        ))
    return items


def fetch_single(channel: str, post_id: str, fetch: Callable[[str], str]) -> Optional[Item]:
    """Один пост по ссылке t.me/<канал>/<id> через виджет встраивания (та же вёрстка, что у t.me/s)."""
    html = fetch(f"https://t.me/{channel}/{post_id}?embed=1&mode=tme")
    items = parse_page(html, channel)
    exact = next((i for i in items if i.external_id == str(post_id)), None)
    if exact:
        return exact
    if items:
        return items[0]
    # запасной вариант: в виджете нет data-post — берём текст напрямую
    soup = BeautifulSoup(html, "html.parser")
    text_el = soup.select_one(".tgme_widget_message_text")
    if not text_el:
        return None
    return Item(source=f"tg:{channel}", kind="telegram", external_id=str(post_id),
                url=f"https://t.me/{channel}/{post_id}", text=_text(text_el),
                anchors=[(a["href"], a.get_text(" ", strip=True)) for a in text_el.select("a[href]")])


def collect(
    channel: str,
    bookmark: Optional[str],
    fetch: Callable[[str], str],
    lookback_days: int = 3,
    max_pages: int = 5,
) -> SourceResult:
    """Собирает все посты новее закладки. При ошибке — SourceResult с error и без новой закладки."""
    source = f"tg:{channel}"
    last_id = int(bookmark) if bookmark else None
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    found: dict[int, Item] = {}
    max_seen: Optional[int] = None
    before: Optional[int] = None
    warning: Optional[str] = None

    try:
        for page in range(max_pages):
            url = BASE.format(channel=channel) + (f"?before={before}" if before else "")
            posts = parse_page(fetch(url), channel)
            if not posts:
                if page == 0:
                    raise SourceError("страница канала пустая — канал закрыт или изменилась вёрстка")
                break
            ids = [int(p.external_id) for p in posts]
            max_seen = max(ids + ([max_seen] if max_seen else []))
            for p in posts:
                pid = int(p.external_id)
                if last_id is not None and pid <= last_id:
                    continue
                if last_id is None and p.published_at and p.published_at < cutoff:
                    continue
                found[pid] = p
            oldest_id = min(ids)
            oldest_date = min((p.published_at for p in posts if p.published_at), default=None)
            if last_id is not None and oldest_id <= last_id + 1:
                break
            if last_id is None and (oldest_date is None or oldest_date < cutoff):
                break
            before = oldest_id
        else:
            warning = f"больше {max_pages} страниц новых постов — часть старых пропущена (закладка перепрыгнула)"
            log.warning("%s: %s", channel, warning)
    except SourceError as e:
        return SourceResult(source=source, error=str(e))
    except Exception as e:  # сеть, таймаут, 4xx/5xx
        return SourceResult(source=source, error=f"{type(e).__name__}: {e}")

    new_bookmark = str(max(max_seen, last_id or 0)) if max_seen else bookmark
    items = [found[k] for k in sorted(found)]
    return SourceResult(source=source, items=items, new_bookmark=new_bookmark, warning=warning)
