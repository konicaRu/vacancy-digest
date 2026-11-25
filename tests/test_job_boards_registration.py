import tempfile
import unittest
from pathlib import Path

import yaml

import main
from vd import digest
from vd.store import Store

ROOT = Path(__file__).resolve().parents[1]


class JobBoardsRegistrationTests(unittest.TestCase):
    def test_both_boards_are_collected_in_morning_and_evening(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = Store(Path(temp.name) / 'state.sqlite')
        self.addCleanup(store.close)
        cfg = {'sources': {'sites': [
            {'name': name, 'enabled': True, 'morning_only': False, 'urls': [], 'lookback_days_first_run': 14}
            for name in ('getmatch', 'geekjob')]}, 'profile': {}}
        for slot in ('am', 'pm'):
            results = main.collect_all(cfg, store, lambda url: '', slot=slot)
            self.assertEqual([r.source for r in results], ['site:getmatch', 'site:geekjob'])

    def test_config_enables_both_boards_for_both_slots(self):
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        sites = {s['name']: s for s in cfg['sources']['sites']}
        for name in ('getmatch', 'geekjob'):
            self.assertTrue(sites[name]['enabled'])
            self.assertFalse(sites[name]['morning_only'])
            self.assertTrue(sites[name]['urls'])

    def test_board_names_are_readable_in_digest(self):
        _, html, text = digest.build([], {'site:getmatch': 0, 'site:geekjob': 0}, {}, {'llm_off': True})
        for name in ('getmatch', 'GeekJob'):
            self.assertIn(name, html)
            self.assertIn(name, text)


if __name__ == '__main__':
    unittest.main()
