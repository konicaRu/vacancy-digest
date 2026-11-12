"""VK: публичный API выдачи и HTML-описания с датой datePosted."""
from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit, parse_qs

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:vk'
BASE = 'https://team.vk.company'


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, count = data['results'], int(data['count'])
        offset = int(parse_qs(urlsplit(url).query).get('offset', ['0'])[0])
        if (not isinstance(rows, list) or count < 0 or offset < 0 or offset + len(rows) > count
                or (offset < count and not rows)):
            raise ValueError('неполная выдача')
        next_url = data.get('next')
        if bool(next_url) != (offset + len(rows) < count):
            raise ValueError('неполное продолжение выдачи')
        if next_url:
            parts = urlsplit(next_url)
            if parts.scheme not in ('http', 'https') or parts.netloc != 'team.vk.company' or parts.path != '/career/api/v2/vacancies/':
                raise ValueError('неожиданная ссылка следующей страницы')
            next_offset = int(parse_qs(parts.query).get('offset', ['0'])[0])
            if next_offset != offset + len(rows):
                raise ValueError('следующая страница не продолжает выдачу')
            next_url = urlunsplit(parts._replace(scheme='https', fragment=''))
        items = []
        for row in rows:
            ext_id, title = str(row['id']), row['title'].strip()
            if not ext_id.isdigit() or not title:
                raise ValueError('неполная карточка')
            group = (row.get('group') or {}).get('name', '')
            company = 'VK / ' + group if group else 'VK'
            fmt = row.get('work_format') or ''
            if fmt.lower() == 'комбинированный':
                fmt = 'Гибрид'
            if row.get('remote') is True:
                fmt = 'Удалённо | ' + fmt
            items.append(Item(SOURCE, 'site', ext_id, f'{BASE}/vacancy/{ext_id}/',
                              ' | '.join([title, '@' + company, fmt]), hint_title=title))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача VK не распознана — проверь API или вёрстку сайта') from e


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    posted = soup.select_one('meta[itemprop="datePosted"][content]')
    return career.add_detail(item, [soup.select_one('[itemprop="description"]')],
                             published=posted['content'] if posted else None)


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=5, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
