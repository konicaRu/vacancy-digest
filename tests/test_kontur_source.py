"""Контур (kontur.ru/career): каталог направления «Аналитика» и карточка с JobPosting."""
import unittest
from pathlib import Path

from vd.models import SourceError
from vd.sources import kontur

FX = Path(__file__).parent / 'fixtures' / 'kontur'
URL = 'https://kontur.ru/career/vacancies?direction=analytics'


def read(name):
    return (FX / name).read_text(encoding='utf-8')


class KonturTests(unittest.TestCase):
    def item(self):
        return next(i for i in kontur.parse_page(read('list_analytics.html'), URL)[0] if i.external_id == '655')

    def test_real_catalog_cards_with_city_and_format(self):
        items, next_url = kontur.parse_page(read('list_analytics.html'), URL)
        self.assertEqual([i.external_id for i in items], ['5886', '655', '4224', '5741'])
        item = self.item()
        self.assertEqual(item.url, 'https://kontur.ru/career/vacancies/655')
        self.assertEqual(item.hint_title, 'Системный аналитик, middle+/senior')
        self.assertEqual(item.employer, 'Контур')
        self.assertIn('В офисе, удалённо или гибридно', item.text)
        self.assertIsNone(next_url)

    def test_page_without_cards_is_an_error(self):
        with self.assertRaises(SourceError):
            kontur.parse_page('<html><body>Ошибка</body></html>', URL)

    def test_real_detail_telecommute_date_and_text(self):
        item = kontur.parse_detail(read('detail_655.html'), self.item())
        self.assertTrue(item.remote_format)
        self.assertEqual(item.published_at.date().isoformat(), '2026-11-20')
        self.assertIn('Задачи', item.text)

    def test_detail_without_telecommute_is_not_remote_and_foreign_title_rejected(self):
        html = read('detail_655.html').replace('"TELECOMMUTE"', '"ONSITE"')
        self.assertFalse(kontur.parse_detail(html, self.item()).remote_format)
        other = next(i for i in kontur.parse_page(read('list_analytics.html'), URL)[0] if i.external_id == '5886')
        with self.assertRaises(SourceError):
            kontur.parse_detail(read('detail_655.html'), other)


if __name__ == '__main__':
    unittest.main()
