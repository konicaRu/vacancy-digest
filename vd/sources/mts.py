"""МТС: публичный каталог API v2 с ISO-датами и полное HTML-описание."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, quote

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:mts'
BASE = 'https://job.mts.ru'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, paging = data['data'], data['meta']['pagination']
        total, limit = int(paging['total']), int(paging['pageSize'])
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        offset = int(query.get('offset', '0'))
        if (not isinstance(rows, list) or total < 0 or limit <= 0 or offset < 0
                or len(rows) > limit or offset + len(rows) > total or (offset < total and not rows)):
            raise ValueError('неполная выдача')
        if 'page' in paging and int(paging['page']) != offset // limit + 1:
            raise ValueError('API не вернуло запрошенную страницу')
        items = []
        for row in rows:
            ext_id, title, slug = str(row['id']), row['title'].strip(), row['slug']
            if not ext_id or not title or not slug:
                raise ValueError('неполная карточка')
            external = row.get('externalUrl') or ''
            legacy = re.search(r'/jobs/(\d+)/?$', urlsplit(external).path)
            public_id = legacy.group(1) if legacy else quote(slug, safe='')
            company = (row.get('employer') or {}).get('title') or 'МТС'
            formats = [fmt['title'] for fmt in row.get('workFormats', [])]
            if row.get('isRemote') is True:
                formats.insert(0, 'Удалённо')
            item_text = ' | '.join([title, '@' + company, *formats])
            salary = row.get('salary') or {}
            if salary.get('from') or salary.get('to'):
                item_text += ' | ' + ' – '.join(str(salary[k]) for k in ('from','to') if salary.get(k)) + ' ₽'
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/vacancy/{public_id}', item_text,
                              published_at=career.parse_date(row.get('publishedAt')), hint_title=title,
                              grade_hint='intern' if row.get('isInternship') else None,
                              links=[external] if external else []))
        next_url = None
        if offset + len(rows) < total:
            query.update(offset=str(offset + len(rows)), limit=str(limit))
            next_url = urlunsplit(parts._replace(query=urlencode(query)))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача МТС не распознана — проверь API или вёрстку сайта') from e


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    meta = soup.select_one('.vacancy__header__meta')
    return career.add_detail(item, [soup.select_one('.vacancy__content')],
                             meta.get_text(' ', strip=True) if meta else '')


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=5, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
