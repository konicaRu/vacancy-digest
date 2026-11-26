"""Страницы вакансий компаний на Huntflow (<компания>.huntflow.io): обычный HTML без структурированного формата."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:huntflow'
SLUG = re.compile(r'/vacancy/([A-Za-z0-9-]+)')


def parse_page(html: str, url: str):
    host = urlsplit(url).hostname or ''
    if not host.endswith('.huntflow.io'):
        raise SourceError(f'не страница Huntflow: {url}')
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text(strip=True) if soup.title else ''
    company = re.sub(r'^Вакансии компании\s+', '', title).strip() or host.split('.')[0]
    items = []
    for a in soup.select('a[href^="/vacancy/"]'):
        match = SLUG.fullmatch(a['href'])
        name = a.get_text(' ', strip=True)
        if not match or not name:
            continue
        items.append(Item(SOURCE, 'site', f'{host}/{match.group(1)}', f'https://{host}/vacancy/{match.group(1)}',
                          f'{name} | @{company}', hint_title=name, employer=company))
    items = list({i.external_id: i for i in items}.values())
    if not items:
        # У компании на Huntflow всегда есть хотя бы одна вакансия; пустая страница — смена вёрстки или сбой.
        raise SourceError(f'на странице {host} не найдено вакансий — проверь вёрстку Huntflow')
    return items, None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.select_one('h1')
    header = h1.find_parent('header') if h1 else None
    if not h1 or h1.get_text(' ', strip=True) != item.hint_title or header is None:
        raise SourceError('карточка Huntflow не распознана — проверь вёрстку сайта')
    return career.add_detail(item, [header.parent])


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
