import unittest
from datetime import date, timedelta

from tests.fixtures import JABKA_HTML, LINKEDIN_EMAIL_HTML, NOW, POST_TEXTS, tg_page, tg_post
from vd.sources import jabka, linkedin_mail, telegram


def make_channel(channel, ids_dates):
    """ids_dates: [(id, datetime)] по возрастанию. Возвращает fetch, отдающий страницы по 5 постов."""
    pages = {}
    ids = [i for i, _ in ids_dates]
    def page_for(before):
        chunk = [x for x in ids_dates if before is None or x[0] < before][-5:]
        return tg_page(channel, [tg_post(channel, i, f"Пост {i}: аналитик", d) for i, d in chunk])
    calls = []
    def fetch(url):
        calls.append(url)
        before = int(url.split("before=")[1]) if "before=" in url else None
        return page_for(before)
    return fetch, calls


class TelegramTests(unittest.TestCase):
    def test_parse_takes_main_text_not_reply_quote(self):
        html = tg_page("nodatanojobs", [
            tg_post("nodatanojobs", 654, POST_TEXTS["vk"], NOW, reply="Цитата из старого поста"),
        ])
        items = telegram.parse_page(html, "nodatanojobs")
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.external_id, "654")
        self.assertEqual(it.url, "https://t.me/nodatanojobs/654")
        self.assertIn("VK Видео", it.text)
        self.assertNotIn("Цитата", it.text)
        self.assertIn("https://t.me/hehircatt", it.links)
        self.assertIsNotNone(it.published_at)

    def test_collect_from_bookmark_paginates(self):
        data = [(i, NOW - timedelta(hours=100 - i)) for i in range(640, 655)]
        fetch, calls = make_channel("ch", data)
        res = telegram.collect("ch", "642", fetch, lookback_days=3, max_pages=5)
        self.assertIsNone(res.error)
        self.assertEqual([int(i.external_id) for i in res.items], list(range(643, 655)))
        self.assertEqual(res.new_bookmark, "654")
        self.assertEqual(len(calls), 3)  # 650-654, 645-649, 640-644

    def test_first_run_uses_lookback(self):
        data = [(i, NOW - timedelta(days=(20 - i) * 0.5)) for i in range(10, 21)]  # 0..5 дней назад
        fetch, _ = make_channel("ch", data)
        res = telegram.collect("ch", None, fetch, lookback_days=3, max_pages=5)
        ids = [int(i.external_id) for i in res.items]
        self.assertTrue(all(i >= 15 for i in ids), ids)  # только последние ~3 дня
        self.assertEqual(res.new_bookmark, "20")

    def test_no_new_posts_keeps_bookmark(self):
        data = [(i, NOW) for i in range(1, 6)]
        fetch, calls = make_channel("ch", data)
        res = telegram.collect("ch", "5", fetch)
        self.assertEqual(res.items, [])
        self.assertEqual(res.new_bookmark, "5")
        self.assertEqual(len(calls), 1)

    def test_network_error_reported_and_bookmark_not_moved(self):
        def fetch(url):
            raise ConnectionError("timeout")
        res = telegram.collect("ch", "10", fetch)
        self.assertIn("timeout", res.error)
        self.assertIsNone(res.new_bookmark)

    def test_empty_page_is_error_not_quiet_day(self):
        res = telegram.collect("ch", "10", lambda url: "<html><body>Канал недоступен</body></html>")
        self.assertIsNotNone(res.error)


