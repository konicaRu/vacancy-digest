"""Сторож Райффайзена (решение пользователя 27.11).

На career.raiffeisen.ru нет списка вакансий: /vacancies переадресует на главную, «Откликнуться» — анкета в пул
по направлению, сами вакансии банк публикует на hh.ru (их не берём). Сторож ничего не собирает: только
предупреждает в письме, когда на странице появятся ссылки на вакансии или JobPosting — тогда писать адаптер.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import SourceResult
from . import career

SOURCE = 'site:raiffeisen'
VACANCY_LINK = re.compile(r'/vacanc(?:y|ies)/(?!embed\b)[^/?#]+')


def collect(urls, fetch, is_seen, first_run, lookback_days=14, max_pages=1, profile=None):
    try:
        found = []
        for url in urls:
            soup = BeautifulSoup(fetch(url), 'html.parser')
            if career.job_posting(soup) or any(VACANCY_LINK.search(a['href']) for a in soup.select('a[href]')):
                found.append(url)
    except Exception as e:
        return SourceResult(source=SOURCE, error=f'{type(e).__name__}: {e}')
    warning = (f'на карьерном сайте появились вакансии ({", ".join(found)}) — пора подключать адаптер'
               if found else None)
    return SourceResult(source=SOURCE, warning=warning, new_bookmark=datetime.now().isoformat(timespec='seconds'))
