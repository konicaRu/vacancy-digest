# Карьерные сайты компаний — бэклог

Источник: Google Документ «Карьерные сайты компаний РФ» (246 компаний, обновлён 4.09.2026):
https://docs.google.com/document/d/1tMgxW62wf4KAz3JdaChmnic1RqDq562AvOjAmIOtsuk/edit
Документ закрыт для роботов (нужна авторизация) — список ниже скопирован из чата 12.11.2026.

Цель: ежедневно (утром, один проход) заходить на карьерные сайты, искать НОВЫЕ удалённые вакансии
аналитика / продуктового аналитика в удалённых компаниях; отклики фиксировать (как в `ledger.status = applied`).

## Первая очередь (решение 12.11.2026)

Проверить на живых данных, что отдаёт обычный запрос (HTML / JS / блокировка), и подключить.

12.11: первая партия выбрана и реализована — Хабр Карьера, Авито (полный раздел аналитики), Aviasales.
Утренний режим; описание подключения — `company-sites-design-2026-11-12.md`, проверка доступности —
`company-sites-probe-2026-11-12.md`. Остальные сайты таблицы остаются в очереди.

Следующая партия 12.11: подключены VK и МТС через публичные API, утром, первый обход за 14 дней.
Живой проверочный сбор: 8 подходят + 4 уточнить, ошибок и предупреждений нет.
Яндекс (`yandex.ru/jobs` и `yandex.com/jobs`) сейчас отдаёт CAPTCHA; 2ГИС дважды не ответил по таймауту.
Их не включали. МегаФон отвечает 200, но полный сбор пока не реализован.

| Компания | Ссылка на вакансии | Заметка из документа |
|---|---|---|
| Хабр Карьера | https://career.habr.com/vacancies | единая платформа, одним парсером закрывает Lamoda, WB, Playrix, Okko, СберЗдоровье, Туту, ivi и др. |
| Dodo Brands | https://dodobrands.huntflow.io/ | платформа Huntflow; сильная продуктовая культура |
| Ozon | https://ozon.tech/vacancies/ | career.ozon.ru блокирует автоматизацию |
| VK | https://team.vk.company/vacancy/ | форма с капчей |
| Авито | https://career.avito.com/vacancies/ | отклик на Fintech уже подан |
| Aviasales | https://www.aviasales.ru/about/vacancies | — |
| Купер (СберМаркет) | https://team.kuper.ru/catalog-vacancies | — |
| Сбербанк | https://rabota.sber.ru/search/ | — |
| Альфа-Банк | https://job.alfabank.ru/vacancies | — |
| Газпромбанк | https://www.gazprombank.ru/personal/page/gpb-job/ | прошлое место работы |
| Т-Банк (Тинькофф) | https://www.tbank.ru/career/vacancies/all/moscow/ | — |
| 2ГИС | https://job.2gis.ru/ | — |
| ВкусВилл | https://vkusvill.ru/job/vacancys/ | — |
| X5 Group | https://rabota.x5.ru/vacancies | — |
| Магнит | https://rabota.magnit.ru/vacancies | — |
| Tele2 | https://careers.t2.ru/ | — |
| МТС | https://job.mts.ru/vacancies | — |
| МегаФон | https://job.megafon.ru/ | — |
| Lamoda | https://career.habr.com/companies/lamodatech | через Хабр Карьеру |
| Wildberries / RWB | https://career.habr.com/companies/wb/vacancies | через Хабр Карьеру |
| Самокат | https://hh.ru/employer/5488399 | только hh (ecom.tech) — hh в проекте отсеивается |
| Okko | https://career.habr.com/companies/okko/vacancies | через Хабр Карьеру |
| СберЗдоровье | https://career.habr.com/companies/sberhealth/vacancies | через Хабр Карьеру |
| Яндекс (все сервисы: Лавка, Маркет, Практикум, Авто.ру, Доставка, Такси) | https://yandex.ru/jobs/ | «предположение», один портал |
| Кинопоиск | https://yandex.ru/jobs/ | тот же портал Яндекса |
| Билайн | https://job.beeline.ru/ | «предположение» |
| HeadHunter (как работодатель) | — (ссылки нет) | найти раздел вакансий |

Уточнено 12.11.2026:
- «Ноно» = Dodo Brands (добавлен в таблицу выше).
- Skyscanner — не нужен, исключён.
- «Теленва» = Tele2 (подтверждено).
- Исключено по документу: Outlines Tech — СТОП-ЛИСТ (уже откликался).

## Бэклог (на потом)

