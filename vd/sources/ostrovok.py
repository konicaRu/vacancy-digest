"""Островок: каталог и карточки career.ostrovok.ru (данные Next.js)."""
from __future__ import annotations

import json

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from ..classify import remote_of
from . import career

SOURCE = 'site:ostrovok'
BASE = 'https://career.ostrovok.ru'


def _props(html: str) -> dict:
    tag = BeautifulSoup(html, 'html.parser').select_one('script#__NEXT_DATA__')
    return json.loads(tag.string)['props']['pageProps']


def _active(row: dict) -> bool:
    return row['approved'] is True and row['actual'] is True and row['state'] == 'OPEN' and row['hidden'] is False


def _html(row: dict) -> list:
    fields = [row.get(k) for k in ('tasks', 'requirements', 'conditions')]
    if any(value is not None and not isinstance(value, str) for value in fields):
        raise ValueError('неверное описание')
    return [BeautifulSoup(value, 'html.parser') for value in fields if value]


def _remote(row: dict) -> bool:
    conditions = BeautifulSoup(row.get('conditions') or '', 'html.parser').get_text(' ', strip=True)
    return remote_of(conditions) == 'yes'


def parse_page(html: str, url: str):
    try:
        rows = _props(html)['vacancies']
        if not isinstance(rows, list):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            if not _active(row):
                continue
            ext_id, title = str(row['id']), row['position'].strip()
            if not ext_id.isdigit() or not title:
                raise ValueError('неполная карточка')
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/vacancy/{ext_id}',
                              f'{title} | @Островок', hint_title=title, remote_format=_remote(row)))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        return items, None
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Островка не распознана — проверь вёрстку сайта') from e


def parse_detail(html: str, item: Item) -> Item:
    try:
        row = _props(html)['vacancy']
        if str(row['id']) != item.external_id:
            raise ValueError('описание другой вакансии')
        if not _active(row):
            item.remote_format = False
            item.text += '\nВакансия закрыта или скрыта'
            return item
        item.remote_format = _remote(row)
        return career.add_detail(item, _html(row),
                                 extra='Формат работы: ' + ('удалёнка в условиях' if item.remote_format else 'удалёнка не подтверждена'),
                                 published=row.get('createdAt'))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка Островка не распознана — проверь вёрстку сайта') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=3, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
