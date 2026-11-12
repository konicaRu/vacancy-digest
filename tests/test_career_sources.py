import json
import unittest
from pathlib import Path

from vd.classify import keyword_classify, classify_all, dedup
from vd.models import Item, SourceError
from vd.sources import habr, avito, aviasales


SAMPLES = Path(__file__).parent / 'samples'
PROFILE = {'title_queries': [{'include': ['аналитик', 'analyst'],
                              'exclude': ['маркетинг', 'system', 'dwh', 'junior']}],
           'exclude_grades': ['junior', 'intern']}


def sample(name, kind):
    return (SAMPLES / f'career_{name}_{kind}.html').read_text(encoding='utf-8')


def habr_page(ids=('1',), next_page=False, title='Data Analyst', date='2026-11-12'):
    cards = ''.join(f'<div class="vacancy-card"><a class="vacancy-card__title-link" '
                    f'href="/vacancies/{i}">{title}</a><div class="vacancy-card__company">Example</div>'
                    f'<time datetime="{date}"></time><div class="vacancy-card__meta">Senior Можно удалённо</div></div>'
                    for i in ids)
    state = {'vacancies': {'list': [{'id': i} for i in ids],
                          'meta': {'currentPage': 1, 'totalPages': 2 if next_page else 1,
                                   'totalResults': len(ids)}}}
    return cards + '<script data-ssr-state type="application/json">' + json.dumps(state) + '</script>'


DETAIL = '<h1>Data Analyst</h1><div class="vacancy-description__text">SQL, Python. Удалённо из РФ.</div>'


class CareerParsingTests(unittest.TestCase):
    def test_habr_real_cards_keep_company_date_and_grade(self):
        items, next_url = habr.parse_page(sample('habr', 'list'), 'https://career.habr.com/vacancies?q=analyst')
        item = next(i for i in items if i.external_id == '1000168909')
        self.assertEqual(item.hint_title, 'Middle/Senior Data Analyst')
        self.assertIn('@CHOICEIT', item.text)
        self.assertEqual(item.published_at.date().isoformat(), '2026-11-08')
        self.assertEqual(item.grade_hint, 'senior')
        self.assertIsNone(next_url)

    def test_habr_pagination_preserves_filters(self):
        _, next_url = habr.parse_page(habr_page(next_page=True),
                                     'https://career.habr.com/vacancies?q=analyst&remote=true')
        self.assertEqual(next_url, 'https://career.habr.com/vacancies?q=analyst&remote=true&page=2')

    def test_habr_company_rating_is_not_part_of_employer_name(self):
        html = habr_page().replace('>Example</div>',
                                  '><a href="/companies/example">Example</a><a href="/companies/example/ratings">4.95</a></div>')
        items, _ = habr.parse_page(html, 'https://career.habr.com/vacancies')
        self.assertEqual(keyword_classify(items[0]).company, 'Example')

    def test_habr_known_empty_is_success_but_changed_markup_is_error(self):
        items, next_url = habr.parse_page(habr_page(ids=()), 'https://career.habr.com/vacancies')
        self.assertEqual(items, [])
        self.assertIsNone(next_url)
        with self.assertRaises(SourceError):
            habr.parse_page('<html>captcha</html>', 'https://career.habr.com/vacancies')
        with self.assertRaises(SourceError):
            habr.parse_page(habr_page().replace('vacancy-card__title-link', 'changed'),
                            'https://career.habr.com/vacancies')

    def test_avito_uses_url_id_and_full_analytics_category(self):
        items, next_url = avito.parse_page(sample('avito', 'list'), 'https://career.avito.com/vacancies/analitika-dannykh/')
        self.assertEqual(len(items), 15)
        self.assertEqual(items[0].external_id, '20953')
        self.assertEqual(items[0].hint_title, 'Аналитик данных в команду маркетинга')
        self.assertIn('@Авито', items[0].text)
        self.assertIsNone(next_url)

    def test_aviasales_title_keeps_team_but_excludes_skill_tags(self):
        items, _ = aviasales.parse_page(sample('aviasales', 'list'), 'https://www.aviasales.ru/about/vacancies')
        item = next(i for i in items if i.external_id == '4345556')
        self.assertEqual(item.hint_title, 'Product Analyst — SERP')
        self.assertIn('@Aviasales', item.text)

    def test_aviasales_different_teams_are_not_lost_as_duplicates(self):
        items, _ = aviasales.parse_page(sample('aviasales', 'list'), 'https://www.aviasales.ru/about/vacancies')
        analysts = [i for i in items if i.external_id in ('4345556', '4219517')]
        for item in analysts:
            item.text += '\nУдалённо из РФ'
        verdicts, _ = classify_all(analysts, PROFILE, None)
        dedup(verdicts, [])
        self.assertEqual(sum(v.bucket != 'drop' for v in verdicts), 2)

    def test_aviasales_reads_all_description_sections(self):
        item = Item('site:aviasales', 'site', '4345556', 'https://www.aviasales.ru/about/vacancies/4345556',
                    'Product Analyst | @Aviasales', hint_title='Product Analyst')
        result = aviasales.parse_detail(sample('aviasales', 'detail'), item)
        self.assertIn('SQL', result.text)
        self.assertIn('Пхукете', result.text)
        self.assertNotIn('Откликнуться', result.text)

    def test_avito_detail_has_own_location_not_similar_jobs(self):
        item = Item('site:avito', 'site', '20953', 'https://career.avito.com/vacancies/analitika-dannykh/20953/',
                    'Аналитик данных | @Авито', hint_title='Аналитик данных')
        result = avito.parse_detail(sample('avito', 'detail'), item)
        self.assertIn('гибрид', result.text.lower())
        self.assertIn('Seller Marketing', result.text)
        self.assertIn('компенсация питания', result.text)
        self.assertIn('возможность работать удалённо', result.text)
        self.assertNotIn('Похожие вакансии', result.text)
        self.assertNotIn('Спецтехники', result.text)
        self.assertEqual(result.published_at.date().isoformat(), '2026-11-11')

    def test_habr_detail_excludes_menu_and_collects_hh_links(self):
        item = Item('site:habr', 'site', '1', 'https://career.habr.com/vacancies/1',
                    'Data Analyst | @Example', hint_title='Data Analyst')
        html = '<nav>Удалённо из РФ</nav><div class="vacancy-description__text">Офис, Москва. '
        html += '<a href="https://hh.ru/vacancy/123">Отклик</a></div>'
        result = habr.parse_detail(html, item)
        self.assertEqual(keyword_classify(result).remote_from_russia, 'no')
        self.assertEqual(result.links, ['https://hh.ru/vacancy/123'])

    def test_missing_detail_is_error_for_every_adapter(self):
        for adapter in (habr, avito, aviasales):
            with self.subTest(adapter=adapter.__name__), self.assertRaises(SourceError):
                adapter.parse_detail('<html>captcha</html>', Item('s', 'site', '1', 'u', 't'))

    def test_unknown_lists_are_errors(self):
        for adapter in (avito, aviasales):
            with self.subTest(adapter=adapter.__name__), self.assertRaises(SourceError):
                adapter.parse_page('<html>captcha</html>', 'https://example.com')


