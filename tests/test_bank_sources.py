import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import main
from vd import digest
from vd.classify import decide, keyword_classify
from vd.models import SourceError
from vd.sources import alfabank, tbank
from vd.store import Store

FIXTURES = Path(__file__).parent / 'fixtures' / 'banks'
ALFA = 'https://job.alfabank.ru/api/vacancies?text=аналитик&skip=0&take=100'
TBANK = 'https://www.tbank.ru/pfpjobs/papi/getVacancies?searchQuery=аналитик&offset=0&limit=10'


def data(name):
    return json.loads((FIXTURES / (name + '.json')).read_text(encoding='utf-8'))


class BankSourceTests(unittest.TestCase):
    def alfa_item(self):
        return alfabank.parse_page(json.dumps(data('alfa_page')), ALFA)[0][0]

    def tbank_item(self, index=0):
        return tbank.parse_page(json.dumps(data('tbank_page')), TBANK)[0][index]

    def test_real_catalogs_and_pagination(self):
        items, next_url = tbank.parse_page(json.dumps(data('tbank_page')), TBANK)
        self.assertEqual(len(items), 7)  # Three internship redirects have no career card.
        self.assertEqual(items[0].external_id, 'ca55f0ed-d75c-437f-bd36-d0f34ac4cb88')
        self.assertIn('/sistemnyj-analitik-union/ca55f0ed-d75c-437f-bd36-d0f34ac4cb88/', items[0].url)
        self.assertIn('offset=10', next_url)
        self.assertIn('searchQuery=', next_url)
        items, next_url = alfabank.parse_page(json.dumps(data('alfa_page')), ALFA)
        self.assertEqual(len(items), 2)
        self.assertIsNone(next_url)
        self.assertEqual(items[0].url, 'https://job.alfabank.ru/vacancies/moskva/remote-job/starshii-ekspert-po-ab-testirovaniiu_produktovyii-analitik_38379')
        page = data('alfa_page')
        page.update(take=1)
        page['items'] = page['items'][:1]
        _, next_url = alfabank.parse_page(json.dumps(page), ALFA.replace('take=100', 'take=1'))
        self.assertIn('skip=1', next_url)

    def test_remote_details_use_structured_format(self):
        alfa = alfabank.parse_detail(json.dumps(data('alfa_remote')), self.alfa_item())
        self.assertTrue(alfa.remote_format)
        self.assertIn('SQL', alfa.text)
        self.assertEqual(keyword_classify(alfa).company, 'Альфа-Банк')
        self.assertEqual(decide(keyword_classify(alfa), {}).bucket, 'main')
        tb = tbank.parse_detail(json.dumps(data('tbank_remote')), self.tbank_item())
        self.assertTrue(tb.remote_format)
        self.assertIn('SQL', tb.text)
        self.assertEqual(keyword_classify(tb).company, 'Т-Банк')
        self.assertIsNone(tb.published_at)

    def test_live_mixed_case_slugs_and_opaque_detail_identity(self):
        page = TBANK.replace('offset=0', 'offset=30')
        items, next_url = tbank.parse_page(json.dumps(data('tbank_mixed_case_page')), page)
        self.assertEqual(len(items), 10)
        self.assertIn('/Lid-produktovoy-analitiki/', items[6].url)
        self.assertIn('offset=40', next_url)
        item = alfabank.parse_page(json.dumps(data('alfa_page')), ALFA)[0][1]
        detail = data('alfa_opaque')
        self.assertFalse(alfabank.parse_detail(json.dumps(detail), item).remote_format)
        detail['slug'] = '/moskva/central-office/other_11111'
        with self.assertRaises(SourceError):
            alfabank.parse_detail(json.dumps(detail), item)

    def test_live_dot_slug_and_urlsafe_opaque_id(self):
        page = TBANK.replace('offset=0&limit=10', 'offset=75&limit=25')
        items, _ = tbank.parse_page(json.dumps(data('tbank_dot_slug_page')), page)
        self.assertIn('/specialist-tehnicheskoy-podderzhki-avto.ru-biznes/', items[13].url)
        row = data('alfa_urlsafe_id')
        item = self.alfa_item()
        item.external_id = '39884'
        item.url = 'https://job.alfabank.ru/vacancies' + row['slug']
        item.hint_title = 'Главный аналитик управления взыскания и дистанционных продаж'
        self.assertTrue(alfabank.parse_detail(json.dumps(row), item).remote_format)

    def test_office_missing_and_wrong_remote_markers_drop_despite_text(self):
        for formats in ([], [{'key': '1005', 'value': 'Офис'}],
                        [{'key': '1003', 'value': 'Гибрид'}]):
            row = data('alfa_remote')
            row['jobTypes'] = formats
            row['description'] = '<p>Можно удалённо в другой команде. SQL.</p>'
            item = alfabank.parse_detail(json.dumps(row), self.alfa_item())
            self.assertFalse(item.remote_format)
            self.assertEqual(decide(keyword_classify(item), {}).bucket, 'drop')
        for tags in ([], [{'text': 'Офис'}, {'text': 'Гибрид'}]):
            row = data('tbank_remote')
            row['payload']['tags'] = tags
            row['payload']['description'] = [{'key': 'Описание', 'content': '<p>Удалённая работа SQL</p>'}]
            item = tbank.parse_detail(json.dumps(row), self.tbank_item())
            self.assertFalse(item.remote_format)
            self.assertEqual(decide(keyword_classify(item), {}).bucket, 'drop')
        office = tbank.parse_detail(json.dumps(data('tbank_office')), self.tbank_item(1))
        self.assertFalse(office.remote_format)

    def test_inactive_hidden_internal_and_expired_are_excluded(self):
        for patch in ({'isHidden': True}, {'isInternal': True}, {'expirationDate': '2000-01-01T00:00:00Z'}):
            row = data('alfa_remote')
            row.update(patch)
            self.assertFalse(alfabank.parse_detail(json.dumps(row), self.alfa_item()).remote_format)
        row = data('tbank_remote')
        row['payload'].update(status='not-found', description=[])
        self.assertFalse(tbank.parse_detail(json.dumps(row), self.tbank_item()).remote_format)

    def test_broken_catalogs_fail_instead_of_becoming_empty_success(self):
        for module, name, url in ((tbank, 'tbank_page', TBANK), (alfabank, 'alfa_page', ALFA)):
            for text in ('{}', '<html>captcha</html>'):
                with self.subTest(module=module.__name__), self.assertRaises(SourceError):
                    module.parse_page(text, url)
            row = data(name)
            if module is tbank:
                row['payload']['nextPagination']['offset'] = 0
            else:
                row['items'] = []
            with self.assertRaises(SourceError):
                module.parse_page(json.dumps(row), url)
        row = data('tbank_page')
        row['payload']['nextPagination']['isFinished'] = True
        with self.assertRaises(SourceError):
            tbank.parse_page(json.dumps(row), TBANK)

    def test_empty_catalogs_are_valid_and_duplicate_ids_are_not(self):
        a = data('alfa_page')
        a.update(total=0, items=[])
        self.assertEqual(alfabank.parse_page(json.dumps(a), ALFA), ([], None))
        t = data('tbank_page')
        t['payload'].update(vacancies=[], nextPagination={'offset': 0, 'totalCount': 0, 'isFinished': True})
        self.assertEqual(tbank.parse_page(json.dumps(t), TBANK), ([], None))
        a = data('alfa_page')
        a['items'][1] = copy.deepcopy(a['items'][0])
        with self.assertRaises(SourceError):
            alfabank.parse_page(json.dumps(a), ALFA)
        t = data('tbank_page')
        t['payload']['vacancies'][1] = copy.deepcopy(t['payload']['vacancies'][0])
        with self.assertRaises(SourceError):
            tbank.parse_page(json.dumps(t), TBANK)

    def test_mismatched_and_missing_descriptions_fail(self):
        for module, name, item, key in ((alfabank, 'alfa_remote', self.alfa_item(), 'id'),
                                        (tbank, 'tbank_remote', self.tbank_item(), 'vacancyId')):
            row = data(name)
            target = row['payload'] if module is tbank else row
            target[key] = 'wrong'
            with self.assertRaises(SourceError):
                module.parse_detail(json.dumps(row), item)
            row = data(name)
            target = row['payload'] if module is tbank else row
            target['description'] = [] if module is tbank else ''
            with self.assertRaises(SourceError):
                module.parse_detail(json.dumps(row), item)

    def test_alfa_collect_seen_lookback_and_detail_failure(self):
        page = data('alfa_page')
        page['items'] = page['items'][:1]
        page.update(total=1)
        page['items'][0]['createdAt'] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        fetch = lambda url: json.dumps(page if url == ALFA else data('alfa_remote'))
        result = alfabank.collect([ALFA], fetch, lambda *_: False, True)
        self.assertEqual(result.seen_ids, ['38379'])
        self.assertEqual(result.items, [])
        result = alfabank.collect([ALFA], fetch, lambda *_: True, False)
        self.assertEqual(result.items, [])
        def failed(url):
            if url != ALFA:
                raise TimeoutError('detail')
            return json.dumps(page)
        result = alfabank.collect([ALFA], failed, lambda *_: False, False)
        self.assertTrue(result.error)
        self.assertIsNone(result.new_bookmark)

    def test_tbank_collect_posts_search_and_offsets_and_warns_on_limit(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append((url, kwargs))
            body = kwargs['json']
            if url.endswith('/getVacancies'):
                if body['pagination']['offset'] == 0:
                    return json.dumps(data('tbank_page'))
                row = data('tbank_page')
                row['payload'].update(vacancies=[], nextPagination={'offset': 10, 'totalCount': 10, 'isFinished': True})
                return json.dumps(row)
            return json.dumps(data('tbank_remote'))
        result = tbank.collect([TBANK], fetch, lambda _s, key: key != 'ca55f0ed-d75c-437f-bd36-d0f34ac4cb88', False)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(calls[0][1]['json']['filters']['generatedGraphQL']['searchQuery'], 'аналитик')
        self.assertEqual(calls[-1][1]['json']['pagination']['offset'], 10)
        self.assertTrue(result.items[0].remote_format)
        result = tbank.collect([TBANK], fetch, lambda *_: True, False, max_pages=1)
        self.assertTrue(result.warning)

    def test_registration_runs_both_banks_in_evening_with_real_parsing(self):
        cfg = {'sources': {'sites': [
            {'name': 'alfabank', 'urls': [ALFA], 'morning_only': False},
            {'name': 'tbank', 'urls': [TBANK], 'morning_only': False, 'max_pages': 1}]}}
        def fetch(url, **kwargs):
            if 'alfabank' in url:
                return json.dumps(data('alfa_page') if '/api/vacancies?' in url else data('alfa_remote'))
            return json.dumps(data('tbank_page'))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'state.sqlite')
            try:
                # Seen prevents fetching details; real catalogs still exercise collector registration.
                with mock.patch.object(store, 'is_seen', return_value=True):
                    results = main.collect_all(cfg, store, fetch, slot='pm')
                self.assertEqual([r.source for r in results], ['site:alfabank', 'site:tbank'])
                self.assertTrue(all(r.error is None for r in results))
            finally:
                store.close()
        self.assertEqual(digest.source_name('site:tbank'), 'Т-Банк')
        self.assertEqual(digest.source_name('site:alfabank'), 'Альфа-Банк')

    def test_make_fetcher_keeps_get_and_supports_read_only_post(self):
        session = mock.Mock()
        with mock.patch.object(main, 'make_session', return_value=session), mock.patch.object(main.time, 'sleep'):
            fetch = main.make_fetcher({})
            fetch('https://example.test/list')
            session.get.assert_called_once_with('https://example.test/list', timeout=25)
            fetch('https://example.test/search', json={'limit': 25})
            session.post.assert_called_once_with('https://example.test/search', json={'limit': 25}, timeout=25)
