"""2GIS fixtures captured from its public API / JSON-LD on 2026-11-16."""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from vd.models import SourceError
from vd.sources import twogis


FIXTURES = Path(__file__).parent / 'fixtures' / 'twogis'
URL = 'https://job.2gis.ru/api/v1/vacancies?page=1&isRemote=true'


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def detail(**changes):
    from bs4 import BeautifulSoup
    data = json.loads(BeautifulSoup(fixture('analyst.html'), 'html.parser').script.string)
    data.update(changes)
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


class TwoGISSourceTests(unittest.TestCase):
    def analyst(self):
        return next(i for i in twogis.parse_page(fixture('page2.json'), URL.replace('page=1', 'page=2'))[0]
                    if i.external_id == '415')

    def test_real_catalog_pagination_and_canonical_urls(self):
        items, next_url = twogis.parse_page(fixture('page1.json'), URL)
        self.assertEqual(len(items), 15)
        self.assertEqual(next_url, URL.replace('page=1', 'page=2'))
        self.assertEqual(items[0].url, 'https://job.2gis.ru/vacancies/testing/620')
        self.assertEqual(items[0].source, 'site:twogis')
        self.assertIsNone(items[0].published_at)
        last, next_url = twogis.parse_page(fixture('page3.json'), URL.replace('page=1', 'page=3'))
        self.assertEqual(len(last), 6)
        self.assertIsNone(next_url)

    def test_detail_remote_description_without_invented_date(self):
        item = twogis.parse_detail(fixture('analyst.html'), self.analyst())
        self.assertTrue(item.remote_format)
        self.assertIn('2GIS Platform', item.text)
        self.assertIn('@2ГИС', item.text)
        self.assertIsNone(item.published_at)

    def test_detail_only_explicit_remote_and_local_job_schema(self):
        for fmt in ('', 'ON_SITE', 'HYBRID'):
            with self.subTest(fmt=fmt):
                item = twogis.parse_detail(detail(jobLocationType=fmt) + '<footer>Удалённо</footer>', self.analyst())
                self.assertFalse(item.remote_format)

    def test_dates_and_detail_identity(self):
        item = twogis.parse_detail(detail(datePosted='2026-11-15T09:00:00Z'), self.analyst())
        self.assertEqual(item.published_at.isoformat(), '2026-11-15T09:00:00+00:00')
        self.assertIsNone(twogis.parse_detail(detail(datePosted='invalid'), self.analyst()).published_at)
        for html in ('<h1>Blocked</h1>', detail(description=''), detail(identifier={'value': '999'})):
            with self.subTest(html=html[:80]), self.assertRaises(SourceError):
                twogis.parse_detail(html, self.analyst())

    def test_empty_is_distinct_from_malformed_or_incomplete_catalog(self):
        empty = dict(items=[], page=1, pageSize=15, totalItems=0, totalPages=0)
        self.assertEqual(twogis.parse_page(json.dumps(empty), URL), ([], None))
        real = json.loads(fixture('page1.json'))
        for data in ({}, dict(real, items=[]), dict(real, page=2), dict(real, totalPages=1),
                     dict(real, items=[{}]), dict(real, items=real['items'][:-1])):
            with self.subTest(data=str(data)[:60]), self.assertRaises(SourceError):
                twogis.parse_page(json.dumps(data), URL)
        with self.assertRaises(SourceError):
            twogis.parse_page('<html>access denied</html>', URL)

    def test_catalog_remote_boolean_is_explicit(self):
        real = json.loads(fixture('page1.json'))
        for value in (False, None, 'true'):
            real['items'][0]['isRemote'] = value
            items, _ = twogis.parse_page(json.dumps(real), URL)
            self.assertFalse(items[0].remote_format)

    def test_collect_full_pagination_seen_limit_and_detail_failure(self):
        pages = {URL.replace('page=1', f'page={n}'): fixture(f'page{n}.json') for n in range(1, 4)}
        analyst_url = 'https://job.2gis.ru/vacancies/analytics/415'
        pages[analyst_url] = fixture('analyst.html')
        result = twogis.collect([URL], pages.__getitem__, lambda *_: False, True)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 36)
        self.assertTrue(next(i for i in result.items if i.external_id == '415').remote_format)
        limited = twogis.collect([URL], pages.__getitem__, lambda *_: False, False, max_pages=1)
        self.assertIsNotNone(limited.warning)
        del pages[analyst_url]
        failed = twogis.collect([URL], pages.__getitem__, lambda *_: False, False)
        self.assertIsNotNone(failed.error)
        self.assertIsNone(failed.new_bookmark)
        seen = twogis.collect([URL], pages.__getitem__, lambda _, ext: ext == '415', False)
        self.assertIsNone(seen.error)
        self.assertEqual(len(seen.items), 35)

    def test_old_detail_is_only_skipped_on_first_run(self):
        row = next(r for r in json.loads(fixture('page2.json'))['items'] if r['id'] == 415)
        catalog = json.dumps(dict(items=[row], page=1, pageSize=15, totalItems=1, totalPages=1))
        old = (date.today() - timedelta(days=15)).isoformat()
        pages = {URL: catalog, 'https://job.2gis.ru/vacancies/analytics/415': detail(datePosted=old)}
        first = twogis.collect([URL], pages.__getitem__, lambda *_: False, True)
        self.assertEqual(first.items, [])
        self.assertEqual(first.seen_ids, ['415'])
        later = twogis.collect([URL], pages.__getitem__, lambda *_: False, False)
        self.assertEqual(len(later.items), 1)


if __name__ == '__main__':
    unittest.main()
