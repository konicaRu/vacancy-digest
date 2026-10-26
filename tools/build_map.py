"""architecture-map.json → architecture-map.html (самодостаточный, без внешних ресурсов).

Запуск из корня проекта:  .venv/Scripts/python tools/build_map.py
Источник правды — architecture-map.json; HTML не править руками.
"""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
m = json.loads((ROOT / "architecture-map.json").read_text(encoding="utf-8"))
e = lambda s: escape(str(s))


def kv_table(d: dict) -> str:
    rows = "".join(f"<tr><th>{e(k)}</th><td>{e(', '.join(v) if isinstance(v, list) else v)}</td></tr>"
                   for k, v in d.items())
    return f"<table>{rows}</table>"


def ul(items) -> str:
    return "<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


FLOW = [("Планировщик", "вход + 3 мин · 17:00"), ("Выпуск уже был?", "утро / вечер"),
        ("Рабочий день?", "календарь РФ · isdayoff"),
        ("Сбор от закладки", "Telegram · jabka · youngjunior"), ("Подборки → вакансии", "ссылки, цитаты, разделы грейда"),
        ("Отбор", "запрос по названию + формат"), ("Дедуп", "запуск + журнал"),
        ("Письмо", "группы · номера · отметки"), ("SMTP Яндекс", "принято?"), ("SQLite", "коммит после отправки")]
flow = "".join(f'<div class="step"><b>{e(a)}</b><span>{e(b)}</span></div>'
               + ('<div class="arr">→</div>' if i < len(FLOW) - 1 else "") for i, (a, b) in enumerate(FLOW))

db = m["database"]
tables = "".join(f"<tr><th><code>{e(k)}</code></th><td>{e(v)}</td></tr>" for k, v in db["tables"].items())
structure = "".join(f"<tr><th><code>{e(k)}</code></th><td>{e(v)}</td></tr>" for k, v in m["structure"].items())
scripts = "".join(f"<tr><th>{e(k)}</th><td><code>{e(v)}</code></td></tr>" for k, v in m["scripts"].items())

html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>vacancy-digest — карта</title>
<style>
:root{{--bg:#fafaf8;--card:#fff;--fg:#1d1d1b;--mute:#6b6b66;--line:#e3e2dc;--acc:#2f855a;--warn:#b7791f;--bad:#b03030}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16171a;--card:#1f2125;--fg:#e8e6e1;--mute:#9a988f;--line:#33353a;--acc:#5fbf8a;--warn:#e0a84a;--bad:#e07070}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}}
.sub{{color:var(--mute);font-size:13px}} code{{font:13px ui-monospace,Consolas,monospace}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{text-align:left;vertical-align:top;padding:6px 8px;border-top:1px solid var(--line)}}
th{{width:28%;color:var(--mute);font-weight:500}} ul{{margin:6px 0;padding-left:20px}} li{{margin:4px 0}}
.flow{{display:flex;flex-wrap:wrap;align-items:center;gap:6px}} .step{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--acc);border-radius:8px;padding:8px 10px;min-width:120px}}
.step b{{display:block;font-size:14px}} .step span{{color:var(--mute);font-size:12px}} .arr{{color:var(--mute)}}
.gotchas li{{border-left:3px solid var(--warn);padding-left:8px;list-style:none;margin-left:-20px}}
.stale{{border-left:3px solid var(--bad)}} a{{color:var(--acc)}}
</style></head><body><main>
<h1>vacancy-digest — карта архитектуры</h1>
<div class="sub">Снимок от {e(m["meta"]["snapshot_date"])} · код {e(m["meta"]["code_revision"])} · машиночитаемая версия — <code>architecture-map.json</code></div>
<div class="card stale"><b>Актуальность.</b> {e(m["meta"]["staleness_policy"])}</div>

<h2>Назначение</h2>
<div class="card">{kv_table(m["project"])}</div>

<h2>Поток одного запуска</h2>
<div class="flow">{flow}</div>
<p class="sub">Петля отметок: письмо → «✓ Откликнулся» / «☑ Разобрал группу» → Google Таблица → следующий выпуск.
Подробная схема с ссылками на код — <a href="architecture-flow.html">architecture-flow.html</a>.</p>

<h2>Гварды и гочи — неочевидное</h2>
<div class="card"><ul class="gotchas">{"".join(f"<li>{e(g)}</li>" for g in m["gotchas"])}</ul></div>

<h2>Стек</h2>
<div class="card">{kv_table(m["stack"])}</div>

<h2>Структура репозитория</h2>
<div class="card"><table>{structure}</table></div>

<h2>База данных</h2>
<div class="card"><p class="sub">{e(db["file"])}</p><table>{tables}</table>
<p><b>Правило записи:</b> {e(db["write_rule"])}<br><b>Миграции:</b> {e(db["migrations"])}</p></div>

<h2>Автоматика</h2>
<div class="card">{kv_table(m["automation"])}</div>

<h2>Команды</h2>
<div class="card"><table>{scripts}</table></div>

<h2>Письмо</h2>
<div class="card">{kv_table(m["frontend"])}</div>

<h2>Секреты</h2>
<div class="card">{kv_table(m["secrets"])}</div>

<h2>Документы</h2>
<div class="card">{kv_table(m["docs"])}</div>

<h2>Roadmap</h2>
<div class="card">{ul(m["roadmap"])}</div>
</main></body></html>
"""
(ROOT / "architecture-map.html").write_text(html, encoding="utf-8")
print("ok", len(html))
