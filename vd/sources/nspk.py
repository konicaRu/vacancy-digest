"""НСПК (www.nspk.ru/vacancies): серверный список по направлениям и карточка; формат — текстом карточки."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:nspk'
CARD = re.compile(r'/vacancies/([0-9a-f-]{36})')


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = {}
    for link in soup.select('.bundles-list__item-info a.bundles-list__item[href]'):
        match = CARD.fullmatch(link['href'])
        title = ' '.join(link.get_text(' ').split())  # в названиях бывают неразрывные пробелы
        if not match or not title:
            raise SourceError('карточка НСПК неполная — проверь вёрстку сайта')
        direction = link.find_parent(class_='bundles-list__item-info').find('span', recursive=False)
        lines = [f'{title} | @НСПК'] + ([' '.join(direction.get_text(' ').split())] if direction else [])
        items.setdefault(match.group(1), Item(SOURCE, 'site', match.group(1), urljoin(url, link['href']),
                                              '\n'.join(lines), hint_title=title, employer='НСПК'))
    if not items:
        raise SourceError('каталог НСПК не распознан — проверь ссылку или вёрстку сайта')
    return list(items.values()), None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    body = soup.select_one('.pages-vacancies-vacancy-slug')
    if not body or item.hint_title not in ' '.join(body.get_text(' ').split()):
        raise SourceError('карточка НСПК не распознана — проверь вёрстку сайта')
    return career.add_detail(item, [body])


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
