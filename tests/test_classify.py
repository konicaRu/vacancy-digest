import unittest

from tests.fixtures import NOW, POST_TEXTS, tg_page, tg_post
from vd.classify import classify_all, decide, dedup, keyword_classify, prefilter, remote_of
from vd.models import Item
from vd.sources import telegram

PROFILE = {
    "target_roles": ["product_analyst", "data_analyst"],
    "data_analyst_required_skills": ["sql", "python", "excel"],
    "exclude_grades": ["intern", "junior"],
    "exclude_title_words": ["стажер", "стажёр", "intern"],
}


_EXC = ["преподаватель", "автор курса", "руководитель", "тимлид", "hr", "бизнес", "business", "системный", "system",
        "1с", "1c", "web", "маркетплейс", "wildberries", "битрикс", "писатель", "junior", "младший", "intern",
        "trainee", "кредитный", "таможенный", "инвестиционный", "маркетолог", "ученик", "фот", "стажер",
        "стажёр", "практикант", "бухгалтер", "ассистент", "финансовый", "dwh", "экономист"]
TITLE_QUERIES = [
    {"include": ["аналитический", "аналитик", "analyst", "дата аналитик", "дата-аналитик", "аналитик данных",
                 "data analyst", "data-аналитик"],
     "exclude": _EXC + ["асутп"]},
    {"include": ["продуктовый аналитик", "аналитик продукта", "продакт-аналитик", "продакт аналитик",
                 "product analyst", "product analytics"],
     "exclude": _EXC + ["дизайнер", "soc"]},
]


def tg_item(key, channel="nodatanojobs", pid=1):
    html = tg_page(channel, [tg_post(channel, pid, POST_TEXTS[key], NOW)])
    return telegram.parse_page(html, channel)[0]


