"""Шесть небольших карьерных сайтов (проба 27.11): Arenadata, Нетология, ЦФТ, НСПК, Nexign, Level.Travel."""
import unittest
from pathlib import Path

from vd.classify import remote_of
from vd.models import SourceError
from vd.sources import arenadata, cft, leveltravel, netology, nexign, nspk

FX = Path(__file__).parent / 'fixtures'


def read(name):
    return (FX / name).read_text(encoding='utf-8')


def by_id(items, external_id):
    return next(i for i in items if i.external_id == external_id)


class ArenadataTests(unittest.TestCase):
    URL = 'https://arenadata.tech/ru/career'

    def test_catalog_from_next_data_all_pages(self):
        items, next_url = arenadata.parse_page(read('arenadata/list.html'), self.URL)
        self.assertEqual(len(items), 16)  # больше 10 видимых на первой странице
        devops = by_id(items, 'devops')
        self.assertEqual(devops.url, 'https://arenadata.tech/ru/career/devops')
        self.assertEqual(devops.hint_title, 'DevOps')
        self.assertIn('Middle', devops.text)
        self.assertIn('Arenadata Catalog', devops.text)
        self.assertEqual(devops.employer, 'Arenadata')
        self.assertNotIn('arenadata-standard', [i.external_id for i in items])  # пакет льгот, не вакансия
        self.assertIsNone(next_url)

    def test_empty_page_is_an_error(self):
        with self.assertRaises(SourceError):
            arenadata.parse_page('<html><body>Технические работы</body></html>', self.URL)

    def test_detail_text_and_title_check(self):
        items = arenadata.parse_page(read('arenadata/list.html'), self.URL)[0]
        item = arenadata.parse_detail(read('arenadata/detail_devops.html'), by_id(items, 'devops'))
        self.assertIn('Что нужно делать', item.text)
        self.assertEqual(remote_of(item.text, item.remote_format), 'no')  # «Готовы к гибридному формату»
        with self.assertRaises(SourceError):
            arenadata.parse_detail(read('arenadata/detail_devops.html'), by_id(items, 'sales-manager'))


class NetologyTests(unittest.TestCase):
    URL = 'https://netology.ru/job'

    def test_catalog_cards_with_remote_label(self):
        items, next_url = netology.parse_page(read('netology/list.html'), self.URL)
        self.assertEqual(len(items), 10)
        first = by_id(items, '2ed1ccbd-58e1-43f8-8510-61d53b46bd2f')
        self.assertEqual(first.url, 'https://netology.ru/job/2ed1ccbd-58e1-43f8-8510-61d53b46bd2f')
        self.assertEqual(first.hint_title, 'Эксперт на модуль «3D-моделирование как источник дохода»')
        self.assertIn('Частичная занятость', first.text)
        self.assertTrue(first.remote_format)
        self.assertEqual(first.employer, 'Нетология')
        self.assertIsNone(next_url)

    def test_empty_page_is_an_error(self):
        with self.assertRaises(SourceError):
            netology.parse_page('<html></html>', self.URL)

    def test_detail(self):
        items = netology.parse_page(read('netology/list.html'), self.URL)[0]
        item = netology.parse_detail(read('netology/detail.html'), by_id(items, '2ed1ccbd-58e1-43f8-8510-61d53b46bd2f'))
        self.assertIn('О нас', item.text)
        other = next(i for i in items if i.external_id != '2ed1ccbd-58e1-43f8-8510-61d53b46bd2f')
        with self.assertRaises(SourceError):
            netology.parse_detail(read('netology/detail.html'), other)


class CftTests(unittest.TestCase):
    URL = 'https://job.cft.ru/'

    def test_catalog_from_next_data(self):
        items, next_url = cft.parse_page(read('cft/list.html'), self.URL)
        self.assertEqual(len(items), 5)
        analyst = by_id(items, '290')
        self.assertEqual(analyst.url, 'https://job.cft.ru/290/')
        self.assertEqual(analyst.hint_title, 'Аналитик (инженер-технолог)')
        self.assertIn('Новосибирск', analyst.text)
        self.assertIn('Аналитика', analyst.text)
        self.assertEqual(analyst.employer, 'ЦФТ')
        self.assertIsNone(next_url)

    def test_empty_page_is_an_error(self):
        with self.assertRaises(SourceError):
            cft.parse_page('<html></html>', self.URL)

    def test_detail(self):
        items = cft.parse_page(read('cft/list.html'), self.URL)[0]
        item = cft.parse_detail(read('cft/detail_290.html'), by_id(items, '290'))
        self.assertIn('Рассматриваем кандидатов только из городов', item.text)
        with self.assertRaises(SourceError):
            cft.parse_detail(read('cft/detail_290.html'), by_id(items, '289'))


