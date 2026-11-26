"""X5 (rabota.x5.ru): открытый API вакансий группы; формат работы — структурированное поле work_format."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:x5'
BASE = 'https://rabota.x5.ru'
API = BASE + '/vacancy/api/v1/public/vacancies/'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
DETAIL = re.compile(re.escape(BASE) + rf'/vacancies/({UUID})')
FORMATS = {'remote': 'удалённо', 'hybrid': 'гибрид', 'office': 'офис'}


def _unit(row: dict) -> str:
    units = [u.get('business_unit', {}).get('name') for u in row.get('business_units') or [] if isinstance(u, dict)]
    return next((u for u in units if isinstance(u, str) and u), 'X5')


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, page, size, total, pages = (data[k] for k in ('items', 'page', 'page_size', 'total', 'pages'))
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (not isinstance(rows, list) or any(type(n) is not int for n in (page, size, total, pages))
                or size < 1 or page < 1 or page != int(query.get('page', ['1'])[0])
                or len(rows) != min(size, max(0, total - (page - 1) * size))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title = row['id'], row['name'].strip()
            if not re.fullmatch(UUID, ext_id) or not title or row['work_format'] not in FORMATS:
                raise ValueError('неполная карточка')
            unit = _unit(row)
            city = row.get('city') or ''
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/vacancies/{ext_id}',
                              f'{title} | @{unit}\nФормат работы: {FORMATS[row["work_format"]]}'
                              + (f'\nГород: {city}' if city else ''),
                              published_at=career.parse_date(row.get('published_at')),
                              hint_title=title, employer=unit, remote_format=row['work_format'] == 'remote'))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if page < pages:
            query['page'] = [str(page + 1)]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача X5 не распознана — проверь API rabota.x5.ru') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        row = json.loads(text)
        if row['id'] != item.external_id or row['work_format'] not in FORMATS:
            raise ValueError('неверная карточка')
        item.remote_format = row['work_format'] == 'remote'
        content = row['content']
        if not isinstance(content, dict) or not any(isinstance(v, str) and v for v in content.values()):
            raise ValueError('неверное описание')
        # Поля описания — обычный текст со строками; экранируем, чтобы BeautifulSoup не принял его за разметку.
        # Флаги вроде character_work (bool) — не текст описания, их пропускаем.
        parts = [BeautifulSoup(html.escape(v).replace('\n', '<br>'), 'html.parser')
                 for v in content.values() if isinstance(v, str) and v]
        return career.add_detail(item, parts, extra='Формат работы: ' + FORMATS[row['work_format']])
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка X5 не распознана — проверь API rabota.x5.ru') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    def api_fetch(url):
        match = DETAIL.fullmatch(url)
        return fetch(API + match.group(1) if match else url)
    return career.collect(SOURCE, urls, api_fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
