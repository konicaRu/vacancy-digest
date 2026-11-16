import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from vd.models import SourceError
from vd.sources import sber


FIXTURES = Path(__file__).parent / 'fixtures'
URL = ('https://rabota.sber.ru/public/app-candidate-public-api-gateway/api/v1/'
       'publications?skip=0&take=2&searchString=analyst')


class SberSourceTests(unittest.TestCase):
    def setUp(self):
        self.page = json.loads((FIXTURES / 'sber_page.json').read_text(encoding='utf-8'))
        self.detail = (FIXTURES / 'sber_detail.html').read_text(encoding='utf-8')

    def parse(self, data=None, url=URL):
        return sber.parse_page(json.dumps(data if data is not None else self.page), url)

    def test_real_page_ids_dates_formats_and_pagination(self):
        items, next_url = self.parse()
        self.assertEqual([x.external_id for x in items], ['4581675', '4578291'])
        self.assertEqual(items[0].published_at.isoformat(), '2026-11-11T08:52:36+00:00')
        self.assertEqual([x.remote_format for x in items], [False, False])
        self.assertEqual(next_url, URL.replace('skip=0', 'skip=2'))
        self.assertEqual(items[0].source, 'site:sber')

    def test_detail_confirms_remote_from_structured_schedule_only(self):
        item = self.parse()[0][1]
        item = sber.parse_detail(self.detail, item)
        self.assertTrue(item.remote_format)
        self.assertIn('Формат работы:', item.text)
        self.assertIn('специалист', item.text.lower())

    def test_hybrid_office_and_missing_schedule_are_not_remote(self):
        data = json.loads(self.detail.split('>', 1)[1].rsplit('</script>', 1)[0])
        for schedule in [1, 2, 3, None, '4']:
            with self.subTest(schedule=schedule):
                row = data['props']['pageProps']['vacancy']
                row['workScheduleId'] = schedule
                row['conditions'] = 'Гибридный формат. Удаленная работа в другой команде.'
                item = self.parse()[0][1]
                sber.parse_detail('<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>', item)
                self.assertFalse(item.remote_format)

    def test_absent_or_invalid_date_is_not_replaced_with_collection_time(self):
        for date in [None, 'bad date']:
            self.page['data']['vacancies'][0]['publicationDate'] = date
            self.assertIsNone(self.parse()[0][0].published_at)

    def test_empty_response_distinct_from_malformed(self):
        self.assertEqual(self.parse({'success': True, 'data': {'vacancies': [], 'total': 0}}), ([], None))
        for data in [{}, {'success': False, 'data': {'vacancies': [], 'total': 0}},
                     {'success': True, 'data': {'vacancies': [], 'total': 2}},
                     {'success': True, 'data': {'vacancies': [], 'total': -1}}]:
            with self.subTest(data=data), self.assertRaises(SourceError):
                self.parse(data)
        with self.assertRaises(SourceError):
            sber.parse_page('<html>blocked</html>', URL)

    def test_incomplete_card_and_detail_fail(self):
        del self.page['data']['vacancies'][0]['title']
        with self.assertRaises(SourceError):
            self.parse()
        item = sber.parse_page((FIXTURES / 'sber_page.json').read_text(encoding='utf-8'), URL)[0][1]
        for html in ['<html>blocked</html>', '<script id="__NEXT_DATA__">{}</script>',
                     self.detail.replace('4578291', '4578292')]:
            with self.subTest(html=html[:50]), self.assertRaises(SourceError):
                sber.parse_detail(html, item)

    def test_collect_reads_next_page_and_failed_page_or_detail_has_no_bookmark(self):
        self.page['data']['vacancies'] = [self.page['data']['vacancies'][1]]
        self.page['data']['vacancies'][0]['title'] = 'Data analyst'
        self.page['data']['vacancies'][0]['publicationDate'] = None
        self.page['data']['total'] = 2
        calls = []
        def fetch(url):
            calls.append(url)
            if '/search/' in url:
                return self.detail
            if 'skip=1' in url:
                return json.dumps({'success': True, 'data': {'vacancies': [dict(self.page['data']['vacancies'][0], internalId=123)], 'total': 2}})
            return json.dumps(self.page)
        result = sber.collect([URL], fetch, lambda *_: False, False)
        self.assertIsNotNone(result.error)  # second detail belongs to a different vacancy
        self.assertIsNone(result.new_bookmark)
        self.assertTrue(any('skip=1' in url for url in calls))
        self.page['data']['total'] = 1
        result = sber.collect([URL], fetch, lambda *_: False, False)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 1)
        self.assertTrue(result.items[0].remote_format)
        def failed(url):
            if '/search/' in url:
                raise TimeoutError('detail failed')
            return json.dumps(self.page)
        result = sber.collect([URL], failed, lambda *_: False, False)
        self.assertIsNotNone(result.error)
        self.assertIsNone(result.new_bookmark)

    def test_seen_and_old_cards_do_not_fetch_details(self):
        self.page['data']['total'] = 2
        calls = []
        def fetch(url):
            calls.append(url)
            return json.dumps(self.page)
        result = sber.collect([URL], fetch, lambda *_: True, False)
        self.assertIsNone(result.error)
        self.assertEqual(calls, [URL])
        calls.clear()
        for row in self.page['data']['vacancies']:
            row['publicationDate'] = '2000-01-01T00:00:00Z'
        result = sber.collect([URL], fetch, lambda *_: False, True)
        self.assertEqual(result.seen_ids, ['4581675', '4578291'])
        self.assertEqual(calls, [URL])
