"""GeekJob: JSON-поиск сайта (фильтр «удалённо») и HTML-карточки вакансий."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:geekjob'
BASE = 'https://geekjob.ru'
ID = re.compile(r'[0-9a-f]{24}')
REMOTE_LABEL = 'Удаленная работа'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, page, nextpage, pages, count = (data[k] for k in ('data', 'page', 'nextpage', 'pagecount', 'documentsCount'))
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (not isinstance(rows, list) or any(type(n) is not int for n in (page, nextpage, pages, count))
                or page != int(query.get('page', ['1'])[0]) or count < 0
                or nextpage not in (0, page + 1) or (nextpage == 0) != (page >= pages)
                or (count > 0 and page <= pages and not rows)):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title = row['id'], row['position'].strip()
            company = (row.get('company') or {}).get('name') or None
            if not ID.fullmatch(ext_id) or not title:
                raise ValueError('неполная карточка')
            remote = row['jobFormat']['remote'] is True and not (row.get('log') or {}).get('archived')
            place = ', '.join(p for p in (row.get('city'), row.get('country')) if p)
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/vacancy/{ext_id}',
                              f'{title} | @{company or "GeekJob"}' + (f'\nЛокация: {place}' if place else ''),
                              hint_title=title, remote_format=remote, employer=company))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if nextpage:
            query['page'] = [str(nextpage)]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача GeekJob не распознана — проверь сайт') from e


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    posting = career.job_posting(soup)
    ident = (posting.get('identifier') or {}).get('name') if isinstance(posting.get('identifier'), dict) else None
    if ident != f'Geekjob {item.external_id}':
        raise SourceError('карточка GeekJob не распознана — проверь вёрстку сайта')
    fmt = soup.select_one('.jobformat')
    formats = fmt.get_text(' ', strip=True) if fmt else ''
    item.remote_format = bool(item.remote_format) and REMOTE_LABEL in formats
    return career.add_detail(item, [soup.select_one('#vacancy-description')],
                             extra='Формат работы: ' + (formats or 'не указан'),
                             published=posting.get('datePosted'))


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
