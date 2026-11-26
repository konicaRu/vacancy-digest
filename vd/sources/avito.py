"""Авито: полный раздел аналитики, а не короткая общая витрина.

С 25.11.2026 карточки ведут на /publications/<раздел>/<uuid>/, а текст вакансии отдаёт открытый API
публикаций careers.avito.ru. В ответе API есть прежний номер вакансии — по нему узнаём уже виденные.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:avito'
API = 'https://careers.avito.ru/service-ats-public-api/aviwork/v1/publications/'
PUBLICATION = re.compile(r'/publications/[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$')
SECTIONS = ('team_description', 'responsibilities', 'requirements', 'conditions')


def parse_page(html: str, url: str):
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for card in soup.select('.vacancies-section__item'):
        a = card.select_one('a.vacancies-section__item-name')
        match = PUBLICATION.search(a.get('href', '')) if a else None
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


def _publication(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get('content', {}).get('attributes'), dict):
        raise ValueError('неверная публикация')
    return data


def parse_detail(text: str, item: Item) -> Item:
    try:
        data = _publication(text)
        if data['publicationId'] != item.external_id:
            raise ValueError('чужая публикация')
        if data['status'] != 'published':
            item.remote_format = False
            item.text += '\nВакансия снята с публикации'
            return item
        attrs = data['content']['attributes']
        values = [attrs.get(k) for k in SECTIONS]
        if any(v is not None and not isinstance(v, str) for v in values):
            raise ValueError('неверное описание')
        formats = ', '.join(attrs.get('work_format') or []) or 'не указан'
        places = ', '.join(attrs.get('location') or [])
        extra = f'Формат работы: {formats}' + (f'\nЛокация: {places}' if places else '')
        # Даты публикации в API нет (updatedAt — дата правки), поэтому published_at не заполняем.
        return career.add_detail(item, [BeautifulSoup(v, 'html.parser') for v in values if v], extra)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('публикация Авито не распознана — проверь API careers.avito.ru') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=5, max_pages=10, profile=None):
    cache: dict[str, str] = {}

    def api_fetch(url):
        match = PUBLICATION.search(url)
        if not match:
            return fetch(url)
        if match.group(1) not in cache:
            cache[match.group(1)] = fetch(API + match.group(1))
        return cache[match.group(1)]

    def seen(source, external_id):
        # Вакансии, виденные до смены адресов, хранятся под прежним номером (vacancies[0].id).
        if is_seen(source, external_id):
            return True
        vacancies = _publication(api_fetch(f'/publications/x/{external_id}/')).get('vacancies') or []
        return any(is_seen(source, str(v.get('id'))) for v in vacancies if isinstance(v, dict))

    return career.collect(SOURCE, urls, api_fetch, seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