class CareerCollectionTests(unittest.TestCase):
    URL = 'https://career.habr.com/vacancies?q=analyst'

    def collect(self, fetch, seen=lambda s, i: False, **kwargs):
        return habr.collect([self.URL], fetch, seen, kwargs.pop('first_run', False),
                            profile=PROFILE, **kwargs)

    def test_seen_and_wrong_title_do_not_fetch_details(self):
        page = habr_page(('1', '2')).replace('href="/vacancies/2">Data Analyst',
                                            'href="/vacancies/2">System Analyst')
        def fetch(url):
            self.assertEqual(url, self.URL, 'known or irrelevant vacancy detail must not be opened')
            return page
        result = self.collect(fetch, seen=lambda s, i: i == '1')
        self.assertIsNone(result.error)
        self.assertEqual([i.external_id for i in result.items], ['2'])
        self.assertTrue(result.new_bookmark)

    def test_collects_new_detail_and_restriction_wins(self):
        detail = DETAIL.replace('Удалённо из РФ', 'Удалённо, кроме России')
        result = self.collect(lambda url: habr_page() if url == self.URL else detail)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(keyword_classify(result.items[0]).remote_from_russia, 'no')

    def test_detail_failure_returns_no_items_or_bookmark(self):
        def fetch(url):
            if url == self.URL: return habr_page(('1', '2'))
            if url.endswith('/1'): return DETAIL
            raise ConnectionError('offline')
        result = self.collect(fetch)
        self.assertTrue(result.error)
        self.assertEqual(result.items, [])
        self.assertEqual(result.seen_ids, [])
        self.assertIsNone(result.new_bookmark)

    def test_first_run_skips_old_dated_cards_before_detail(self):
        result = self.collect(lambda url: habr_page(date='2000-01-01'), first_run=True)
        self.assertIsNone(result.error)
        self.assertEqual(result.items, [])
        self.assertEqual(result.seen_ids, ['1'])

    def test_first_run_includes_undated_active_vacancy(self):
        url = 'https://www.aviasales.ru/about/vacancies'
        result = aviasales.collect([url], lambda u: sample('aviasales', 'list') if u == url
                                   else sample('aviasales', 'detail'), lambda s, i: False,
                                   True, profile=PROFILE)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 19)
        self.assertEqual(sum(i.hint_title.startswith('Product Analyst — ') for i in result.items), 2)

    def test_page_limit_warns_without_losing_candidates(self):
        result = self.collect(lambda url: habr_page(next_page=True) if url == self.URL else DETAIL,
                              max_pages=1)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 1)
        self.assertTrue(result.warning)

    def test_repeated_page_does_not_loop_and_warns(self):
        page = habr_page(next_page=True)
        result = self.collect(lambda url: DETAIL if '/vacancies/1' in url else page)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 1)
        self.assertTrue(result.warning)

    def test_duplicate_urls_are_processed_once(self):
        def fetch(url):
            return habr_page() if '?' in url else DETAIL
        result = habr.collect([self.URL, self.URL], fetch, lambda s, i: False, False, profile=PROFILE)
        self.assertEqual([i.external_id for i in result.items], ['1'])

    def test_overlapping_queries_still_follow_next_page(self):
        second = self.URL + '&language=ru'
        def fetch(url):
            if url == self.URL: return habr_page()
            if url == second: return habr_page(next_page=True)
            if 'page=2' in url: return habr_page(('2',))
            return DETAIL
        result = habr.collect([self.URL, second], fetch, lambda s, i: False, False, profile=PROFILE)
        self.assertEqual([i.external_id for i in result.items], ['1', '2'])
