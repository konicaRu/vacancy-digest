import json
import unittest
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import main
from vd.classify import keyword_classify, prefilter
from vd.models import Item, SourceError
from vd.sources import vk, mts
from vd.store import Store


SAMPLES = Path(__file__).parent / 'samples'
NO_DETAILS = {'title_queries': [{'include': ['unmatched-role'], 'exclude': []}]}


def sample(name):
    return (SAMPLES / f'career_{name}').read_text(encoding='utf-8')


class VKSourceTests(unittest.TestCase):
    URL = 'https://team.vk.company/career/api/v2/vacancies/?title=аналитик&limit=25&offset=0'

    def test_real_list_titles_company_and_explicit_remote(self):
        items, next_url = vk.parse_page(sample('vk_api.json'), self.URL)
        self.assertEqual(len(items), 25)
        self.assertEqual(items[0].external_id, '54827')
        self.assertEqual(items[0].hint_title, 'Аналитик-исследователь')
        self.assertEqual(items[0].url, 'https://team.vk.company/vacancy/54827/')
        verdict = keyword_classify(items[0])
        self.assertEqual(verdict.company, 'VK / Облако')
        self.assertEqual(verdict.remote_from_russia, 'yes')
        self.assertEqual(urlparse(next_url).scheme, 'https')
        self.assertEqual(parse_qs(urlparse(next_url).query)['offset'], ['25'])

    def test_combined_format_is_hybrid(self):
        items, _ = vk.parse_page(sample('vk_api.json'), self.URL)
        item = next(i for i in items if i.external_id == '52312')
        self.assertEqual(keyword_classify(item).remote_from_russia, 'no')

    def test_all_thirty_vacancies_are_read(self):
        result = vk.collect([self.URL], lambda u: sample('vk_next.json' if 'offset=25' in u else 'vk_api.json'),
                            lambda s,i: False, False, profile=NO_DETAILS)
        self.assertIsNone(result.error)
        self.assertIsNone(result.warning)
        self.assertEqual(len(result.items), 30)
        self.assertEqual(len({i.external_id for i in result.items}), 30)

    def test_real_description_and_publication_date_without_similar_jobs(self):
        item = Item('site:vk', 'site', '51963', 'https://team.vk.company/vacancy/51963/',
                    'Старший продуктовый аналитик | @VK / VK Видео', hint_title='Старший продуктовый аналитик')
        html = sample('vk_detail.html') + '<nav>Удалённо из РФ</nav><section>Похожие вакансии: Head of analytics</section>'
        item = vk.parse_detail(html, item)
        self.assertEqual(item.published_at.date().isoformat(), '2026-11-12')
        self.assertIn('Superset', item.text)
        self.assertNotIn('Похожие вакансии', item.text)
        self.assertNotIn('Head of analytics', item.text)
        self.assertEqual(keyword_classify(item).remote_from_russia, 'unknown')

    def test_empty_and_broken_lists_are_different(self):
        self.assertEqual(vk.parse_page('{"count":0,"next":null,"results":[]}', self.URL), ([], None))
        for bad in ('<html>captcha</html>', '{"results":[]}', '{"count":30,"next":null,"results":[]}'):
            with self.subTest(bad=bad), self.assertRaises(SourceError):
                vk.parse_page(bad, self.URL)

    def test_next_must_stay_on_public_api(self):
        for bad_url in ('https://other.example/internal', 'http://team.vk.company/admin/'):
            data = json.loads(sample('vk_api.json')); data['next'] = bad_url
            with self.subTest(url=bad_url), self.assertRaises(SourceError):
                vk.parse_page(json.dumps(data), self.URL)

    def test_incomplete_or_nonadvancing_next_keeps_no_state(self):
        for next_url in (None, self.URL):
            data = json.loads(sample('vk_api.json')); data['next'] = next_url
            result = vk.collect([self.URL], lambda u: json.dumps(data), lambda s,i: False,
                                False, profile=NO_DETAILS)
            with self.subTest(next_url=next_url):
                self.assertTrue(result.error)
                self.assertEqual(result.items, [])
                self.assertIsNone(result.new_bookmark)


