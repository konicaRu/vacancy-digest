"""Образцы страниц для тестов. Вёрстка повторяет структуру t.me/s и jabka.work,
тексты — укороченные пересказы реальных постов из каналов (октябрь 2026)."""
from datetime import datetime, timedelta, timezone


def tg_post(channel: str, pid: int, html_text: str, dt: datetime, reply: str = "") -> str:
    reply_html = (f'<a class="tgme_widget_message_reply" href="https://t.me/{channel}/{pid - 1}">'
                  f'<div class="tgme_widget_message_text js-message_text">{reply}</div></a>') if reply else ""
    return f"""
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="{channel}/{pid}">
  <div class="tgme_widget_message_bubble">
   <div class="tgme_widget_message_author"><span>{channel}</span></div>
   {reply_html}
   <div class="tgme_widget_message_text js-message_text" dir="auto">{html_text}</div>
   <div class="tgme_widget_message_footer compact js-message_footer">
    <span class="tgme_widget_message_meta">
     <a class="tgme_widget_message_date" href="https://t.me/{channel}/{pid}">
      <time datetime="{dt.isoformat()}" class="time">{dt:%H:%M}</time></a></span>
   </div>
  </div>
 </div>
</div>"""


def tg_page(channel: str, posts: list[str]) -> str:
    return f"""<!DOCTYPE html><html><head><title>{channel}</title></head><body>
<section class="tgme_channel_history js-message_history">{''.join(posts)}</section></body></html>"""


NOW = datetime.now(timezone.utc)

POST_TEXTS = {
    "vk": ("🚀 <b>Middle+ / Senior Product Analyst в VK Видео, контентная аналитика</b><br/>"
           "Задачи: исследовать структуру смотрения, строить систему контентных метрик.<br/>"
           "Требования: SQL, Python, статистика.<br/><b>Условия:</b> Удаленка по РФ<br/>"
           'Нанимающий менеджер: <a href="https://t.me/hehircatt">@hehircatt</a>'),
    "aihr": ("🚀 <b>Senior Product / Data Analyst в AI HR Tech-стартап</b><br/>"
             "Требования: сильный SQL и Python, A/B-тесты.<br/>"
             "<b>Условия:</b> Полная удалёнка (не РФ) или офис в Варшаве"),
    "junior": ("🚀 <b>Junior / Middle Data Analyst в MAXLINE</b><br/>Собирать дашборды, считать LTV. "
               "SQL, Python.<br/>Локация: Минск, полный офис."),
    "sa": ("⚡️ <b>Системный аналитик в Bell Integrator</b><br/>REST, Kafka, SQL, BPMN.<br/>"
           "Формат: Удаленка (РФ)"),
    "vv_product": ("⚡️ <b>Продуктовый аналитик во ВкусВилл</b><br/>Продуктовые метрики, A/B-тесты, ClickHouse, "
                   "Python и SQL.<br/><b>Условия:</b> Формат работы - удаленка (офис по желанию)<br/>"
                   "🤖 Карьерный интенсив · Гайд по резюме"),
    "nofmt": ("⚡️ <b>Продуктовый аналитик</b><br/>Международный B2B SaaS-продукт. Сильный SQL, "
              "A/B-тестирование, понимание ML.<br/>Рекрутер: @someone_hr"),
    "digest": ("⭐️ <b>Подборка актуальных вакансий за неделю</b><br/>"
               '<a href="https://t.me/careerstation_analyst/125">Продуктовый аналитик в Getmatch</a><br/>'
               '<a href="https://t.me/careerstation_analyst/124">Data-Аналитик во ВкусВилл</a><br/>'
               '<a href="https://t.me/careerstation_analyst/130">Data-аналитик в Andersen Lab</a>'),
    "ad": "🔥 <b>30 000 ₽ за Телеграм-бота без опыта</b><br/>Пройди бесплатный мини-курс по вайбкодингу!",
    # недельная подборка как на скриншоте: ссылки на посты канала, на другой канал и на сайт
    "weekly": ("⭐️ <b>Подборка актуальных вакансий за неделю</b><br/>"
               "Собрали активные вакансии прошлой недели, чтобы вы успели откликнуться!<br/>"
               "<b>Продуктовый аналитик</b><br/>"
               '• <a href="https://t.me/careerstation_analyst/90">Продуктовый аналитик в Home Credit Bank</a><br/>'
               '• <a href="https://t.me/careerstation_analyst/7">Продуктовый аналитик в Купер</a><br/>'
               '• <a href="https://t.me/careerstation_pm/1117">Продуктовый аналитик в Game Gears</a><br/>'
               '• <a href="https://team.vk.company/vacancy/?q=product">Подборка вакансий продуктовых аналитиков в VK</a><br/>'
               "<b>Системный-аналитик/ Бизнес-аналитик</b><br/>"
               '• <a href="https://t.me/careerstation_analyst/91">Бизнес-аналитик в AIFC</a><br/>'
               "Всем отличной недели! 🔥<br/>"
               '🤖 <a href="https://careerstation.ru/intensive-pm">Карьерный интенсив. Старт 17 августа</a><br/>'
               '🤖 <a href="https://t.me/careerstation_bot?start=link_x">Гайд по резюме</a><br/>'
               '<a href="https://t.me/s/careerstation_analyst?q=%23Analyst">#Analyst</a>'),
    # подборка одной компании со ссылками на hh и общими условиями
    "otp": ("⚡️ <b>Подборка вакансий аналитиков в Ipoteka bank OTP Group</b><br/>"
            '🔹 <a href="https://hh.uz/vacancy/136452861">Middle/Senior Data Analyst</a><br/>'
            '🔹 <a href="https://hh.uz/vacancy/136876545">System Analyst</a><br/>'
            "<b>Условия:</b><br/>• Локация: Ташкент, офис"),
    "da_noskills": ("🚀 <b>Аналитик данных в контентный проект</b><br/>Выгрузки из DataLens, рассылка отчётов. "
                    "Удалённая работа."),
}

