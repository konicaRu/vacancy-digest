"""Сборка письма-дайджеста: HTML + текстовая версия."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from html import escape
from urllib.parse import quote

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
    if source == "marks":
        return "Отметки откликов (Google Таблица)"
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


def _card_html(v: Verdict, accent: str, applied_href: str = "") -> str:
    src = card_source(v)
    if v.also_in:
        src += " · также: " + ", ".join(source_name(s) for s in v.also_in)
    extra = f" · отклик: {escape(v.contact)}" if v.contact and not v.contact.startswith("http") else ""
    applied = (f' · <a href="{escape(applied_href)}" style="color:#2f855a;font-weight:600;">'
               f'✓ Откликнулся</a>' if applied_href else "")
    title = escape(v.title or "Без названия")
    num = f'<span style="color:#888;font-weight:400;">{v.num}.</span> ' if v.num else ""
    return (
        f'<div style="border-left:3px solid {accent};padding:6px 12px;margin:12px 0;">'
        f'<div style="font-size:15px;font-weight:600;line-height:1.35;">{num}'
        f'<a href="{escape(v.item.url)}" style="color:#1a1a1a;text-decoration:none;">{title}</a></div>'
        f'<div style="font-size:13px;color:#555;margin-top:2px;">{escape(_meta(v))}</div>'
        + (f'<div style="font-size:13px;color:#333;margin-top:4px;">{escape(v.reason)}</div>' if v.reason else "")
        + f'<div style="font-size:12px;color:#888;margin-top:4px;">{escape(src)}{extra} · '
          f'<a href="{escape(v.item.url)}" style="color:#2b6cb0;">открыть</a>{applied}</div>'
        f'</div>'
    )


def _section(title: str, note: str, rows: list[Verdict], accent: str, href=None) -> str:
    if not rows:
        return ""
    body = "".join(_card_html(v, accent, href(v) if href else "") for v in rows)
    return (f'<h2 style="font-size:16px;margin:24px 0 2px;color:#1a1a1a;">{escape(title)} '
            f'<span style="color:#888;font-weight:400;">· {len(rows)}</span></h2>'
            f'<div style="font-size:12px;color:#888;">{escape(note)}</div>{body}')


ACCENT = {"main": "#2f855a", "unknown_format": "#b7791f"}


def _groups(main: list[Verdict], unknown: list[Verdict]) -> list[tuple[str, list[Verdict]]]:
    """Группы по источнику (вакансия из подборки — в группе канала-подборки); внутри: подходят, потом уточнить.
    Сначала источники, где больше подходящих."""
    g: dict[str, list[Verdict]] = defaultdict(list)
    for v in main + unknown:
        g[v.item.via or v.item.source].append(v)
    return sorted(g.items(), key=lambda kv: (-sum(v.bucket == "main" for v in kv[1]), -len(kv[1]),
                                             source_name(kv[0])))


def _group_label(src: str, rows: list[Verdict], limit: int = 5000) -> str:
    """Строка в таблицу для «Разобрал группу»: все номера и названия; хвост — «и ещё N», чтобы ссылка не разрослась."""
    head = f"Разобрано · {source_name(src)}: "
    parts: list[str] = []
    for i, v in enumerate(rows):
        candidate = head + "; ".join(parts + [f"{v.num}. {v.title}"])
        if len(quote(candidate)) > limit:
            return head + "; ".join(parts) + f"; и ещё {len(rows) - i}"
        parts.append(f"{v.num}. {v.title}")
    return head + "; ".join(parts)


def _group_html(src: str, rows: list[Verdict], href, group_href: str) -> str:
    n_main = sum(v.bucket == "main" for v in rows)
    note = " · ".join(p for p in (f"подходят {n_main}" if n_main else "",
                                  f"уточнить {len(rows) - n_main}" if len(rows) > n_main else "") if p)
    body = "".join(_card_html(v, ACCENT[v.bucket], href(v) if href else "") for v in rows)
    link = (f'<div style="margin:2px 0 8px 15px;font-size:13px;"><a href="{escape(group_href)}" '
            f'style="color:#2f855a;font-weight:600;">☑ Разобрал группу ({len(rows)})</a></div>' if group_href else "")
    return (f'<h2 style="font-size:16px;margin:24px 0 2px;color:#1a1a1a;">{escape(source_name(src))} '
            f'<span style="color:#888;font-weight:400;">· {len(rows)}</span></h2>'
            f'<div style="font-size:12px;color:#888;">{escape(note)}</div>{body}{link}')


def build(verdicts: list[Verdict], read_stats: dict, failed: dict[str, str],
          llm_info: dict, run_date: date | None = None,
          bundle_info: dict | None = None, tag: str | None = None,
          mark_link=None, marked: list[dict] | None = None) -> tuple[str, str, str]:
    """Возвращает (тема, html, текст). Вакансиям проставляет сквозные номера (v.num).
    tag — метка выпуска («vd-20261020-am»); код вакансии — f"{tag}-{num}". mark_link(код) → ссылка
    «Откликнулся» под вакансией; marked — вакансии, отмеченные с прошлого письма (подтверждение вверху)."""
    run_date = run_date or date.today()
    by = defaultdict(list)
    for v in verdicts:
        by[v.bucket].append(v)
    main, unknown, network = by["main"], by["unknown_format"], by["network"]
    groups = _groups(main, unknown)
    for n, v in enumerate(network + [v for _, rows in groups for v in rows], start=1):
        v.num = n

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
    href = (lambda v: mark_link(f"{tag}-{v.num}", " · ".join(p for p in (v.title, v.company) if p))
            if (tag and mark_link) else None)
    group_href = (lambda src, rows: mark_link(f"{tag}-{','.join(str(v.num) for v in rows)}", _group_label(src, rows))
                  if (tag and mark_link) else None)
    marked_line = ""
    if marked:
        applied = [m for m in marked if m.get("status", "applied") == "applied"]
        n_reviewed = len(marked) - len(applied)
        names = ", ".join(m["title"] + (f" ({m['company']})" if m.get("company") else "") for m in applied)
        parts = ([f"Отмечено откликов: {len(applied)} — {names}"] if applied else []) + \
                ([f"разобрано: {n_reviewed}"] if n_reviewed else [])
        marked_line = "; ".join(parts)
        marked_line = marked_line[0].upper() + marked_line[1:] + ". Больше их не пришлю."
    marked_html = (f'<div style="background:#f0f7f2;color:#22543d;padding:8px 12px;margin:12px 0;font-size:13px;">'
                   f'{escape(marked_line)}</div>') if marked_line else ""
    legend = ('<div style="font-size:12px;color:#888;margin:8px 0;">Зелёная полоса — можно удалённо из РФ, '
              'оранжевая — формат не указан, стоит уточнить.</div>') if groups else ""
    groups_html = "".join(_group_html(src, rows, href, group_href(src, rows) if group_href else "")
                          for src, rows in groups)

    # --- статистика по источникам ---
    # вакансия из подборки засчитывается каналу, где была подборка
    in_digest = Counter((v.item.via or v.item.source) for v in verdicts if v.bucket != "drop")
    drop_reasons = Counter(v.drop_reason for v in verdicts if v.bucket == "drop" and v.drop_reason)

    stat_rows = ""
    for src in sorted(set(read_stats) | set(failed)):
        if src in failed:
            stat_rows += (f'<tr><td style="padding:2px 12px 2px 0;">{escape(source_name(src))}</td>'
                          f'<td colspan="2" style="color:#b03030;">не прочитан: {escape(failed[src])}</td></tr>')
        elif not read_stats.get(src):
            stat_rows += (f'<tr><td style="padding:2px 12px 2px 0;">{escape(source_name(src))}</td>'
                          f'<td colspan="2" style="padding:2px 12px;color:#888;">новых постов нет</td></tr>')
        else:
            found = in_digest.get(src, 0)
            cell = str(found) if found else '<span style="color:#888;">подходящих не найдено</span>'
            stat_rows += (f'<tr><td style="padding:2px 12px 2px 0;">{escape(source_name(src))}</td>'
                          f'<td style="padding:2px 12px;text-align:right;">{read_stats[src]}</td>'
                          f'<td style="padding:2px 12px;">{cell}</td></tr>')

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
{warn}{marked_html}{empty}{legend}
{_section("От знакомых", "Посты людей из LinkedIn — можно попросить рекомендацию", network, "#8a5cf6", href)}
{groups_html}
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
    if marked_line:
        lines += [marked_line, ""]
    text_groups = ([("От знакомых", network, "")] if network else []) + \
                  [(source_name(src), rows, group_href(src, rows) if group_href else "") for src, rows in groups]
    for title, rows, ghref in text_groups:
        lines.append(f"== {title} ({len(rows)}) ==")
        for v in rows:
            lines.append(f"{v.num}. {v.title} — {_meta(v)}")
            if v.reason:
                lines.append(f"  {v.reason}")
            lines.append(f"  {v.item.url}")
            if href:
                lines.append(f"  откликнулся: {href(v)}")
        if ghref:
            lines.append(f"разобрал группу: {ghref}")
        lines.append("")
    if not (main or unknown or network):
        lines.append("Новых подходящих вакансий нет.")
    lines += ["", "== Источники =="]
    for src in sorted(set(read_stats) | set(failed)):
        if src in failed:
            status = f"не прочитан: {failed[src]}"
        elif not read_stats.get(src):
            status = "новых постов нет"
        elif in_digest.get(src):
            status = f"новых {read_stats[src]}, в письме {in_digest[src]}"
        else:
            status = f"новых {read_stats[src]}, подходящих не найдено"
        lines.append(f"{source_name(src)}: {status}")
    text = "\n".join(lines)
    return subject, html, text
