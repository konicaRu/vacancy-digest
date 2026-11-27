"""Отслеживание постов выбранных рекрутеров LinkedIn (страницы «Все действия» / «Публикации»)."""
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from vd import digest
from vd import linkedin_browser as browser
from vd.sources import linkedin_posts as lp

NOW = datetime(2026, 11, 25, 12)
BODY = '''Привет! Ищем Senior Product Analyst в Prequel.
Задачи: A/B-тесты, SQL, Python. Полная удалёнка.'''
PERSON = 'https://www.linkedin.com/in/recruiter-example-123/'
COMPANY = 'https://www.linkedin.com/company/jobs-example/'


def post(key='7529156726835658753', text=BODY):
    return dict(id=key, url=f'https://www.linkedin.com/feed/update/urn:li:activity:{key}/',
                author='Recruiter Example', text=text, complete=True,
                published_at=NOW.isoformat(), links=[])


class RelativeDateTests(unittest.TestCase):
    def test_months_and_years_are_recognised(self):
        cases = {'3 г. • ': NOW - timedelta(days=3 * 365), '2 мес. • Отредактировано': NOW - timedelta(days=60),
                 '1 mo •': NOW - timedelta(days=30), '2 yr': NOW - timedelta(days=730),
                 '1 нед. •': NOW - timedelta(weeks=1), '5 мин.': NOW - timedelta(minutes=5)}
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(browser.relative_date(label, NOW), expected)


