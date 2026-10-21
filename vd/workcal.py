"""Производственный календарь РФ: письма — только в рабочие дни (с переносами).

Календарь года берём с isdayoff.ru одной строкой «0/1» на каждый день (1 — выходной) и кэшируем
в data/calendar-<год>.txt — дальше без сети. Не скачался — правило «пн–пт» и предупреждение в письмо;
плохой ответ не кэшируем, следующий запуск попробует снова.
"""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path
from typing import Callable, Optional

URL = "https://isdayoff.ru/api/getdata?year={year}"


def _check(data: str, year: int) -> str:
    days = 366 if calendar.isleap(year) else 365
    if len(data) != days or set(data) - {"0", "1"}:
        raise ValueError(f"ожидалось {days} символов 0/1, получено {len(data)}: {data[:40]!r}")
    return data


def is_workday(day: date, cache_dir: Path, fetch: Callable[[str], str], url: str = URL) -> tuple[bool, Optional[str]]:
    """(рабочий ли день, предупреждение или None)."""
    path = cache_dir / f"calendar-{day.year}.txt"
    try:
        if path.exists():
            data = _check(path.read_text(encoding="utf-8").strip(), day.year)
        else:
            data = _check(fetch(url.format(year=day.year)).strip(), day.year)
            cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(data, encoding="utf-8")
    except Exception as e:
        return day.weekday() < 5, f"производственный календарь не загружен ({type(e).__name__}: {e}) — работаю по пн–пт"
    return data[day.timetuple().tm_yday - 1] == "0", None
