import argparse
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import main
from vd import digest, mailer
from vd.store import Store
from tests.test_career_sources import sample, habr_page


class CareerScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state.sqlite')
        self.addCleanup(self.store.close)
        self.urls = {'habr': 'https://career.habr.com/vacancies?q=analyst',
                     'avito': 'https://career.avito.com/vacancies/analitika-dannykh/',
                     'aviasales': 'https://www.aviasales.ru/about/vacancies'}
        self.cfg = {'sources': {'sites': [dict(name=name, enabled=True, morning_only=True,
                                              urls=[url]) for name, url in self.urls.items()]},
                    'profile': {'title_queries': [{'include': ['unmatched'], 'exclude': []}]}}

    def fetch(self, url):
        for name, expected in self.urls.items():
            if url == expected: return sample(name, 'list')
        raise AssertionError('unexpected request: ' + url)

    def test_morning_collects_three_new_sources(self):
        results = main.collect_all(self.cfg, self.store, self.fetch, slot='am')
        self.assertEqual([r.source for r in results], ['site:habr', 'site:avito', 'site:aviasales'])
        self.assertFalse(any(r.error for r in results))

    def test_evening_omits_morning_sources_without_empty_stats(self):
        self.assertEqual(main.collect_all(self.cfg, self.store, self.fetch, slot='pm'), [])

    def test_evening_dry_run_still_checks_sources(self):
        results = main.collect_all(self.cfg, self.store, self.fetch, slot='pm', dry_run=True)
        self.assertEqual(len(results), 3)
        self.assertFalse(any(r.error for r in results))

    def test_disabled_source_stays_disabled_in_dry_run(self):
        self.cfg['sources']['sites'][0]['enabled'] = False
        results = main.collect_all(self.cfg, self.store, self.fetch, slot='am', dry_run=True)
        self.assertEqual([r.source for r in results], ['site:avito', 'site:aviasales'])

    def test_existing_site_keeps_evening_schedule(self):
        from tests.fixtures import JABKA_HTML
        self.cfg['sources']['sites'].append({'name': 'jabka', 'urls': ['https://jabka.work/']})
        results = main.collect_all(self.cfg, self.store, lambda u: JABKA_HTML, slot='pm')
        self.assertEqual([r.source for r in results], ['site:jabka'])
        self.assertIsNone(results[0].error)

    def test_source_names_in_letter(self):
        _, html, text = digest.build([], {'site:habr': 0, 'site:avito': 0, 'site:aviasales': 0},
                                      {}, {'llm_off': True})
        for label in ['Хабр Карьера', 'Авито', 'Aviasales']:
            self.assertIn(label, html)
            self.assertIn(label, text)

    def run_pipeline(self, *, evening=False, dry_run=False, send_error=False):
        cfg = dict(self.cfg, run={'workdays_only': False, 'once_per_slot': False},
                   llm={'enabled': False}, marks={'enabled': False},
                   mail={'to': 'test@example.com', 'send_when_empty': True})
        cfg['sources'] = {'sites': [self.cfg['sources']['sites'][0]]}
        args = argparse.Namespace(stats=False, force=False, dry_run=dry_run, no_llm=True)
        at = datetime(2026, 11, 12, 18 if evening else 10)
        def send(*args):
            if send_error: raise mailer.SendError('offline')
            return 'test-message'
        with mock.patch.object(main, 'ROOT', Path(self.tmp.name)), \
             mock.patch.object(main, '_now', return_value=at), \
             mock.patch.object(main, 'make_fetcher', return_value=lambda u: habr_page(date='2000-01-01')), \
             mock.patch.object(main.mailer, 'send', side_effect=send):
            return main._run(args, cfg, self.store)

    def test_pipeline_evening_passes_slot_to_collectors(self):
        self.assertEqual(self.run_pipeline(evening=True), 0)
        self.assertIsNone(self.store.get_bookmark('site:habr'))

    def test_old_first_run_card_is_remembered_only_after_delivery(self):
        self.assertEqual(self.run_pipeline(send_error=True), 1)
        self.assertFalse(self.store.is_seen('site:habr', '1'))
        self.assertIsNone(self.store.get_bookmark('site:habr'))
        self.assertEqual(self.run_pipeline(), 0)
        self.assertTrue(self.store.is_seen('site:habr', '1'))
        self.assertTrue(self.store.get_bookmark('site:habr'))

    def test_dry_run_does_not_commit_skipped_cards(self):
        self.assertEqual(self.run_pipeline(evening=True, dry_run=True), 0)
        self.assertFalse(self.store.is_seen('site:habr', '1'))
        self.assertIsNone(self.store.get_bookmark('site:habr'))
