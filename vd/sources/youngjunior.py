"""youngjunior.ru: выдача разделов (/data-analyst/jobs, /product-analyst/jobs) приходит в HTML.

Сайт «junior и без опыта», но вакансии без метки грейда бывают и middle (Циан, опыт от 3 лет).
Метка junior/intern в карточке → Item.grade_hint → отсев; формат («удалёнка» / «в офис» / «стажировка»)
попадает в текст и разбирается как обычно. Листание и «свежесть» — как у jabka.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceResult
from . import jabka

SOURCE = "site:youngjunior"
BASE = "https://youngjunior.ru"
MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9,
          "окт": 10, "ноя": 11, "дек": 12}
GRADES = {"junior": "junior", "intern": "intern", "middle": "middle", "senior": "senior", "lead": "lead"}


def parse_date(text: str, today: date) -> Optional[datetime]:
    """«сегодня», «вчера», «3 дня назад», «5 окт» → дата; непонятное — None."""
    t = text.strip().lower()
    if t == "сегодня":
        d = today
    elif t == "вчера":
        d = today - timedelta(days=1)
    elif m := re.match(r"(\d+)\s+д\w*\s+назад", t):
        d = today - timedelta(days=int(m.group(1)))
    elif (m := re.match(r"(\d{1,2})\s+([а-я]{3})", t)) and m.group(2) in MONTHS:
        d = date(today.year, MONTHS[m.group(2)], int(m.group(1)))
        if d > today:  # «28 дек» в январе — прошлый год
            d = d.replace(year=today.year - 1)
    else:
        return None
    return datetime.combine(d, datetime.min.time())


def parse_page(html: str, today: Optional[date] = None) -> list[Item]:
    today = today or date.today()
    items: dict[str, Item] = {}
    for art in BeautifulSoup(html, "html.parser").select("article"):
        a = art.select_one("a[href*='/jobs/']")
        if a is None:
            continue
        href = str(a.get("href", ""))
        m = re.search(r"/jobs/(\d+)$", href)
        h3 = a.select_one("h3")
        if not (m and h3):
            continue
        title = h3.get_text(" ", strip=True)
        meta = [s.get_text(strip=True) for s in a.select("div span") if s.get_text(strip=True) not in ("", "·")]
        grade = next((GRADES[x.lower()] for x in meta if x.lower() in GRADES), None)
        fmt = meta[0] if meta else ""
        if fmt.lower() == "стажировка":
            grade = grade or "intern"
        company_el = art.select_one("b")
        company = company_el.get_text(strip=True) if company_el else ""
        city_el = company_el.find_next_sibling("span") if company_el else None
        city = city_el.get_text(strip=True) if city_el else ""
        date_el = art.select_one("span.whitespace-nowrap")
        text = " | ".join(p for p in (title, *meta, f"@{company}" if company else "", city) if p)
        items[m.group(1)] = Item(source=SOURCE, kind="site", external_id=m.group(1), url=urljoin(BASE, href),
                                 text=text, hint_title=title, grade_hint=grade,
                                 published_at=parse_date(date_el.get_text(strip=True), today) if date_el else None)
    return list(items.values())


def collect(urls: list[str], fetch: Callable[[str], str], is_seen: Callable[[str, str], bool],
            first_run: bool, lookback_days: int = 3, max_pages: int = 10) -> SourceResult:
    return jabka.collect(urls, fetch, is_seen, first_run, lookback_days, max_pages, source=SOURCE, parse=parse_page)