class ClipboardTests(unittest.TestCase):
    def test_busy_clipboard_is_retried_briefly(self):
        user = mock.Mock()
        user.OpenClipboard.side_effect = [0, 0, 1]
        with mock.patch.object(browser.time, 'sleep') as sleep:
            browser._open_clipboard(user)
        self.assertEqual(user.OpenClipboard.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_clipboard_busy_for_too_long_is_an_error(self):
        user = mock.Mock()
        user.OpenClipboard.return_value = 0
        with mock.patch.object(browser.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Буфер занят'):
                browser._open_clipboard(user)
        self.assertEqual(user.OpenClipboard.call_count, 10)


class ProfilePageTests(unittest.TestCase):
    def test_person_and_company_pages(self):
        self.assertEqual(lp.profile_page(PERSON), (PERSON + 'recent-activity/all/', True))
        self.assertEqual(lp.profile_page('https://www.linkedin.com/in/%D0%BC%D0%B0%D1%80%D0%B8%D1%8F-123'),
                         ('https://www.linkedin.com/in/%D0%BC%D0%B0%D1%80%D0%B8%D1%8F-123/recent-activity/all/', True))
        self.assertEqual(lp.profile_page(COMPANY), (COMPANY + 'posts/', False))

    def test_other_addresses_are_rejected(self):
        for value in ('https://evil.test/in/olga/', 'http://www.linkedin.com/in/olga/',
                      'https://www.linkedin.com/feed/', 'https://www.linkedin.com/in/olga/details/skills/',
                      'https://www.linkedin.com/in/olga/?trk=x', 'https://www.linkedin.com/in/', ''):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    lp.profile_page(value)


def page_with_cards(headers):
    """Mock profile page: card i has header text headers[i] and body 'Текст вакансии i'."""
    def make_card(index):
        card = mock.Mock()
        card.get_attribute.return_value = None
        boxes = mock.Mock()
        boxes.count.return_value = 1
        body = mock.Mock()
        body.locator.return_value.count.return_value = 0
        body.inner_text.return_value = f'Текст вакансии {index}'
        boxes.nth.return_value = body
        boxes.locator.return_value.evaluate_all.return_value = []
        authors = mock.Mock()
        authors.count.return_value = 0
        card.locator.side_effect = lambda selector: boxes if 'expandable-text-box' in selector else authors
        card.inner_text.return_value = f'Публикация в ленте\nOlga\n{headers[index]}\nТекст вакансии {index}'
        return card
    card_list = [make_card(i) for i in range(len(headers))]
    cards = mock.Mock()
    cards.count.return_value = len(card_list)
    cards.nth.side_effect = lambda index: card_list[index]
    main_element = mock.Mock()

    def locate(selector):
        if 'listitem' in selector:
            return mock.Mock(filter=mock.Mock(return_value=cards))
        found = mock.Mock()
        found.count.return_value = 1
        return found
    main_element.locator.side_effect = locate
    return card_list, main_element


class ScanProfileTests(unittest.TestCase):
    def run_scan(self, profile, headers, seen=()):
        card_list, main_element = page_with_cards(headers)
        keys = {card: str(7000000000000000000 + i) for i, card in enumerate(card_list)}
        opened = []

        def permalink(_page, card):
            opened.append(card_list.index(card))
            key = keys[card]
            return key, f'https://www.linkedin.com/feed/update/urn:li:activity:{key}/'
        page = mock.Mock()
        command = {'action': 'scan_profile', 'profile': profile, 'max_posts': 5, 'max_scrolls': 0,
                   'days': 7, 'timeout_sec': 25, 'seen_ids': [keys[card_list[i]] for i in seen]}
        with mock.patch.object(browser, '_main', return_value=main_element) as main_check, \
             mock.patch.object(browser, '_permalink', side_effect=permalink):
            result = browser.scan(page, command)
        return result, opened, page, main_check

    def test_person_profile_stops_at_first_old_post_before_copying_its_link(self):
        result, opened, page, main_check = self.run_scan(PERSON, ['2 дн. •', '3 дн. •', '2 нед. •', '1 ч. •'], seen=[1])
        page.goto.assert_called_once()
        self.assertEqual(page.goto.call_args[0][0], PERSON + 'recent-activity/all/')
        self.assertEqual(main_check.call_args[0][1], '/in/recruiter-example-123/recent-activity/all/')
        self.assertEqual([p['text'] for p in result['posts']], ['Текст вакансии 0'])
        self.assertEqual(opened, [0, 1])  # старый пост и всё после него не открывали
        self.assertEqual(result['seen'], 1)
        self.assertTrue(result['complete'], result['errors'])

    def test_company_page_skips_old_posts_but_keeps_reading(self):
        result, opened, _, _ = self.run_scan(COMPANY, ['3 г. •', '1 ч. •', '2 мес. •', '5 ч. •'])
        self.assertEqual([p['text'] for p in result['posts']], ['Текст вакансии 1', 'Текст вакансии 3'])
        self.assertEqual(opened, [1, 3])

    def test_undated_post_is_skipped_and_reported(self):
        result, opened, _, _ = self.run_scan(PERSON, ['Продвигается', '1 ч. •'])
        self.assertEqual([p['text'] for p in result['posts']], ['Текст вакансии 1'])
        self.assertEqual(opened, [1])
        self.assertEqual(result['undated'], 1)

    def test_profile_without_posts_is_empty_not_an_error(self):
        # Elina, Мария, Елена, Дарья (26.11): страница профиля открылась, но карточек постов нет —
        # раньше 15 с ожидания заканчивались ошибкой в каждом выпуске.
        page = mock.Mock()
        page.url = PERSON + 'recent-activity/all/'
        page.wait_for_function.side_effect = TimeoutError('Timeout 15000ms exceeded.')
        result = browser.scan(page, {'action': 'scan_profile', 'profile': PERSON, 'max_posts': 5,
                                     'max_scrolls': 0, 'days': 7, 'timeout_sec': 25})
        self.assertEqual(result['posts'], [])
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['complete'])
        self.assertTrue(result['empty'])

    def test_search_page_without_cards_is_still_an_error(self):
        page = mock.Mock()
        page.url = 'https://www.linkedin.com/search/results/content/?keywords=x'
        page.wait_for_function.side_effect = TimeoutError('Timeout 15000ms exceeded.')
        with self.assertRaises(TimeoutError):
            browser.scan(page, {'hashtag': '#hiring', 'max_posts': 1, 'max_scrolls': 0})

    def test_login_wall_on_profile_is_still_an_error(self):
        page = mock.Mock()
        page.url = 'https://www.linkedin.com/authwall?sessionRedirect=x'
        with self.assertRaisesRegex(RuntimeError, 'ручной вход'):
            browser.scan(page, {'action': 'scan_profile', 'profile': PERSON, 'max_posts': 5,
                                'max_scrolls': 0, 'days': 7, 'timeout_sec': 25})

    def test_hashtag_scan_still_requires_search_page(self):
        _, main_element = page_with_cards([])
        page = mock.Mock()
        with mock.patch.object(browser, '_main', return_value=main_element) as main_check:
            browser.scan(page, {'hashtag': '#hiring', 'max_posts': 1, 'max_scrolls': 0})
        self.assertIn('/search/results/content/', page.goto.call_args[0][0])
        self.assertEqual(main_check.call_args[0][1], '/search/results/content/')


class SearchExhaustedTests(unittest.TestCase):
    """26.11: у русских запросов 1–3 поста — выдача кончилась, это не «лимит прокруток»."""

    def scan(self, visible, added_per_scroll):
        card_list, main_element = page_with_cards(['1 ч. •'] * (visible + 2 * added_per_scroll))
        state = {'n': visible}
        cards = main_element.locator('[role="listitem"]').filter()
        cards.count.side_effect = lambda: state['n']
        page = mock.Mock()
        page.wait_for_timeout.side_effect = lambda _ms: state.update(n=state['n'] + added_per_scroll)
        keys = iter(range(7100000000000000000, 7100000000000000100))

        def permalink(_page, _card):
            key = str(next(keys))
            return key, f'https://www.linkedin.com/feed/update/urn:li:activity:{key}/'
        with mock.patch.object(browser, '_main', return_value=main_element), \
             mock.patch.object(browser, '_permalink', side_effect=permalink):
            return browser.scan(page, {'hashtag': '#vacancy аналитик', 'max_posts': 20, 'max_scrolls': 2,
                                       'days': 7, 'timeout_sec': 75})

    def test_no_new_cards_after_scroll_means_results_are_complete(self):
        result = self.scan(3, 0)
        self.assertEqual(len(result['posts']), 3)
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['complete'])

    def test_scroll_limit_with_growing_results_is_still_reported(self):
        result = self.scan(3, 3)  # каждая прокрутка добавляет карточки, а прокрутки кончились
        self.assertTrue(any('лимит прокруток' in e for e in result['errors']), result['errors'])


