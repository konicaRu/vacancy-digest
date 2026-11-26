"""Selectel (selectel.ru/careers/all/): серверный каталог всех вакансий; формат работы — только текстом карточки."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:selectel'
CARD = re.compile(r'/careers/all/vacancy/(\d+)/')


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for card in soup.select('.vacancies__cards .card'):
        link = card.select_one('a[href]')
        match = CARD.fullmatch(link.get('href', '')) if link else None
        title_el = card.select_one('h4')
        title = title_el.get_text(' ', strip=True) if title_el else ''
        if not match or not title:
            raise SourceError('карточка Selectel неполная — проверь вёрстку сайта')
        tags = [el.get_text(' ', strip=True) for el in card.select('.card-header__tags .tag')]
        city = card.select_one('.card-footer__price-value')
        lines = [f'{title} | @Selectel', *tags] + ([city.get_text(' ', strip=True)] if city else [])
        items.append(Item(SOURCE, 'site', match.group(1), urljoin(url, link['href']), '\n'.join(lines),
                          hint_title=title, employer='Selectel'))
    if not items:
        raise SourceError('каталог Selectel не распознан — проверь ссылку или вёрстку сайта')
    return list({i.external_id: i for i in items}.values()), None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.select_one('h1')
    if not h1 or h1.get_text(' ', strip=True) != item.hint_title:
        raise SourceError('карточка Selectel не распознана — проверь вёрстку сайта')
    return career.add_detail(item, [soup.select_one('.vacancy__info')])


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