JABKA_HTML = """<!DOCTYPE html><html><body><main>
<a href="/jobs/analitik-dlya-razvitiya-sistemy-metrik-i-monetizatsii-avito-rabota-20261018-eo56">
  <div><span>220K ₽</span><span>3K$</span></div>
  <div class="title">Аналитик для развития системы метрик и монетизации</div>
  <div>@Авито Работа</div><div>Digital Platforms</div><div>Москва·удаленка·11ч</div>
  <div>SQL</div><div>Data Analysis</div></a>
<a href="/jobs/produktovyy-analitik-dlya-razrabotki-ai-resheniy-remote-20261018-rerb">
  <div><span>211K ₽</span></div>
  <div class="title">Продуктовый аналитик для разработки AI-решений</div>
  <div>AI/Big Data</div><div>удаленка·17ч</div><div>Python</div><div>SQL</div></a>
<a href="/jobs/sistemnyy-analitik-it-kompaniya-20261018-gbmg">
  <div><span>250K ₽</span></div><div class="title">Системный аналитик</div><div>@ИТ компания</div>
  <div>Россия·удаленка·9ч</div></a>
<a href="/jobs/starshiy-analitik-dannykh-dlya-mobilnoy-igry-hypercell-games-20261001-4tsu">
  <div><span>289K ₽</span></div><div class="title">Старший аналитик данных для мобильной игры</div>
  <div>@Hypercell Games</div><div>удаленка·18д</div><div>SQL</div></a>
<a href="/jobs/produktovyy-analitik-dlya-razrabotki-ai-resheniy-remote-20261018-rerb">дубль ссылки</a>
<a href="/about">О проекте</a>
</main></body></html>"""

LINKEDIN_EMAIL_HTML = """<html><body><table>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc">Product Analyst</a>
<br/>Acme Fintech · Remote (EMEA)</td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?trk=x">Senior Data Analyst</a>
<br/>Globex · Cyprus (Hybrid)</td></tr>
<tr><td>Иван Петров опубликовал(а): Ищем продуктового аналитика в команду платежей, удалённо по РФ, пишите!
<a href="https://www.linkedin.com/feed/update/urn:li:activity:7501234567890123456/">Посмотреть публикацию</a></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?other=1">Product Analyst</a></td></tr>
</table></body></html>"""
