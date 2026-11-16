import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from vd import digest
from vd.classify import keyword_classify, decide
from vd.models import SourceError, SourceResult
from vd.sources import magnit
from vd.store import Store

FIXTURES = Path(__file__).parent / 'fixtures' / 'magnit'
URL = 'https://magnit.tech/api/v1/vacancy?page=1'


def sample(name):
    return (FIXTURES / (name + '.json')).read_text(encoding='utf-8')


def one_page():
    data = json.loads(sample('page6'))
    row = json.loads(sample('active'))['results']
    data['results'] = [row]
    data['meta'].update(total=1, per_page=9, current_page=1, has_more_pages=False, **{'from': 1, 'to': 1})
    return json.dumps(data)


class MagnitSourceTests(unittest.TestCase):
    def item(self):
        return magnit.parse_page(one_page(), URL)[0][0]

    def test_real_catalog_pages_and_public_url(self):
        items, next_url = magnit.parse_page(sample('page1'), URL)
        self.assertEqual(len(items), 9)
        self.assertEqual(items[0].external_id, '2921')
        self.assertEqual(items[0].url, 'https://magnit.tech/vacancies/2921')
        self.assertEqual(next_url, URL.replace('page=1', 'page=2'))
        last, next_url = magnit.parse_page(sample('page6'), URL.replace('page=1', 'page=6'))
        self.assertEqual(len(last), 3)
        self.assertIsNone(next_url)

    def test_real_active_detail_confirmed_remote_and_no_invented_date(self):
        item = magnit.parse_detail(sample('active'), self.item())
        self.assertTrue(item.remote_format)
        self.assertIsNone(item.published_at)
        self.assertIn('SQL', item.text)
        self.assertEqual(keyword_classify(item).company, 'Магнит Tech')
        self.assertEqual(decide(keyword_classify(item), {}).bucket, 'main')

    def test_detail_format_is_authoritative_over_list_and_generic_text(self):
        original = json.loads(sample('active'))
        for formats in ([], [{'foreign_id': 16100, 'name': 'Москва (гибрид/офис)'}]):
            with self.subTest(formats=formats):
                data = copy.deepcopy(original)
                data['results']['work_formats'] = formats
                data['results']['offer'] = '<p>Удалённо в другой команде.</p>'
                item = magnit.parse_detail(json.dumps(data), self.item())
                self.assertFalse(item.remote_format)
                self.assertEqual(decide(keyword_classify(item), {}).bucket, 'drop')

    def test_archived_and_unpublished_never_pass(self):
        data = json.loads(sample('active'))
        for changes in ({'status': 'archived'}, {'is_published': False}):
            changed = copy.deepcopy(data)
            changed['results'].update(changes)
            item = magnit.parse_detail(json.dumps(changed), self.item())
            self.assertFalse(item.remote_format)
            self.assertEqual(decide(keyword_classify(item), {}).bucket, 'drop')

    def test_broken_pagination_empty_and_wrong_detail_are_distinct(self):
        empty = json.loads(one_page())
        empty['results'] = []
        empty['meta'].update(total=0, has_more_pages=False, **{'from': None, 'to': None})
        self.assertEqual(magnit.parse_page(json.dumps(empty), URL), ([], None))
        original = json.loads(sample('page1'))
        for patch in ({'current_page': 2}, {'has_more_pages': False}, {'total': 1}):
            data = copy.deepcopy(original)
            data['meta'].update(patch)
            with self.subTest(patch=patch), self.assertRaises(SourceError):
                magnit.parse_page(json.dumps(data), URL)
        for bad in ('<html>blocked</html>', '{}', sample('archived')):
            with self.subTest(bad=bad[:40]), self.assertRaises(SourceError):
                magnit.parse_detail(bad, self.item())

    def test_collect_fetches_api_details_but_keeps_public_link_and_seen(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return one_page() if url == URL else sample('active')
        result = magnit.collect([URL], fetch, lambda *_: False, True)
        self.assertIsNone(result.error)
        self.assertEqual(calls, [URL, 'https://magnit.tech/api/v1/vacancy/3107'])
        self.assertEqual(result.items[0].url, 'https://magnit.tech/vacancies/3107')
        calls.clear()
        result = magnit.collect([URL], fetch, lambda *_: True, False)
        self.assertEqual(calls, [URL])
        self.assertEqual(result.items, [])
        def failed(url):
            if url != URL:
                raise TimeoutError('detail')
            return one_page()
        result = magnit.collect([URL], failed, lambda *_: False, False)
        self.assertTrue(result.error)
        self.assertIsNone(result.new_bookmark)

    def test_registration_schedule_and_source_name(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = Store(Path(temp.name) / 'state.sqlite')
        self.addCleanup(store.close)
        cfg = {'sources': {'sites': [{'name': 'magnit', 'urls': [URL], 'morning_only': True}]}}
        with mock.patch.object(magnit, 'collect', return_value=SourceResult(source='site:magnit')):
            self.assertEqual(main.collect_all(cfg, store, lambda _: '', slot='am')[0].source, 'site:magnit')
            self.assertEqual(main.collect_all(cfg, store, lambda _: '', slot='pm'), [])
            self.assertEqual(len(main.collect_all(cfg, store, lambda _: '', slot='pm', dry_run=True)), 1)
        self.assertEqual(digest.source_name('site:magnit'), 'Магнит Tech')
