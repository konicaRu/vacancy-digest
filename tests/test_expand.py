import unittest

from tests.fixtures import NOW, POST_TEXTS, tg_page, tg_post
from vd.classify import decide, keyword_classify
from vd.expand import expand_bundles, is_bundle, role_anchors
from vd.sources import telegram

PROFILE = {"target_roles": ["product_analyst", "data_analyst"],
           "data_analyst_required_skills": ["sql", "python", "excel"],
           "exclude_grades": ["intern", "junior"], "exclude_title_words": []}

HOME_CREDIT = ("⚡️ <b>Продуктовый аналитик в Home Credit Bank</b><br/>Метрики кредитных продуктов, A/B-тесты, "
               "SQL, Python.<br/><b>Условия:</b> удалёнка по РФ")


def post(key_or_html, channel="careerstation_analyst", pid=100):
    html = POST_TEXTS.get(key_or_html, key_or_html)
    return telegram.parse_page(tg_page(channel, [tg_post(channel, pid, html, NOW)]), channel)[0]


class ExpandTests(unittest.TestCase):
    def test_bundle_detection_ignores_footer_and_hashtags(self):
        weekly = post("weekly")
        self.assertTrue(is_bundle(weekly))
        titles = [t for _, t in role_anchors(weekly)]
        self.assertIn("Продуктовый аналитик в Home Credit Bank", titles)
        self.assertNotIn("Карьерный интенсив. Старт 17 августа", titles)
        self.assertNotIn("#Analyst", titles)
        self.assertFalse(is_bundle(post("vk", "nodatanojobs")))  # обычная вакансия — не подборка

    def test_weekly_digest_expanded_without_duplicates(self):
        weekly = post("weekly", pid=100)
        already_in_run = post("vv_product", pid=7)                    # пост 7 пришёл в этом же запуске
        seen = {("tg:careerstation_analyst", "91")}                    # пост 91 видели вчера
        fetched = []

        def fetch_post(ch, pid):
            fetched.append((ch, pid))
            if (ch, pid) == ("careerstation_analyst", "90"):
                return telegram.parse_page(tg_page(ch, [tg_post(ch, 90, HOME_CREDIT, NOW)]), ch)[0]
            raise ConnectionError("не открылся")

        out, info = expand_bundles([weekly, already_in_run], lambda s, e: (s, e) in seen, fetch_post)
        self.assertEqual(info, {"bundles": 1, "links": 5, "new": 3, "known": 2, "fetched": 1, "fetch_failed": 1})
        self.assertEqual(fetched, [("careerstation_analyst", "90"), ("careerstation_pm", "1117")])
        by_id = {i.external_id: i for i in out}
        self.assertNotIn("100", by_id)                        # сама подборка в письмо не идёт
        self.assertIn("удалёнка по РФ", by_id["90"].text)    # полный текст поста подтянут
        self.assertEqual(by_id["90"].via, "tg:careerstation_analyst")
        self.assertEqual(by_id["1117"].text, "Продуктовый аналитик в Game Gears")  # не открылся → название из ссылки
        vk = by_id["https://team.vk.company/vacancy/?q=product"]
        self.assertEqual(vk.kind, "digest_link")
        # разбор: Home Credit подходит, VK — роль есть, формат неизвестен
        self.assertEqual(decide(keyword_classify(by_id["90"]), PROFILE).bucket, "main")
        self.assertEqual(decide(keyword_classify(by_id["1117"]), PROFILE).bucket, "unknown_format")

    def test_company_bundle_takes_conditions_from_post(self):
        otp = post("otp", pid=128)
        out, info = expand_bundles([otp], lambda s, e: False, lambda ch, pid: None)
        self.assertEqual(info["new"], 2)
        da = next(i for i in out if "136452861" in i.url)
        self.assertTrue(da.text.startswith("Вакансия: Middle/Senior Data Analyst"))
        self.assertIn("Ташкент", da.text)
        v = decide(keyword_classify(da), PROFILE)
        self.assertEqual((v.bucket, v.drop_reason), ("drop", "нельзя удалённо из РФ"))

    def test_seen_digest_links_not_repeated(self):
        otp = post("otp", pid=128)
        seen = {("tg:careerstation_analyst", "https://hh.uz/vacancy/136452861"),
                ("tg:careerstation_analyst", "https://hh.uz/vacancy/136876545")}
        out, info = expand_bundles([otp], lambda s, e: (s, e) in seen, lambda ch, pid: None)
        self.assertEqual((out, info["known"]), ([], 2))

    def test_embed_page_parsed(self):
        html = tg_page("careerstation_pm", [tg_post("careerstation_pm", 1117, HOME_CREDIT, NOW)])
        it = telegram.fetch_single("careerstation_pm", "1117", lambda url: html)
        self.assertEqual((it.external_id, it.url), ("1117", "https://t.me/careerstation_pm/1117"))
        # виджет без data-post — текст всё равно достаём
        bare = '<div class="tgme_widget_message_text">Продуктовый аналитик, удалёнка</div>'
        it2 = telegram.fetch_single("x", "5", lambda url: bare)
        self.assertEqual(it2.text, "Продуктовый аналитик, удалёнка")


if __name__ == "__main__":
    unittest.main()


class SectionGradeTests(unittest.TestCase):
    def test_lead_section_is_recognised(self):
        from vd.expand import section_grade
        text = "Подборка вакансий из бигтеха\nLead:\n- Lead Product Analyst в Ozon"
        self.assertEqual(section_grade(text, "Lead Product Analyst в Ozon"), "lead")
