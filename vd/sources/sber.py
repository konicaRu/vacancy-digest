"""Сбер: публичная выдача и данные самой вакансии из Next.js."""
from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:sber'
BASE = 'https://rabota.sber.ru'
# Public /api/v1/schedules: id=4, «Удаленная работа».
REMOTE_SCHEDULE = 4


def parse_page(text: str, url: str):
    try:
        response = json.loads(text)
        if response['success'] is not True:
            raise ValueError('ошибка API')
        data = response['data']
        rows, total = data['vacancies'], data['total']
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        params = dict(query)
        skip, take = int(params.get('skip', 0)), int(params.get('take', 10))
        if (not isinstance(rows, list) or type(total) is not int or total < 0
                or skip < 0 or take < 1 or len(rows) > take
                or skip + len(rows) > total or (skip < total and not rows)):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title = str(row['internalId']), row['title'].strip()
            if not ext_id.isdigit() or not title:
                raise ValueError('неполная карточка')
            # The server resolves the final numeric id and redirects to its canonical slug.
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/search/job-{ext_id}/',
                              title + ' | @Сбер', hint_title=title,
                              published_at=career.parse_date(row.get('publicationDate')),
                              remote_format=False))
        if len({item.external_id for item in items}) != len(items):
            raise ValueError('повтор карточки в выдаче')
        next_url = None
        if skip + len(rows) < total:
            query = [(key, value) for key, value in query if key != 'skip']
            query.insert(0, ('skip', str(skip + len(rows))))
            next_url = urlunsplit(parts._replace(query=urlencode(query), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Сбера не распознана — проверь публичный API') from e


def parse_detail(html: str, item: Item) -> Item:
    try:
        soup = BeautifulSoup(html, 'html.parser')
        script = soup.select_one('script#__NEXT_DATA__')
        row = json.loads(script.get_text())['props']['pageProps']['vacancy']
        if str(row['internalId']) != item.external_id or not row['title'].strip():
            raise ValueError('описание другой вакансии')
        descriptions = [row.get(key) for key in ('introduction', 'duties', 'requirements', 'conditions')]
        if not any(isinstance(value, str) and value.strip() for value in descriptions[1:]):
            raise ValueError('описание отсутствует')
        if any(value is not None and not isinstance(value, str) for value in descriptions):
            raise ValueError('неверный формат описания')
        schedule = row.get('workScheduleId')
        item.remote_format = type(schedule) is int and schedule == REMOTE_SCHEDULE
        content = BeautifulSoup('\n'.join(value for value in descriptions if value), 'html.parser')
        return career.add_detail(item, [content],
                                 extra='Формат работы: ' + ('удаленная работа' if item.remote_format else 'удалёнка не подтверждена'),
                                 published=row.get('publicationDate'))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('описание Сбера не распознано — проверь данные вакансии') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
