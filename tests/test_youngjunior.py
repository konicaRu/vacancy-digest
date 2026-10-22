"""youngjunior.ru — живые страницы разделов /data-analyst/jobs и /product-analyst/jobs от 22.10.2026."""
import unittest
from datetime import date, timedelta
from pathlib import Path

from tests.test_classify import TITLE_QUERIES
from vd.classify import decide, keyword_classify
from vd.sources import youngjunior

SAMPLES = Path(__file__).parent / "samples"
PROFILE = {"target_roles": ["product_analyst", "data_analyst"], "exclude_grades": ["intern", "junior"],
           "exclude_title_words": [], "title_queries": TITLE_QUERIES}


def page(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.items = {i.external_id: i for i in youngjunior.parse_page(page("yj_data-analyst_2026-10-22.html"),
                                                                          today=date(2026, 10, 22))}

    def test_card_fields(self):
        self.assertEqual(len(self.items), 20)
        cian = self.items["92689"]
        self.assertEqual(cian.source, "site:youngjunior")
        self.assertEqual(cian.url, "https://youngjunior.ru/data-analyst/jobs/92689")
        self.assertEqual(cian.hint_title, "Продуктовый аналитик")
        self.assertEqual(cian.published_at.date(), date(2026, 10, 22))  # «сегодня»
        v = keyword_classify(cian)
        self.assertEqual(v.company, "Циан")
        self.assertEqual(v.remote_from_russia, "yes")  # «удалёнка»
        self.assertIsNone(cian.grade_hint)  # метки грейда нет — Middle возможен (в вакансии: опыт от 3 лет)
        self.assertEqual(decide(v, PROFILE).bucket, "main")

    def test_grade_label_and_office_are_dropped(self):
        junior = self.items["92299"]  # «Аналитик данных (WB/Ozon) удалёнка · не указана · junior»
        self.assertEqual(junior.grade_hint, "junior")
        self.assertEqual(decide(keyword_classify(junior), PROFILE).drop_reason, "грейд: junior (подборка)")
        self.assertEqual(self.items["90747"].grade_hint, "intern")  # «стажировка … intern»
        office = decide(keyword_classify(self.items["92683"]), PROFILE)  # «в офис»
        self.assertEqual(office.drop_reason, "нельзя удалённо из РФ")

    def test_relative_dates(self):
        today = date(2026, 10, 22)
        cases = {"сегодня": today, "вчера": today - timedelta(days=1), "3 дня назад": today - timedelta(days=3),
                 "12 дней назад": today - timedelta(days=12), "5 окт": date(2026, 10, 5), "непонятно": None}
        for text, expected in cases.items():
            with self.subTest(text=text):
                got = youngjunior.parse_date(text, today)
                self.assertEqual(got.date() if got else None, expected)


class CollectTests(unittest.TestCase):
    def test_collects_both_sections_and_stops_on_empty_page(self):
        pages = {"https://youngjunior.ru/data-analyst/jobs": page("yj_data-analyst_2026-10-22.html"),
                 "https://youngjunior.ru/product-analyst/jobs": page("yj_product-analyst_2026-10-22.html")}
        res = youngjunior.collect(list(pages), lambda u: pages.get(u, "<html></html>"), lambda s, e: False,
                                  first_run=False, lookback_days=5)
        self.assertIsNone(res.error)
        self.assertEqual(res.source, "site:youngjunior")
        self.assertGreater(len(res.items), 20)  # оба раздела, дубли между разделами склеены по id


if __name__ == "__main__":
    unittest.main()
