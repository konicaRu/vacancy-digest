"""Авито: полный раздел аналитики, а не короткая общая витрина."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:avito'


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for card in soup.select('.vacancies-section__item'):
        a = card.select_one('a.vacancies-section__item-name')
        match = re.search(r'/vacancies/[^/]+/(\d+)/?$', a.get('href', '')) if a else None
        if not match:
            raise SourceError('карточка Авито неполная — проверь вёрстку сайта')
        title = a.get_text(' ', strip=True)
        formats = [el.get_text(' ', strip=True) for el in card.select('.vacancies-section__item-format')]
        grade = 'intern' if card.get('data-vacancy-intern') == 'Да' else None
        items.append(Item(SOURCE, 'site', match.group(1), urljoin(url, a['href']),
                          ' | '.join([title, '@Авито', *formats]), hint_title=title, grade_hint=grade))
    if not items:
        raise SourceError('выдача Авито не распознана — проверь ссылку или вёрстку сайта')
    # Общая витрина показывает лишь часть аналитики; перейти в полный раздел.
    more = soup.select_one('a[data-show-all-link][href="/vacancies/analitika-dannykh/"]')
    return items, urljoin(url, more['href']) if more else None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    locations = soup.select('.page-info--detail .page-info__link-wrap-text')
    posting = career.job_posting(soup)
    return career.add_detail(item, soup.select('.vacancies-detail__description'),
                             ' '.join(el.get_text(' ', strip=True) for el in locations),
                             posting.get('datePosted'))


def collect(urls, fetch, is_seen, first_run, lookback_days=5, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
