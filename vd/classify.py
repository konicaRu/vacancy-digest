"""Отбор: предфильтр кодом → разбор (LLM или запасной по ключевым словам) → корзина → дедуп."""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Optional

from .llm import LLMUnavailable
from .models import Item, Verdict

log = logging.getLogger(__name__)

ROLE_HINT = re.compile(r"аналитик|analyst|analytics|аналитика|\bbi\b", re.I)
DIGEST_HINT = re.compile(r"подборк|за (прошлую )?неделю|актуальных вакансий", re.I)
HIRING_HINT = re.compile(r"ищем|ищу|вакансия|hiring|#hiring|open position|открыта позиция|в команду", re.I)


# ---------------------------------------------------------------- предфильтр
def prefilter(item: Item) -> Optional[str]:
    """Возвращает причину отсева или None, если пост стоит показывать модели."""
    text = item.text or ""
    if len(text.strip()) < 30 and not item.hint_title:
        return "пустой пост"
    if item.kind == "linkedin_post":
        return None if HIRING_HINT.search(text) else "пост без признаков найма"
    if not ROLE_HINT.search(text):
        return "нет слова «аналитик»"
    tme_links = sum(1 for link in item.links if "t.me/" in link)
    if DIGEST_HINT.search(text[:200]) and tme_links >= 3:
        return "подборка (дубль постов канала)"
    return None


# ------------------------------------------------- запасной разбор без LLM
NO_RF = re.compile(r"не\s*из\s*рф|\(не\s*рф\)|не\s*рф\b|кроме\s+(?:беларуси\s+и\s+)?росси|кроме\s+рф|"
                   r"not\s+(?:from\s+)?russia|excluding\s+russia|except\s+russia", re.I)
REMOTE = re.compile(r"удал[её]нн|удал[её]нк|удаленно|удалённо|remote|из любой точки", re.I)
OFFICE = re.compile(r"\bофис|гибрид|hybrid|релокац|relocat|onsite|on-site", re.I)
SALARY = re.compile(r"(\d[\d\s]{2,}(?:\s*[-–]\s*\d[\d\s]{2,})?\s*(?:₽|руб|\$|USD|€|EUR|USDT))", re.I)
CONTACT = re.compile(r"(@[A-Za-z0-9_]{4,})")
EMOJI_PUNCT = re.compile(r"^[\W_]+", re.U)


def _title_from_text(item: Item) -> str:
    if item.hint_title:
        return item.hint_title.strip()
    for line in (item.text or "").splitlines():
        line = EMOJI_PUNCT.sub("", line).strip()
        if len(line) >= 5:
            return line[:140]
    return ""


def _role_of(s: str) -> str:
    s = s.lower()
    if re.search(r"продукт\w*\s+(?:/\s*\w+\s+)?аналитик|product\s*(?:/\s*data\s*)?analyst|аналитик\w*\s+продукт", s):
        return "product_analyst"
    if re.search(r"аналитик\w*\s+данных|data[\s\-]*analyst|data[\s\-]*аналитик|дата[\s\-]*аналитик", s):
        return "data_analyst"
    if re.search(r"\bbi[\s\-]*(?:analyst|аналитик)", s):
        return "bi_analyst"
    if re.search(r"системн\w*\s+аналитик|system\s+analyst", s):
        return "system_analyst"
    if re.search(r"бизнес[\s\-]*аналитик|business\s+analyst", s):
        return "business_analyst"
    if re.search(r"маркетинг\w*\s+аналитик|marketing\s+analy", s):
        return "marketing_analyst"
    if re.search(r"финансов\w*\s+аналитик|financial\s+analyst", s):
        return "financial_analyst"
    return "other"


def _grade_of(s: str) -> str:
    s = s.lower()
    if re.search(r"стаж[её]р|intern|trainee", s):
        return "intern"
    if re.search(r"junior|джун|младш", s):
        return "junior"
    if re.search(r"middle|мидл", s):
        return "middle"
    if re.search(r"senior|сеньор|старш|ведущ", s):
        return "senior"
    if re.search(r"lead|лид|head", s):
        return "lead"
    return "unknown"


