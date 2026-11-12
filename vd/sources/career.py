"""Общий обход карьерных сайтов: карточки → новые подходящие описания."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..classify import ROLE_HINT, title_match
from ..models import Item, SourceError, SourceResult


def parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
    except ValueError:
        return None


def job_posting(soup: BeautifulSoup) -> dict:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict) and node.get('@type') == 'JobPosting':
                return node
    return {}


def add_detail(item: Item, elements, extra: str = '', published: str | None = None) -> Item:
    """Добавить только поля самой вакансии, а не меню или похожие предложения."""
    elements = [el for el in elements if el is not None]
    if not elements or not any(el.get_text(strip=True) for el in elements):
        raise SourceError('описание вакансии не найдено — проверь вёрстку сайта')
    item.text = '\n'.join([item.text, extra, *(el.get_text(' ', strip=True) for el in elements)]).strip()
    item.links = list(dict.fromkeys(urljoin(item.url, a['href'])
                                  for el in elements for a in el.select('a[href]')))
    item.published_at = item.published_at or parse_date(published)
    return item


def collect(source, urls, fetch, is_seen, first_run, parse_page, parse_detail,
            lookback_days=5, max_pages=10, profile=None) -> SourceResult:
    cutoff = date.today() - timedelta(days=lookback_days)
    found: dict[str, Item] = {}
    skipped: list[str] = []
    visited: set[str] = set()
    warnings: list[str] = []
    queries = (profile or {}).get('title_queries', [])
    try:
        for start_url in urls:
            url = start_url
            page_ids: set[frozenset[str]] = set()
            for _ in range(max_pages):
                if url in visited:
                    break
                visited.add(url)
                items, next_url = parse_page(fetch(url), url)
                ids = {item.external_id for item in items}
                signature = frozenset(ids)
                if ids and signature in page_ids:
                    if next_url:
                        warnings.append('сайт повторил страницу — выдача прочитана не целиком')
                    break
                page_ids.add(signature)
                for item in items:
                    if item.external_id in found or item.external_id in skipped or is_seen(source, item.external_id):
                        continue
                    if first_run and item.published_at and item.published_at.date() < cutoff:
                        skipped.append(item.external_id)
                        continue
                    title = item.hint_title or ''
                    relevant = not title_match(title, queries) if queries else bool(ROLE_HINT.search(title))
                    if relevant:
                        item = parse_detail(fetch(item.url), item)
                        if first_run and item.published_at and item.published_at.date() < cutoff:
                            skipped.append(item.external_id)
                            continue
                    found[item.external_id] = item
                if not next_url:
                    break
                url = next_url
            else:
                warnings.append(f'достигнут лимит {max_pages} страниц — выдача прочитана не целиком')
    except Exception as e:
        return SourceResult(source=source, error=f'{type(e).__name__}: {e}')
    return SourceResult(source=source, items=list(found.values()), seen_ids=skipped,
                        new_bookmark=datetime.now().isoformat(timespec='seconds'),
                        warning='; '.join(dict.fromkeys(warnings)) or None)
