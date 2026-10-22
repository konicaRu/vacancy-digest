"""jabka.work: выдача поиска приходит прямо в HTML.

Фильтры (поиск, удалёнка) зашиты в ссылку из config.yaml.
У каждой вакансии ссылка вида /jobs/<slug>-YYYYMMDD-<код>, из неё берём дату и id.
Закладки по времени нет — новизну определяем по таблице seen.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError, SourceResult

JOB_RE = re.compile(r"/jobs/([a-z0-9\-]+?)-(\d{8})-([a-z0-9]{3,})/?$", re.I)


def parse_page(html: str, base_url: str = "https://jabka.work") -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    items: dict[str, Item] = {}
    for a in soup.select("a[href*='/jobs/']"):
        href = a.get("href", "")
        m = JOB_RE.search(href.split("?")[0])
        if not m:
            continue
        ext_id = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if ext_id in items:
            continue
        text = a.get_text(" | ", strip=True)
        try:
            published = datetime.strptime(m.group(2), "%Y%m%d")
        except ValueError:
            published = None
        # первая «текстовая» часть карточки, не похожая на зарплату, — скорее всего название
        parts = [p.strip() for p in text.split("|") if p.strip()]
        hint = next((p for p in parts if not re.match(r"^[\d\s.,?KkMм₽$£€]+$", p)), None)
        items[ext_id] = Item(
            source="site:jabka",
            kind="site",
            external_id=ext_id,
            url=urljoin(base_url, href),
            text=text,
            published_at=published,
            hint_title=hint,
        )
    return list(items.values())


def collect(
    urls: list[str],
    fetch: Callable[[str], str],
    is_seen: Callable[[str, str], bool],
    first_run: bool,
    lookback_days: int = 3,
    max_pages: int = 10,
    source: str = "site:jabka",
    parse: Callable[[str], list[Item]] = lambda html: parse_page(html),
) -> SourceResult:
    """Листает выдачу (&page=2, 3, …), пока на странице есть свежие непросмотренные карточки:
    на 1-й странице только ~20 карточек за последние сутки, а ~19 удалённых «Аналитиков» выходит в день.
    source/parse — для другого сайта с такой же выдачей (youngjunior.ru)."""
    cutoff = datetime.combine(date.today() - timedelta(days=lookback_days), datetime.min.time())
    collected: dict[str, Item] = {}
    try:
        for url in urls:
            prev_ids: set[str] = set()
            for n in range(1, max_pages + 1):
                page_url = url if n == 1 else f"{url}{'&' if '?' in url else '?'}page={n}"
                page_items = parse(fetch(page_url))
                if not page_items:
                    if n == 1:
                        raise SourceError(f"в выдаче {url} не найдено ни одной вакансии — проверь ссылку или вёрстку сайта")
                    break
                ids = {it.external_id for it in page_items}
                if ids == prev_ids:  # сайт не понял номер страницы и отдал ту же
                    break
                prev_ids = ids
                fresh = False
                for it in page_items:
                    if is_seen(source, it.external_id):
                        continue
                    old = it.published_at is not None and it.published_at < cutoff
                    if old and first_run:
                        continue
                    fresh = fresh or not old
                    collected[it.external_id] = it
                if not fresh:  # дальше только старое или уже виденное (закреплённые старые карточки не мешают)
                    break
    except SourceError as e:
        return SourceResult(source=source, error=str(e))
    except Exception as e:
        return SourceResult(source=source, error=f"{type(e).__name__}: {e}")
    # маркер «источник уже читали» — нужен, чтобы отличать первый запуск
    return SourceResult(source=source, items=list(collected.values()),
                        new_bookmark=datetime.now().isoformat(timespec="seconds"))
