"""Nexign (job.nexign.com/jobs): серверный каталог с пагинацией и карточка.

Удалёнка: в FAQ каждой карточки — «можно работать из любой точки России» (решение пользователя 27.11:
считать удалёнкой), если в тексте самой вакансии не сказано об офисе или гибриде. FAQ в текст не берём.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..classify import remote_of
from ..models import Item, SourceError
from . import career

SOURCE = 'site:nexign'
CARD = re.compile(r'/jobs/([a-z0-9_-]+/[a-z0-9_-]+)')
POLICY = re.compile(r'из\s+любой\s+точки\s+России', re.I)


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for link in soup.select('a[href]'):
        match = CARD.fullmatch(link['href'])
        if not match:
            continue
        title_el = link.select_one('.vacancy-card__title')
        title = title_el.get_text(' ', strip=True) if title_el else ''
        if not title:
            raise SourceError('карточка Nexign неполная — проверь вёрстку сайта')
        city = link.select_one('.vacancy-card__suptitle')
        lines = [f'{title} | @Nexign'] + ([city.get_text(' ', strip=True)] if city else [])
        items.append(Item(SOURCE, 'site', match.group(1), urljoin(url, link['href']), '\n'.join(lines),
                          hint_title=title, employer='Nexign'))
    if not items:
        raise SourceError('каталог Nexign не распознан — проверь ссылку или вёрстку сайта')
    nxt = soup.select_one('.pager-next a[href]')
    return list({i.external_id: i for i in items}.values()), urljoin(url, nxt['href']) if nxt else None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.select_one('.vacancy-details__title')
    if not title or title.get_text(' ', strip=True) != item.hint_title:
        raise SourceError('карточка Nexign не распознана — проверь вёрстку сайта')
    location = soup.select_one('.vacancy-details__location')
    item = career.add_detail(item, [location, soup.select_one('.vacancy-details__content')])
    faq = soup.select_one('.vacancy-details__faq')
    if faq and POLICY.search(faq.get_text(' ', strip=True)) and remote_of(item.text) != 'no':
        item.remote_format = True
    return item


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=5, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
