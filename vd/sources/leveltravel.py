"""Level.Travel (career.level.travel): вакансии — раскрывающиеся блоки Tilda на одной странице, без карточек."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:leveltravel'
FIELD = re.compile(r'li_title__(\d+)')


def _vacancies(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    for wrapper in soup.select('.t668__wrapper'):
        title_el = wrapper.select_one('.t668__title')
        match = FIELD.fullmatch(title_el.get('field', '')) if title_el else None
        title = title_el.get_text(' ', strip=True) if title_el else ''
        if not match or not title:
            raise SourceError('блок вакансии Level.Travel неполный — проверь вёрстку сайта')
        yield match.group(1), title, wrapper.select_one('.t668__content')


def parse_page(html: str, url: str):
    base = url.split('#', 1)[0]
    items = [Item(SOURCE, 'site', key, f'{base}#vacancy-{key}', f'{title} | @Level.Travel',
                  hint_title=title, employer='Level.Travel') for key, title, _ in _vacancies(html)]
    if not items:
        raise SourceError('вакансии Level.Travel не найдены — проверь ссылку или вёрстку сайта')
    return items, None


def parse_detail(html: str, item: Item) -> Item:
    for key, title, content in _vacancies(html):
        if key == item.external_id and title == item.hint_title:
            return career.add_detail(item, [content])
    raise SourceError('вакансия Level.Travel пропала со страницы — проверь вёрстку сайта')


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
