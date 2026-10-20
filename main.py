"""Утренний дайджест вакансий.

    python main.py              обычный запуск (раз в день, отправка письма)
    python main.py --dry-run    собрать и отобрать, письмо не слать, состояние не менять
    python main.py --force      запустить, даже если сегодня письмо уже ушло
    python main.py --no-llm     без локальной модели, отбор по ключевым словам
    python main.py --stats      сколько вакансий дал каждый источник за 30 дней
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from vd import digest, mailer
from vd.classify import classify_all, dedup, dedup_key
from vd.config import ConfigError, load_config
from vd.expand import expand_bundles
from vd.marks import fetch_marks, mark_link
from vd.llm import LMStudioClient
from vd.sources import jabka, linkedin_mail, make_session, telegram
from vd.store import Store

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("digest")


def setup_logging() -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(ROOT / "logs" / "run.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[fh, sh])


def make_fetcher(cfg: dict):
    session = make_session()
    timeout = cfg.get("run", {}).get("http_timeout_sec", 25)

    def fetch(url: str) -> str:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
        time.sleep(1)  # вежливая пауза между запросами
        return r.text
    return fetch


def collect_all(cfg: dict, store: Store, fetch) -> list:
    results = []
    tg_cfg = cfg["sources"].get("telegram", {})
    for ch in tg_cfg.get("channels", []):
        if not ch.get("enabled", True):
            continue
        name = ch["name"]
        res = telegram.collect(name, store.get_bookmark(f"tg:{name}"), fetch,
                               tg_cfg.get("lookback_days_first_run", 3), tg_cfg.get("max_pages_per_run", 5))
        log.info("%s: новых постов %s%s", res.source, len(res.items), f", ОШИБКА: {res.error}" if res.error else "")
        results.append(res)

    for site in cfg["sources"].get("sites", []):
        if not site.get("enabled", True):
            continue
        if site["name"] == "jabka":
            first_run = store.get_bookmark("site:jabka") is None
            res = jabka.collect(site["urls"], fetch, store.is_seen, first_run, site.get("lookback_days_first_run", 3))
        else:
            log.warning("Сайт %s пока не поддерживается", site["name"])
            continue
        log.info("%s: новых вакансий %s%s", res.source, len(res.items), f", ОШИБКА: {res.error}" if res.error else "")
        results.append(res)

    li = cfg["sources"].get("linkedin_mail", {})
    if li.get("enabled"):
        res = linkedin_mail.collect(li, cfg["mail"], store.get_bookmark("linkedin"))
        log.info("linkedin: элементов %s%s", len(res.items), f", ОШИБКА: {res.error}" if res.error else "")
        results.append(res)
    return results


def run(args) -> int:
    try:
        cfg = load_config(ROOT)
    except ConfigError as e:
        log.error("Конфиг не прочитан, останавливаюсь: %s", e)
        return 2

    store = Store(ROOT / "data" / "state.sqlite")
    try:
        return _run(args, cfg, store)
    finally:
        store.close()


def _run(args, cfg: dict, store: Store) -> int:
    if args.stats:
        for src, bucket, n in store.source_stats(30):
            print(f"{digest.source_name(src):35} {bucket:15} {n}")
        return 0

    if cfg.get("run", {}).get("once_per_day", True) and store.sent_today() and not (args.force or args.dry_run):
        log.info("Сегодня дайджест уже отправлен — выхожу (для повторной отправки: --force)")
        return 0

    run_id = store.start_run()
    started = time.time()
    fetch = make_fetcher(cfg)
    results = collect_all(cfg, store, fetch)
    failed = {r.source: r.error for r in results if r.error}

    items = [it for r in results for it in r.items if not store.is_seen(it.source, it.external_id)]
    read_stats = Counter({r.source: 0 for r in results if not r.error})
    read_stats.update(it.source for it in items)

    # подборки → отдельные вакансии (новые посты из подборок забираем целиком)
    tg_cfg = cfg["sources"].get("telegram", {})
    bundle_info: dict = {}
    to_classify = items
    if tg_cfg.get("expand_digests", True):
        to_classify, bundle_info = expand_bundles(
            items, store.is_seen,
            lambda ch, pid: telegram.fetch_single(ch, pid, fetch),
            tg_cfg.get("max_digest_fetches", 30))
        if bundle_info.get("bundles"):
            log.info("Подборки: %s, ссылок %s, новых %s, уже видели %s",
                     bundle_info["bundles"], bundle_info["links"], bundle_info["new"], bundle_info["known"])

    profile = cfg.get("profile", {})
    llm = None
    llm_requested = cfg.get("llm", {}).get("enabled", True) and not args.no_llm
    if llm_requested and to_classify:
        client = LMStudioClient(cfg["llm"], profile.get("about", ""))
        if client.ensure_server():
            llm = client
        else:
            log.warning("LM Studio недоступна — отбор по ключевым словам")
    verdicts, llm_info = classify_all(to_classify, profile, llm)
    llm_info["llm_off"] = not llm_requested  # выключена намеренно (конфиг или --no-llm) — без жёлтой плашки
    if not to_classify:
        llm_info["llm_used"] = True  # разбирать было нечего — предупреждение про модель не нужно
    dedup(verdicts, store.recent_ledger(cfg.get("run", {}).get("dedup_days", 30)))

    # отметки «Откликнулся» / «Разобрал группу» из Google Формы: показываем в письме, статус — только после отправки
    marks_cfg = cfg.get("marks", {})
    marked: list[dict] = []
    if marks_cfg.get("enabled"):
        try:
            marked = store.pending_marks(fetch_marks(marks_cfg, fetch))
        except Exception as e:
            failed["marks"] = f"{type(e).__name__}: {e}"
            log.warning("Отметки откликов не прочитаны: %s", e)
    now = datetime.now()
    tag = f"vd-{now:%Y%m%d}-{'am' if now.hour < 17 else 'pm'}"
    subject, html, text = digest.build(
        verdicts, dict(read_stats), failed, llm_info, bundle_info=bundle_info, tag=tag, marked=marked,
        mark_link=(lambda code, label: mark_link(marks_cfg, code, label)) if marks_cfg.get("enabled") else None)
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"digest_{date.today():%Y-%m-%d}.html"
    out_file.write_text(html, encoding="utf-8")

    picked = [v for v in verdicts if v.bucket != "drop"]
    stats = {
        "read": dict(read_stats), "failed": failed, "picked": len(picked),
        "by_bucket": dict(Counter(v.bucket for v in verdicts)),
        "bundles": bundle_info,
        "llm": llm_info, "seconds": round(time.time() - started, 1),
    }
    log.info("Итог: прочитано %s, в письмо %s, не прочитано источников %s, %.0f с",
             len(items), len(picked), len(failed), stats["seconds"])

    if args.dry_run:
        store.finish_run(run_id, "dry-run", stats)
        log.info("Пробный прогон: письмо не отправлено, состояние не менялось. Дайджест: %s", out_file)
        return 0

    bookmarks = {r.source: r.new_bookmark for r in results if not r.error and r.new_bookmark}
    seen = list({(it.source, it.external_id) for it in items + to_classify})
    ledger_rows = [{"dedup_key": dedup_key(v), "title": v.title, "company": v.company,
                    "url": v.item.url, "source": v.item.source, "bucket": v.bucket,
                    "code": f"{tag}-{v.num}"} for v in picked]
    marks = {m["code"]: m["status"] for m in marked}

    if not picked and not failed and not cfg["mail"].get("send_when_empty", True):
        store.commit_after_send(bookmarks, seen, ledger_rows, marks)
        store.finish_run(run_id, "empty", stats)
        log.info("Новых нет, письмо не отправляю (send_when_empty: false)")
        return 0

    try:
        msg_id = mailer.send(cfg["mail"], subject, html, text)
    except mailer.SendError as e:
        # Письмо не ушло → закладки и журнал не трогаем, следующий запуск соберёт всё заново
        store.finish_run(run_id, "failed", stats, str(e))
        log.error("Письмо НЕ отправлено: %s", e)
        return 1

    store.commit_after_send(bookmarks, seen, ledger_rows, marks)
    stats["message_id"] = msg_id
    store.finish_run(run_id, "sent", stats)
    log.info("Письмо отправлено на %s (%s)", cfg["mail"]["to"], subject)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Утренний дайджест вакансий")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args(argv)
    setup_logging()
    try:
        return run(args)
    except Exception:
        log.exception("Необработанная ошибка")
        return 3


if __name__ == "__main__":
    sys.exit(main())