def remote_of(text: str) -> str:
    if NO_RF.search(text):
        return "no"
    if REMOTE.search(text):
        return "yes"
    if OFFICE.search(text):
        return "no"
    return "unknown"


def keyword_classify(item: Item) -> Verdict:
    text = item.text or ""
    title = _title_from_text(item)
    role = _role_of(title)
    if role == "other":
        role = _role_of(text[:300])
    company = None
    # jabka: «@Компания» или «@ | Компания» (живая карточка — @ и название разными частями)
    m = re.search(r"@\s*(?:\|\s*)?([^|·\n]{2,40})", text) if item.kind == "site" else None
    if m:
        company = m.group(1).strip()
    else:
        m = re.search(r"\bв[о]?\s+([A-ZА-ЯЁ][\w.\-]+(?:\s+[A-ZА-ЯЁ][\w.\-]+)?)", title)
        if m:
            company = m.group(1)
    ad_like = re.search(r"курс|интенсив|вебинар|мини-курс", text[:200], re.I) and not re.search(
        r"задачи|требования|обязанности|условия", text, re.I)
    sal = SALARY.search(text)
    # на сайтах «@Компания» — это название работодателя, а не контакт
    contact = CONTACT.search(text) if item.kind != "site" else None
    return Verdict(
        item=item,
        is_vacancy=not ad_like,
        title=title,
        company=company,
        role=role,
        grade=_grade_of(title),
        remote_from_russia=remote_of(text),
        salary=sal.group(1).strip() if sal else None,
        contact=contact.group(1) if contact else None,
        reason="",  # про режим без модели предупреждает плашка в письме
        by_llm=False,
    )


# ---------------------------------------------------------------- корзины
TITLE_TAIL = re.compile(r"\s[—–-]\s")


def _has_word(text: str, term: str, whole: bool = False) -> bool:
    """По началу слова («системный» ловит «системного»); whole — только целое слово
    («аналитик» не ловит «…для аналитики»). Дефис разделяет слова: «BI-Аналитик», «Data-аналитик»."""
    tail = r"(?!\w)" if whole else ""
    return re.search(r"(?<!\w)" + re.escape(term.lower()) + tail, text) is not None


def title_match(title: str, queries: list[dict]) -> str:
    """Запросы в духе hh.ru NAME:(include…) AND NOT NAME:(exclude…), проверяется должность до « — »
    (на jabka после тире идёт описание). Пусто — подходит, иначе причина отсева."""
    role = TITLE_TAIL.split(title, maxsplit=1)[0].lower()
    stop = ""
    for q in queries:
        if not any(_has_word(role, t, whole=True) for t in q.get("include", [])):
            continue
        bad = next((t for t in q.get("exclude", []) if _has_word(role, t)), None)
        if bad is None:
            return ""
        stop = stop or bad
    return f"стоп-слово в должности: {stop}" if stop else "должность не подходит под запрос"


def decide(v: Verdict, profile: dict) -> Verdict:
    targets = set(profile.get("target_roles", ["product_analyst", "data_analyst"]))
    exclude_grades = set(profile.get("exclude_grades", ["intern", "junior"]))
    exclude_words = [w.lower() for w in profile.get("exclude_title_words", [])]
    queries = profile.get("title_queries")

    def drop(reason: str) -> Verdict:
        v.bucket, v.drop_reason = "drop", reason
        return v

    if not v.is_vacancy:
        return drop("не вакансия")
    title_l = (v.title or "").lower()
    if any(w in title_l for w in exclude_words):
        return drop("стоп-слово в должности")
    if v.item.kind == "linkedin_post":
        # от знакомых показываем мягче: любая аналитика, кроме явно не-удалённой
        if v.remote_from_russia == "no":
            return drop("нельзя удалённо из РФ")
        v.bucket = "network"
        return v
    if queries:
        reason = title_match(v.title or "", queries)
        if reason:
            return drop(reason)
    elif v.role not in targets:
        return drop(f"роль: {v.role}")
    if v.grade in exclude_grades:
        return drop(f"грейд: {v.grade}")
    if v.remote_from_russia == "no":
        return drop("нельзя удалённо из РФ")
    v.bucket = "main" if v.remote_from_russia == "yes" else "unknown_format"
    return v


