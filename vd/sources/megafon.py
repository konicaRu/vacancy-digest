"""МегаФон: серверный каталог и полные карточки из __INITIAL_STATE__."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:megafon'
BASE = 'https://job.megafon.ru'


def _response(text: str, key: str) -> dict:
    soup = BeautifulSoup(text, 'html.parser')
    for script in soup.select('script'):
        content = script.get_text()
        if '__INITIAL_STATE__=' in content:
            data = json.JSONDecoder().raw_decode(content.split('__INITIAL_STATE__=', 1)[1].lstrip())[0]
            state = data[key]
            if state['processStatus'] != 'SUCCESS' or not isinstance(state['response'], dict):
                raise ValueError('неуспешный ответ')
            return state['response']
    raise ValueError('состояние страницы отсутствует')


def _published(value):
    return datetime.fromtimestamp(value, timezone.utc) if value else None


def _format(row):
    tag = row.get('tag') or {}
    return tag.get('code') == 'remote', tag.get('title') or 'не указан'


def parse_page(text: str, url: str):
    try:
        data = _response(text, 'vacancies')
        rows = data['vacancies']
        page, pages, total = int(data['page']), int(data['pages']), int(data['total'])
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        requested = int(query.get('page', ['1'])[0])
        if (not isinstance(rows, list) or page != requested or page < 1 or pages < 0 or total < 0
                or (total == 0 and (rows or pages not in (0, 1)))
                or (total > 0 and (not rows or page > pages or len(rows) > total))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title = str(row['id']), row['title'].strip()
            segments = [row['city']['slug'], row['sector']['slug'], row['slug']]
            if not ext_id.isdigit() or not title or any(not segment or '/' in segment for segment in segments):
                raise ValueError('неполная карточка')
            remote, format_title = _format(row)
            company = row['organisation']['title'].strip()
            items.append(Item(SOURCE, 'site', ext_id, BASE + '/vacancy/' + '/'.join(segments),
                              f'{title} | @{company}\nФормат работы: {format_title}',
                              hint_title=title, published_at=_published(row.get('publishedAt')),
                              remote_format=remote))
        next_url = None
        if page < pages:
            query['page'] = [str(page + 1)]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError) as e:
        raise SourceError('выдача МегаФона не распознана — проверь вёрстку сайта') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        row = _response(text, 'vacancy')
        if str(row['id']) != item.external_id or not row['title'].strip():
            raise ValueError('карточка другой вакансии')
        description = row.get('description')
        if not isinstance(description, str) or not BeautifulSoup(description, 'html.parser').get_text(strip=True):
            raise ValueError('описание отсутствует')
        if 'tag' in row:
            item.remote_format, format_title = _format(row)
        else:
            format_title = 'Удалённо' if item.remote_format else 'удалёнка не подтверждена'
        item.published_at = _published(row.get('publishedAt')) or item.published_at
        elements = [BeautifulSoup(row.get(key) or '', 'html.parser')
                    for key in ('description', 'requirements', 'conditions')]
        return career.add_detail(item, elements, extra='Формат работы: ' + format_title)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError) as e:
        raise SourceError('карточка МегаФона не распознана — проверь вёрстку сайта') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