### Приоритет A (не вошли в первую очередь)
Банки.ру https://banki.huntflow.io/ (ПА есть, но гибрид 4/1) ·
Точка Банк https://hr.tochka.com/vacancies/ (блокирует автоматизацию) · Skyeng https://job.skyeng.ru/vacancies (аналитиков нет) ·
Outlines Tech — СТОП-ЛИСТ ·
ВсеИнструменты.ру https://rabota.vseinstrumenti.ru/ · Золотое яблоко https://job.goldapple.ru/search/all ·
GetCourse https://getcourse.ru/career · Skillbox https://skillbox.ru/jobs/ · iSpring https://www.ispring.ru/company/jobs ·
Нетология https://netology.ru/work-in-netology · Учи.ру https://career.uchi.ru/ · MY.GAMES https://careers.my.games/ ·
Хантфлоу https://huntflow.ru/career/ · JetBrains https://www.jetbrains.com/careers/jobs/ · Miro https://miro.com/careers/open-positions/ ·
Semrush https://careers.semrush.com/jobs/ · Wrike https://www.wrike.com/jobs/ · Level.Travel https://career.level.travel/ ·
Островок https://career.ostrovok.ru/ · Туту.ру https://career.habr.com/companies/tutu/vacancies ·
GlowByte https://job.glowbyteconsulting.com/ · Positive Technologies https://global.ptsecurity.com/en/about/vacancy/ ·
Redmadrobot https://job.redmadrobot.com/ · Selectel https://selectel.ru/careers/ · Timeweb https://timeweb.com/ru/team/ ·
Visiology https://ru.visiology.su/about/job-openings · Аренадата https://career.arenadata.tech/ ·
Лаборатория Касперского https://careers.kaspersky.ru/vacancies · МойСклад https://www.moysklad.ru/company/careers/ ·
СКБ Контур https://kontur.ru/career · Домклик https://career.domclick.ru/vacancies · Циан https://www.cian.ru/vacancies/ ·
ivi https://habr.com/ru/companies/ivi/vacancies/ · QIWI https://jobs.qiwi.com/vacancies · Модульбанк https://job.modulbank.ru/ ·
Сравни.ру https://career.sravni.ru/ · ЮMoney https://jobs.yoomoney.ru/ · Playrix https://career.habr.com/companies/playrixhr ·
Поток https://career.habr.com/companies/potok · amoCRM https://hh.ru/employer/999442 · Whoosh https://hh.ru/employer/3536822 ·
CloudPayments https://hh.ru/employer/1871618 · inDrive https://indrive.com/en/careers/ ·
без ссылки: SuperJob, Работа.ру, Creatio, Luxms, Modus BI, Полиматика, Форсайт, ЮKassa.

### Приоритет B / C — с ссылкой на вакансии
- ИТ: IBS https://ibs.ru/career/ · InfoWatch https://www.infowatch.ru/company/career · Nexign https://job.nexign.com/ ·
  Postgres Professional https://career.postgrespro.ru/ · Softline https://softline.ru/job · Группа Астра https://astra.ru/about/career/ ·
  Диасофт https://www.diasoft.ru/about/career/ · КРОК https://careers.croc.ru/ · ЛАНИТ https://job.lanit.ru/ · ЦФТ https://job.cft.ru/about/ ·
  Naumen https://career.habr.com/companies/naumen
- Банки: Ак Барс https://www.akbars.ru/career/vacancies/ · ВТБ https://rabota-vtb.ru/career · МКБ https://mkb.ru/about/work ·
  ПСБ https://job.psbank.ru/vacancies/all · Райффайзен https://career.raiffeisen.ru/ · Совкомбанк https://people.sovcombank.ru/vacancies
- Ритейл: DNS https://www.dns-shop.ru/jobs/ · Детский мир https://jobs.detmir.ru/ · Лента https://career.lenta.com/ ·
  Лемана Про https://rabota.lemanapro.ru/ · М.Видео-Эльдорадо https://career.mvideoeldorado.ru/ · Петрович https://petrovichjob.ru/vakancies/ ·
  Ситилинк https://job.citilink.ru/vacs/ · Спортмастер https://job.sportmaster.ru/vacancies/ · Азбука Вкуса https://career.habr.com/companies/av/vacancies
- Металлургия: ММК https://mmk.ru/ru/career/ · НЛМК https://career.nlmk.com/vacancy/ · ОМК https://omk-job.ru/ ·
  Северсталь https://career.severstal.com/vacancies/ (родной город, есть Северсталь Диджитал) · ЕВРАЗ https://hh.ru/employer/19989 ·
  Норникель https://hh.ru/employer/740 · ТМК https://www.tmk-group.ru/vacancies/
