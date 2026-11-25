"""СДЭК, Домклик и компании на Huntflow (Банки.ру) — на сохранённых реальных ответах."""
import copy
import json
import unittest
from pathlib import Path
from urllib.parse import unquote

from vd.classify import keyword_classify
from vd.models import SourceError
from vd.sources import cdek, domclick, huntflow

FX = Path(__file__).parent / 'fixtures'


def read(path):
    return (FX / path).read_text(encoding='utf-8')


CDEK_URL = 'https://rabota.cdek.ru/api/vacancies?q=аналитик&offset=0&limit=10'
DC_URL = 'https://career.domclick.ru/api/v1/vacancy/?offset=0&limit=100'
HF_URL = 'https://banki.huntflow.io/'


class CdekTests(unittest.TestCase):
    def item(self, title='Старший аналитик данных'):
        items, _ = cdek.parse_page(read('cdek/search_analyst.json'), CDEK_URL)
        return next(i for i in items if i.hint_title == title)

    def test_real_search_items_remote_tag_and_public_url(self):
        items, next_url = cdek.parse_page(read('cdek/search_analyst.json'), CDEK_URL)
        self.assertEqual([i.external_id for i in items], ['13863', '13720', '8973'])
        self.assertEqual(items[0].url, 'https://rabota.cdek.ru/vacancies/item/13863')
        self.assertTrue(all(i.remote_format for i in items))
        self.assertEqual(items[0].employer, 'СДЭК')
        self.assertIsNone(next_url)

    def test_pagination_follows_offset_and_total(self):
        url = 'https://rabota.cdek.ru/api/vacancies?offset=0&limit=10'
        items, next_url = cdek.parse_page(read('cdek/page_offset0.json'), url)
        self.assertEqual(len(items), 10)
        self.assertEqual(next_url, url.replace('offset=0', 'offset=10'))
        data = json.loads(read('cdek/page_offset0.json'))
        data['vacancies'] = data['vacancies'][:4]
        with self.assertRaises(SourceError):
            cdek.parse_page(json.dumps(data), url)

    def test_card_without_remote_tag_is_not_remote(self):
        data = json.loads(read('cdek/search_analyst.json'))
        data['vacancies'][0]['tags'] = [{'code': 'office', 'name': 'Офис'}]
        items, _ = cdek.parse_page(json.dumps(data), CDEK_URL)
        self.assertFalse(items[0].remote_format)

    def test_real_detail_adds_description_and_checks_identifier(self):
        item = cdek.parse_detail(read('cdek/detail_13863.html'), self.item())
        self.assertIn('Superset'.lower(), item.text.lower())
        self.assertIn('Формат работы: Удалённо', item.text)
        self.assertEqual(keyword_classify(item).company, 'СДЭК')
        with self.assertRaises(SourceError):
            cdek.parse_detail(read('cdek/detail_13863.html').replace('"value":13863', '"value":1'), self.item())


