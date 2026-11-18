"""Альфа-Банк: публичный каталог и карточки job.alfabank.ru."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:alfabank'
BASE = 'https://job.alfabank.ru'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, total, skip, take = (data[k] for k in ('items', 'total', 'skip', 'take'))
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (any(type(n) is not int for n in (total, skip, take))
                or total < 0 or skip < 0 or take < 1
                or skip != int(query.get('skip', ['0'])[0])
                or take != int(query.get('take', ['10'])[0])
                or not isinstance(rows, list) or len(rows) != min(take, max(0, total - skip))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            key, title, slug = str(row['id']), row['name'].strip(), row['slug']
            if (not key.isdigit() or not title or not isinstance(slug, str)
                    or not slug.startswith('/') or slug.startswith('//')
                    or '?' in slug or '#' in slug or not slug.endswith('_' + key)):
                raise ValueError('неполная карточка')
            items.append(Item(SOURCE, 'site', key, BASE + '/vacancies' + slug,
                              title + ' | @Альфа-Банк', hint_title=title,
                              published_at=career.parse_date(row.get('createdAt')), remote_format=False))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if skip + len(rows) < total:
            query['skip'] = [str(skip + len(rows))]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Альфа-Банка не распознана — проверь API сайта') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        row = json.loads(text)
        key, title = str(row['id']), row['name'].strip()
        # Some public detail responses encrypt id; the canonical slug stays unchanged.
        opaque = bool(re.fullmatch(r'[A-Za-z0-9+/_-]{20,}={1,2}', key))
        same_slug = isinstance(row.get('slug'), str) and BASE + '/vacancies' + row['slug'] == item.url
        if (key != item.external_id and not (opaque and same_slug and title == item.hint_title)) or not title:
            raise ValueError('описание другой вакансии')
        if any(type(row[k]) is not bool for k in ('isHidden', 'isInternal')):
            raise ValueError('неизвестный статус карточки')
        expiry = career.parse_date(row.get('expirationDate'))
        if row.get('expirationDate') and (not expiry or expiry.tzinfo is None):
            raise ValueError('неверная дата закрытия')
        if row['isHidden'] or row['isInternal'] or (expiry and expiry <= datetime.now(timezone.utc)):
            item.remote_format = False
            item.text += '\nВакансия закрыта или не опубликована для внешних кандидатов'
            return item
        formats = row.get('jobTypes') or []
        if not isinstance(formats, list) or any(not isinstance(f, dict) or not isinstance(f.get('value'), str) for f in formats):
            raise ValueError('неверный формат работы')
        item.remote_format = any(f.get('key') == '1003' and f['value'].strip() == 'Дистанционная работа' for f in formats)
        description = row['description']
        if not isinstance(description, str) or not description.strip():
            raise ValueError('описание отсутствует')
        return career.add_detail(item, [BeautifulSoup(description, 'html.parser')],
                                 extra='Формат работы: ' + ', '.join(f['value'] for f in formats),
                                 published=row.get('createdAt'))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка Альфа-Банка не распознана — проверь API сайта') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    def api_fetch(url):
        if url.startswith(BASE + '/vacancies/'):
            key = url.rsplit('_', 1)[-1]
            return fetch(BASE + '/api/vacancies/' + key)
        return fetch(url)
    return career.collect(SOURCE, urls, api_fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
