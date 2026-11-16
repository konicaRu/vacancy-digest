"""2GIS public vacancy catalog and JobPosting descriptions."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:twogis'
BASE = 'https://job.2gis.ru'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows = data['items']
        page, size, total, pages = (data[k] for k in ('page', 'pageSize', 'totalItems', 'totalPages'))
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (any(type(v) is not int for v in (page, size, total, pages))
                or page < 1 or size < 1 or total < 0 or pages < 0
                or page != int(query.get('page', ['1'])[0])
                or not isinstance(rows, list)
                or pages != (total + size - 1) // size
                or page > max(1, pages)
                or len(rows) != min(size, max(0, total - (page - 1) * size))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title, section = str(row['id']), row['title'].strip(), row['direction']['slug']
            if not ext_id.isdigit() or not title or not re.fullmatch(r'[a-z_]+', section):
                raise ValueError('неполная карточка')
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/vacancies/{section}/{ext_id}',
                              ' | '.join([title, '@2ГИС', row.get('shortDescription') or '']),
                              hint_title=title, remote_format=row.get('isRemote') is True))
        next_url = None
        if page < pages:
            query['page'] = [str(page + 1)]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача 2ГИС не распознана — проверь API сайта') from e


def parse_detail(html: str, item: Item) -> Item:
    posting = career.job_posting(BeautifulSoup(html, 'html.parser'))
    identifier = posting.get('identifier')
    if not isinstance(identifier, dict) or str(identifier.get('value')) != item.external_id:
        raise SourceError('описание 2ГИС не распознано — нет идентификатора вакансии')
    item.remote_format = posting.get('jobLocationType') == 'TELECOMMUTE'
    description = BeautifulSoup(posting.get('description') or '', 'html.parser')
    return career.add_detail(item, [description],
                             extra='Формат работы: ' + ('Удалённо' if item.remote_format else 'удалёнка не подтверждена'),
                             published=posting.get('datePosted'))


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
