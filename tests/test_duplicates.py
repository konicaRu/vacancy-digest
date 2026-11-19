import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from vd import digest
from vd.classify import dedup_key
from vd.models import Item, Verdict
from vd.store import Store
from vd import duplicates
from vd.sources import jabka
from unittest import mock
from types import SimpleNamespace
import main
from vd import mailer
from vd.models import SourceResult

NOW = datetime(2026, 11, 19, 12)
AVITO = 'https://career.avito.com/vacancies/analitika-dannykh/20883/'
DESCRIPTION = '''Команда модерации
Задачи:
Развивать метрики качества модерации пользовательского контента.
Оценивать влияние алгоритмов автоматических проверок на пользователей.
Автоматизировать операционные процессы и создавать сценарии анализа для агентов.
Требования:
Опыт планирования аналитических исследований и проверки статистических гипотез.
Умение визуализировать результаты исследований и объяснять выводы коллегам.
Условия:
Удалённая работа из РФ, ДМС, обучение и спорт.'''


def job(key, source='tg:jobs', title='Аналитик данных в команду модерации', links=(), text=DESCRIPTION):
    item = Item(source, 'telegram' if source.startswith('tg:') else 'site', key,
                f'https://t.me/jobs/{key}' if source.startswith('tg:') else f'https://jabka.work/jobs/{key}',
                text, hint_title=title, links=list(links))
    return Verdict(item=item, title=title, company='Авито', is_vacancy=True,
                   bucket='main', grade='middle', remote_from_russia='yes')


def ledger(v, code='old-code'):
    return dict(dedup_key=dedup_key(v), title=v.title, company=v.company,
                url=v.item.url, source=v.item.source, bucket=v.bucket, code=code)


