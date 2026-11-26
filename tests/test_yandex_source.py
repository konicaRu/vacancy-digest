"""Яндекс (yandex.ru/jobs): открытый API публикаций; формат работы — work_modes."""
import json
import unittest
from pathlib import Path

from vd.models import SourceError
from vd.sources import yandex

FX = Path(__file__).parent / 'fixtures' / 'yandex'
URL = 'https://yandex.ru/jobs/api/publications/?text=аналитик&page_size=10'


def read(name):
    return (FX / name).read_text(encoding='utf-8')


def detail_name():
    return next(p.name for p in FX.glob('detail_*.json'))


class YandexTests(unittest.TestCase):
    def first(self):
        return yandex.parse_page(read('search_page1.json'), URL)[0][0]

    def test_real_page_items_service_format_and_next_cursor(self):
        items, next_url = yandex.parse_page(read('search_page1.json'), URL)
        self.assertEqual(len(items), 10)
        first = items[0]
        data = json.loads(read('search_page1.json'))['results'][0]
        self.assertEqual(first.external_id, str(data['id']))
        self.assertEqual(first.url, 'https://yandex.ru/jobs/vacancies/' + data['publication_slug_url'])
        self.assertEqual(first.employer, 'Яндекс')
        self.assertIn(data['public_service']['name'], first.text)
        self.assertFalse(first.remote_format)
        self.assertTrue(next_url.startswith('https://yandex.ru/jobs/api/jobs/publications/?'))
        self.assertIn('cursor=', next_url)

    def test_remote_work_mode_and_last_page(self):
        data = json.loads(read('search_page1.json'))
        data['results'][0]['vacancy']['work_modes'] = [{'id': 1, 'slug': 'remote', 'name': 'Удалённый'}]
        data['next'] = None
        items, next_url = yandex.parse_page(json.dumps(data), URL)
        self.assertTrue(items[0].remote_format)
        self.assertIsNone(next_url)

    def test_foreign_next_link_or_broken_answer_is_an_error(self):
        data = json.loads(read('search_page1.json'))
        for bad in (dict(data, next='https://evil.test/jobs/api/'), dict(data, results=None)):
            with self.subTest(bad=bad.get('next')), self.assertRaises(SourceError):
                yandex.parse_page(json.dumps(bad), URL)

    def test_real_detail_sections_date_and_format(self):
        item = yandex.parse_detail(read(detail_name()), self.first())
        self.assertIn('SQL', item.text)
        self.assertIsNotNone(item.published_at)
        self.assertFalse(item.remote_format)
        other = json.loads(read(detail_name()))
        other['id'] = 1
        with self.assertRaises(SourceError):
            yandex.parse_detail(json.dumps(other), self.first())

    def test_collect_reads_detail_api_by_id(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url == URL:
                data = json.loads(read('search_page1.json'))
                data['next'] = None
                return json.dumps(data)
            pid = url.rstrip('/').rsplit('/', 1)[1]
            detail = json.loads(read(detail_name()))
            detail['id'] = int(pid)
            return json.dumps(detail)
        res = yandex.collect([URL], fetch, lambda *_: False, False, profile={})
        self.assertIsNone(res.error, res.error)
        first_id = json.loads(read('search_page1.json'))['results'][0]['id']
        self.assertIn(f'https://yandex.ru/jobs/api/publications/{first_id}/', calls)


if __name__ == '__main__':
    unittest.main()