class SearchWithoutDateFilterTests(unittest.TestCase):
    """27.11: с фильтром LinkedIn «за неделю» русские запросы давали 0 постов. Ищем без фильтра,
    сортировка по дате, дата проверяется до копирования ссылки, на первом старом посте — стоп."""

    def run_search(self, headers, days=30):
        card_list, main_element = page_with_cards(headers)
        opened = []

        def permalink(_page, card):
            opened.append(card_list.index(card))
            key = str(7200000000000000000 + card_list.index(card))
            return key, f'https://www.linkedin.com/feed/update/urn:li:activity:{key}/'
        page = mock.Mock()
        with mock.patch.object(browser, '_main', return_value=main_element), \
             mock.patch.object(browser, '_permalink', side_effect=permalink):
            result = browser.scan(page, {'hashtag': '#vacancy аналитик', 'max_posts': 20, 'max_scrolls': 2,
                                         'days': days, 'timeout_sec': 75})
        return result, opened, page

    def test_search_url_has_no_date_filter_but_sorts_by_date(self):
        _, _, page = self.run_search(['1 ч. •'])
        url = page.goto.call_args[0][0]
        self.assertNotIn('datePosted', url)
        self.assertIn('sortBy=%22date_posted%22', url)

    def test_stops_at_first_post_older_than_window_before_copying_its_link(self):
        result, opened, _ = self.run_search(['2 дн. •', '3 нед. •', '2 мес. •', '1 ч. •'])
        self.assertEqual(opened, [0, 1])
        self.assertEqual(len(result['posts']), 2)
        self.assertEqual(result['errors'], [])  # выдача прочитана до старых постов — она полная

    def test_undated_search_card_is_still_read(self):
        result, opened, _ = self.run_search(['Продвигается', '1 ч. •'])
        self.assertEqual(opened, [0, 1])