# ---------------------------------------------------------------- дедуп
_STOP = re.compile(r"\b(вакансия|в|во|компанию|компания|ищем|ищет)\b")


def norm(s: Optional[str]) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s)
    s = _STOP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def dedup_key(v: Verdict) -> str:
    return f"{norm(v.company)}|{norm(v.title)}"


def _similar(t1: str, c1: str, t2: str, c2: str) -> bool:
    if not t1 or not t2:
        return False
    ratio = SequenceMatcher(None, t1, t2).ratio()
    if c1 and c2:
        return c1 == c2 and ratio >= 0.8
    if c1 or c2:
        return ratio >= 0.9
    return ratio >= 0.95 and len(t1) > 25


def dedup(verdicts: list[Verdict], recent_ledger: list[dict]) -> None:
    """Помечает дубли (внутри запуска и уже отправленные ранее) корзиной drop."""
    ledger_norm = [(norm(r.get("title")), norm(r.get("company")), r.get("dedup_key"), r.get("url"))
                   for r in recent_ledger]
    kept: list[Verdict] = []
    order = {"network": 0, "main": 1, "unknown_format": 2}
    for v in sorted((x for x in verdicts if x.bucket != "drop"), key=lambda x: order.get(x.bucket, 9)):
        t, c, key = norm(v.title), norm(v.company), dedup_key(v)
        # без компании ключ = одно название («|senior data analyst») — тогда дубль только по той же ссылке
        if any(v.item.url == lu or (c and key == lk) or _similar(t, c, lt, lc)
               for lt, lc, lk, lu in ledger_norm):
            v.bucket, v.drop_reason = "drop", "уже присылал раньше"
            continue
        twin = next((k for k in kept if _similar(t, c, norm(k.title), norm(k.company))), None)
        if twin:
            if v.item.source not in twin.also_in and v.item.source != twin.item.source:
                twin.also_in.append(v.item.source)
            v.bucket, v.drop_reason = "drop", "дубль из другого источника"
            continue
        kept.append(v)


# ---------------------------------------------------------------- всё вместе
CONTACT_OK = re.compile(r"^(?:@[A-Za-z0-9_]{4,}|[\w.+\-]+@[\w\-]+\.[\w.\-]+|https?://\S+)$")


def guard_llm(v: Verdict) -> Verdict:
    """Проверка ответа модели кодом.
    • «нельзя удалённо», а в тексте ни слова о формате — модель путает «не подходит» с «не удалённо» → unknown;
    • контакт — только @ник, почта или ссылка (модель кладёт туда «[LinkedIn]», «@»)."""
    if v.remote_from_russia == "no" and remote_of(v.item.text or "") == "unknown":
        v.remote_from_russia = "unknown"
    if v.contact and not CONTACT_OK.match(v.contact):
        v.contact = None
    return v


def classify_all(items: list[Item], profile: dict, llm) -> tuple[list[Verdict], dict]:
    """llm — LMStudioClient или None. Если модель падает по ходу — дальше работаем по ключевым словам."""
    verdicts: list[Verdict] = []
    info = {"llm_used": llm is not None, "llm_failed": False, "llm_errors": 0}
    for item in items:
        reason = prefilter(item)
        if reason:
            verdicts.append(Verdict(item=item, bucket="drop", drop_reason=reason))
            continue
        v = None
        if llm is not None and not info["llm_failed"]:
            try:
                v = llm.classify(item)
            except LLMUnavailable as e:
                log.error("LLM недоступна, переключаюсь на ключевые слова: %s", e)
                info["llm_failed"] = True
            except Exception as e:
                info["llm_errors"] += 1
                log.warning("Не разобран %s: %s", item.url, e)
            else:
                v = guard_llm(v)
        if v is None:
            v = keyword_classify(item)
        verdicts.append(decide(v, profile))
    return verdicts, info
