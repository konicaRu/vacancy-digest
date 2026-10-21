"""Отметки «Откликнулся» из Google Формы.

Под каждой вакансией в письме — ссылка на formResponse с кодом вакансии (vd-ГГГГММДД-am|pm-N):
один клик записывает код в таблицу ответов. Таблица открыта по ссылке на просмотр, каждый
запуск читает её CSV-выгрузку и переводит найденные вакансии в статус applied.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Callable
from urllib.parse import quote

# только коды выпусков (тестовые «vd-test-…» не подходят): выпуск + номер или номера группы через запятую
CODE_RE = re.compile(r"(vd-\d{8}-(?:am|pm)\d*)-(\d+(?:,\d+)*)(?![\w,])")  # am2 — повторная отправка (--force)
REVIEWED = "Разобрано"


def parse_marks(csv_text: str) -> dict[str, str]:
    """{код вакансии: applied | reviewed} из CSV таблицы ответов (колонка id; пустые и чужие строки пропускаем).
    «vd-20261020-am-7 · Продуктовый аналитик · Авито» — откликнулся на одну;
    «vd-20261020-am-1,2,5 · Разобрано · jabka.work: …» — разобрал группу. Отклик важнее «разобрано»."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return {}
    header = [h.strip().lower() for h in rows[0]]
    col = header.index("id") if "id" in header else len(header) - 1
    marks: dict[str, str] = {}
    for r in rows[1:]:
        value = r[col].strip() if len(r) > col else ""
        m = CODE_RE.match(value)
        if not m:
            continue
        status = "reviewed" if value[m.end():].lstrip(" ·").startswith(REVIEWED) else "applied"
        for n in m.group(2).split(","):
            code = f"{m.group(1)}-{n}"
            if marks.get(code) != "applied":
                marks[code] = status
    return marks


def fetch_marks(marks_cfg: dict, fetch: Callable[[str], str]) -> dict[str, str]:
    return parse_marks(fetch(marks_cfg["sheet_csv_url"]))


def mark_link(marks_cfg: dict, code: str, label: str = "") -> str:
    """Ссылка «Откликнулся»: в таблицу ответов пишется «код · название · компания» — читаемый список откликов."""
    value = f"{code} · {label}" if label else code
    return f'{marks_cfg["form_url"]}?{marks_cfg["form_field"]}={quote(value)}&submit=Submit'
