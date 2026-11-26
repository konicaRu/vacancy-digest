"""Яндекс (yandex.ru/jobs): открытый API публикаций; удалёнка — work_modes со slug «remote»."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:yandex'
BASE = 'https://yandex.ru'
API = BASE + '/jobs/api/publications/'
DETAIL = re.compile(re.escape(BASE) + r'/jobs/vacancies/[\w-]+-(\d+)')
SECTIONS = ('short_summary', 'description', 'duties', 'key_qualifications', 'additional_requirements',
            'conditions', 'our_team')


def _modes(row: dict) -> list[str]:
    modes = (row.get('vacancy') or {}).get('work_modes') or []
    if not isinstance(modes, list) or any(not isinstance(m, dict) for m in modes):
        raise ValueError('неверный формат работы')
    return [m.get('slug') for m in modes]


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, count, nxt = data['results'], data['count'], data.get('next')
        if not isinstance(rows, list) or type(count) is not int or (nxt is not None and not (
                isinstance(nxt, str) and nxt.startswith('/jobs/api/'))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, slug, title = row['id'], row['publication_slug_url'], row['title'].strip()
            if type(ext_id) is not int or not re.fullmatch(rf'[\w-]+-{ext_id}', slug) or not title:
                raise ValueError('неполная карточка')
            modes = _modes(row)
            service = (row.get('public_service') or {}).get('name') or ''
            names = ', '.join(m.get('name', '') for m in row['vacancy']['work_modes']) or 'не указан'
            items.append(Item(SOURCE, 'site', str(ext_id), f'{BASE}/jobs/vacancies/{slug}',
                              f'{title} | @Яндекс' + (f' / {service}' if service else '') + f'\nФормат работы: {names}',
                              hint_title=title, employer='Яндекс', remote_format='remote' in modes))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        return items, (BASE + nxt if nxt else None)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Яндекса не распознана — проверь API yandex.ru/jobs') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        row = json.loads(text)
        if str(row['id']) != item.external_id or row.get('status') != 'published':
            raise ValueError('неверная карточка')
        item.remote_format = 'remote' in _modes(row)
        values = [row.get(k) for k in SECTIONS]
        parts = [BeautifulSoup(v.replace('\n', '<br>'), 'html.parser') for v in values if isinstance(v, str) and v]
        return career.add_detail(item, parts, published=row.get('published_at'))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка Яндекса не распознана — проверь API yandex.ru/jobs') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    def api_fetch(url):
        match = DETAIL.fullmatch(url)
        return fetch(f'{API}{match.group(1)}/' if match else url)
    return career.collect(SOURCE, urls, api_fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
