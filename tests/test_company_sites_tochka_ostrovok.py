import json
import re
import unittest
from pathlib import Path

from vd.classify import decide, keyword_classify
from vd.models import SourceError
from vd.sources import make_session, ostrovok, tochka

FIXTURES = Path(__file__).parent / 'fixtures' / 'company'
TOCHKA = 'https://hr.tochka.com/vacancies/it/remote-work/'
OSTROVOK = 'https://career.ostrovok.ru/vacancy'


def sample(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def ostrovok_state(html):
    return json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S).group(1))


def with_state(html, state):
    return re.sub(r'(<script id="__NEXT_DATA__"[^>]*>).*?(</script>)',
                  lambda m: m.group(1) + json.dumps(state, ensure_ascii=False) + m.group(2), html, flags=re.S)


class TochkaTests(unittest.TestCase):
    def item(self, slug='middle_analyst'):
        return next(i for i in tochka.parse_page(sample('tochka_catalog.html'), TOCHKA)[0] if i.external_id == slug)

    def test_real_catalog(self):
        items, next_url = tochka.parse_page(sample('tochka_catalog.html'), TOCHKA)
        self.assertEqual(len(items), 6)
        self.assertIsNone(next_url)
        item = self.item()
        self.assertEqual(item.url, 'https://hr.tochka.com/vacancies/catalog/middle_analyst/')
        self.assertEqual(item.hint_title, 'Мидл+ продуктовый аналитик')
        self.assertTrue(item.remote_format)

    def test_real_detail_confirms_remote_and_passes_filters(self):
        item = tochka.parse_detail(sample('tochka_detail.html'), self.item())
        self.assertTrue(item.remote_format)
        self.assertEqual(item.published_at.date().isoformat(), '2026-08-03')
        self.assertIn('SQL', item.text)
        self.assertIn('Что делать', item.text)
        self.assertEqual(keyword_classify(item).company, 'Точка Банк')
        self.assertEqual(decide(keyword_classify(item), {}).bucket, 'main')

    def test_detail_without_telecommute_is_not_remote(self):
        html = sample('tochka_detail.html').replace('"jobLocationType":"TELECOMMUTE"', '"jobLocationType":"ONSITE"')
        item = tochka.parse_detail(html, self.item())
        self.assertFalse(item.remote_format)
        self.assertEqual(decide(keyword_classify(item), {}).bucket, 'drop')

    def test_catalog_must_be_complete_and_recognised(self):
        html = sample('tochka_catalog.html')
        for broken in (html.replace('\\"total\\":6', '\\"total\\":26'), '<html></html>'):
            with self.assertRaises(SourceError):
                tochka.parse_page(broken, TOCHKA)

    def test_wrong_detail_is_rejected(self):
        with self.assertRaises(SourceError):
            tochka.parse_detail(sample('tochka_detail.html'), self.item('data-analytics'))

    def test_tochka_origin_uses_extra_ca_only_for_exact_origin(self):
        session = make_session()
        exact = session.get_adapter('https://hr.tochka.com/vacancies/')
        self.assertIs(exact, session.get_adapter('https://www.tbank.ru/'))
        self.assertIsNot(session.get_adapter('https://hr.tochka.com.evil.example/'), exact)
        self.assertIsNot(session.get_adapter('https://tochka.com/'), exact)


class OstrovokTests(unittest.TestCase):
    def items(self):
        return {i.external_id: i for i in ostrovok.parse_page(sample('ostrovok_catalog.html'), OSTROVOK)[0]}

    def test_real_catalog_and_urls(self):
        items = self.items()
        self.assertEqual(len(items), 6)
        self.assertEqual(items['3484'].url, 'https://career.ostrovok.ru/vacancy/3484')
        self.assertEqual(items['3484'].hint_title, 'Senior Product Analyst (B2C Hotels)')
        self.assertTrue(items['3473'].remote_format)

    def test_real_detail_passes_filters(self):
        item = ostrovok.parse_detail(sample('ostrovok_detail.html'), self.items()['3484'])
        self.assertTrue(item.remote_format)
        self.assertIn('SQL', item.text)
        self.assertEqual(keyword_classify(item).company, 'Островок')
        self.assertEqual(decide(keyword_classify(item), {}).bucket, 'main')

    def test_inactive_cards_are_skipped_in_catalog_and_never_pass_in_detail(self):
        html = sample('ostrovok_catalog.html')
        state = ostrovok_state(html)
        state['props']['pageProps']['vacancies'][1]['actual'] = False
        self.assertNotIn('3484', {i.external_id for i in ostrovok.parse_page(with_state(html, state), OSTROVOK)[0]})
        detail = sample('ostrovok_detail.html')
        state = ostrovok_state(detail)
        state['props']['pageProps']['vacancy']['state'] = 'CLOSED'
        item = ostrovok.parse_detail(with_state(detail, state), self.items()['3484'])
        self.assertFalse(item.remote_format)
        self.assertEqual(decide(keyword_classify(item), {}).bucket, 'drop')

    def test_no_remote_in_conditions_is_not_remote(self):
        detail = sample('ostrovok_detail.html')
        state = ostrovok_state(detail)
        state['props']['pageProps']['vacancy']['conditions'] = '<p>Работа в офисе в Москве.</p>'
        item = ostrovok.parse_detail(with_state(detail, state), self.items()['3484'])
        self.assertFalse(item.remote_format)

    def test_unrecognised_pages_and_wrong_detail_fail(self):
        for call in (lambda: ostrovok.parse_page('<html></html>', OSTROVOK),
                     lambda: ostrovok.parse_detail(sample('ostrovok_detail.html'), self.items()['3473'])):
            with self.assertRaises(SourceError):
                call()


if __name__ == '__main__':
    unittest.main()
