"""Т-Банк: публичные читающие POST API карьерного каталога."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:tbank'
BASE = 'https://www.tbank.ru'
API = BASE + '/pfpjobs/papi/'
UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
CATEGORIES = {'tcareer_it': 'it', 'tcareer_back_office': 'back-office'}


def _payload(text):
    data = json.loads(text)
    if data['resultCode'] != 'OK' or not isinstance(data['payload'], dict):
        raise ValueError('ошибка API')
    return data['payload']


def parse_page(text: str, url: str):
    try:
        data = _payload(text)
        rows, pagination = data['vacancies'], data['nextPagination']
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        offset, limit = int(query.get('offset', ['0'])[0]), int(query.get('limit', ['10'])[0])
        end, total, finished = (pagination[k] for k in ('offset', 'totalCount', 'isFinished'))
        if (offset < 0 or limit < 1 or type(end) is not int or type(total) is not int or total < 0
                or type(finished) is not bool or not isinstance(rows, list)
                or len(rows) != min(limit, max(0, total - offset))
                or end != offset + len(rows) or finished != (end >= total)):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            if row.get('redirectUrl'):
                continue  # External campaigns (e.g. internships) have no public career card.
            key, title, slug = row['urlSlug'], row['title'].strip(), row['seoSlug']
            category = CATEGORIES[row['category']]
            if (not re.fullmatch(UUID, key) or not title or not isinstance(slug, str)
                    or not slug.strip() or slug in ('.', '..') or any(c in slug for c in '/?#')):
                raise ValueError('неполная карточка')
            # The publication UUID identifies the card; the server resolves its location.
            url = f'{BASE}/career/{category}/vacancy/moscow/{quote(slug, safe="")}/{key}/'
            items.append(Item(SOURCE, 'site', key, url, title + ' | @Т-Банк',
                              hint_title=title, remote_format=False))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if not finished:
            query['offset'] = [str(end)]
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача Т-Банка не распознана — проверь API сайта') from e


def parse_detail(text: str, item: Item) -> Item:
    try:
        row = _payload(text)
        if row['vacancyId'] != item.external_id or not row['title'].strip():
            raise ValueError('описание другой вакансии')
        if row['status'] not in ('published', 'not-found'):
            raise ValueError('неизвестный статус карточки')
        if row['status'] == 'not-found' or row.get('redirectUrl'):
            item.remote_format = False
            item.text += '\nВакансия закрыта или перенесена'
            return item
        tags = row.get('tags') or []
        if not isinstance(tags, list) or any(not isinstance(t, dict) or not isinstance(t.get('text'), str) for t in tags):
            raise ValueError('неверный формат работы')
        item.remote_format = any(t['text'].strip().lower().replace('ё', 'е') == 'удаленный' for t in tags)
        blocks = row['description']
        if not isinstance(blocks, list):
            raise ValueError('неверное описание')
        elements = []
        for block in blocks:
            content = block['content']
            if isinstance(content, str):
                elements.append(BeautifulSoup(content, 'html.parser'))
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part['description'], str):
                        raise ValueError('неверный блок описания')
                    elements.append(BeautifulSoup(part['description'], 'html.parser'))
            else:
                raise ValueError('неверный блок описания')
        return career.add_detail(item, elements, extra='Формат работы: ' + ', '.join(t['text'] for t in tags))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('карточка Т-Банка не распознана — проверь API сайта') from e


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=30, profile=None):
    def api_fetch(url):
        if url.startswith(API + 'getVacancies?'):
            query = parse_qs(urlsplit(url).query)
            body = {'filters': {'generatedGraphQL': {
                'type': 'T_CAREER', 'status': 'ACTIVE',
                'searchQuery': query['searchQuery'][0],
                'includeSeoAndPcPublications': False, 'includeInternshipPublications': True,
                'userGroup': {'groups': ['CONTROL'], 'type': 'SPECIFIC'},
                'or': [{'category': key} for key in CATEGORIES]}},
                'pagination': {'offset': int(query.get('offset', ['0'])[0])},
                'limit': int(query.get('limit', ['10'])[0])}
            return fetch(API + 'getVacancies', json=body)
        match = re.fullmatch(re.escape(BASE) + r'/career/(it|back-office)/vacancy/[^/]+/[^/]+/(' + UUID + r')/', url)
        if not match:
            raise SourceError('неизвестный адрес карточки Т-Банка')
        category = next(key for key, value in CATEGORIES.items() if value == match.group(1))
        return fetch(API + 'getVacancyDescription', json={
            'urlSlug': match.group(2), 'options': {'groups': ['CONTROL'], 'category': category}})
    return career.collect(SOURCE, urls, api_fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
