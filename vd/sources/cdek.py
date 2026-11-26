"""СДЭК: открытый API поиска вакансий и HTML-карточка с JobPosting."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, SourceError
from . import career

SOURCE = 'site:cdek'
BASE = 'https://rabota.cdek.ru'
PAGE_SIZE = 10  # размер страницы API, если limit не задан в ссылке


def parse_page(text: str, url: str):
    try:
        data = json.loads(text)
        rows, total = data['vacancies'], data['total']
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        offset = int(query.get('offset', ['0'])[0])
        limit = int(query.get('limit', [str(PAGE_SIZE)])[0])
        if (not isinstance(rows, list) or type(total) is not int or total < 0 or offset < 0 or limit < 1
                or len(rows) != min(limit, max(0, total - offset))):
            raise ValueError('неполная выдача')
        items = []
        for row in rows:
            ext_id, title = row['id'], row['title'].strip()
            if type(ext_id) is not int or not title:
                raise ValueError('неполная карточка')
            tags = [t for t in row.get('tags') or [] if isinstance(t, dict)]
            formats = ', '.join(t.get('name') or '' for t in tags if t.get('name')) or 'не указан'
            place = ((row.get('location') or {}).get('fullAddress') or '').strip()
            items.append(Item(SOURCE, 'site', str(ext_id), f'{BASE}/vacancies/item/{ext_id}',
                              f'{title} | @СДЭК\nФормат работы: {formats}' + (f'\nЛокация: {place}' if place else ''),
                              hint_title=title, employer='СДЭК',
                              remote_format=any(t.get('code') == 'remote' for t in tags)))
        if len({i.external_id for i in items}) != len(items):
            raise ValueError('повтор карточки')
        next_url = None
        if offset + len(rows) < total:
            query.update(offset=[str(offset + len(rows))], limit=[str(limit)])
            next_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True), fragment=''))
        return items, next_url
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SourceError('выдача СДЭК не распознана — проверь API сайта') from e


def parse_detail(html: str, item: Item) -> Item:
    soup = BeautifulSoup(html, 'html.parser')
    posting = career.job_posting(soup)
    ident = posting.get('identifier') if isinstance(posting.get('identifier'), dict) else {}
    if str(ident.get('value')) != item.external_id:
        raise SourceError('карточка СДЭК не распознана — проверь вёрстку сайта')
    return career.add_detail(item, [soup.select_one('main')], published=posting.get('datePosted'))


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=10, profile=None):
    return career.collect(SOURCE, urls, fetch, is_seen, first_run, parse_page, parse_detail,
                          lookback_days, max_pages, profile)
