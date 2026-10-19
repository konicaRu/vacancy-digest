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
        self.assertEqual(self.bucket("da_noskills").drop_reason, "аналитик данных без SQL/Python/Excel")

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
