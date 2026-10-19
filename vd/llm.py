"""Разбор поста локальной моделью через LM Studio (OpenAI-совместимый API).

Модели достаётся одно узкое суждение: «что это за вакансия и подходит ли она».
Закладки, дубли и отправку делает код.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

from .models import Item, Verdict

log = logging.getLogger(__name__)

ROLES = ["product_analyst", "data_analyst", "bi_analyst", "system_analyst",
         "business_analyst", "marketing_analyst", "financial_analyst", "other"]
GRADES = ["intern", "junior", "middle", "senior", "lead", "unknown"]

SCHEMA = {
    "type": "object",
    "properties": {
        "is_vacancy": {"type": "boolean"},
        "title": {"type": "string"},
        "company": {"type": "string"},
        "role": {"type": "string", "enum": ROLES},
        "grade": {"type": "string", "enum": GRADES},
        "remote_from_russia": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "salary": {"type": "string"},
        "contact": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["is_vacancy", "title", "company", "role", "grade",
                 "remote_from_russia", "salary", "contact", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Ты — фильтр вакансий для одного кандидата.
Профиль кандидата: {about}

Тебе дают текст одного Telegram-поста, карточки вакансии с сайта или фрагмента письма LinkedIn.
Ответь строго одним JSON-объектом по схеме, без пояснений вне JSON.
Если текст начинается со строки «Вакансия: …», а ниже дан контекст поста-подборки, разбирай
только вакансию из первой строки; из контекста бери лишь общие условия (локация, формат работы).

Поля:
- is_vacancy: true, только если это объявление о найме на конкретную должность.
  Реклама курсов и интенсивов, подборки ссылок на другие посты, статьи и советы — false.
  Рекламная подпись канала в конце поста не делает вакансию рекламой.
- title: должность коротко, как в тексте.
- company: название компании или "" если не указано.
- role: product_analyst (продуктовый аналитик, product analyst),
  data_analyst (аналитик данных, data analyst, data-аналитик, дата-аналитик),
  bi_analyst (BI-аналитик), system_analyst, business_analyst, marketing_analyst,
  financial_analyst, other. «Product/Data Analyst» — это product_analyst.
- grade: самый младший уровень, на который готовы взять («Junior/Middle» → junior,
  «Middle+/Senior» → middle). Если не указан — unknown.
- remote_from_russia:
  yes — можно работать полностью удалённо, находясь в России
        («удалёнка по РФ», «из любой точки», «удалённо», «офис по желанию»);
  no — только офис или гибрид, релокация, «удалёнка не из РФ», «кроме России»,
        работа только для жителей другой страны;
  unknown — формат не указан или неясен.
- salary: вилка как в тексте или "".
- contact: ссылка или @username для отклика, или "".
- reason: одна короткая фраза по-русски — почему подходит или нет кандидату."""


class LLMUnavailable(Exception):
    pass


def _lms_binary() -> str | None:
    found = shutil.which("lms")
    if found:
        return found
    candidate = Path(os.path.expanduser("~")) / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms")
    return str(candidate) if candidate.exists() else None


class LMStudioClient:
    def __init__(self, cfg: dict, about: str):
        self.base = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.timeout = cfg.get("timeout_sec", 180)
        self.max_chars = cfg.get("max_chars_per_item", 3500)
        self.suffix = cfg.get("prompt_suffix", "") or ""
        self.autostart = cfg.get("autostart_server", True)
        self.system = SYSTEM_PROMPT.format(about=about.strip())
        self._tried_load = False

    # ---------- сервер ----------
    def _ping(self) -> bool:
        try:
            return requests.get(f"{self.base}/models", timeout=5).ok
        except requests.RequestException:
            return False

    def ensure_server(self) -> bool:
        if self._ping():
            return True
        if not self.autostart:
            return False
        lms = _lms_binary()
        if not lms:
            log.warning("LM Studio не отвечает, а утилита lms не найдена")
            return False
        log.info("Запускаю сервер LM Studio: %s server start", lms)
        try:
            subprocess.run([lms, "server", "start"], timeout=90, capture_output=True)
        except Exception as e:
            log.warning("Не удалось запустить сервер LM Studio: %s", e)
            return False
        for _ in range(15):
            time.sleep(2)
            if self._ping():
                return True
        return False

    def _load_model(self) -> None:
        if self._tried_load:
            return
        self._tried_load = True
        lms = _lms_binary()
        if lms:
            log.info("Загружаю модель %s", self.model)
            try:
                subprocess.run([lms, "load", self.model], timeout=300, capture_output=True)
            except Exception as e:
                log.warning("lms load не сработал: %s", e)

    # ---------- разбор ----------
    def classify(self, item: Item) -> Verdict:
        text = item.text[: self.max_chars]
        user = f"Источник: {item.source}\n---\n{text}"
        if self.suffix:
            user += f"\n{self.suffix}"
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 500,
            "messages": [{"role": "system", "content": self.system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "vacancy", "strict": True, "schema": SCHEMA}},
        }
        data = None
        for attempt in range(2):
            try:
                r = requests.post(f"{self.base}/chat/completions", json=payload, timeout=self.timeout)
            except requests.RequestException as e:
                raise LLMUnavailable(str(e))
            if r.status_code >= 400:
                body = r.text[:300]
                if "model" in body.lower() and not self._tried_load:
                    self._load_model()
                    continue
                raise LLMUnavailable(f"HTTP {r.status_code}: {body}")
            content = r.json()["choices"][0]["message"].get("content") or ""
            data = _extract_json(content)
            if data is not None:
                break
        if data is None:
            raise ValueError("модель не вернула JSON")
        return Verdict(
            item=item,
            is_vacancy=bool(data.get("is_vacancy")),
            title=(data.get("title") or item.hint_title or "").strip(),
            company=(data.get("company") or "").strip() or None,
            role=data.get("role") if data.get("role") in ROLES else "other",
            grade=data.get("grade") if data.get("grade") in GRADES else "unknown",
            remote_from_russia=data.get("remote_from_russia") if data.get("remote_from_russia") in ("yes", "no", "unknown") else "unknown",
            salary=(data.get("salary") or "").strip() or None,
            contact=(data.get("contact") or "").strip() or None,
            reason=(data.get("reason") or "").strip(),
            by_llm=True,
        )


def _extract_json(content: str):
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None
