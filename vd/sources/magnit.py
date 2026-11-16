"""Magnit Tech: публичный API каталога и подробных карточек."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:magnit'
BASE = 'https://magnit.tech'
# /api/v1/work_format: Москва/Краснодар — гибрид/офис, другие города — удалённо.
REMOTE_FORMAT = 16108


def _formats(row):
    formats = row.get('work_formats') or []
    if not isinstance(formats, list) or any(not isinstance(f, dict) or not isinstance(f.get('name'), str) for f in formats):
        raise ValueError('неверный формат работы')
    remote = any(type(f.get('foreign_id')) is int and f['foreign_id'] == REMOTE_FORMAT for f in formats)
    return remote, ', '.join(f['name'] for f in formats) or 'не указан'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        if data['success'] is not True:
            raise ValueError('ошибка API')
        rows, meta = data['results'], data['meta']
        page, size, total = (meta[k] for k in ('current_page', 'per_page', 'total'))
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (not isinstance(rows, list) or any(type(n) is not int for n in (page, size, total))
                or size < 1 or total < 0 or page < 1 or page > max(1, (total + size - 1) // size)
                or page != int(query.get('page', ['1'])[0])
                or len(rows) != min(size, max(0, total - (page - 1) * size))
                or type(meta['has_more_pages']) is not bool
                or meta['has_more_pages'] != (page * size < total)
                or (rows and (meta['from'] != (page - 1) * size + 1
                              or meta['to'] != (page - 1) * size + len(rows)))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title = str(row['id']), row['title'].strip()
            if not ext_id.isdigit() or not title:
                raise ValueError('неполная карточка')
            remote, formats = _formats(row)
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/vacancies/{ext_id}',
                              f'{title} | @Магнит Tech\nФормат работы: {formats}',
                              hint_title=title, remote_format=remote,
                              grade_hint='intern' if row.get('is_internship') is True else None))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if meta['has_more_pages']:
            query['page'] = [str(page + 1)]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Магнит Tech не распознана — проверь API сайта') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        data = json.loads(text)
        row = data['results']
        if (data['success'] is not True or str(row['id']) != item.external_id
                or row['status'] not in ('active', 'archived') or type(row['is_published']) is not bool):
            raise ValueError('неверная карточка')
        if row['status'] == 'archived' or not row['is_published']:
            item.remote_format = False
            item.text += '\nВакансия в архиве или не опубликована'
            return item
        item.remote_format, formats = _formats(row)
        if row.get('for_beginners') is True:
            item.grade_hint = 'intern'
        fields = [row.get(k) for k in ('description', 'about_product', 'tasks', 'skills', 'extra_skills', 'offer')]
        if any(value is not None and not isinstance(value, str) for value in fields):
            raise ValueError('неверное описание')
        elements = [BeautifulSoup(value, 'html.parser') for value in fields if value]
        return career.add_detail(item, elements, extra='Формат работы: ' + formats)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка Магнит Tech не распознана — проверь API сайта') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=20, profile=None):
    def api_fetch(url):
        match = re.fullmatch(re.escape(BASE) + r'/vacancies/(\d+)', url)
        return fetch(f'{BASE}/api/v1/vacancy/{match.group(1)}' if match else url)
    return career.collect(SOURCE, urls, api_fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
