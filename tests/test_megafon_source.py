import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from vd.classify import keyword_classify
from vd.models import SourceError
from vd.sources import megafon


SAMPLES = Path(__file__).parent / 'samples'
URL = 'https://job.megafon.ru/vacancy/all/any/?q=аналитик'
NO_DETAILS = {'title_queries': [{'include': ['unmatched'], 'exclude': []}]}


def sample(name):
    return (SAMPLES / f'career_megafon_{name}.html').read_text(encoding='utf8')


def state(name):
    return json.JSONDecoder().raw_decode(sample(name).split('__INITIAL_STATE__=', 1)[1])[0]


def html(data):
    return '<script>window.__INITIAL_STATE__=' + json.dumps(data) + ';window.__SSR__=true;</script>'


class MegafonSourceTests(unittest.TestCase):
    def test_real_list_and_pagination(self):
        items, next_url = megafon.parse_page(sample('analyst'), URL)
        self.assertEqual(len(items), 10)
        self.assertEqual(items[0].external_id, '4831')
        self.assertEqual(items[0].hint_title, 'Менеджер по аналитике клиентского опыта')
        self.assertIn('@МегаФон', items[0].text)
        self.assertIn('/moskva/biznes-napravlenia/', items[0].url)
        self.assertEqual(items[0].published_at.date().isoformat(), '2026-11-13')
        self.assertEqual(parse_qs(urlsplit(next_url).query), {'q': ['аналитик'], 'page': ['2']})
        self.assertTrue(items[3].remote_format)
        self.assertFalse(items[0].remote_format)
        self.assertFalse(items[1].remote_format)

    def test_real_detail_keeps_company_title_and_excludes_footer(self):
        item = megafon.parse_page(sample('analyst'), URL)[0][0]
        item = megafon.parse_detail(sample('detail') + '<footer>Удаленно всем</footer>', item)
        self.assertIn('Qlik Sense', item.text)
        self.assertIn('SQL', item.text)
        self.assertNotIn('Удаленно всем', item.text)
        self.assertEqual(keyword_classify(item).company, 'МегаФон')
        self.assertFalse(item.remote_format)

    def test_only_explicit_remote_tag_confirms_detail(self):
        original = state('detail')
        for tag, want in [({'code': 'remote', 'title': 'Удаленка'}, True),
                          ({'code': 'hybrid_shift', 'title': 'Гибридный график'}, False),
                          (None, False)]:
            with self.subTest(tag=tag):
                data = copy.deepcopy(original)
                data['vacancy']['response']['tag'] = tag
                data['vacancy']['response']['description'] = '<p>Аналитик данных. Удалённо.</p>'
                item = megafon.parse_page(sample('analyst'), URL)[0][0]
                item.remote_format = True
                item = megafon.parse_detail(html(data), item)
                self.assertEqual(item.remote_format, want)
                self.assertEqual(keyword_classify(item).remote_from_russia, 'yes' if want else 'no')

    def test_empty_is_valid_but_malformed_or_incomplete_is_error(self):
        empty = {'vacancies': {'processStatus': 'SUCCESS', 'response':
                 {'page': 1, 'pages': 0, 'total': 0, 'vacancies': []}}}
        self.assertEqual(megafon.parse_page(html(empty), URL), ([], None))
        broken = state('analyst')
        broken['vacancies']['response']['vacancies'] = []
        for value in ['<h1>blocked</h1>', '<script>window.__INITIAL_STATE__={bad}</script>', html(broken)]:
            with self.subTest(value=value[:50]), self.assertRaises(SourceError):
                megafon.parse_page(value, URL)

    def test_catalog_remote_is_preserved_when_detail_has_no_format_field(self):
        data = state('detail')
        data['vacancy']['response'].pop('tag', None)
        data['vacancy']['response']['description'] = '<p>Аналитик данных. SQL.</p>'
        item = megafon.parse_page(sample('analyst'), URL)[0][0]
        item.remote_format = True
        self.assertTrue(megafon.parse_detail(html(data), item).remote_format)

    def test_detail_failure_discards_items_and_bookmark(self):
        data = state('detail')
        data['vacancy']['response']['id'] = 999
        result = megafon.collect([URL], lambda url: sample('analyst') if url == URL else html(data),
                                 lambda *_: False, False)
        self.assertTrue(result.error)
        self.assertEqual(result.items, [])
        self.assertIsNone(result.new_bookmark)
        self.assertEqual(result.seen_ids, [])

    def test_pagination_and_first_run_cutoff(self):
        first = state('english')
        rows = first['vacancies']['response']['vacancies']
        rows[0]['publishedAt'] = 1
        rows[1]['publishedAt'] = int(datetime.now(timezone.utc).timestamp())
        second = copy.deepcopy(first)
        first['vacancies']['response'].update(page=1, pages=2, total=2, vacancies=rows[:1])
        second['vacancies']['response'].update(page=2, pages=2, total=2, vacancies=rows[1:])
        result = megafon.collect([URL], lambda url: html(second if 'page=2' in url else first),
                                 lambda *_: False, True, profile=NO_DETAILS)
        self.assertIsNone(result.error)
        self.assertIsNone(result.warning)
        self.assertEqual(result.seen_ids, ['4805'])
        self.assertEqual([x.external_id for x in result.items], ['4696'])


if __name__ == '__main__':
    unittest.main()
