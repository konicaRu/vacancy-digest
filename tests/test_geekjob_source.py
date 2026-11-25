import json
import unittest
from pathlib import Path
from urllib.parse import unquote

from vd.classify import decide, keyword_classify
from vd.models import SourceError
from vd.sources import geekjob

FIXTURES = Path(__file__).parent / 'fixtures' / 'geekjob'
URL = 'https://geekjob.ru/json/find/vacancy?page=1&qs=аналитик&rm=1'
DETAIL_ID = '6a0b179d8598180d10086a52'


def sample(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def listing():
    return json.loads(sample('list.json'))


class GeekjobSourceTests(unittest.TestCase):
    def item(self):
        items, _ = geekjob.parse_page(sample('list.json'), URL)
        return next(i for i in items if i.external_id == DETAIL_ID)

    def test_real_list_items_have_public_url_company_and_remote_flag(self):
        items, next_url = geekjob.parse_page(sample('list.json'), URL)
        self.assertEqual(len(items), 39)
        self.assertIsNone(next_url)
        item = self.item()
        self.assertEqual(item.url, 'https://geekjob.ru/vacancy/' + DETAIL_ID)
        self.assertEqual(item.hint_title, 'Head of Product Analytics / CDO')
        self.assertEqual(item.employer, 'NEWHR')
        archived = {i.hint_title for i in items if not i.remote_format}
        self.assertEqual(archived, {'Influence marketing manager'})  # в выдаче архивная вакансия 2023 года

    def test_next_page_follows_nextpage(self):
        data = listing()
        data.update(nextpage=2, pagecount=2)
        _, next_url = geekjob.parse_page(json.dumps(data), URL)
        self.assertEqual(unquote(next_url), URL.replace('page=1', 'page=2'))

    def test_inconsistent_page_is_an_error(self):
        for change in ({'page': 2}, {'nextpage': 5, 'pagecount': 2}, {'data': []}):
            with self.subTest(change=change):
                data = listing()
                data.update(change)
                with self.assertRaises(SourceError):
                    geekjob.parse_page(json.dumps(data), URL)

    def test_not_remote_or_archived_card_is_not_confirmed_remote(self):
        data = listing()
        data['data'][0]['jobFormat']['remote'] = False
        data['data'][1]['log']['archived'] = '2026-11-20'
        items, _ = geekjob.parse_page(json.dumps(data), URL)
        self.assertFalse(items[0].remote_format)
        self.assertFalse(items[1].remote_format)

    def test_real_detail_adds_description_date_and_passes_classifier(self):
        item = geekjob.parse_detail(sample('detail.html'), self.item())
        self.assertIn('Продуктовая аналитика', item.text)
        self.assertEqual(item.published_at.date().isoformat(), '2026-05-18')
        self.assertTrue(item.remote_format)
        verdict = keyword_classify(item)
        self.assertEqual(verdict.company, 'NEWHR')
        self.assertEqual(decide(verdict, {}).remote_from_russia, 'yes')

    def test_detail_without_remote_label_is_not_remote(self):
        html = sample('detail.html').replace('Удаленная работа', 'Гибрид')
        self.assertFalse(geekjob.parse_detail(html, self.item()).remote_format)

    def test_detail_of_other_vacancy_is_rejected(self):
        html = sample('detail.html').replace('Geekjob ' + DETAIL_ID, 'Geekjob 000')
        with self.assertRaises(SourceError):
            geekjob.parse_detail(html, self.item())

    def test_collect_opens_only_matching_titles(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url == URL:
                return sample('list.json')
            return sample('detail.html').replace('Geekjob ' + DETAIL_ID, 'Geekjob ' + url.rsplit('/', 1)[1])

        profile = {'title_queries': [{'include': ['аналитик', 'analyst', 'product analytics'], 'exclude': ['системный', 'system']}]}
        res = geekjob.collect([URL], fetch, lambda s, i: False, False, 14, 5, profile=profile)
        self.assertIsNone(res.error, res.error)
        self.assertEqual(len(res.items), 39)
        self.assertIn('https://geekjob.ru/vacancy/' + DETAIL_ID, calls)
        opened = {u.rsplit('/', 1)[1] for u in calls if '/vacancy/' in u}
        titles = {i.external_id: i.hint_title for i in res.items}
        self.assertFalse(any('Системный' in titles[i] for i in opened))


if __name__ == '__main__':
    unittest.main()
