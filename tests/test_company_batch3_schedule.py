import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import main
from vd import digest
from vd.models import SourceResult
from vd.store import Store


class NewCompanyScheduleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'state.sqlite')
        self.addCleanup(self.store.close)
        self.cfg = {'sources': {'sites': [
            {'name': name, 'enabled': True, 'morning_only': True, 'urls': [name],
             'lookback_days_first_run': 14, 'max_pages': 10}
            for name in ('megafon', 'sber', 'twogis')]}, 'profile': {}}
        self.collectors = {}
        for name in ('megafon', 'sber', 'twogis'):
            collector = mock.Mock(return_value=SourceResult(source='site:' + name))
            self.collectors[name] = collector
            patch = mock.patch.object(main, name, SimpleNamespace(collect=collector), create=True)
            patch.start()
            self.addCleanup(patch.stop)

    def test_morning_dispatches_all_three_companies(self):
        results = main.collect_all(self.cfg, self.store, lambda url: '', slot='am')
        self.assertEqual([r.source for r in results], ['site:megafon', 'site:sber', 'site:twogis'])
        for collector in self.collectors.values():
            collector.assert_called_once()

    def test_evening_skips_and_dry_run_checks_all_companies(self):
        self.assertEqual(main.collect_all(self.cfg, self.store, lambda url: '', slot='pm'), [])
        results = main.collect_all(self.cfg, self.store, lambda url: '', slot='pm', dry_run=True)
        self.assertEqual(len(results), 3)

    def test_company_names_are_readable_in_digest(self):
        _, html, text = digest.build([], {'site:megafon': 0, 'site:sber': 0, 'site:twogis': 0},
                                      {}, {'llm_off': True})
        for name in ('МегаФон', 'Сбер', '2ГИС'):
            self.assertIn(name, html)
            self.assertIn(name, text)