class MatchingTests(unittest.TestCase):
    def test_unknown_id_cannot_bridge_two_incompatible_positions(self):
        a, b, c = job('1'), job('2', links=[AVITO]), job('3', links=[AVITO.replace('20883', '999')])
        rows = duplicates.analyze([a, b, c], [], NOW)
        self.assertEqual(sum(v.bucket != 'drop' for v in (a, b, c)), 2)
        self.assertEqual(len({r['entity_id'] for r in rows}), 2)

    def test_two_positions_in_one_post_keep_distinct_publications_and_marks(self):
        a, b = job('1', links=[AVITO]), job('1', links=[AVITO.replace('20883', '999')])
        rows = duplicates.analyze([a, b], [], NOW)
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        self.assertNotEqual(rows[0]['key'], rows[1]['key'])
        self.assertNotEqual(dedup_key(a), dedup_key(b))

    def test_weak_and_strong_group_members_share_one_archived_entity(self):
        a = job('1')
        b = job('2', links=[AVITO])
        b.item.text += '\nПодробности вакансии'
        c = job('3', links=[AVITO], title='Data Analyst')
        rows = duplicates.analyze([a, b, c], [], NOW)
        self.assertEqual(sum(v.bucket != 'drop' for v in (a, b, c)), 1)
        self.assertEqual(len({r['entity_id'] for r in rows}), 1)

    def test_grade_conflict_without_shared_identity_is_not_merged(self):
        a, b = job('1'), job('2')
        b.grade = 'senior'
        duplicates.analyze([a, b], [], NOW)
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        self.assertFalse(b.possible_duplicate)

    def test_shared_conditions_without_colon_are_not_semantic_evidence(self):
        benefits = '\nУсловия работы\nПолная удалённая работа медицинское страхование обучение спорт '
        benefits += 'современный офис питание компенсация курсов библиотека конференции оборудование поддержка коллег'
        a = job('1', 'site:jabka', title='Аналитик данных для команды модерации',
                text='Задачи: анализировать продажи товаров.' + benefits)
        b = job('2', text='Задачи: проверять качество изображений.' + benefits)
        duplicates.analyze([a, b], [], NOW)
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        self.assertFalse(a.possible_duplicate or b.possible_duplicate)

    def test_paginated_lists_filters_and_general_forms_do_not_confirm_identity(self):
        for url in ('https://career.test/jobs/page/2', 'https://career.test/jobs/search/42',
                    'https://career.test/jobs?jobId=1&jobId=2',
                    'https://career.test/apply?jobId=1', 'https://career.test/jobs?page=2'):
            self.assertFalse(duplicates.identity(url), url)

    def test_shared_employer_id_merges_rephrased_titles_and_keeps_sources(self):
        a = job('1', 'site:jabka', title='Аналитик данных для команды модерации', links=[AVITO])
        b = job('2', links=[AVITO + '?utm_source=tg'])
        rows = duplicates.analyze([b, a], [], NOW)
        self.assertEqual(sum(v.bucket != 'drop' for v in (a, b)), 1)
        self.assertEqual(len({r['entity_id'] for r in rows}), 1)
        kept = next(v for v in (a, b) if v.bucket != 'drop')
        self.assertEqual({u for _, u in kept.source_links}, {a.item.url, b.item.url})

    def test_different_explicit_ids_do_not_merge_even_with_same_title(self):
        a, b = job('1', links=[AVITO]), job('2', links=[AVITO.replace('20883', '999')])
        duplicates.analyze([a, b], [], NOW)
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        self.assertFalse(b.possible_duplicate)

    def test_ambiguous_links_and_general_contacts_are_not_identity(self):
        a = job('1', links=[AVITO, AVITO.replace('20883', '999')])
        b = job('2', title='Другой аналитик', links=[AVITO])
        duplicates.analyze([a, b], [], NOW)
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        for url in ('https://career.avito.com/vacancies/', 'https://t.me/recruiter',
                    'https://company.test/apply', 'https://company.test/jobs', 'mailto:hr@test.ru'):
            self.assertFalse(duplicates.identity(url), url)

    def test_meaningful_query_ids_are_not_lost(self):
        self.assertNotEqual(duplicates.identity('https://jobs.test/vacancy?id=1'),
                            duplicates.identity('https://jobs.test/vacancy?id=2'))
        self.assertTrue(duplicates.identity('https://jobs.test/vacancy?id=1'))

    def test_semantic_match_only_marks_and_renders_both_versions(self):
        a = job('1', 'site:jabka', title='Аналитик данных для команды модерации')
        b = job('2')
        rows = duplicates.analyze([a, b], [], NOW)
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        self.assertEqual(len({r['entity_id'] for r in rows}), 2)
        marked = next(v for v in (a, b) if v.possible_duplicate)
        _, html, text = digest.build([a, b], {}, {}, {'llm_off': True})
        self.assertIn('Возможный дубль', html)
        self.assertIn('Возможный дубль', text)
        self.assertIn(marked.possible_duplicate['url'], html)

    def test_quality_team_unknown_company_and_boilerplate_are_not_suggestions(self):
        a = job('1', 'site:jabka', title='Аналитик данных для команды модерации')
        for b in (job('2', title='Аналитик данных для оценки качества модерации'),
                  job('3', title='Аналитик данных для команды платежей'),
                  job('4', text='SQL Python удалённо ДМС спорт обучение')):
            duplicates.analyze([a, b], [], NOW)
            self.assertEqual(b.bucket, 'main')
            self.assertFalse(b.possible_duplicate)
        b = job('5')
        b.company = None
        duplicates.analyze([a, b], [], NOW)
        self.assertFalse(b.possible_duplicate)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.sqlite'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.close())

    def save(self, v, code='old-code', marks=None):
        rows = duplicates.analyze([v], self.store.duplicate_history(), datetime.now())
        self.store.commit_after_send({}, [], [ledger(v, code)] if v.bucket != 'drop' else [],
                                     marks or {}, publications=rows)
        return rows

    def test_reopen_preserves_descriptions_links_codes_and_old_marks(self):
        a = job('1', 'site:jabka', links=[AVITO])
        self.save(a, marks={'old-code': 'applied'})
        before = self.store.conn.execute('SELECT * FROM ledger').fetchall()
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(before, self.store.conn.execute('SELECT * FROM ledger').fetchall())
        history = self.store.duplicate_history()
        self.assertTrue(any(r.get('text') == DESCRIPTION for r in history))
        b = job('2', links=[AVITO])
        duplicates.analyze([b], history, datetime.now() + timedelta(days=60))
        self.assertEqual(b.bucket, 'drop')
        self.assertEqual(self.store.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_semantic_marks_do_not_inherit_status_and_window_is_ten_days(self):
        self.save(job('1', 'site:jabka', title='Аналитик данных для команды модерации'),
                  marks={'old-code': 'applied'})
        for days, expected in ((9, True), (11, False)):
            b = job('2')
            duplicates.analyze([b], self.store.duplicate_history(), datetime.now() + timedelta(days=days))
            self.assertEqual(b.bucket, 'main')
            self.assertEqual(bool(b.possible_duplicate), expected)

    def test_exact_expiry_and_pending_old_mark(self):
        self.save(job('1', 'site:jabka', links=[AVITO]))
        later = datetime.now() + timedelta(days=31)
        b = job('2', links=[AVITO])
        duplicates.analyze([b], self.store.duplicate_history(), later)
        self.assertEqual(b.bucket, 'main')
        c = job('3', links=[AVITO])
        duplicates.analyze([c], self.store.duplicate_history({'old-code': 'reviewed'}), later)
        self.assertEqual(c.bucket, 'drop')

    def test_different_ids_in_history_do_not_merge_through_legacy_title_rule(self):
        self.save(job('1', links=[AVITO]))
        b = job('2', links=[AVITO.replace('20883', '999')])
        duplicates.analyze([b], self.store.duplicate_history(), datetime.now())
        self.assertEqual(b.bucket, 'main')
        self.assertFalse(b.possible_duplicate)

    def test_archiving_new_job_does_not_lose_other_legacy_history(self):
        old = job('legacy', title='BI аналитик другой команды')
        self.store.commit_after_send({}, [], [ledger(old)], {'old-code': 'applied'})
        self.save(job('1', links=[AVITO]), code='new-code')
        repeat = job('legacy', title=old.title)
        duplicates.analyze([repeat], self.store.duplicate_history(), datetime.now() + timedelta(days=60))
        self.assertEqual(repeat.bucket, 'drop')

    def test_first_observation_does_not_slide_with_later_alias(self):
        a = job('1', links=[AVITO])
        rows = self.save(a)
        first = rows[0]['first_seen']
        b = job('2', links=[AVITO])
        aliases = duplicates.analyze([b], self.store.duplicate_history(), datetime.now() + timedelta(days=9))
        self.store.commit_after_send({}, [], [], publications=aliases)
        self.assertEqual({r['first_seen'] for r in self.store.duplicate_history() if r.get('text')}, {first})

    def test_resend_by_exact_url_keeps_old_entity_and_old_mark_after_window(self):
        a = job('1', 'site:employer')
        a.item.url = 'https://example.test/openings/moderation'
        old_rows = self.save(a)
        later = datetime.now() + timedelta(days=31)
        b = job('2', links=[AVITO])
        b.item.url = a.item.url
        rows = duplicates.analyze([b], self.store.duplicate_history(), later)
        self.assertEqual(b.bucket, 'main')
        self.assertEqual(rows[0]['entity_id'], old_rows[0]['entity_id'])
        self.assertEqual(rows[0]['first_seen'], old_rows[0]['first_seen'])
        self.store.commit_after_send({}, [], [ledger(b, 'new-code')], publications=rows)
        self.store.commit_after_send({}, [], [], {'old-code': 'applied'}, publications=[])
        c = job('3', title='Data Analyst', links=[AVITO])
        duplicates.analyze([c], self.store.duplicate_history(), later + timedelta(days=31))
        self.assertEqual(c.bucket, 'drop')

    def test_explicit_employer_restriction_blocks_same_id_syndicated_remote_claim(self):
        employer = job('1', 'site:avito', links=[])
        employer.item.url = AVITO
        employer.item.remote_format = False
        employer.item.text = 'Аналитик данных. Удалённая работа не предусмотрена. Только офис.'
        employer.remote_from_russia = 'no'
        employer.bucket = 'drop'
        employer.drop_reason = 'нельзя удалённо из РФ'
        copy = job('2', links=[AVITO])
        rows = duplicates.analyze([employer, copy], [], datetime.now())
        self.assertEqual(copy.bucket, 'drop')
        self.assertEqual(len(rows), 2)
        self.store.commit_after_send({}, [], [], publications=rows)
        tomorrow = job('3', links=[AVITO])
        duplicates.analyze([tomorrow], self.store.duplicate_history(), datetime.now() + timedelta(days=1))
        self.assertEqual(tomorrow.bucket, 'drop')

    def test_archive_rolls_back_with_business_state(self):
        v = job('1')
        rows = duplicates.analyze([v], [], datetime.now())
        with self.assertRaises(KeyError):
            self.store.commit_after_send({'tg:jobs': '1'}, [('tg:jobs', '1')],
                                         [{'dedup_key': 'broken'}], publications=rows)
        self.assertEqual(self.store.duplicate_history(), [])
        self.assertIsNone(self.store.get_bookmark('tg:jobs'))

    def test_multiple_jobs_from_bundle_have_distinct_publications(self):
        a, b = job('1'), job('1', title='Аналитик платежей')
        b.item.url = 'https://company.test/jobs/2'
        rows = duplicates.analyze([a, b], [], datetime.now())
        self.store.commit_after_send({}, [], [ledger(a, 'a'), ledger(b, 'b')], publications=rows)
        self.assertEqual(len(self.store.conn.execute('SELECT * FROM publications').fetchall()), 2)

    def test_legacy_exact_match_attaches_old_code_and_suppressed_alias(self):
        a = job('1', 'site:jabka')
        self.store.commit_after_send({}, [], [ledger(a)], {'old-code': 'applied'})
        b = job('2', title=a.title, links=[AVITO])
        rows = duplicates.analyze([b], self.store.duplicate_history(), datetime.now())
        self.assertEqual(b.bucket, 'drop')
        self.store.commit_after_send({}, [], [], publications=rows)
        c = job('3', title='Data Analyst', links=[AVITO])
        duplicates.analyze([c], self.store.duplicate_history(), datetime.now() + timedelta(days=60))
        self.assertEqual(c.bucket, 'drop')

    def test_old_code_still_marks_vacancy_after_resend(self):
        a = job('1', 'site:jabka', links=[AVITO])
        self.save(a)
        self.store.conn.execute("UPDATE ledger SET reported_at='2020-01-01'")
        self.store.conn.execute("UPDATE vacancy_deliveries SET reported_at='2020-01-01'")
        self.store.conn.commit()
        a.bucket = 'main'
        self.save(a, code='new-code')
        self.assertEqual(len(self.store.pending_marks({'old-code': 'applied'})), 1)
        self.store.commit_after_send({}, [], [], {'old-code': 'applied'}, publications=[])
        b = job('2', links=[AVITO])
        duplicates.analyze([b], self.store.duplicate_history(), datetime.now() + timedelta(days=60))
        self.assertEqual(b.bucket, 'drop')


DETAIL = '<script type="application/ld+json">' + json.dumps({
    '@type': 'JobPosting', 'title': 'Аналитик данных для команды модерации',
    'hiringOrganization': {'name': 'Авито'},
    'description': '<p>' + DESCRIPTION + '</p><a href="' + AVITO + '">Откликнуться</a>'
}, ensure_ascii=False) + '</script><main><a href="https://other.test/jobs/99">Похожая вакансия</a></main>'


class EnrichmentTests(unittest.TestCase):
    def test_real_jabka_freeworkfeed_pair_is_suggested_without_inventing_employer_id(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/dedup_avito.json').read_text(encoding='utf-8'))
        a = job('1', 'site:jabka', title=fixture['jabka']['title'])
        a.item.url = fixture['jabka']['url']
        jabka.enrich([a.item], lambda _: '<script type="application/ld+json">' + json.dumps(fixture['jabka']) + '</script>')
        b = job('4295', links=fixture['telegram']['links'], text=fixture['telegram']['text'])
        b.company = None
        rows = duplicates.analyze([a, b], [], NOW)
        self.assertEqual([a.bucket, b.bucket], ['main', 'main'])
        self.assertTrue(any(v.possible_duplicate for v in (a, b)))
        self.assertEqual(len({r['entity_id'] for r in rows}), 2)

    def test_detail_supplies_employer_text_and_only_job_links(self):
        a = job('1', 'site:jabka').item
        original = a.text
        warnings = jabka.enrich([a], lambda _: DETAIL)
        self.assertEqual(warnings, [])
        self.assertEqual(a.employer, 'Авито')
        self.assertIn('Автоматизировать', a.text)
        self.assertEqual(a.links, [AVITO])
        self.assertEqual(a.original_text, original)

    def test_observation_and_duplicate_totals_render_in_both_versions(self):
        _, html, text = digest.build([], {}, {}, {'llm_off': True}, duplicate_info={
            'confirmed': 2, 'possible': 1, 'successful_observations_before': 3})
        for body in (html, text):
            self.assertIn('подтверждённых 2', body)
            self.assertIn('возможных 1', body)
            self.assertIn('3/6', body)

    def test_failure_and_request_limit_keep_original_cards(self):
        items = [job(str(n), 'site:jabka').item for n in range(3)]
        original = [i.text for i in items]
        calls = []
        def fetch(url):
            calls.append(url)
            raise TimeoutError('offline')
        warnings = jabka.enrich(items, fetch, limit=1)
        self.assertEqual(len(calls), 1)
        self.assertEqual([i.text for i in items], original)
        self.assertTrue(warnings)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'state.sqlite')
        self.addCleanup(self.store.close)
        self.cfg = {'sources': {'telegram': {'expand_digests': False}},
                    'run': {'workdays_only': False}, 'llm': {'enabled': False},
                    'mail': {'send_when_empty': True, 'to': 'test@example.com'}}

    def run_pipeline(self, dry=False, failure=False, empty=False):
        a = job('1', 'site:jabka').item
        if empty:
            results = []
        else:
            results = [SourceResult('site:jabka', [a], new_bookmark='1')]
        args = SimpleNamespace(stats=False, force=False, dry_run=dry, no_llm=True)
        with mock.patch.object(main, 'ROOT', self.root), \
             mock.patch.object(main, '_now', return_value=NOW), \
             mock.patch.object(main, 'collect_all', return_value=results), \
             mock.patch.object(main, 'make_fetcher', return_value=lambda _: DETAIL), \
             mock.patch.object(mailer, 'send', side_effect=mailer.SendError('offline') if failure else None,
                               return_value='test-message'):
            return main._run(args, self.cfg, self.store)

    def test_success_archives_and_counts_observation(self):
        self.assertEqual(self.run_pipeline(), 0)
        self.assertTrue(self.store.duplicate_history()[0].get('text'))
        self.assertEqual(self.store.duplicate_observation_count(), 1)

    def test_dry_run_and_failed_send_do_not_archive_or_count(self):
        for dry, failed in ((True, False), (False, True)):
            self.run_pipeline(dry=dry, failure=failed)
            self.assertEqual(self.store.duplicate_history(), [])
            self.assertEqual(self.store.duplicate_observation_count(), 0)

    def test_empty_success_counts_without_email(self):
        self.cfg['mail']['send_when_empty'] = False
        self.run_pipeline(empty=True)
        self.assertEqual(self.store.duplicate_observation_count(), 1)


if __name__ == '__main__':
    unittest.main()