class JabkaTests(unittest.TestCase):
    def test_parse(self):
        items = jabka.parse_page(JABKA_HTML)
        self.assertEqual(len(items), 4)  # дубль ссылки схлопнут, /about пропущен
        avito = items[0]
        self.assertEqual(avito.external_id, "analitik-dlya-razvitiya-sistemy-metrik-i-monetizatsii-avito-rabota-20261018-eo56")
        self.assertEqual(avito.url.split("/")[2], "jabka.work")
        self.assertEqual(avito.hint_title, "Аналитик для развития системы метрик и монетизации")
        self.assertEqual(avito.published_at.strftime("%Y%m%d"), "20261018")

    def test_collect_skips_seen_and_old_on_first_run(self):
        seen = {("site:jabka", "sistemnyy-analitik-it-kompaniya-20261018-gbmg")}
        res = jabka.collect(["u"], lambda u: JABKA_HTML, lambda s, e: (s, e) in seen,
                            first_run=True, lookback_days=36500)
        self.assertEqual(len(res.items), 3)
        res2 = jabka.collect(["u"], lambda u: JABKA_HTML, lambda s, e: False, first_run=True, lookback_days=0)
        self.assertEqual(res2.items, [])  # все карточки старше «сегодня»

    def jabka_pages(self, pages):
        """pages: {номер: [(код, дней назад)]} → fetch для URL выдачи и &page=N; пишет, какие страницы запрошены."""
        today = date.today()

        def card(code, ago):
            d = (today - timedelta(days=ago)).strftime("%Y%m%d")
            return f'<a href="/jobs/analitik-{code}-{d}-{code}x"><div class="title">Аналитик {code}</div></a>'

        asked = []

        def fetch(url):
            n = int(url.split("page=")[1]) if "page=" in url else 1
            asked.append(n)
            return "<html>" + "".join(card(c, a) for c, a in pages.get(n, [])) + "</html>"
        return fetch, asked

    def test_paginates_until_cards_older_than_window(self):
        # живая выдача 20.10: на 1-й странице всё за 19.10, за 16–18.10 — дальше (&page=2…)
        fetch, asked = self.jabka_pages({1: [("aaa", 0), ("bbb", 1)],
                                         2: [("ccc", 2), ("ddd", 9)],
                                         3: [("eee", 9), ("fff", 10)],
                                         4: [("ggg", 11)]})
        res = jabka.collect(["https://jabka.work/?search=x"], fetch, lambda s, e: False, True, lookback_days=5)
        self.assertIsNone(res.error)
        self.assertEqual(sorted(i.hint_title for i in res.items), ["Аналитик aaa", "Аналитик bbb", "Аналитик ccc"])
        self.assertEqual(asked, [1, 2, 3])  # на 3-й нет свежих — дальше не листаем

    def test_paginates_until_already_seen(self):
        fetch, asked = self.jabka_pages({1: [("aaa", 0), ("bbb", 0)], 2: [("ccc", 1)], 3: [("ddd", 1)]})
        seen = lambda s, e: e.startswith("analitik-ccc")
        res = jabka.collect(["https://jabka.work/?search=x"], fetch, seen, first_run=False, lookback_days=5)
        self.assertEqual(len(res.items), 2)
        self.assertEqual(asked, [1, 2])

    def test_stops_when_site_ignores_page_parameter(self):
        asked = []
        res = jabka.collect(["u"], lambda u: asked.append(u) or JABKA_HTML, lambda s, e: False, True,
                            lookback_days=36500)
        self.assertEqual(len(res.items), 4)
        self.assertEqual(len(asked), 2)  # 2-я страница совпала с 1-й — остановились

    def test_empty_listing_is_error(self):
        res = jabka.collect(["u"], lambda u: "<html><a href='/about'>x</a></html>", lambda s, e: False, True)
        self.assertIsNotNone(res.error)


class LinkedInMailTests(unittest.TestCase):
    def test_parse_jobs_and_posts(self):
        items = linkedin_mail.parse_email("Новые вакансии: Product Analyst", LINKEDIN_EMAIL_HTML, "17")
        kinds = sorted(i.kind for i in items)
        self.assertEqual(kinds, ["linkedin_job", "linkedin_job", "linkedin_post"])
        job = next(i for i in items if i.external_id == "job:4012345678")
        self.assertEqual(job.url, "https://www.linkedin.com/jobs/view/4012345678/")
        self.assertIn("Acme Fintech", job.text)
        post = next(i for i in items if i.kind == "linkedin_post")
        self.assertIn("Иван Петров", post.text)

    def test_imap_date_is_english(self):
        from datetime import date
        self.assertEqual(linkedin_mail.imap_date(date(2026, 10, 5)), "05-Oct-2026")


if __name__ == "__main__":
    unittest.main()
