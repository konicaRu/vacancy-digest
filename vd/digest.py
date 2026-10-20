"""Сборка письма-дайджеста: HTML + текстовая версия."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from html import escape

from .models import Verdict

ROLE_RU = {
    "product_analyst": "Продуктовый аналитик", "data_analyst": "Аналитик данных",
    "bi_analyst": "BI-аналитик", "system_analyst": "Системный аналитик",
    "business_analyst": "Бизнес-аналитик", "marketing_analyst": "Маркетинговый аналитик",
    "financial_analyst": "Финансовый аналитик", "other": "",
}
GRADE_RU = {"intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior",
            "lead": "Lead", "unknown": ""}
REMOTE_RU = {"yes": "удалённо из РФ", "no": "не из РФ", "unknown": "формат не указан"}


def source_name(source: str) -> str:
    if source.startswith("tg:"):
        return f"TG · {source[3:]}"
    if source.startswith("site:"):
        return {"jabka": "jabka.work"}.get(source[5:], source[5:])
    if source == "linkedin":
        return "LinkedIn"
    return source


def _meta(v: Verdict) -> str:
    parts = [v.company or "", ROLE_RU.get(v.role, ""), GRADE_RU.get(v.grade, ""),
             REMOTE_RU.get(v.remote_from_russia, ""), v.salary or ""]
    return " · ".join(p for p in parts if p)


def card_source(v: Verdict) -> str:
    src = source_name(v.item.source)
    if v.item.via and v.item.via != v.item.source:
        src += f" · из подборки {source_name(v.item.via)}"
    elif v.item.via:
        src += " · из подборки"
    return src


def _card_html(v: Verdict, accent: str) -> str:
    src = card_source(v)
    if v.also_in:
        src += " · также: " + ", ".join(source_name(s) for s in v.also_in)
    extra = f" · отклик: {escape(v.contact)}" if v.contact and not v.contact.startswith("http") else ""
    title = escape(v.title or "Без названия")
    return (
        f'<div style="border-left:3px solid {accent};padding:6px 12px;margin:12px 0;">'
        f'<div style="font-size:15px;font-weight:600;line-height:1.35;">'
        f'<a href="{escape(v.item.url)}" style="color:#1a1a1a;text-decoration:none;">{title}</a></div>'
        f'<div style="font-size:13px;color:#555;margin-top:2px;">{escape(_meta(v))}</div>'
        + (f'<div style="font-size:13px;color:#333;margin-top:4px;">{escape(v.reason)}</div>' if v.reason else "")
        + f'<div style="font-size:12px;color:#888;margin-top:4px;">{escape(src)}{extra} · '
          f'<a href="{escape(v.item.url)}" style="color:#2b6cb0;">открыть</a></div>'
        f'</div>'
    )


def _section(title: str, note: str, rows: list[Verdict], accent: str) -> str:
    if not rows:
        return ""
    body = "".join(_card_html(v, accent) for v in rows)
    return (f'<h2 style="font-size:16px;margin:24px 0 2px;color:#1a1a1a;">{escape(title)} '
            f'<span style="color:#888;font-weight:400;">· {len(rows)}</span></h2>'
            f'<div style="font-size:12px;color:#888;">{escape(note)}</div>{body}')


def build(verdicts: list[Verdict], read_stats: dict, failed: dict[str, str],
          llm_info: dict, run_date: date | None = None,
          bundle_info: dict | None = None) -> tuple[str, str, str]:
    """Возвращает (тема, html, текст)."""
    run_date = run_date or date.today()
    by = defaultdict(list)
    for v in verdicts:
        by[v.bucket].append(v)
    main, unknown, network = by["main"], by["unknown_format"], by["network"]

    # --- тема ---
    bits = []
    if network:
        bits.append(f"{len(network)} от знакомых")
    if main:
        bits.append(f"{len(main)} подходят")
    if unknown:
        bits.append(f"{len(unknown)} уточнить")
    subject = f"{run_date:%d.%m}: " + (", ".join(bits) if bits else "новых нет")
    if failed:
        subject += f" (не прочитано источников: {len(failed)})"

    # --- статистика по источникам ---
    # вакансия из подборки засчитывается каналу, где была подборка
    in_digest = Counter((v.item.via or v.item.source) for v in verdicts if v.bucket != "drop")
    drop_reasons = Counter(v.drop_reason for v in verdicts if v.bucket == "drop" and v.drop_reason)

    stat_rows = ""
    for src in sorted(set(read_stats) | set(failed)):
        if src in failed:
            stat_rows += (f'<tr><td style="padding:2px 12px 2px 0;">{escape(source_name(src))}</td>'
                          f'<td colspan="2" style="color:#b03030;">не прочитан: {escape(failed[src])}</td></tr>')
        else:
            stat_rows += (f'<tr><td style="padding:2px 12px 2px 0;">{escape(source_name(src))}</td>'
                          f'<td style="padding:2px 12px;text-align:right;">{read_stats.get(src, 0)}</td>'
                          f'<td style="padding:2px 12px;text-align:right;">{in_digest.get(src, 0)}</td></tr>')

    warn = ""
    if failed:
        warn += ('<div style="background:#fdecec;color:#8a1f1f;padding:8px 12px;margin:12px 0;font-size:13px;">'
                 'Не удалось прочитать: ' + escape(", ".join(source_name(s) for s in failed)) +
                 '. Их закладки не сдвинуты — следующий запуск заберёт пропущенное.</div>')
    if llm_info.get("llm_failed") or not (llm_info.get("llm_used") or llm_info.get("llm_off")):
        warn += ('<div style="background:#fff6e0;color:#7a5a00;padding:8px 12px;margin:12px 0;font-size:13px;">'
                 'Локальная модель была недоступна — отбор по ключевым словам, точность ниже обычной.</div>')

    empty = "" if (main or unknown or network) else (
        '<p style="font-size:14px;color:#555;">Новых подходящих вакансий нет. '
        'Агент отработал, источники прочитаны — см. статистику ниже.</p>')

    top_drops = ", ".join(f"{r} — {n}" for r, n in drop_reasons.most_common(5))
    bi = bundle_info or {}
    bundles_line = ""
    if bi.get("bundles"):
        bundles_line = (f'<div style="font-size:11px;color:#999;margin-top:4px;">Подборки: {bi["bundles"]}, '
                        f'ссылок на вакансии {bi["links"]}, из них новых {bi["new"]}, уже видели {bi["known"]}'
                        + (f', не открылось {bi["fetch_failed"]}' if bi.get("fetch_failed") else "") + '</div>')
    html = f"""<html><body style="margin:0;padding:0;background:#ffffff;">
