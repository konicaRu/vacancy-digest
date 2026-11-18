import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

import main

from vd.classify import classify_all, dedup, dedup_key, remote_of
from vd.models import Item, Verdict, SourceResult
from vd import mailer
from vd.expand import expand_bundles
from vd.store import Store


def vacancy(title, key, source='site:bank', url=None):
    item = Item(source, 'site', key, url or 'https://bank.example/jobs/' + key,
                title + '\nУдалённо из РФ. SQL, Python.', hint_title=title)
    return Verdict(item=item, title=title, company='Банк', is_vacancy=True, bucket='main')


class AuditDedupTests(unittest.TestCase):
    def test_different_teams_are_not_duplicates_in_run_or_history(self):
        a = vacancy('Продуктовый аналитик (платежи)', '1')
        b = vacancy('Продуктовый аналитик (кредиты)', '2')
        dedup([a, b], [])
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        dedup([b], [{'dedup_key': 'legacy', 'title': a.title, 'company': a.company,
                     'url': a.item.url, 'source': a.item.source}])
        self.assertEqual(b.bucket, 'main')

    def test_same_title_different_site_ids_survive_and_keep_separate_marks(self):
        a, b = (vacancy('Продуктовый аналитик', key) for key in ('1', '2'))
        dedup([a, b], [])
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'state.sqlite')
            try:
                rows = [{'dedup_key': dedup_key(v), 'title': v.title, 'company': v.company,
                         'url': v.item.url, 'source': v.item.source, 'bucket': 'main', 'code': key}
                        for v, key in ((a, 'one'), (b, 'two'))]
                store.commit_after_send({}, [], rows, {'one': 'applied'})
                self.assertEqual(store.conn.execute('SELECT code,status FROM ledger ORDER BY code').fetchall(),
                                 [('one', 'applied'), ('two', 'new')])
                b.bucket = 'main'
                dedup([b], [store.recent_ledger(30)[0]])
                self.assertEqual(b.bucket, 'main')
            finally:
                store.close()

    def test_same_canonical_url_merges_even_if_titles_differ(self):
        a = vacancy('Data Analyst', '1', 'site:bank', 'https://bank.example/jobs/1?utm_source=tg')
        b = vacancy('Аналитик данных', '2', 'tg:jobs', 'https://bank.example/jobs/1#apply')
        dedup([a, b], [])
        self.assertEqual([a.bucket, b.bucket], ['main', 'drop'])

    def test_identity_preserves_meaningful_query_and_unknown_company_jobs(self):
        a = vacancy('Senior Data Analyst', '1', url='https://bank.example/jobs?id=1')
        b = vacancy('Senior Data Analyst', '2', url='https://bank.example/jobs?id=2')
        a.company = b.company = None
        self.assertNotEqual(dedup_key(a), dedup_key(b))
        dedup([a, b], [])
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])


class AuditRemoteTests(unittest.TestCase):
    def test_explicit_denials_and_non_russian_residency_are_not_remote_from_rf(self):
        for text in ('Удалённая работа не предусмотрена. Только офис.',
                     'Дистанционный формат не предусмотрен.',
                     'Remote work is not available. Onsite only.',
                     'Удалённая работа: нет', 'Remote (EU only)', 'Remote: EU only',
                     'Удалённо только для жителей Казахстана',
                     'Удалённо только для Казахстана', 'Remote EU only',
                     'Работа не удалённая.', 'Мы не предлагаем удалённую работу.',
                     'Remote work is unavailable.',
                     'No remote work.', 'Нет возможности удалённой работы.',
                     'Удалённо. Работа только из Казахстана.',
                     'Remote. Candidates must be based in the EU.',
                     'Remote only from Armenia.'):
            with self.subTest(text=text):
                self.assertEqual(remote_of(text), 'no')
                self.assertEqual(remote_of(text, True), 'no')

    def test_positive_choice_rf_and_no_relocation_remain_allowed(self):
        for text in ('Полная удалёнка или гибрид на выбор.',
                     'Удалённо. Работа только из России.',
                     'Remote only from Russia.',
                     'Remote, no relocation required.',
                     'Remote work only.', 'Remote only from home.',
                     'Удалённо, в офис только по желанию.',
                     'Удалёнка или офис — только на ваш выбор.',
                     'Дистанционный формат работы или офис на выбор.'):
            with self.subTest(text=text):
                self.assertEqual(remote_of(text), 'yes')
        self.assertEqual(remote_of('Remote only from Wonderland.'), 'unknown')

    def test_llm_yes_cannot_override_explicit_restrictions(self):
        from unittest import mock
        item = vacancy('Продуктовый аналитик', '1').item
        item.text = 'Продуктовый аналитик\nУдалённая работа не предусмотрена.'
        answer = Verdict(item=item, title=item.hint_title, is_vacancy=True,
                         role='product_analyst', remote_from_russia='yes')
        llm = mock.Mock()
        llm.classify.return_value = answer
        verdicts, _ = classify_all([item], {}, llm)
        self.assertEqual(verdicts[0].bucket, 'drop')

    def test_ostrovok_does_not_treat_negation_as_remote(self):
        from vd.sources import ostrovok
        self.assertFalse(ostrovok._remote({'conditions': '<p>Дистанционный формат не предусмотрен</p>'}))


class AuditBundleRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state.sqlite')
        self.addCleanup(self.store.close)
        self.cfg = {'sources': {'telegram': {'channels': [{'name': 'parent', 'enabled': True}]}},
                    'run': {'workdays_only': False}, 'llm': {'enabled': False},
                    'mail': {'send_when_empty': True, 'to': 'test@example.com'}}
        self.bundle = Item('tg:parent', 'telegram', '100', 'https://t.me/parent/100',
                           'Подборка Middle:\nПродуктовый аналитик\nАналитик данных',
                           published_at=datetime(2026, 11, 18, 8, 0),
                           anchors=[('https://t.me/childjobs/1', 'Продуктовый аналитик'),
                                    ('https://t.me/childjobs/2', 'Аналитик данных')])

    def child(self, pid):
        title = 'Продуктовый аналитик' if pid == '1' else 'Аналитик данных'
        return Item('tg:childjobs', 'telegram', pid, 'https://t.me/childjobs/' + pid,
                    title + '\nУдалённо из РФ, SQL, Python.', hint_title=title)

    def run_pipeline(self, results, child_fetch, dry=False, fail_send=False):
        args = SimpleNamespace(stats=False, force=True, dry_run=dry, no_llm=True)
        with mock.patch.object(main, 'ROOT', self.root), \
             mock.patch.object(main, 'collect_all', return_value=results), \
             mock.patch.object(main, 'make_fetcher', return_value=lambda _: ''), \
             mock.patch.object(main.telegram, 'fetch_single', side_effect=child_fetch), \
             mock.patch.object(mailer, 'send', side_effect=mailer.SendError('offline') if fail_send else None,
                               return_value='<test>') as send:
            result = main._run(args, self.cfg, self.store)
        return result, send

    def initial(self):
        return [SourceResult('tg:parent', [self.bundle], new_bookmark='100')]

    def first_fetch(self, ch, pid, fetch=None):
        if pid == '2':
            raise TimeoutError('offline')
        return self.child(pid)

    def test_failed_child_is_retried_after_bookmark_advanced_and_restart(self):
        code, _ = self.run_pipeline(self.initial(), self.first_fetch)
        self.assertEqual(code, 0)
        self.assertFalse(self.store.is_seen('tg:childjobs', '2'))
        self.assertFalse(self.store.is_seen('tg:parent', '100'))
        self.assertTrue(self.store.is_seen('tg:childjobs', '1'))
        self.assertEqual(self.store.get_bookmark('tg:parent'), '100')
        self.assertEqual(len(self.store.list_pending_bundles()), 1)
        # Reopen SQLite: pending payload must survive a process restart.
        self.store.close()
        self.store = Store(self.root / 'state.sqlite')
        self.addCleanup(self.store.close)
        calls = []
        def success(ch, pid, fetch=None):
            calls.append(pid)
            return self.child(pid)
        code, send = self.run_pipeline([], success)
        self.assertEqual(code, 0)
        self.assertEqual(calls, ['2'])
        self.assertTrue(self.store.is_seen('tg:childjobs', '2'))
        self.assertTrue(self.store.is_seen('tg:parent', '100'))
        self.assertEqual(self.store.list_pending_bundles(), [])
        self.assertIn('Аналитик данных', send.call_args.args[2])

    def test_failed_send_and_dry_run_do_not_commit_pending_or_children(self):
        for dry, fail_send in ((True, False), (False, True)):
            with self.subTest(dry=dry):
                self.run_pipeline(self.initial(), self.first_fetch, dry=dry, fail_send=fail_send)
                self.assertFalse(self.store.is_seen('tg:childjobs', '1'))
                self.assertIsNone(self.store.get_bookmark('tg:parent'))
                self.assertEqual(self.store.list_pending_bundles(), [])

    def test_send_failure_keeps_existing_pending_until_later_success(self):
        self.run_pipeline(self.initial(), self.first_fetch)
        self.run_pipeline([], lambda ch, pid, fetch=None: self.child(pid), dry=True)
        self.assertEqual(len(self.store.list_pending_bundles()), 1)
        self.assertFalse(self.store.is_seen('tg:childjobs', '2'))
        self.run_pipeline([], lambda ch, pid, fetch=None: self.child(pid), fail_send=True)
        self.assertEqual(len(self.store.list_pending_bundles()), 1)
        self.assertFalse(self.store.is_seen('tg:childjobs', '2'))

    def test_disabled_channel_keeps_queue_without_fetching_it(self):
        self.run_pipeline(self.initial(), self.first_fetch)
        self.cfg['sources']['telegram']['channels'][0]['enabled'] = False
        def forbidden(*a):
            self.fail('Disabled pending channel must not be fetched')
        self.run_pipeline([], forbidden)
        self.assertEqual(len(self.store.list_pending_bundles()), 1)

    def test_nested_failure_retains_root_and_attempt_budget_counts_failures(self):
        nested = self.child('1')
        nested.text = 'Подборка Middle:\nАналитик данных'
        nested.anchors = [('https://t.me/otherjobs/3', 'Аналитик данных')]
        calls, pending = [], []
        def fetch(ch, pid):
            calls.append(pid)
            if pid == '1':
                return nested
            raise TimeoutError('offline')
        out, info = expand_bundles([self.bundle], lambda *_: False, fetch, max_fetch=2, pending=pending)
        self.assertEqual(calls, ['1', '3'])
        self.assertEqual(info['fetched'], 2)
        self.assertEqual(out, [])
        self.assertEqual({i.external_id for i in pending}, {'100', '1'})

    def test_nested_bundle_makes_progress_with_one_attempt_per_run(self):
        self.cfg['sources']['telegram']['max_digest_fetches'] = 1
        self.bundle.anchors = self.bundle.anchors[:1]
        nested = self.child('1')
        nested.text = 'Подборка Middle:\nАналитик данных'
        nested.anchors = [('https://t.me/childjobs/3', 'Аналитик данных')]
        calls = []
        def fetch(ch, pid, fetch=None):
            calls.append(pid)
            return nested if pid == '1' else self.child(pid)
        self.run_pipeline(self.initial(), fetch)
        self.run_pipeline([], fetch)
        self.assertEqual(calls, ['1', '3'])
        self.assertTrue(self.store.is_seen('tg:childjobs', '3'))
        self.assertEqual(self.store.list_pending_bundles(), [])

    def test_permanent_early_failures_do_not_starve_new_healthy_bundle(self):
        self.cfg['sources']['telegram']['max_digest_fetches'] = 1
        healthy = Item('tg:parent', 'telegram', '200', 'https://t.me/parent/200',
                       'Подборка Middle:\nАналитик данных',
                       anchors=[('https://t.me/childjobs/3', 'Аналитик данных')])
        calls = []
        def fetch(ch, pid, fetch=None):
            calls.append(pid)
            if pid != '3':
                raise TimeoutError('permanent failure')
            return self.child(pid)
        self.run_pipeline(self.initial(), fetch)
        self.run_pipeline([SourceResult('tg:parent', [healthy], new_bookmark='200')], fetch)
        self.run_pipeline([], fetch)
        self.assertTrue(self.store.is_seen('tg:childjobs', '3'))
        self.assertEqual(calls, ['1', '2', '3'])

    def test_queue_and_business_state_roll_back_together(self):
        self.run_pipeline(self.initial(), self.first_fetch)
        with self.assertRaises(KeyError):
            self.store.commit_after_send({'tg:parent': '200'}, [('tg:childjobs', '2')],
                                         [{'dedup_key': 'broken', 'title': 'broken'}], pending_bundles=[])
        self.assertEqual(len(self.store.list_pending_bundles()), 1)
        self.assertEqual(self.store.get_bookmark('tg:parent'), '100')
        self.assertFalse(self.store.is_seen('tg:childjobs', '2'))


