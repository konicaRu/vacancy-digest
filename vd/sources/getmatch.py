"""getmatch: открытый API выдачи и карточек вакансий."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:getmatch'
BASE = 'https://getmatch.ru'
DETAIL = re.compile(re.escape(BASE) + r'/vacancies/(\d+)(?:-[\w-]*)?')
JUNIOR = {'junior': 'junior', 'intern': 'intern'}


def _covers_russia(req: dict) -> bool:
    places = [req.get('location_id'), *(req.get('ancestors') or [])]
    return 'russia' in places


def remote_of(reqs: list) -> bool:
    """Удалёнка: формат remote для России или «весь мир», без исключения России."""
    if any(r.get('exclude') is True and (_covers_russia(r) or r.get('location_id') == '_cu-world') for r in reqs):
        return False
    return any(r.get('format') == 'remote' and r.get('exclude') is not True
               and (_covers_russia(r) or r.get('location_id') == '_cu-world') for r in reqs)


def _check_reqs(reqs) -> list:
    if not isinstance(reqs, list) or any(not isinstance(r, dict) or not isinstance(r.get('format'), str) for r in reqs):
        raise ValueError('неверный формат работы')
    return reqs


def _formats(row: dict) -> str:
    labels = [i.get('label') for i in row.get('location_items') or [] if isinstance(i, dict)]
    return ', '.join(label for label in labels if isinstance(label, str) and label) or 'не указан'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, meta = data['offers'], data['meta']
        total, offset, limit = (meta[k] for k in ('total', 'offset', 'limit'))
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (not isinstance(rows, list) or any(type(n) is not int for n in (total, offset, limit))
                or limit < 1 or total < 0 or offset < 0
                or offset != int(query.get('offset', ['0'])[0])
                or len(rows) != min(limit, max(0, total - offset))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title, path = str(row['id']), row['position'].strip(), row['url']
            company = (row.get('company') or {}).get('name') or None
            if not ext_id.isdigit() or not title or not DETAIL.fullmatch(BASE + path):
                raise ValueError('неполная карточка')
            reqs = _check_reqs(row['location_requirements'])
            items.append(Item(SOURCE, 'site', ext_id, BASE + path,
                              f'{title} | @{company or "getmatch"}\nФормат работы: {_formats(row)}',
                              published_at=career.parse_date(row.get('published_at')),
                              hint_title=title, remote_format=remote_of(reqs), employer=company))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if offset + len(rows) < total:
            query['offset'] = [str(offset + len(rows))]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача getmatch не распознана — проверь API сайта') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        row = json.loads(text)
        if str(row['id']) != item.external_id or type(row['is_active']) is not bool:
            raise ValueError('неверная карточка')
        if not row['is_active']:
            item.remote_format = False
            item.text += '\nВакансия закрыта'
            return item
        item.remote_format = remote_of(_check_reqs(row['location_requirements']))
        item.grade_hint = JUNIOR.get(row.get('seniority')) or item.grade_hint
        fields = [row.get(k) for k in ('short_description', 'description', 'offer_description', 'stack_description')]
        if any(value is not None and not isinstance(value, str) for value in fields):
            raise ValueError('неверное описание')
        elements = [BeautifulSoup(value.replace('\n', '<br>'), 'html.parser') for value in fields if value]
        return career.add_detail(item, elements, extra='Формат работы: ' + _formats(row),
                                 published=row.get('published_at'))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка getmatch не распознана — проверь API сайта') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    def api_fetch(url):
        match = DETAIL.fullmatch(url)
        return fetch(f'{BASE}/api/offers/{match.group(1)}' if match else url)
    return career.collect(SOURCE, urls, api_fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