class MTSSourceTests(unittest.TestCase):
    URL = 'https://job.mts.ru/api/v2/catalog/v1/vacancies?q=аналитик&limit=25&offset=0'

    def test_real_card_keeps_iso_date_brand_and_office(self):
        items, next_url = mts.parse_page(sample('mts_api.json'), self.URL)
        self.assertEqual(len(items), 25)
        self.assertEqual(items[0].external_id, 'pka9irdiz6fw2t1qxcgyl3fw')
        self.assertEqual(items[0].url, 'https://job.mts.ru/vacancy/727074746952322298')
        self.assertEqual(items[0].hint_title, 'Продуктовый аналитик (Телеком продукты B2C)')
        self.assertEqual(items[0].published_at.date().isoformat(), '2026-11-12')
        verdict = keyword_classify(items[0])
        self.assertEqual(verdict.company, 'ПАО МТС')
        self.assertEqual(verdict.remote_from_russia, 'no')
        self.assertEqual(parse_qs(urlparse(next_url).query)['offset'], ['25'])
        self.assertEqual(parse_qs(urlparse(next_url).query)['q'], ['аналитик'])

    def test_all_forty_six_vacancies_are_read(self):
        result = mts.collect([self.URL], lambda u: sample('mts_next.json' if 'offset=25' in u else 'mts_api.json'),
                             lambda s,i: False, False, profile=NO_DETAILS)
        self.assertIsNone(result.error)
        self.assertIsNone(result.warning)
        self.assertEqual(len(result.items), 46)

    def test_api_ignoring_offset_is_failure_without_state(self):
        result = mts.collect([self.URL], lambda u: sample('mts_api.json'),
                             lambda s,i: False, False, profile=NO_DETAILS)
        self.assertTrue(result.error)
        self.assertEqual(result.items, [])
        self.assertIsNone(result.new_bookmark)

    def test_wrong_page_number_is_not_accepted(self):
        data = json.loads(sample('mts_next.json')); data['meta']['pagination']['page'] = 1
        with self.assertRaises(SourceError):
            mts.parse_page(json.dumps(data), self.URL.replace('offset=0','offset=25'))

    def test_remote_and_intern_hints_are_preserved(self):
        data = json.loads(sample('mts_api.json'))
        data['data'][0].update(isRemote=True, isInternship=True, workFormats=[])
        items, _ = mts.parse_page(json.dumps(data), self.URL)
        self.assertEqual(keyword_classify(items[0]).remote_from_russia, 'yes')
        self.assertEqual(items[0].grade_hint, 'intern')

    def test_real_description_includes_final_conditions(self):
        items, _ = mts.parse_page(sample('mts_api.json'), self.URL)
        item = mts.parse_detail(sample('mts_detail.html'), items[0])
        self.assertIn('стоматологию', item.text)
        self.assertIn('Собственный корпоративный университет', item.text)
        self.assertNotIn('Ведущий аналитик по данным', item.text)
        self.assertEqual(item.published_at.date().isoformat(), '2026-11-12')

    def test_external_hh_link_survives_description_loading(self):
        data = json.loads(sample('mts_api.json'))
        data['data'][0]['externalUrl'] = 'https://hh.ru/vacancy/123'
        items, _ = mts.parse_page(json.dumps(data), self.URL)
        item = mts.parse_detail(sample('mts_detail.html'), items[0])
        self.assertIn('https://hh.ru/vacancy/123', item.links)
        self.assertEqual(prefilter(item), 'ссылка на hh.ru')

    def test_empty_and_broken_lists_are_different(self):
        empty = '{"data":[],"meta":{"pagination":{"total":0,"pageSize":25}}}'
        self.assertEqual(mts.parse_page(empty, self.URL), ([], None))
        for bad in ('<html>captcha</html>', '{"data":[]}',
                    '{"data":[],"meta":{"pagination":{"total":46,"pageSize":25}}}'):
            with self.subTest(bad=bad), self.assertRaises(SourceError):
                mts.parse_page(bad, self.URL)

    def test_bad_card_does_not_silently_disappear(self):
        data = json.loads(sample('mts_api.json')); del data['data'][0]['id']
        with self.assertRaises(SourceError): mts.parse_page(json.dumps(data), self.URL)


class MoreCompanyIntegrationTests(unittest.TestCase):
    def test_morning_registration_and_evening_skip(self):
        cfg = {'sources': {'sites': [
            {'name':'vk','morning_only':True,'urls':[VKSourceTests.URL]},
            {'name':'mts','morning_only':True,'urls':[MTSSourceTests.URL]}]}, 'profile': NO_DETAILS}
        def fetch(url):
            name = 'vk' if 'team.vk.company' in url else 'mts'
            return sample(name + ('_next.json' if 'offset=25' in url else '_api.json'))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'state.sqlite')
            try:
                morning = main.collect_all(cfg, store, fetch, slot='am')
                self.assertEqual([r.source for r in morning], ['site:vk', 'site:mts'])
                self.assertFalse(any(r.error for r in morning))
                self.assertEqual(main.collect_all(cfg, store, fetch, slot='pm'), [])
                self.assertEqual(len(main.collect_all(cfg, store, fetch, slot='pm', dry_run=True)), 2)
            finally: store.close()

    def test_failed_description_keeps_no_items_or_bookmark(self):
        for adapter,url,filename in [(vk,VKSourceTests.URL,'vk_api.json'), (mts,MTSSourceTests.URL,'mts_api.json')]:
            def fetch(request_url):
                if request_url == url: return sample(filename)
                raise ConnectionError('offline')
            result = adapter.collect([url], fetch, lambda s,i: False, False)
            with self.subTest(source=adapter.__name__):
                self.assertTrue(result.error)
                self.assertEqual(result.items, [])
                self.assertIsNone(result.new_bookmark)
