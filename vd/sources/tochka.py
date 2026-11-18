"""Точка Банк: каталог «Удалённо» (состояние Next.js) и карточки с JobPosting."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:tochka'
BASE = 'https://hr.tochka.com'
CHUNK = re.compile(r'self\.__next_f\.push\(\[1,(".*?")\]\)</script>', re.S)
SLUG = re.compile(r'[A-Za-z0-9_\-]+')


def parse_page(html: str, url: str):
    try:
        state = ''.join(json.loads(chunk) for chunk in CHUNK.findall(html))
        start = state.index('"initialVacancies":') + len('"initialVacancies":')
        data, _ = json.JSONDecoder().raw_decode(state[start:])
        meta, rows = data['meta'], data['items']
        total, page, size = (meta[k] for k in ('total', 'page', 'pageSize'))
        # Следующие страницы подгружаются кнопкой «Показать ещё» — без выдачи по URL читать их нельзя.
        if (any(type(n) is not int for n in (total, page, size)) or page != 1 or size < 1
                or not isinstance(rows, list) or len(rows) != total or total > size):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            slug, title = row['slug'], row['title'].strip()
            if not isinstance(slug, str) or not SLUG.fullmatch(slug) or not title:
                raise ValueError('неполная карточка')
            items.append(Item(SOURCE, 'site', slug, f'{BASE}/vacancies/catalog/{slug}/',
                              f'{title} | @Точка Банк\nФормат работы: {row.get("workFormatInRussian") or "не указан"}',
                              hint_title=title, remote_format=row.get('workFormat') == 'remotely'))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        return items, None
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Точки не распознана — проверь вёрстку сайта') from e


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    posting = career.job_posting(soup)
    if posting.get('@id') != f'{BASE}/vacancies/catalog/{item.external_id}/#job':
        raise SourceError('карточка Точки не распознана — нет описания вакансии')
    item.remote_format = posting.get('jobLocationType') == 'TELECOMMUTE'
    return career.add_detail(item, soup.select('[class*="details_sections"]'),
                             extra='Формат работы: ' + ('Удалённо' if item.remote_format else 'удалёнка не подтверждена'),
                             published=posting.get('datePosted'))


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=3, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
