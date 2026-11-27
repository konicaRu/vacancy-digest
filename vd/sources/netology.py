"""Нетология (netology.ru/job): серверный список вакансий с меткой «Можно удаленно» и карточка."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:netology'
CARD = re.compile(r'/job/([0-9a-f-]{36})\??')


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for card in soup.select('a[href^="/job/"]'):
        match = CARD.fullmatch(card.get('href', ''))
        title_el = card.select_one('[class^="vacancies_vacancyTitle"]')
        title = title_el.get_text(' ', strip=True) if title_el else ''
        if not match or not title:
            raise SourceError('карточка Нетологии неполная — проверь вёрстку сайта')
        badges = [el.get_text(' ', strip=True) for el in card.select('[class^="badge_text"]')]
        desc = card.select_one('[class^="vacancies_vacancyDescription"]')
        formats = [el.get_text(' ', strip=True) for el in desc.find_all('div')] if desc else []
        items.append(Item(SOURCE, 'site', match.group(1), urljoin(url, f'/job/{match.group(1)}'),
                          '\n'.join([f'{title} | @Нетология', ' '.join(badges), *formats]).strip(),
                          hint_title=title, employer='Нетология',
                          remote_format=True if 'Можно удаленно' in formats else None))
    if not items:
        raise SourceError('каталог Нетологии не распознан — проверь ссылку или вёрстку сайта')
    return list({i.external_id: i for i in items}.values()), None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.select_one('h1')
    if not h1 or h1.get_text(' ', strip=True) != item.hint_title:
        raise SourceError('карточка Нетологии не распознана — проверь вёрстку сайта')
    return career.add_detail(item, [soup.select_one('[class^="vacancy_root"]')])


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
