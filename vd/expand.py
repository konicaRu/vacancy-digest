"""Разворачивание постов-подборок в отдельные вакансии.

Подборка — пост, где несколько ссылок с названиями должностей:
  • недельные «Подборка актуальных вакансий за неделю» (ссылки на посты канала);
  • «Подборка вакансий аналитиков в Uzum / OTP» (ссылки на hh, сайт компании, LinkedIn).

Каждая ссылка-должность становится отдельным элементом:
  • ссылка на пост Telegram — пропускаем, если этот пост уже видели (в этом запуске или раньше),
    иначе забираем полный текст поста;
  • любая другая ссылка — берём название из текста ссылки, а условия (локация, формат) —
    из самого поста-подборки.
Сам пост-подборка в письмо не попадает, его заменяют найденные вакансии.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from .models import Item

log = logging.getLogger(__name__)

TME_POST = re.compile(r"^https?://t\.me/(?!s/)([A-Za-z0-9_]{4,})/(\d+)/?(?:\?.*)?$")
ROLE_WORDS = re.compile(r"аналитик|analyst|analytics|аналитика", re.I)


def role_anchors(item: Item) -> list[tuple[str, str]]:
    """Ссылки, текст которых похож на должность (без хештегов, ботов и подписей канала)."""
    out, seen = [], set()
    for href, text in item.anchors:
        t = (text or "").strip()
        if not t or t.startswith("#") or t.startswith("@"):
            continue
        # хештеги канала (t.me/s/...?q=) и ссылки на ботов (?start=) — не вакансии
        if href.startswith(("https://t.me/s/", "http://t.me/s/")) or "?start=" in href or href in seen:
            continue
        if ROLE_WORDS.search(t):
            out.append((href, t))
            seen.add(href)
    return out


def is_bundle(item: Item) -> bool:
    return item.kind == "telegram" and len(role_anchors(item)) >= 2


def expand_bundles(
    items: list[Item],
    is_seen: Callable[[str, str], bool],
    fetch_post: Callable[[str, str], Optional[Item]],
    max_fetch: int = 30,
) -> tuple[list[Item], dict]:
    info = {"bundles": 0, "links": 0, "new": 0, "known": 0, "fetched": 0, "fetch_failed": 0}
    current = {(it.source, it.external_id) for it in items}
    taken: set[tuple[str, str]] = set()
    out: list[Item] = []

    for it in items:
        if not is_bundle(it):
            out.append(it)
            continue
        info["bundles"] += 1
        for href, title in role_anchors(it):
            info["links"] += 1
            m = TME_POST.match(href)
            if m:
                ch, pid = m.group(1), m.group(2)
                key = (f"tg:{ch}", pid)
                if key in current or key in taken or is_seen(*key):
                    info["known"] += 1
                    continue
                taken.add(key)
                child = None
                if info["fetched"] < max_fetch:
                    try:
                        child = fetch_post(ch, pid)
                        info["fetched"] += 1
                    except Exception as e:
                        info["fetch_failed"] += 1
                        log.warning("Не открылся пост из подборки %s: %s", href, e)
                if child is None or not (child.text or "").strip():
                    child = Item(source=f"tg:{ch}", kind="telegram", external_id=pid,
                                 url=f"https://t.me/{ch}/{pid}", text=title, hint_title=title)
                child.via = it.source
                out.append(child)
                info["new"] += 1
            else:
                url = href.split("#")[0]
                key = (it.source, url)
                if key in taken or is_seen(*key):
                    info["known"] += 1
                    continue
                taken.add(key)
                text = (f"Вакансия: {title}\nСсылка: {url}\n---\n"
                        f"Контекст (пост-подборка, где была ссылка):\n{(it.text or '')[:1500]}")
                out.append(Item(source=it.source, kind="digest_link", external_id=url, url=url,
                                text=text, hint_title=title, published_at=it.published_at, via=it.source))
                info["new"] += 1
    return out, info
