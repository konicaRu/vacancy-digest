"""Тесты на живых страницах, сохранённых при первом пробном прогоне (19.10.2026)."""
import unittest
from pathlib import Path

from tests.test_classify import TITLE_QUERIES
from vd.classify import classify_all, decide, keyword_classify
from vd.expand import expand_bundles
from vd.models import Verdict
from vd.sources import telegram

SAMPLES = Path(__file__).parent / "samples"
CH = "careerstation_analyst"
PROFILE = {"target_roles": ["product_analyst", "data_analyst"],
           "data_analyst_required_skills": ["sql", "python", "excel"],
           "exclude_grades": ["intern", "junior"], "exclude_title_words": []}


def sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


class LiveTelegramTests(unittest.TestCase):
    def test_heading_split_into_bold_tags_stays_one_line(self):
        # <b> Senior Data</b> <b>Аналитик в Банк 131 </b> — одна строка заголовка, а не две
        post = telegram.fetch_single(CH, "233", lambda url: sample("tg_embed_careerstation_analyst_233.html"))
        self.assertIn("Senior Data Аналитик в Банк 131", post.text.splitlines()[0])
        self.assertEqual(keyword_classify(post).title, "Senior Data Аналитик в Банк 131")

    def test_nested_bundle_from_weekly_digest_is_expanded(self):
        # недельная подборка 248 ссылается на пост 239, который сам — подборка двух вакансий Авито
        page = telegram.parse_page(sample("tg_careerstation_analyst_2026-10-19.html"), CH)
        weekly = next(i for i in page if i.external_id == "248")

        def fetch_post(ch, pid):
            if (ch, pid) == (CH, "239"):
                return telegram.fetch_single(ch, pid, lambda url: sample("tg_embed_careerstation_analyst_239.html"))
            return None

        out, info = expand_bundles([weekly], lambda s, e: False, fetch_post)
        by_id = {i.external_id: i for i in out}
        self.assertNotIn("239", by_id)  # вложенная подборка заменена своими вакансиями
        avito = [i for i in out if i.kind == "digest_link" and "docs.google.com" in i.url]
        self.assertEqual(sorted(i.hint_title for i in avito),
                         ["Аналитик в команду Авито Работы, Анти-абьюз",
                          "Аналитик в команду монетизации Авито Работы"])
        self.assertTrue(all(i.via == f"tg:{CH}" for i in avito))
        self.assertEqual(info["bundles"], 2)


class MtsBankBundleTests(unittest.TestCase):
    """t.me/mtsbankcareer: два формата подборок (живая страница 20.10.2026)."""

    def setUp(self):
        page = telegram.parse_page(sample("tg_mtsbankcareer_2026-10-20.html"), "mtsbankcareer")
        self.posts = {i.external_id: i for i in page}

    def expand(self, pid):
        return expand_bundles([self.posts[pid]], lambda s, e: False, lambda ch, p: None)

    def test_quote_bundle_split_into_vacancies_with_own_text(self):
        # пост 2531: каждая вакансия — цитата «название / описание / Москва | Офис или гибрид / Откликнуться»
        out, info = self.expand("2531")
        self.assertEqual(info["bundles"], 1)
        self.assertNotIn("2531", [i.external_id for i in out])  # сам пост в письмо не идёт
        titles = {i.hint_title: i for i in out}
        self.assertIn("Старший продуктовый аналитик", titles)
        self.assertIn("Ведущий бизнес-аналитик", titles)
        self.assertNotIn("Старший бренд-менеджер", titles)  # не аналитик — не разворачиваем
        pa = titles["Старший продуктовый аналитик"]
        self.assertEqual(pa.url.split("?")[0], "https://job.mtsbank.ru/vacancies/5351")
        self.assertIn("Офис или гибрид", pa.text)
        self.assertNotIn("бренд", pa.text.lower())  # текст — только своей цитаты
        # формат проверяется по самой вакансии: офис → отсев с верной причиной
        v = decide(keyword_classify(pa), dict(PROFILE, title_queries=TITLE_QUERIES))
        self.assertEqual(v.drop_reason, "нельзя удалённо из РФ")

    def test_link_bundle_from_screenshot(self):
        # пост 2521 «Мяу, вакансии»: названия — сами ссылки на сайт
        out, info = self.expand("2521")
        self.assertEqual(info["bundles"], 1)
        self.assertEqual(sorted(i.hint_title for i in out), ["Бизнес-аналитик", "Системный аналитик"])


class FakeLLM:
    """Отвечает как Qwen на живом прогоне 19.10: «remote=no», хотя про формат в посте ни слова."""

    def __init__(self, remote="no", contact="[LinkedIn]"):
        self.remote, self.contact = remote, contact

    def classify(self, item):
        return Verdict(item=item, is_vacancy=True, title="Senior Data Аналитик", company="Hypercell Games",
                       role="data_analyst", grade="senior", remote_from_russia=self.remote,
                       contact=self.contact, reason="Не подходит: опыт в мобильных играх", by_llm=True)


class LLMGuardTests(unittest.TestCase):
    def hypercell(self):
        return telegram.fetch_single(CH, "247", lambda url: sample("tg_embed_careerstation_analyst_247.html"))

    def test_llm_no_without_format_words_becomes_unknown(self):
        verdicts, _ = classify_all([self.hypercell()], PROFILE, FakeLLM(remote="no"))
        self.assertEqual(verdicts[0].remote_from_russia, "unknown")
        self.assertEqual(verdicts[0].bucket, "unknown_format")

    def test_llm_no_kept_when_text_mentions_office(self):
        item = self.hypercell()
        item.text += "\nФормат: гибрид, офис в Москве"
        verdicts, _ = classify_all([item], PROFILE, FakeLLM(remote="no"))
        self.assertEqual(verdicts[0].bucket, "drop")

    def test_contact_must_look_like_handle_email_or_link(self):
        cases = {"[LinkedIn]": None, "@": None, "[ссылка]": None, "@julietes": "@julietes",
                 "hr@company.ru": "hr@company.ru", "https://t.me/julietes": "https://t.me/julietes"}
        for raw, expected in cases.items():
            verdicts, _ = classify_all([self.hypercell()], PROFILE, FakeLLM(contact=raw))
            self.assertEqual(verdicts[0].contact, expected, raw)


if __name__ == "__main__":
    unittest.main()