<div style="max-width:640px;margin:0 auto;padding:16px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a1a;">
<div style="font-size:20px;font-weight:700;">Вакансии на {run_date:%d.%m.%Y}</div>
{warn}{empty}
{_section("От знакомых", "Посты людей из LinkedIn — можно попросить рекомендацию", network, "#8a5cf6")}
{_section("Подходят", "Нужная роль, можно работать удалённо из России", main, "#2f855a")}
{_section("Формат не указан", "Роль подходит, про удалёнку в тексте ничего нет — стоит уточнить", unknown, "#b7791f")}
<h2 style="font-size:14px;margin:28px 0 4px;color:#555;">Источники</h2>
<table style="font-size:12px;color:#555;border-collapse:collapse;">
<tr><td style="padding:2px 12px 2px 0;color:#888;">источник</td><td style="padding:2px 12px;color:#888;">новых</td><td style="padding:2px 12px;color:#888;">в письме</td></tr>
{stat_rows}</table>
<div style="font-size:11px;color:#999;margin-top:8px;">Отсеяно: {escape(top_drops) or "—"}</div>
{bundles_line}
</div></body></html>"""

    # --- текстовая версия ---
    lines = [f"Вакансии на {run_date:%d.%m.%Y}", ""]
    if failed:
        lines += ["Не удалось прочитать: " + ", ".join(source_name(s) for s in failed), ""]
    for title, rows in (("От знакомых", network), ("Подходят", main), ("Формат не указан", unknown)):
        if rows:
            lines.append(f"== {title} ({len(rows)}) ==")
            for v in rows:
                lines.append(f"- {v.title} — {_meta(v)}")
                if v.reason:
                    lines.append(f"  {v.reason}")
                lines.append(f"  {v.item.url}")
            lines.append("")
    if not (main or unknown or network):
        lines.append("Новых подходящих вакансий нет.")
    text = "\n".join(lines)
    return subject, html, text