class DomclickTests(unittest.TestCase):
    def items(self):
        return domclick.parse_page(read('domclick/list.json'), DC_URL)[0]

    def test_real_catalog_formats_and_public_url(self):
        items = self.items()
        self.assertEqual(len(items), 20)
        product = next(i for i in items if i.external_id == '187')
        self.assertEqual(product.url, 'https://career.domclick.ru/vacancy/product-analyst-produktovyi-analitik-137444932')
        self.assertEqual(product.hint_title, 'Product Analyst/Продуктовый аналитик')
        self.assertFalse(product.remote_format)  # HYBRID
        self.assertEqual(sum(bool(i.remote_format) for i in items), 5)
        self.assertEqual(product.employer, 'Домклик')

    def test_full_page_asks_for_next_and_bad_answer_is_error(self):
        data = json.loads(read('domclick/list.json'))
        data['pagination']['limit'] = 20
        _, next_url = domclick.parse_page(json.dumps(data), DC_URL.replace('limit=100', 'limit=20'))
        self.assertEqual(unquote(next_url), DC_URL.replace('limit=100', 'limit=20').replace('offset=0', 'offset=20'))
        self.assertIsNone(domclick.parse_page(read('domclick/list.json'), DC_URL)[1])
        with self.assertRaises(SourceError):
            domclick.parse_page(json.dumps({'success': False, 'result': [], 'pagination': {}}), DC_URL)

    def test_real_detail_text_format_and_archive(self):
        product = next(i for i in self.items() if i.external_id == '187')
        item = domclick.parse_detail(read('domclick/detail_187.json'), product)
        self.assertIn('Централизованная аналитика', item.text)
        self.assertFalse(item.remote_format)
        data = json.loads(read('domclick/detail_187.json'))
        remote = copy.deepcopy(data)
        remote['result']['vacancycontent']['work_format'] = ['HYBRID', 'REMOTE']
        self.assertTrue(domclick.parse_detail(json.dumps(remote), product).remote_format)
        archived = copy.deepcopy(remote)
        archived['result']['archived'] = True
        self.assertFalse(domclick.parse_detail(json.dumps(archived), product).remote_format)
        data['result']['id'] = 1
        with self.assertRaises(SourceError):
            domclick.parse_detail(json.dumps(data), product)

    def test_collect_reads_detail_api_for_matching_titles_only(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url == DC_URL:
                return read('domclick/list.json')
            slug = url.rstrip('/').rsplit('/', 1)[1]
            data = json.loads(read('domclick/detail_187.json'))
            row = next(r for r in json.loads(read('domclick/list.json'))['result'] if r['slug'] == slug)
            data['result'].update(id=row['id'], slug=slug, title=row['title'])
            return json.dumps(data)
        profile = {'title_queries': [{'include': ['аналитик', 'analyst'], 'exclude': ['руководитель']}]}
        res = domclick.collect([DC_URL], fetch, lambda *_: False, False, 14, 5, profile=profile)
        self.assertIsNone(res.error, res.error)
        details = [u for u in calls if '/detail/' in u]
        self.assertIn('https://career.domclick.ru/api/v1/vacancy/detail/product-analyst-produktovyi-analitik-137444932/', details)
        self.assertEqual(len(details), 2)


class HuntflowTests(unittest.TestCase):
    def test_real_company_page_items_and_employer(self):
        items, next_url = huntflow.parse_page(read('huntflow/banki_list.html'), HF_URL)
        self.assertEqual(len(items), 10)
        crm = next(i for i in items if i.hint_title == 'Аналитик CRM')
        self.assertEqual(crm.url, 'https://banki.huntflow.io/vacancy/analitik-crm')
        self.assertEqual(crm.external_id, 'banki.huntflow.io/analitik-crm')
        self.assertEqual(crm.employer, 'Banki.ru')
        self.assertIsNone(crm.remote_format)  # у Huntflow формат только текстом
        self.assertIsNone(next_url)

    def test_page_without_vacancies_is_an_error(self):
        with self.assertRaises(SourceError):
            huntflow.parse_page('<html><title>Вакансии компании X</title><body></body></html>', HF_URL)

    def test_real_detail_text_and_title_check(self):
        crm = next(i for i in huntflow.parse_page(read('huntflow/banki_list.html'), HF_URL)[0]
                   if i.hint_title == 'Аналитик CRM')
        item = huntflow.parse_detail(read('huntflow/banki_detail_analitik-crm.html'), crm)
        self.assertIn('Сегментирование клиентской базы', item.text)
        self.assertIn('4 офисных дня', item.text)
        other = next(i for i in huntflow.parse_page(read('huntflow/banki_list.html'), HF_URL)[0]
                     if i.hint_title == 'Юрист')
        with self.assertRaises(SourceError):
            huntflow.parse_detail(read('huntflow/banki_detail_analitik-crm.html'), other)


class RegistrationTests(unittest.TestCase):
    NAMES = ('cdek', 'domclick', 'huntflow')

    def test_collected_in_both_slots_and_enabled_in_config(self):
        import tempfile

        import yaml

        import main
        from vd.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'state.sqlite')
            try:
                cfg = {'sources': {'sites': [{'name': n, 'enabled': True, 'morning_only': False, 'urls': []}
                                             for n in self.NAMES]}, 'profile': {}}
                for slot in ('am', 'pm'):
                    results = main.collect_all(cfg, store, lambda url: '', slot=slot)
                    self.assertEqual([r.source for r in results], ['site:' + n for n in self.NAMES])
            finally:
                store.close()
        config = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text(encoding='utf-8'))
        sites = {s['name']: s for s in config['sources']['sites']}
        for name in self.NAMES:
            self.assertTrue(sites[name]['enabled'])
            self.assertFalse(sites[name]['morning_only'])
            self.assertTrue(sites[name]['urls'])

    def test_readable_names_in_digest(self):
        from vd import digest
        _, html, text = digest.build([], {f'site:{n}': 0 for n in self.NAMES}, {}, {'llm_off': True})
        for label in ('СДЭК', 'Домклик', 'Huntflow'):
            self.assertIn(label, html)
            self.assertIn(label, text)


if __name__ == '__main__':
    unittest.main()