class CollectRecruitersTests(unittest.TestCase):
    cfg = {'hashtags': ['#hiring'], 'recruiters': [{'name': 'Recruiter Example', 'url': PERSON},
                                                   {'name': 'Jobs Example', 'url': COMPANY}]}

    def test_recruiter_posts_are_collected_with_their_own_label_and_budget(self):
        commands = []
        elapsed = [0]

        def request(command):
            commands.append(command)
            elapsed[0] += 2000  # хэштеги съели весь общий бюджет
            if command.get('profile') == PERSON:
                return {'posts': [post()], 'complete': True, 'scanned': 1, 'seen': 0, 'errors': []}
            return {'posts': [], 'complete': True, 'scanned': 0, 'seen': 0, 'errors': []}
        with mock.patch.object(lp.time, 'monotonic', side_effect=lambda: elapsed[0]):
            result = lp.collect(self.cfg, Path('.'), lambda *_: False, None, request=request, now=NOW)
        profiles = [c for c in commands if c['action'] == 'scan_profile']
        self.assertEqual([c['profile'] for c in profiles], [PERSON])  # второй — после бюджета рекрутеров
        self.assertEqual(profiles[0]['max_posts'], 5)
        self.assertEqual(profiles[0]['max_scrolls'], 0)
        self.assertLessEqual(profiles[0]['timeout_sec'], 25)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].discovery_tags, ['рекрутер: Recruiter Example'])
        self.assertEqual(result.stats['recruiters']['Recruiter Example']['new'], 1)

    def test_search_window_is_separate_from_recruiter_window(self):
        commands = []

        def request(command):
            commands.append(command)
            return {'posts': [], 'complete': True, 'scanned': 0, 'errors': []}
        cfg = {'hashtags': ['#vacancy аналитик'], 'recruiters': [{'name': 'Olga', 'url': PERSON}],
               'lookback_days_first_run': 7, 'search_days': 30}
        lp.collect(cfg, Path('.'), lambda *_: False, None, request=request, now=NOW)
        days = {c['action']: c['days'] for c in commands}
        self.assertEqual(days, {'scan_posts': 30, 'scan_profile': 7})

    def test_recruiters_alone_are_enough_and_bad_address_is_a_warning(self):
        cfg = {'recruiters': [{'name': 'Bad', 'url': 'https://evil.test/in/x/'}, {'name': 'Olga', 'url': PERSON}]}
        result = lp.collect(cfg, Path('.'), lambda *_: False, None,
                            request=lambda c: {'posts': [post()], 'complete': True, 'scanned': 1, 'errors': []}, now=NOW)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 1)
        self.assertIn('Bad', result.warning)

    def test_recruiters_can_live_in_a_local_file_outside_git(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'data').mkdir()
            (Path(tmp) / 'data' / 'recruiters.yaml').write_text(
                f'- name: Olga\n  url: "{PERSON}"\n', encoding='utf-8')
            calls = []

            def request(command):
                calls.append(command.get('profile'))
                return {'posts': [], 'complete': True, 'scanned': 0, 'errors': []}
            lp.collect({'recruiters_file': 'data/recruiters.yaml'}, Path(tmp), lambda *_: False, None,
                       request=request, now=NOW)
            self.assertEqual(calls, [PERSON])
            missing = lp.collect({'recruiters_file': 'data/none.yaml'}, Path(tmp), lambda *_: False, None,
                                 request=request, now=NOW)
            self.assertIn('none.yaml', missing.error)

    def test_post_seen_under_hashtag_is_not_read_twice_from_profile(self):
        def request(command):
            return {'posts': [post()], 'complete': True, 'scanned': 1, 'errors': []}
        result = lp.collect({'hashtags': ['#hiring'], 'recruiters': [{'name': 'Olga', 'url': PERSON}]},
                            Path('.'), lambda *_: False, None, request=request, now=NOW)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].discovery_tags, ['#hiring', 'рекрутер: Olga'])


class DigestRecruitersTests(unittest.TestCase):
    def test_recruiters_are_one_summary_line_plus_productive_names(self):
        info = {lp.SOURCE: {'tags': {}, 'recruiters': {
            'Olga': {'viewed': 2, 'new': 1, 'passed': 1, 'errors': 0},
            'Ivan': {'viewed': 0, 'new': 0, 'passed': 0, 'errors': 1},
            'Anna': {'viewed': 3, 'new': 2, 'passed': 0, 'errors': 0}}}}
        _, html, text = digest.build([], {lp.SOURCE: 0}, {}, {'llm_off': True}, source_info=info)
        for body in (html, text):
            self.assertIn('Рекрутеры LinkedIn: профилей 3, прочитано 2, новых постов 3, в письме 1', body)
            self.assertIn('дали вакансии: Olga', body)
            self.assertNotIn('Anna:', body)


if __name__ == '__main__':
    unittest.main()
