from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class SourceError(Exception):
    """Источник не прочитан: сеть, блокировка, изменилась вёрстка. Закладку не двигаем."""


@dataclass
class Item:
    """Сырая единица из источника: пост канала, карточка сайта, блок письма LinkedIn."""
    source: str                     # "tg:nodatanojobs", "site:jabka", "linkedin"
    kind: str                       # telegram | site | linkedin_job | linkedin_post
    external_id: str                # id поста / вакансии внутри источника
    url: str
    text: str
    published_at: Optional[datetime] = None
    hint_title: Optional[str] = None
    links: list[str] = field(default_factory=list)
    anchors: list[tuple[str, str]] = field(default_factory=list)   # (ссылка, текст ссылки)
    blocks: list[tuple[str, str]] = field(default_factory=list)    # цитаты со ссылкой: (текст цитаты, ссылка)
    via: Optional[str] = None       # пришло из подборки этого источника (для статистики и подписи)


@dataclass
class Verdict:
    """Результат разбора одного Item."""
    item: Item
    is_vacancy: bool = False
    title: str = ""
    company: Optional[str] = None
    role: str = "other"
    grade: str = "unknown"
    remote_from_russia: str = "unknown"   # yes | no | unknown
    salary: Optional[str] = None
    contact: Optional[str] = None
    reason: str = ""
    by_llm: bool = False
    num: int = 0                          # номер в письме (для отметки «Отозвался»)
    bucket: str = "drop"                  # main | unknown_format | network | drop
    drop_reason: str = ""
    also_in: list[str] = field(default_factory=list)


@dataclass
class SourceResult:
    source: str
    items: list[Item] = field(default_factory=list)
    new_bookmark: Optional[str] = None
    error: Optional[str] = None
