"""Домклик: открытый API каталога и карточек вакансий; формат работы — структурированное поле."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:domclick'
BASE = 'https://career.domclick.ru'
DETAIL = re.compile(re.escape(BASE) + r'/vacancy/([a-z0-9-]+)')
FORMATS = {'REMOTE': 'удалённо', 'HYBRID': 'гибрид', 'ON_SITE': 'офис'}


def _formats(content: dict):
    formats = content.get('work_format') or []
    if not isinstance(formats, list) or any(not isinstance(f, str) for f in formats):
        raise ValueError('неверный формат работы')
    return 'REMOTE' in formats, ', '.join(FORMATS.get(f, f) for f in formats) or 'не указан'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, meta = data['result'], data['pagination']
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        offset, limit = meta['offset'], meta['limit']
        if (data['success'] is not True or not isinstance(rows, list) or type(offset) is not int
                or type(limit) is not int or limit < 1 or len(rows) > limit
                or offset != int(query.get('offset', ['0'])[0])):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, slug, title = row['id'], row['slug'], row['title'].strip()
            if type(ext_id) is not int or not DETAIL.fullmatch(f'{BASE}/vacancy/{slug}') or not title:
                raise ValueError('неполная карточка')
            remote, formats = _formats(row['vacancycontent'])
            area = (row.get('area') or {}).get('name') or ''
            items.append(Item(SOURCE, 'site', str(ext_id), f'{BASE}/vacancy/{slug}',
                              f'{title} | @Домклик\nФормат работы: {formats}' + (f'\nГород: {area}' if area else ''),
                              hint_title=title, employer='Домклик', remote_format=remote))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if rows and len(rows) == limit:  # API не отдаёт total: полная страница — повод спросить следующую
            query.update(offset=[str(offset + limit)], limit=[str(limit)])
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Домклика не распознана — проверь API сайта') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        data = json.loads(text)
        row = data['result']
        if data['success'] is not True or str(row['id']) != item.external_id or type(row['archived']) is not bool:
            raise ValueError('неверная карточка')
        if row['archived']:
            item.remote_format = False
            item.text += '\nВакансия в архиве'
            return item
        content = row['vacancycontent']
        item.remote_format, formats = _formats(content)
        description = content.get('description')
        skills = content.get('key_skills') or []
        if not isinstance(description, str) or not isinstance(skills, list):
            raise ValueError('неверное описание')
        extra = f'Формат работы: {formats}' + (f'\nНавыки: {", ".join(map(str, skills))}' if skills else '')
        return career.add_detail(item, [BeautifulSoup(description, 'html.parser')], extra=extra)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка Домклика не распознана — проверь API сайта') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=5, profile=None):
    def api_fetch(url):
        match = DETAIL.fullmatch(url)
        return fetch(f'{BASE}/api/v1/vacancy/detail/{match.group(1)}/' if match else url)
    return career.collect(SOURCE, urls, api_fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
