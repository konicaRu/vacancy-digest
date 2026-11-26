"""Selectel (selectel.ru/careers): серверный каталог всех вакансий и карточка; формат работы — только текстом."""
import unittest
from pathlib import Path

from vd.models import SourceError
from vd.sources import selectel

FX = Path(__file__).parent / 'fixtures' / 'selectel'
URL = 'https://selectel.ru/careers/all/'


def read(name):
    return (FX / name).read_text(encoding='utf-8')


class SelectelTests(unittest.TestCase):
    def items(self):
        return selectel.parse_page(read('list_all.html'), URL)[0]

    def test_real_catalog_cards_direction_and_city(self):
        items, next_url = selectel.parse_page(read('list_all.html'), URL)
        self.assertEqual(len(items), 26)
        first = next(i for i in items if i.external_id == '2088')
        self.assertEqual(first.url, 'https://selectel.ru/careers/all/vacancy/2088/')
        self.assertEqual(first.hint_title, 'Руководитель направления системного администрирования')
        self.assertIn('Системное администрирование', first.text)
        self.assertIn('Санкт-Петербург', first.text)
        self.assertEqual(first.employer, 'Selectel')
        self.assertIsNone(next_url)
        self.assertIn('Business Analyst (AI workflow solutions)', [i.hint_title for i in items])

    def test_page_without_cards_is_an_error(self):
        with self.assertRaises(SourceError):
            selectel.parse_page('<html><body>Технические работы</body></html>', URL)

    def test_real_detail_text_and_title_check(self):
        first = next(i for i in self.items() if i.external_id == '2088')
        item = selectel.parse_detail(read('detail_2088.html'), first)
        self.assertIn('Задачи', item.text)
        self.assertIsNone(item.remote_format)  # формат только текстом — решает общий разбор
        other = next(i for i in self.items() if i.external_id != '2088')
        with self.assertRaises(SourceError):
            selectel.parse_detail(read('detail_2088.html'), other)


if __name__ == '__main__':
    unittest.main()
