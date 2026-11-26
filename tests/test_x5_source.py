"""X5 (rabota.x5.ru): открытый API вакансий группы, формат работы — структурированное поле."""
import json
import unittest
from pathlib import Path
from urllib.parse import unquote

from vd.classify import decide, keyword_classify
from vd.models import SourceError
from vd.sources import x5

FX = Path(__file__).parent / 'fixtures' / 'x5'
URL = 'https://rabota.x5.ru/vacancy/api/v1/public/vacancies?search=analyst&page=1&page_size=10'
URL_RU = 'https://rabota.x5.ru/vacancy/api/v1/public/vacancies?search=аналитик&page=1&page_size=10'
FULL_STACK = '70e115c3'


def read(name):
    return (FX / name).read_text(encoding='utf-8')


def detail_name():
    return next(p.name for p in FX.glob('detail_*.json'))


class X5Tests(unittest.TestCase):
    def full_stack(self):
        return x5.parse_page(read('search_analyst_page1.json'), URL)[0][0]

    def test_real_search_item_remote_unit_and_public_url(self):
        items, next_url = x5.parse_page(read('search_analyst_page1.json'), URL)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertTrue(item.external_id.startswith(FULL_STACK))
        self.assertEqual(item.url, 'https://rabota.x5.ru/vacancies/' + item.external_id)
        self.assertEqual(item.hint_title, 'Full Stack Analytics / Product Analyst (AI-first)')
        self.assertEqual(item.employer, 'X5 Tech')
        self.assertTrue(item.remote_format)
        self.assertEqual(item.published_at.date().isoformat(), '2026-09-07')
        self.assertIsNone(next_url)

    def test_pages_and_formats_of_real_multi_page_search(self):
        items, next_url = x5.parse_page(read('search_analitik_page1.json'), URL_RU)
        self.assertEqual(len(items), 10)
        self.assertEqual(unquote(next_url), URL_RU.replace('page=1', 'page=2'))
        formats = {i.hint_title: i.remote_format for i in items}
        self.assertFalse(formats['Продуктовый аналитик'])  # гибрид в X5 Tech
        data = json.loads(read('search_analitik_page1.json'))
        data['items'] = data['items'][:3]
        with self.assertRaises(SourceError):
            x5.parse_page(json.dumps(data), URL_RU)

    def test_real_detail_adds_all_sections_and_passes_classifier(self):
        item = x5.parse_detail(read(detail_name()), self.full_stack())
        self.assertIn('LLM', item.text)
        self.assertIn('Формат работы: удалённо', item.text)
        self.assertEqual(decide(keyword_classify(item), {}).bucket, 'main')

    def test_detail_format_is_rechecked_and_other_vacancy_rejected(self):
        data = json.loads(read(detail_name()))
        office = dict(data, work_format='office')
        self.assertFalse(x5.parse_detail(json.dumps(office), self.full_stack()).remote_format)
        other = dict(data, id='00000000-0000-0000-0000-000000000000')
        with self.assertRaises(SourceError):
            x5.parse_detail(json.dumps(other), self.full_stack())

    def test_collect_reads_detail_api(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return read('search_analyst_page1.json') if url == URL else read(detail_name())
        res = x5.collect([URL], fetch, lambda *_: False, False, profile={})
        self.assertIsNone(res.error, res.error)
        self.assertTrue(any('/vacancy/api/v1/public/vacancies/' + FULL_STACK in u for u in calls))
        self.assertIn('LLM', res.items[0].text)


if __name__ == '__main__':
    unittest.main()