class RemoteTests(unittest.TestCase):
    def test_real_phrases(self):
        cases = {
            "Условия: Удаленка по РФ": "yes",
            "Формат работы - удаленка (офис по желанию)": "yes",
            "Полная удалёнка (не РФ) или офис в Варшаве": "no",
            "Формат: полная удалёнка, из любой точки мира, кроме Беларуси и России": "no",
            "Гибридный формат: можно из дома, можно из офиса в Москве": "no",
            "Удалёнка из любой точки мира или уютный офис в Ташкенте": "yes",
            "Международный B2B SaaS-продукт, рынок США": "unknown",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(remote_of(text), expected)


class PrefilterTests(unittest.TestCase):
    def test_digest_and_ads_are_dropped(self):
        self.assertIn("подборка", prefilter(tg_item("digest")))
        self.assertEqual(prefilter(tg_item("ad")), "нет слова «аналитик»")
        self.assertIsNone(prefilter(tg_item("vk")))
        # подпись канала про «интенсив» не мешает вакансии дойти до разбора
        self.assertIsNone(prefilter(tg_item("vv_product")))


class HHLinkTests(unittest.TestCase):
    """На hh.ru откликаюсь сам — вакансии со ссылкой туда в письмо не нужны."""

    def item(self, url="https://t.me/ch/1", links=(), kind="telegram"):
        return Item(source="tg:ch", kind=kind, external_id="1", url=url, links=list(links),
                    text="Продуктовый аналитик в Авито. Удалённо из РФ, SQL, Python, A/B-тесты.")

    def test_post_linking_to_hh_is_dropped(self):
        for link in ("https://hh.ru/vacancy/123", "https://spb.hh.ru/vacancy/9?from=tg", "http://headhunter.ru/vacancy/1"):
            with self.subTest(link=link):
                self.assertEqual(prefilter(self.item(links=[link])), "ссылка на hh.ru")

    def test_bundle_link_to_hh_is_dropped(self):
        self.assertEqual(prefilter(self.item(url="https://hh.ru/vacancy/555", kind="digest_link")), "ссылка на hh.ru")

    def test_similar_hosts_are_not_hh(self):
        for link in ("https://github.com/hh/repo", "https://ahh.ru/x", "https://career.habr.com/vacancies/1"):
            with self.subTest(link=link):
                self.assertIsNone(prefilter(self.item(links=[link])))


class DecideTests(unittest.TestCase):
    def bucket(self, key):
        return decide(keyword_classify(tg_item(key)), PROFILE)

    def test_buckets(self):
        self.assertEqual(self.bucket("vk").bucket, "main")
        self.assertEqual(self.bucket("vv_product").bucket, "main")
        self.assertEqual(self.bucket("nofmt").bucket, "unknown_format")
        v = self.bucket("aihr")
        self.assertEqual((v.bucket, v.drop_reason), ("drop", "нельзя удалённо из РФ"))
        self.assertEqual(self.bucket("junior").drop_reason, "грейд: junior")
        self.assertEqual(self.bucket("sa").drop_reason, "роль: system_analyst")
        # требование SQL/Python/Excel снято 20.10: критерий — запрос по названию и формат
        self.assertNotEqual(self.bucket("da_noskills").bucket, "drop")

    def test_title_queries_replace_role_patterns(self):
        # названия — с живого прогона 20.10 (careerstation_analyst, jabka.work)
        profile = dict(PROFILE, title_queries=TITLE_QUERIES)
        cases = {
            "Аналитик в команду монетизации Авито Работы": "",
            "BI-Аналитик в Лабораторию Касперского": "",
            "Senior Data-аналитик": "",
            "Продуктовый аналитик для разработки AI-решений": "",
            "Data Analyst — аналитика данных и ETL для бизнеса": "",  # «бизнес» после тире не считается
            "Product Lead — аналитика и ML для предсказания LTV": "должность не подходит под запрос",
            "Data and Analytics Lead": "должность не подходит под запрос",
            # включающие слова — целым словом: «аналитики» (чего?) — не «аналитик» (живые названия jabka 20.10)
            "Разработчик для автоматизации аналитики Instagram Reels": "должность не подходит под запрос",
            "QA Engineer для B2B SaaS-платформы аналитики инфлюенсеров": "должность не подходит под запрос",
            "Product Lead для аналитики и роста мобильных подписок": "должность не подходит под запрос",
            "Редактор-аналитик для исследований рынка survival-игр": "",
            "Системный аналитик": "стоп-слово в должности: системный",
            "Бизнес-аналитик в Aventus IT": "стоп-слово в должности: бизнес",
            "Business Analyst": "стоп-слово в должности: business",                       # jabka, 21.10
            "Senior Technical Business Analyst для платформы ONDE": "стоп-слово в должности: business",
            "Systems Analyst (Middle)": "стоп-слово в должности: system",
            "Junior Data Аналитик": "стоп-слово в должности: junior",
        }
        for title, reason in cases.items():
            with self.subTest(title=title):
                item = Item(source="site:jabka", kind="site", external_id=title, url="u",
                            text=f"{title}\nУдалённо из России", hint_title=title)
                v = decide(keyword_classify(item), profile)
                self.assertEqual(v.drop_reason, reason)
                if not reason:
                    self.assertEqual(v.bucket, "main")

    def test_company_from_title(self):
        v = keyword_classify(tg_item("vv_product"))
        self.assertEqual(v.company, "ВкусВилл")


class DedupTests(unittest.TestCase):
    def test_cross_channel_duplicate_merged(self):
        a = decide(keyword_classify(tg_item("vv_product", "nodatanojobs", 1)), PROFILE)
        b = decide(keyword_classify(tg_item("vv_product", "careerstation_analyst", 2)), PROFILE)
        dedup([a, b], [])
        kept = [v for v in (a, b) if v.bucket != "drop"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].also_in, ["tg:careerstation_analyst"])

    def test_already_reported_is_dropped(self):
        a = decide(keyword_classify(tg_item("vk")), PROFILE)
        ledger = [{"dedup_key": "x", "title": a.title, "company": a.company}]
        dedup([a], ledger)
        self.assertEqual(a.drop_reason, "уже присылал раньше")

    def test_same_generic_title_without_company_is_not_a_duplicate(self):
        # 33 из 39 строк журнала 21.10 — без компании: «|senior data analyst» не должен глушить чужие вакансии
        def jabka_v(url):
            item = Item(source="site:jabka", kind="site", external_id=url, url=url,
                        text="Senior Data Analyst | Россия | удаленка", hint_title="Senior Data Analyst")
            return decide(keyword_classify(item), dict(PROFILE, title_queries=TITLE_QUERIES))
        ledger = [{"dedup_key": "|senior data analyst", "title": "Senior Data Analyst", "company": None,
                   "url": "https://jabka.work/jobs/a"}]
        other, same = jabka_v("https://jabka.work/jobs/b"), jabka_v("https://jabka.work/jobs/a")
        dedup([other, same], ledger)
        self.assertNotEqual(other.bucket, "drop")
        self.assertEqual(same.drop_reason, "уже присылал раньше")

    def test_junior_from_one_channel_drops_twin_in_another(self):
        def v(channel, grade_hint):
            item = Item(source=f"tg:{channel}", kind="digest_link", external_id=channel, url=f"https://x/{channel}",
                        text="Data Analyst в Сбер Банк\nУдалённо из РФ", hint_title="Data Analyst в Сбер Банк",
                        grade_hint=grade_hint)
            return decide(keyword_classify(item), dict(PROFILE, title_queries=TITLE_QUERIES))
        junior, twin = v("bigtechjobs", "junior"), v("newdirections", None)
        self.assertEqual(twin.bucket, "main")  # сам по себе — подходит
        dedup([junior, twin], [])
        self.assertEqual(twin.drop_reason, "грейд: junior (подборка другого канала)")

    def test_jabka_company_after_separated_at_sign(self):
        # живая карточка jabka 21.10: «@» и компания — разные части текста
        text = ("164K ₽ | 3K$ | Системный аналитик для автоматизации HR-процессов | @ | Mirapolis | · | HRTech | "
                "Москва | · | удаленка | · | 1ч | Системный Анализ")
        item = Item(source="site:jabka", kind="site", external_id="x", url="u", text=text,
                    hint_title="Системный аналитик для автоматизации HR-процессов")
        self.assertEqual(keyword_classify(item).company, "Mirapolis")


class LLMFallbackTests(unittest.TestCase):
    def test_llm_failure_switches_to_keywords(self):
        from vd.llm import LLMUnavailable

        class Broken:
            calls = 0
            def classify(self, item):
                Broken.calls += 1
                raise LLMUnavailable("connection refused")

        items = [tg_item("vk", pid=1), tg_item("nofmt", pid=2)]
        verdicts, info = classify_all(items, PROFILE, Broken())
        self.assertTrue(info["llm_failed"])
        self.assertEqual(Broken.calls, 1)  # после первого отказа модель больше не дёргаем
        self.assertEqual([v.bucket for v in verdicts], ["main", "unknown_format"])


if __name__ == "__main__":
    unittest.main()
