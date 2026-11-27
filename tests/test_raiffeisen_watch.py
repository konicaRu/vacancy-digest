"""Сторож Райффайзена: у career.raiffeisen.ru нет списка вакансий (только анкета в пул) — ждём, когда появится."""
import unittest
from pathlib import Path

from vd.sources import raiffeisen

HOME = (Path(__file__).parent / 'fixtures' / 'raiffeisen' / 'home.html').read_text(encoding='utf-8')
URL = 'https://career.raiffeisen.ru/vacancies'


def run(html):
    return raiffeisen.collect([URL], lambda url: html, lambda *a: False, True)


class RaiffeisenWatchTests(unittest.TestCase):
    def test_current_site_without_vacancies_is_quiet(self):
        res = run(HOME)  # /vacancies сейчас переадресует на главную без ссылок на вакансии
        self.assertEqual(res.items, [])
        self.assertIsNone(res.error)
        self.assertIsNone(res.warning)
        self.assertIsNotNone(res.new_bookmark)

    def test_vacancy_links_raise_a_warning(self):
        res = run('<html><a href="/vacancies/123-data-analyst">Data Analyst</a></html>')
        self.assertEqual(res.items, [])
        self.assertIn('появились вакансии', res.warning)

    def test_job_posting_raises_a_warning(self):
        res = run('<script type="application/ld+json">{"@type": "JobPosting", "title": "Аналитик"}</script>')
        self.assertIn('появились вакансии', res.warning)

    def test_embed_route_is_not_a_vacancy(self):
        self.assertIsNone(run('<html><a href="/vacancies/embed">x</a></html>').warning)

    def test_fetch_failure_is_an_error(self):
        def broken(url):
            raise ConnectionError('нет сети')
        res = raiffeisen.collect([URL], broken, lambda *a: False, True)
        self.assertIn('ConnectionError', res.error)


if __name__ == '__main__':
    unittest.main()