class AuditHTTPRetryTests(unittest.TestCase):
    def server(self, statuses, retry_after=None):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.command, self.rfile.read(int(self.headers.get('Content-Length', 0)))))
                self.send_response(statuses[min(len(calls) - 1, len(statuses) - 1)])
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                if retry_after:
                    self.send_header('Retry-After', retry_after)
                self.end_headers()
                self.wfile.write(b'read successfully')
            do_POST = do_GET
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.addCleanup(cleanup)
        return f'http://127.0.0.1:{server.server_port}/', calls

    def test_temporary_http_errors_retry_then_return_real_response(self):
        url, calls = self.server([503, 502, 200])
        with mock.patch.object(main.time, 'sleep') as sleep:
            self.assertEqual(main.make_fetcher({})(url), 'read successfully')
        self.assertEqual(len(calls), 3)
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [1, 2, 1])

    def test_attempts_are_bounded_and_permanent_status_is_not_retried(self):
        for statuses, count in (([504], 3), ([404], 1), ([403], 1)):
            url, calls = self.server(statuses)
            with self.subTest(status=statuses[0]), mock.patch.object(main.time, 'sleep'):
                with self.assertRaises(requests.HTTPError):
                    main.make_fetcher({})(url)
                self.assertEqual(len(calls), count)

    def test_read_only_post_payload_is_preserved(self):
        url, calls = self.server([502, 200])
        with mock.patch.object(main.time, 'sleep'):
            self.assertEqual(main.make_fetcher({})(url, json={'offset': 25}), 'read successfully')
        self.assertEqual(calls, [('POST', b'{"offset": 25}'), ('POST', b'{"offset": 25}')])

    def test_small_retry_after_is_honoured_but_long_one_is_not_bypassed(self):
        url, calls = self.server([429, 200], retry_after='2')
        with mock.patch.object(main.time, 'sleep') as sleep:
            self.assertEqual(main.make_fetcher({})(url), 'read successfully')
        self.assertEqual(sleep.call_args_list[0].args, (2,))
        url, calls = self.server([429, 200], retry_after='3600')
        with mock.patch.object(main.time, 'sleep'), self.assertRaises(requests.HTTPError):
            main.make_fetcher({})(url)
        self.assertEqual(len(calls), 1)

    def test_timeout_and_reset_retry_but_ssl_does_not(self):
        response = requests.Response()
        response.status_code = 200
        response._content = b'read successfully'
        session = mock.Mock()
        session.get.side_effect = [requests.Timeout('timeout'), requests.ConnectionError('reset'), response]
        with mock.patch.object(main, 'make_session', return_value=session), mock.patch.object(main.time, 'sleep'):
            self.assertEqual(main.make_fetcher({})('https://example.test/'), 'read successfully')
        session.get.side_effect = requests.exceptions.SSLError('untrusted')
        session.get.reset_mock()
        with mock.patch.object(main, 'make_session', return_value=session), mock.patch.object(main.time, 'sleep'):
            with self.assertRaises(requests.exceptions.SSLError):
                main.make_fetcher({})('https://example.test/')
        self.assertEqual(session.get.call_count, 1)