- Финтех: Мосбиржа https://career.moex.com/ · НСПК https://www.nspk.ru/vacancies
- Медицина: Гемотест https://gemotest.ru/hr/ · Хеликс https://helix.ru/job
- Нефтегаз: Газпром нефть https://career.gazprom-neft.ru/ · Лукойл https://lukoil.ru/Company/Career/Vacancies
- Страхование: Ингосстрах https://www.ingos.ru/career · АльфаСтрахование https://hh.ru/employer/370 ·
  Ренессанс Страхование (SuperJob) · Росгосстрах https://www.rgs.ru/about/career · СОГАЗ https://career.sogaz.ru/
- Машиностроение: Ростсельмаш https://rostselmash.com/career/vacancy/ · КАМАЗ https://hh.ru/employer/52951
- Госкорпорации: Росатом https://rosatom-career.ru/vacancies · Алмаз-Антей http://career.almaz-antey.ru/ ·
  Роскосмос https://russianspacesystems.ru/career/vacancy/ · Ростех https://rostec.ru/careers/vacancy/
- Логистика: Почта России https://www.pochta.ru/vacancy-list · СДЭК https://rabota.cdek.ru/
- Химия: СИБУР https://career.sibur.ru/vacancies/ · Акрон https://www.acron.ru/career/ · Уралхим https://www.uralchem.ru/career/ ·
  ФосАгро https://www.phosagro.ru/career-education/career/
- Энергетика: Интер РАО https://www.interrao.ru/company/staff/ · РусГидро https://career.habr.com/companies/rushydro/vacancies
- Travel: S7 https://www.s7.ru/ru/vacancies/ · Аэрофлот https://vacancy.aeroflot.ru/
- АПК: Мираторг https://miratorg.ru/career/vacancies/ · Черкизово https://vacancies.cherkizovo.com/vacancies
- Добыча: АЛРОСА https://www.alrosa.ru/vakansii/ · Полюс https://career.polyus.com/
- Транспорт: Делимобиль https://career.delimobil.ru/ · РЖД https://team.rzd.ru/
- Gamedev: Wargaming https://wargaming.com/en/careers/ · Astrum https://career.habr.com/companies/astrum-entertainment
- Телеком: Ростелеком https://job.rt.ru/

### Приоритет B / C — ссылки на вакансии не найдены («не искал»)
- ИТ: 1С, DIS Group, Directum, ELMA, REG.RU, БАРС Груп, Битрикс24, Инфосистемы Джет, Калуга Астрал, Код Безопасности, Неофлекс, ОТР, Первая Форма, Такском, Тензор, Merlion
- Банки: Открытие, Росбанк, ОТП, Ренессанс Кредит, Россельхозбанк, Русский Стандарт, Уралсиб, Хоум Банк
- Ритейл: Gloria Jeans, Melon Fashion, Л'Этуаль, Красное&Белое, О'Кей
- Металлургия: Металлоинвест, Мечел, РУСАЛ, УГМК
- Финтех: Best2Pay, Payler, БКС, Делобанк, Займер, Мани Мен, Робокасса, Финам, Атон
- Медицина: Аптека.ру, Здравсити, Инвитро, Медси, Сбер Еаптека, Мать и дитя
- Нефтегаз: Газпром, Новатэк, Роснефть, Сургутнефтегаз, Татнефть, Транснефть
- Страхование: ВСК, РЕСО-Гарантия, Согласие
- Машиностроение: АвтоВАЗ, ГАЗ, Синара, Соллерс, Трансмашхолдинг
- Госкорпорации: ОАК · Логистика: Boxberry, Деловые линии, ПЭК · Химия: ЕвроХим
- Энергетика: Мосэнерго, Россети, Т Плюс · EdTech: GeekBrains, SkillFactory, Фоксфорд, Синергия
- Travel: Победа, Уральские авиалинии · АПК: Русагро, ЭФКО · Добыча: СУЭК
- Медиа: Premier, START, Газпром-Медиа · Транспорт: Ситидрайв · FMCG: Балтика, Очаково
- SaaS: Bitrix, Ivideon · Классифайды: Дром, Юла · Общепит: Кухня на районе, Тануки
- Телеком: ЭР-Телеком · E-commerce: Утконос · HR-tech: FriendWork · Интернет: Rambler

Приоритеты (B/C) из документа сохранены только по группам выше: все «B» и «C» перечислены как есть; «C» — низкая вероятность
(нефтегаз, металлургия, химия, энергетика, госкорпорации, машиностроение), их брать в последнюю очередь.
