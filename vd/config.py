from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

MAIL_PRESETS = {
    "gmail":  {"imap": "imap.gmail.com",  "smtp": "smtp.gmail.com",  "smtp_port": 465},
    "yandex": {"imap": "imap.yandex.ru",  "smtp": "smtp.yandex.ru",  "smtp_port": 465},
}


class ConfigError(Exception):
    pass


def load_config(root: Path) -> dict:
    """Читает config.yaml и secrets.env заново при каждом запуске.

    Если конфиг не читается — останавливаемся, а не работаем «по умолчанию».
    """
    cfg_path = root / "config.yaml"
    if not cfg_path.exists():
        raise ConfigError(f"Не найден {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    load_dotenv(root / "secrets.env", override=True)
    provider = (cfg.get("mail", {}).get("provider") or "gmail").lower()
    if provider not in MAIL_PRESETS:
        raise ConfigError(f"mail.provider должен быть gmail или yandex, а не {provider!r}")
    cfg.setdefault("mail", {})
    cfg["mail"]["preset"] = MAIL_PRESETS[provider]
    cfg["mail"]["user"] = os.getenv("EMAIL_USER", "").strip()
    cfg["mail"]["password"] = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not cfg["mail"].get("to"):
        cfg["mail"]["to"] = cfg["mail"]["user"]
    return cfg
