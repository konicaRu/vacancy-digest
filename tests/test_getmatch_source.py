import copy
import json
import unittest
from pathlib import Path

from vd.classify import decide, keyword_classify
from vd.models import SourceError
from vd.sources import getmatch

FIXTURES = Path(__file__).parent / 'fixtures' / 'getmatch'
URL = 'https://getmatch.ru/api/offers?sp=product_analyst&sp=data_analyst_bi&pa=all&offset=0&limit=5'


def sample(name):
    return (FIXTURES / (name + '.json')).read_text(encoding='utf-8')


def req(location_id, fmt='remote', exclude=False, ancestors=(), country=''):
    return {'location_id': location_id, 'format': fmt, 'exclude': exclude,
            'ancestors': list(ancestors), 'country': country}


class GetmatchSourceTests(unittest.TestCase):
    def first_item(self):
        return getmatch.parse_page(sample('page0'), URL)[0][0]

    def test_real_catalog_page_items_remote_and_next_offset(self):
        items, next_url = getmatch.parse_page(sample('page0'), URL)
        self.assertEqual([i.external_id for i in items], ['37066', '37362', '35466', '34579', '37345'])
        first = items[0]
        self.assertEqual(first.url, 'https://getmatch.ru/vacancies/37066-produktovyi-analitik')
        self.assertEqual(first.hint_title, 'Продуктовый аналитик')
        self.assertEqual(first.employer, 'Aльфа-банк')
        self.assertEqual(first.published_at.date().isoformat(), '2026-11-25')
        self.assertEqual([i.remote_format for i in items], [True, False, False, True, True])
        self.assertEqual(next_url, URL.replace('offset=0', 'offset=5'))

    def test_last_real_page_has_no_next(self):
        items, next_url = getmatch.parse_page(sample('page65'), URL.replace('offset=0', 'offset=65'))
        self.assertEqual(len(items), 5)
        self.assertIsNone(next_url)

    def test_inconsistent_page_is_an_error_not_a_quiet_partial_read(self):
        data = json.loads(sample('page0'))
        data['offers'] = data['offers'][:3]
        with self.assertRaises(SourceError):
            getmatch.parse_page(json.dumps(data), URL)
        with self.assertRaises(SourceError):
            getmatch.parse_page(sample('page0'), URL.replace('offset=0', 'offset=5'))

    def test_remote_needs_russia_or_whole_world_and_no_exclusion(self):
        world = ['_cu-world']
        russia = ['moscow', 'mo__russia', 'russia', '_cu-europe', '_cu-world']
        cases = [
            ([req('russia', ancestors=world)], True),
            ([req('moscow__mo__russia', ancestors=russia)], True),
            ([req('_cu-world')], True),
            ([req('belarus', ancestors=['_cu-europe', '_cu-world'])], False),
            ([req('moscow__mo__russia', 'hybrid', ancestors=russia)], False),
            ([req('_cu-world'), req('russia', exclude=True, ancestors=world)], False),
            ([], False),
        ]
        for reqs, expected in cases:
            with self.subTest(reqs=reqs):
                self.assertIs(getmatch.remote_of(reqs), expected)

    def test_real_detail_adds_description_and_keeps_confirmed_remote(self):
        item = getmatch.parse_detail(sample('detail_37066'), self.first_item())
        self.assertTrue(item.remote_format)
        self.assertIn('продуктовой аналитики цифровых каналов', item.text)
        self.assertIn('Что делать', item.text)
        verdict = keyword_classify(item)
        self.assertEqual(verdict.company, 'Aльфа-банк')
        self.assertEqual(decide(verdict, {}).bucket, 'main')

    def test_detail_format_overrides_catalog_and_inactive_is_excluded(self):
        original = json.loads(sample('detail_37066'))
        hybrid = copy.deepcopy(original)
        hybrid['location_requirements'][0]['format'] = 'hybrid'
        self.assertFalse(getmatch.parse_detail(json.dumps(hybrid), self.first_item()).remote_format)
        closed = copy.deepcopy(original)
        closed['is_active'] = False
        self.assertFalse(getmatch.parse_detail(json.dumps(closed), self.first_item()).remote_format)

    def test_junior_seniority_becomes_grade_hint(self):
        data = json.loads(sample('detail_37066'))
        data['seniority'] = 'junior'
        self.assertEqual(getmatch.parse_detail(json.dumps(data), self.first_item()).grade_hint, 'junior')

    def test_detail_of_other_vacancy_is_rejected(self):
        data = json.loads(sample('detail_37066'))
        data['id'] = 1
        with self.assertRaises(SourceError):
            getmatch.parse_detail(json.dumps(data), self.first_item())

    def test_collect_reads_api_detail_only_for_matching_titles(self):
        last = URL.replace('offset=0', 'offset=65')
        first, second = json.loads(sample('page0')), json.loads(sample('page65'))
        for page in (first, second):
            page['meta']['total'] = 10
        second['meta']['offset'] = 5
        pages = {URL: json.dumps(first), URL.replace('offset=0', 'offset=5'): json.dumps(second)}
        calls = []

        def fetch(url):
            calls.append(url)
            if url in pages:
                return pages[url]
            if url.startswith('https://getmatch.ru/api/offers/'):
                data = json.loads(sample('detail_37066'))
                data['id'] = int(url.rsplit('/', 1)[1])
                return json.dumps(data)
            raise AssertionError(url)

        profile = {'title_queries': [{'include': ['аналитик', 'analyst'], 'exclude': ['руководитель', 'head']}]}
        res = getmatch.collect([URL], fetch, lambda s, i: False, False, 14, 5, profile=profile)
        self.assertIsNone(res.error, res.error)
        self.assertEqual(len(res.items), 10)
        details = [u for u in calls if '/api/offers/' in u]
        self.assertIn('https://getmatch.ru/api/offers/37066', details)
        self.assertNotIn('https://getmatch.ru/api/offers/37362', details)  # «Руководитель…»
        self.assertNotIn(last, calls)


if __name__ == '__main__':
    unittest.main()
