"""Arenadata (arenadata.tech/ru/career): весь каталог — в данных Next.js страницы; формат — текстом карточки."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:arenadata'
BASE = 'https://arenadata.tech/ru/career/'
# Запись каталога в потоке Next.js: {"slug":…,"featured":…,"position":…,"positionGrade":…,"product":…,"department":…}
ROW = re.compile(r'\{"slug":"([a-z0-9-]+)","featured":(?:true|false),"position":("(?:[^"\\]|\\.)*"),'
                 r'"positionGrade":(null|"[^"]*"),"product":("(?:[^"\\]|\\.)*"),"department":("(?:[^"\\]|\\.)*")')


def _flight(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    try:
        return ''.join(json.loads(f'"{chunk}"') for chunk in chunks)
    except ValueError as exc:
        raise SourceError('данные Arenadata не распознаны — проверь вёрстку сайта') from exc


def parse_page(html: str, url: str):
    items = {}
    for slug, position, grade, product, department in ROW.findall(_flight(html)):
        title = json.loads(position).strip()
        details = [json.loads(grade).capitalize() if grade != 'null' else '', json.loads(product), json.loads(department)]
        items.setdefault(slug, Item(SOURCE, 'site', slug, BASE + slug,
                                    '\n'.join([f'{title} | @Arenadata', *filter(None, details)]),
                                    hint_title=title, employer='Arenadata'))
    if not items:
        raise SourceError('каталог Arenadata не распознан — проверь ссылку или вёрстку сайта')
    return list(items.values()), None


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.select_one('h1')
    if not h1 or h1.get_text(' ', strip=True) != item.hint_title:
        raise SourceError('карточка Arenadata не распознана — проверь вёрстку сайта')
    return career.add_detail(item, [soup.select_one('#vacancy-description')])


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