class NspkTests(unittest.TestCase):
    URL = 'https://www.nspk.ru/vacancies'

    def test_catalog_with_direction(self):
        items, next_url = nspk.parse_page(read('nspk/list.html'), self.URL)
        self.assertEqual(len(items), 10)
        first = by_id(items, '118844c7-1a7a-449b-a346-7bf08bae0e63')
        self.assertEqual(first.url, 'https://www.nspk.ru/vacancies/118844c7-1a7a-449b-a346-7bf08bae0e63')
        self.assertEqual(first.hint_title, 'Главный специалист (Отдел методологии и развития контроля)')
        self.assertIn('Аудит и комплаенс', first.text)
        self.assertEqual(first.employer, 'НСПК')
        self.assertIsNone(next_url)

    def test_empty_page_is_an_error(self):
        with self.assertRaises(SourceError):
            nspk.parse_page('<html></html>', self.URL)

    def test_origin_uses_russian_ca_only_for_exact_origin(self):
        from vd.sources import make_session
        session = make_session()
        exact = session.get_adapter('https://www.nspk.ru/vacancies')
        self.assertIs(exact, session.get_adapter('https://www.tbank.ru/'))
        self.assertIsNot(session.get_adapter('https://www.nspk.ru.evil.example/'), exact)
        self.assertIsNot(session.get_adapter('https://nspk.ru/'), exact)

    def test_detail_office_format(self):
        items = nspk.parse_page(read('nspk/list.html'), self.URL)[0]
        item = nspk.parse_detail(read('nspk/detail.html'), by_id(items, '118844c7-1a7a-449b-a346-7bf08bae0e63'))
        self.assertIn('Обязанности', item.text)
        self.assertEqual(remote_of(item.text, item.remote_format), 'no')
        other = next(i for i in items if i.external_id != '118844c7-1a7a-449b-a346-7bf08bae0e63')
        with self.assertRaises(SourceError):
            nspk.parse_detail(read('nspk/detail.html'), other)


class NexignTests(unittest.TestCase):
    URL = 'https://job.nexign.com/jobs'

    def test_catalog_pages(self):
        items, next_url = nexign.parse_page(read('nexign/list_0.html'), self.URL)
        self.assertEqual(len(items), 6)
        analyst = by_id(items, 'analytics/senior-sistemnyy-analitik')
        self.assertEqual(analyst.url, 'https://job.nexign.com/jobs/analytics/senior-sistemnyy-analitik')
        self.assertEqual(analyst.hint_title, 'Senior системный аналитик')
        self.assertIn('Санкт-Петербург', analyst.text)
        self.assertEqual(analyst.employer, 'Nexign')
        self.assertEqual(next_url, 'https://job.nexign.com/jobs?page=1')
        items, next_url = nexign.parse_page(read('nexign/list_1.html'), next_url)
        self.assertEqual(len(items), 3)
        self.assertIsNone(next_url)

    def test_empty_page_is_an_error(self):
        with self.assertRaises(SourceError):
            nexign.parse_page('<html></html>', self.URL)

    def test_detail_company_remote_policy_without_faq_text(self):
        items = nexign.parse_page(read('nexign/list_0.html'), self.URL)[0]
        item = nexign.parse_detail(read('nexign/detail_analyst.html'), by_id(items, 'analytics/senior-sistemnyy-analitik'))
        self.assertIn('Задачи', item.text)
        self.assertNotIn('Как проходит собеседование', item.text)  # FAQ в текст не берём
        self.assertTrue(item.remote_format)  # FAQ: «из любой точки России» (решение 27.11)

    def test_office_in_vacancy_text_overrides_policy(self):
        items = nexign.parse_page(read('nexign/list_0.html'), self.URL)[0]
        html = read('nexign/detail_analyst.html').replace('Задачи</h3>', 'Задачи</h3><p>Работа в офисе</p>', 1)
        item = nexign.parse_detail(html, by_id(items, 'analytics/senior-sistemnyy-analitik'))
        self.assertIsNone(item.remote_format)
        self.assertEqual(remote_of(item.text, item.remote_format), 'no')

    def test_detail_title_check(self):
        items = nexign.parse_page(read('nexign/list_0.html'), self.URL)[0]
        other = next(i for i in items if i.external_id != 'analytics/senior-sistemnyy-analitik')
        with self.assertRaises(SourceError):
            nexign.parse_detail(read('nexign/detail_analyst.html'), other)


class LevelTravelTests(unittest.TestCase):
    URL = 'https://career.level.travel/'

    def test_accordion_vacancies_with_full_text(self):
        items, next_url = leveltravel.parse_page(read('leveltravel/page.html'), self.URL)
        self.assertEqual([i.hint_title for i in items],
                         ['Account Manager', 'Менеджер продуктового промо в маркетинг'])
        first = items[0]
        self.assertEqual(first.external_id, '1786969600513')
        self.assertEqual(first.url, 'https://career.level.travel/#vacancy-1786969600513')
        self.assertEqual(first.employer, 'Level.Travel')
        self.assertIsNone(next_url)

    def test_empty_page_is_an_error(self):
        with self.assertRaises(SourceError):
            leveltravel.parse_page('<html></html>', self.URL)

    def test_detail_from_same_page(self):
        first = leveltravel.parse_page(read('leveltravel/page.html'), self.URL)[0][0]
        item = leveltravel.parse_detail(read('leveltravel/page.html'), first)
        self.assertIn('Чем предстоит заниматься', item.text)
        self.assertIn('Формат работы из офиса', item.text)
        self.assertNotIn('Менеджер продуктового промо', item.text)
        self.assertEqual(remote_of(item.text, item.remote_format), 'no')


if __name__ == '__main__':
    unittest.main()
