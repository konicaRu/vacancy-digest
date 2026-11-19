"""Подтверждённые связи публикаций и осторожные предположения, без записи состояния."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlparse

from .classify import canonical_url, dedup, dedup_key, norm, remote_of, _same_vacancy
from .models import Verdict

VERSION = 'conservative-v1'


def identity(url: str) -> str:
    """Только конкретная карточка/ID. Общие формы, контакты и агрегаторы исключены."""
    p = urlparse(canonical_url(url))
    host = (p.hostname or '').lower().removeprefix('www.')
    if p.scheme not in ('http', 'https') or host in ('t.me', 'telegram.me', 'jabka.work', 'youngjunior.ru'):
        return ''
    if p.username or p.password:
        return ''
    path = p.path.rstrip('/')
    route = re.search(r'/(?:jobs?|vacanc(?:y|ies)|positions|requisitions)(?:/|$)', path, re.I)
    if not route:
        return ''
    tail = path[route.end():].strip('/')
    if any(segment.lower() in ('page', 'search', 'filter', 'filters', 'category', 'categories',
                               'apply', 'application', 'list', 'all') for segment in tail.split('/')):
        return ''
    query = parse_qsl(p.query, keep_blank_values=True)
    if any(k.lower() in ('page', 'offset', 'search', 'q', 'filter', 'category') for k, _ in query):
        return ''
    ids = [(k.lower(), v) for k, v in query
           if k.lower() in ('jobid', 'job_id', 'vacancyid', 'vacancy_id', 'gh_jid', 'requisitionid')
           or (k.lower() == 'id' and not tail)]
    if len(ids) > 1:
        return ''
    if len(ids) == 1 and ids[0][1]:
        return host + ':' + p.path.rstrip('/') + '?' + p.query
    if re.search(r'/(?:jobs?|vacanc(?:y|ies)|positions|requisitions)/(?:[^/]+/)*[^/]*\d[^/]*$', path, re.I):
        return host + ':' + path + ('?' + p.query if p.query else '')
    return ''


def identities(v: Verdict) -> set[str]:
    urls = [v.item.url, *v.item.links]
    if v.contact and v.contact.startswith('http'):
        urls.append(v.contact)
    # LLM-invented contacts must not establish identity: only URLs present in the input.
    return set(v.confirmed_identities) | {key for url in urls if (url != v.contact or url in [v.item.url, *v.item.links])
                                         if (key := identity(url))}


def publication_key(v: Verdict) -> str:
    raw = '\n'.join((v.item.source, v.item.external_id, canonical_url(v.item.url), v.publication_variant))
    return hashlib.sha256(raw.encode()).hexdigest()


def _date(value):
    return datetime.fromisoformat(value).replace(tzinfo=None) if value else None


def _title_context(title):
    words = norm(title).split()
    generic = {'аналитик', 'аналитика', 'данных', 'data', 'analyst', 'для', 'в', 'по', 'команды',
               'команду', 'команда', 'senior', 'middle', 'junior', 'ведущий', 'старший'}
    return {w for w in words if w not in generic}


def _content(text):
    # Conditions and promotional tails are shared by many unrelated vacancies.
    text = re.split(r'условия(?:\s+работы)?\s*(?::|\n|$)|что мы предлагаем|работа у нас|мы предлагаем|benefits|what we offer',
                    text, maxsplit=1, flags=re.I)[0]
    return {w for w in norm(text).split() if len(w) > 3 and w not in
            {'удаленно', 'работа', 'обучение', 'аналитик', 'данных', 'команда', 'требования', 'задачи'}}


def _semantic(a, b):
    if not a.get('company') or norm(a['company']) != norm(b.get('company')):
        return ''
    if a.get('identity') and b.get('identity') and a['identity'] != b['identity']:
        return ''
    ga, gb = a.get('grade', 'unknown'), b.get('grade', 'unknown')
    if ga != 'unknown' and gb != 'unknown' and ga != gb:
        return ''
    ca, cb = _title_context(a['title']), _title_context(b['title'])
    if not ca or ca != cb:
        return ''
    ta, tb = _content(a.get('text', '')), _content(b.get('text', ''))
    common = len(ta & tb)
    if common >= 12 and common / max(min(len(ta), len(tb)), 1) >= .5:
        return 'Совпадают работодатель, направление команды и содержательная часть описания'
    return ''


def _recent(row, now, days):
    sent = _date(row.get('reported_at'))
    return row.get('status') in ('applied', 'reviewed') or bool(sent and sent >= now - timedelta(days=days))


def _format_restriction(v):
    return (v.is_vacancy and v.remote_from_russia == 'no' and bool(identity(v.item.url))
            and remote_of(v.item.text, v.item.remote_format) == 'no')


def analyze(verdicts: list[Verdict], history: list[dict], now: datetime, exact_days: int = 30,
            permanent_confirmed: bool = False) -> list[dict]:
    """Изменяет только verdicts; возвращает пакет для атомарной записи после отправки."""
    now = now.replace(tzinfo=None)
    candidates = [v for v in verdicts if v.bucket != 'drop' or _format_restriction(v)]
    posts = {}
    for v in candidates:
        v.confirmed_identities = []
        posts.setdefault((v.item.source, v.item.external_id, canonical_url(v.item.url)), []).append(v)
    for members in posts.values():
        signatures = {(tuple(sorted(identities(v))), norm(v.title), norm(v.company)) for v in members}
        if len(signatures) > 1:
            for v in members:
                signature = '\n'.join([*sorted(identities(v)), norm(v.title), norm(v.company)])
                v.publication_variant = hashlib.sha256(signature.encode()).hexdigest()[:16]
    rows = []
    for v in candidates:
        if v.item.employer:
            v.company = v.item.employer
        elif not v.company and any((urlparse(u).hostname or '') == 'career.avito.com' for u in v.item.links):
            v.company = 'Авито'
        keys = identities(v)
        key = publication_key(v)
        v.possible_duplicate = None
        v.source_links = [(v.item.source, v.item.url)]
        v.duplicate_group = 'vacancy:' + key
        rows.append(dict(key=key, entity_id=v.duplicate_group, identity=next(iter(keys)) if len(keys) == 1 else '',
                         ambiguous=len(keys) > 1, title=v.title, company=v.company, grade=v.grade,
                         text=v.item.text, url=v.item.url, source=v.item.source,
                         original_text=v.item.original_text or v.item.text,
                         team=' '.join(sorted(_title_context(v.title))),
                         format_restriction=bool(_format_restriction(v)),
                         observed_at=now.isoformat(timespec='seconds'),
                         external_id=v.item.external_id, links=v.item.links,
                         published_at=v.item.published_at.isoformat() if v.item.published_at else None,
                         first_seen=now.isoformat(timespec='seconds'), ledger_key=dedup_key(v), suggestion=None))
    pairs = sorted(zip(candidates, rows), key=lambda pair: (
        0 if pair[1]['format_restriction'] else 1,
        0 if identity(pair[0].item.url) else 1, -len(pair[0].item.text), pair[1]['key']))
    kept = []
    for v, row in pairs:
        matches = [h for h in history if (row['identity'] and h.get('identity') == row['identity'])
                   or (canonical_url(h.get('url')) == canonical_url(row['url'])
                       and _same_vacancy(v, norm(h.get('title')), norm(h.get('company')),
                                         h.get('url'), h.get('source'), archived=h))]
        entity_ids = {h['entity_id'] for h in matches}
        # Reuse an archived entity even when a normal delivery has aged out of suppression.
        if len(entity_ids) == 1:
            v.duplicate_group = row['entity_id'] = next(iter(entity_ids))
            row['first_seen'] = min([row['first_seen'], *(h['first_seen'] for h in matches)])
        twin = next(((k, r) for k, r in kept if row['identity'] and r['identity'] == row['identity']), None)
        if twin:
            k, r = twin
            v.duplicate_group = row['entity_id'] = r['entity_id']
            row['first_seen'] = r['first_seen']
            k.source_links.extend(v.source_links)
            if v.item.source != k.item.source and v.item.source not in k.also_in:
                k.also_in.append(v.item.source)
            if v.bucket == 'unknown_format' and k.bucket == 'main':
                k.bucket, k.remote_from_russia = 'unknown_format', 'unknown'
            v.bucket, v.drop_reason = 'drop', ('источник вакансии запрещает удалёнку из РФ'
                                             if r['format_restriction'] else 'дубль по исходной вакансии')
        elif any(h.get('format_restriction') and _date(h.get('observed_at'))
                 and _date(h['observed_at']) >= now - timedelta(days=exact_days) for h in matches):
            v.bucket, v.drop_reason = 'drop', 'источник вакансии запрещает удалёнку из РФ'
        elif any(_recent(h, now, exact_days) or (permanent_confirmed and h.get('reported_at')) for h in matches):
            v.bucket, v.drop_reason = 'drop', 'уже присылал раньше'
        else:
            kept.append((v, row))
    recent = [h for h in history if _recent(h, now, exact_days)]
    dedup(verdicts, recent)
    # Existing exact-title/URL rules may establish a group as well; never lose suppressed publications.
    redirects = {}
    for v, row in pairs:
        if v.drop_reason == 'уже присылал раньше' and row['entity_id'] == 'vacancy:' + row['key']:
            previous = next((h for h in recent if _same_vacancy(
                v, norm(h.get('title')), norm(h.get('company')), h.get('url'), h.get('source'), archived=h)), None)
            if previous:
                v.duplicate_group = previous['entity_id']
                row['first_seen'] = min(row['first_seen'], previous['first_seen'])
        if row['entity_id'] != v.duplicate_group:
            redirects[row['entity_id']] = v.duplicate_group
    for v, row in pairs:
        entity = v.duplicate_group
        visited = set()
        while entity in redirects and entity not in visited:
            visited.add(entity)
            entity = redirects[entity]
        row['entity_id'] = v.duplicate_group = entity
    group_ids = {}
    for _, row in pairs:
        if row['identity']:
            group_ids.setdefault(row['entity_id'], set()).add(row['identity'])
    for _, row in pairs:
        known = group_ids.get(row['entity_id'], set())
        if len(known) == 1:
            row['identity'] = next(iter(known))
        elif len(known) > 1:
            row['ambiguous'] = True
    visible = [(v, r) for v, r in pairs if v.bucket != 'drop']
    for index, (v, row) in enumerate(visible):
        if row['ambiguous']:
            continue
        options = [(h, False) for h in history if not h.get('ambiguous')
                   and _date(h.get('first_seen')) and _date(h['first_seen']) >= now - timedelta(days=10)
                   and h['entity_id'] != row['entity_id']]
        options += [(r, True) for _, r in visible[:index] if not r['ambiguous']]
        for other, current in options:
            reason = _semantic(row, other)
            if reason:
                suggestion = dict(key=other['key'], url=other['url'], title=other['title'],
                                  source=other['source'], date=other.get('reported_at') or other['first_seen'],
                                  current=current, reason=reason, version=VERSION)
                v.possible_duplicate = row['suggestion'] = suggestion
                break
    return rows
