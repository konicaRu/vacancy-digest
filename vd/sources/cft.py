"""ЦФТ (job.cft.ru): все вакансии — блок данных Next.js главной страницы; формат — текстом карточки."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:cft'


def _clean(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _name(node, key) -> str:
    return _clean((((node or {}).get('data') or {}).get('attributes') or {}).get(key))


def _next_data(html: str) -> dict:
    match = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    try:
        return json.loads(match.group(1)) if match else {}
    except ValueError:
        return {}


def parse_page(html: str, url: str):
    blocks = ((_next_data(html).get('props') or {}).get('pageProps') or {}).get('blocks') or []
    rows = [v for b in blocks if b.get('__typename') == 'ComponentBlocksVacanciesContent'
            for v in (b.get('data') or {}).get('vacancies') or []]
    items = []
    for row in rows:
        attrs = row.get('attributes') or {}
        title = _clean(attrs.get('title'))
        if not str(row.get('id', '')).isdigit() or not title:
            raise SourceError('вакансия ЦФТ неполная — проверь вёрстку сайта')
        field = ((attrs.get('professionalField') or {}).get('data') or {}).get('attributes') or {}
        details = [_name(field.get('specialization'), 'title'), _name(attrs.get('city'), 'name'),
                   _name(attrs.get('grade'), 'name')]
        items.append(Item(SOURCE, 'site', row['id'], f'https://job.cft.ru/{row["id"]}/',
                          '\n'.join([f'{title} | @ЦФТ', *filter(None, details)]), hint_title=title, employer='ЦФТ'))
    if not items:
        raise SourceError('каталог ЦФТ не распознан — проверь ссылку или вёрстку сайта')
    return items, None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.select_one('h1')
    if not h1 or _clean(h1.get_text(' ')) != item.hint_title:
        raise SourceError('карточка ЦФТ не распознана — проверь вёрстку сайта')
    # Описание — блок с текстом сразу после шапки; ищем ближайший к h1 контейнер с разделами вакансии.
    body = h1.find_parent(lambda el: el.name in ('section', 'main', 'div')
                          and len(el.get_text(' ', strip=True)) > len(h1.get_text(strip=True)) + 200)
    return career.add_detail(item, [body])


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
