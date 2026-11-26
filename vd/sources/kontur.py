"""Контур (kontur.ru/career): каталог направления и карточка вакансии; удалёнка — JobPosting TELECOMMUTE."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:kontur'
CARD = re.compile(r'/career/vacancies/(\d+)')


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for card in soup.select('a.vacancy'):
        match = CARD.fullmatch(card.get('href', ''))
        title_el = card.select_one('.vacancy__title')
        title = title_el.get_text(' ', strip=True) if title_el else ''
        if not match or not title:
            raise SourceError('карточка Контура неполная — проверь вёрстку сайта')
        details = [el.get_text(' ', strip=True).replace('\xa0', ' ') for el in card.select('.vacancy__description span')]
        items.append(Item(SOURCE, 'site', match.group(1), urljoin(url, card['href']),
                          '\n'.join([f'{title} | @Контур', *details]), hint_title=title, employer='Контур'))
    if not items:
        raise SourceError('каталог Контура не распознан — проверь ссылку или вёрстку сайта')
    return items, None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    posting = career.job_posting(soup)
    if posting.get('title', '').strip() != item.hint_title:
        raise SourceError('карточка Контура не распознана — проверь вёрстку сайта')
    item.remote_format = posting.get('jobLocationType') == 'TELECOMMUTE'
    return career.add_detail(item, [soup.select_one('.col-md-8 .text')], published=posting.get('datePosted'))


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
