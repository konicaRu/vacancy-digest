"""Хабр Карьера: HTML-карточки и метаданные пагинации из SSR-состояния."""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:habr'


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    state_el = soup.select_one('script[data-ssr-state]')
    try:
        vacancies = json.loads(state_el.get_text())['vacancies']
        meta = vacancies['meta']
        current, total = int(meta['currentPage']), int(meta['totalPages'])
    except (AttributeError, ValueError, TypeError, KeyError) as e:
        raise SourceError('не найдены данные выдачи Хабр Карьеры — проверь вёрстку сайта') from e
    items = []
    for card in soup.select('.vacancy-card'):
        a = card.select_one('a.vacancy-card__title-link')
        if not a:
            continue
        match = re.search(r'/vacancies/(\d+)/?$', a.get('href', ''))
        company = card.select_one('.vacancy-card__company')
        time_el = card.select_one('time[datetime]')
        meta_el = card.select_one('.vacancy-card__meta')
        salary = card.select_one('.vacancy-card__salary')
        if not match or not company:
            raise SourceError('карточка Хабр Карьеры неполная — проверь вёрстку сайта')
        company_name = company.select_one('a[href^="/companies/"]') or company
        title = a.get_text(' ', strip=True)
        meta_text = meta_el.get_text(' ', strip=True) if meta_el else ''
        grade = next((g for g in ('intern', 'junior', 'middle', 'senior', 'lead')
                      if re.search(rf'\b{g}\b', meta_text, re.I)), None)
        text = ' | '.join([title, '@' + company_name.get_text(' ', strip=True), meta_text,
                           salary.get_text(' ', strip=True) if salary else ''])
        items.append(Item(SOURCE, 'site', match.group(1), urljoin(url, a['href']), text,
                          published_at=career.parse_date(time_el['datetime']) if time_el else None,
                          hint_title=title, grade_hint=grade))
    if len(items) != len(vacancies['list']) or (not items and meta.get('totalResults', 0)):
        raise SourceError('карточки Хабр Карьеры не совпадают с выдачей — проверь вёрстку сайта')
    next_url = None
    if current < total:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        query['page'] = str(current + 1)
        next_url = urlunsplit(parts._replace(query=urlencode(query)))
    return items, next_url


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    header = soup.select_one('.vacancy-header .vacancy-meta')
    return career.add_detail(item, [soup.select_one('.vacancy-description__text')],
                             header.get_text(' ', strip=True) if header else '')


def collect(urls, fetch, is_seen, first_run, lookback_days=5, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
