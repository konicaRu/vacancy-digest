"""Aviasales: активные HTML-карточки и все разделы описания вакансии."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:aviasales'


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for a in soup.select('a[data-id][href^="/about/vacancies/"]'):
        match = re.fullmatch(r'/about/vacancies/(\d+)/?', a['href'])
        title_el = a.select_one('[data-test-id="brand-text"]')
        if not match or not title_el:
            raise SourceError('карточка Aviasales неполная — проверь вёрстку сайта')
        title = title_el.get_text(' ', strip=True)
        team_el = a.select_one('[class*="team-"]')
        if team_el and team_el.get_text(strip=True):
            title += ' — ' + team_el.get_text(' ', strip=True).split(':', 1)[-1].strip()
        items.append(Item(SOURCE, 'site', match.group(1), urljoin(url, a['href']),
                          title + ' | @Aviasales', hint_title=title))
    if not items:
        raise SourceError('выдача Aviasales не распознана — проверь ссылку или вёрстку сайта')
    return items, None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    location = soup.select_one('[class*="teamAndLocation-"]')
    return career.add_detail(item, soup.select('[class*="dynamicContent-"]'),
                             location.get_text(' ', strip=True) if location else '')


def collect(urls, fetch, is_seen, first_run, lookback_days=5, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
