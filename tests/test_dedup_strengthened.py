"""Усиленный дедуп между источниками (25.11): реальные пропущенные дубли и защита от ложных склеек."""
import unittest

from vd.classify import dedup
from vd.models import Item, Verdict


def verdict(source, url, title, company=None, bucket='main'):
    item = Item(source, 'site' if source.startswith('site:') else 'telegram', url.rsplit('/', 1)[-1], url, title)
    return Verdict(item=item, is_vacancy=True, title=title, company=company, bucket=bucket,
                   source_links=[(source, url)])


def merged(a, b):
    dedup([a, b], [])
    return b.bucket == 'drop' and b.drop_reason == 'дубль из другого источника'


class StrengthenedDedupTests(unittest.TestCase):
    def test_same_post_in_two_channels_with_reworded_title(self):
        # careerstation_analyst и wntdan, 19.11: одна вакансия Grand Mobile пришла дважды
        a = verdict('tg:careerstation_analyst', 'https://t.me/careerstation_analyst/301',
                    'Data Analyst / Product Analyst в Grand Mobile', 'Grand Mobile')
        b = verdict('tg:wntdan', 'https://t.me/wntdan/1201', 'Data / Product Analyst Grand Mobile')
        self.assertTrue(merged(a, b))
        self.assertIn('tg:wntdan', a.also_in)

    def test_company_suffix_in_title_does_not_hide_duplicate(self):
        # myresume_ru и jabka, 23.11
        a = verdict('tg:myresume_ru', 'https://t.me/myresume_ru/5001',
                    'Ведущий аналитик по ценообразованию в ROSSKO', 'ROSSKO')
        b = verdict('site:jabka', 'https://jabka.work/jobs/analitik-20261123-abc',
                    'Ведущий аналитик по ценообразованию', 'ROSSKO')
        self.assertTrue(merged(a, b))

    def test_ids_of_different_sites_do_not_block_same_title_and_company(self):
        # сайт Островка и getmatch: у каждого свой номер вакансии
        a = verdict('site:ostrovok', 'https://career.ostrovok.ru/vacancy/3484',
                    'Senior Product Analyst (B2C Hotels)', 'Островок')
        b = verdict('site:getmatch', 'https://getmatch.ru/vacancies/37271-senior-product-analyst-b2c-hotels',
                    'Senior Product Analyst (B2C Hotels)', 'Островок')
        self.assertTrue(merged(a, b))

    def test_already_sent_from_other_site_is_not_sent_again(self):
        b = verdict('site:getmatch', 'https://getmatch.ru/vacancies/37271-senior-product-analyst-b2c-hotels',
                    'Senior Product Analyst (B2C Hotels)', 'Островок')
        dedup([b], [{'title': 'Senior Product Analyst (B2C Hotels)', 'company': 'Островок',
                     'url': 'https://career.ostrovok.ru/vacancy/3484', 'source': 'site:ostrovok'}])
        self.assertEqual(b.drop_reason, 'уже присылал раньше')

    def test_different_positions_stay_separate(self):
        cases = [
            # разные команды одной компании
            (('site:ostrovok', 'https://career.ostrovok.ru/vacancy/3484', 'Senior Product Analyst (B2C Hotels)', 'Островок'),
             ('site:getmatch', 'https://getmatch.ru/vacancies/37000-product-analyst-content', 'Product Analyst (Content)', 'Островок')),
            # общее название без компании — не основание склеивать
            (('tg:careerstation_analyst', 'https://t.me/careerstation_analyst/320', 'BI Аналитик', None),
             ('site:youngjunior', 'https://youngjunior.ru/jobs/1', 'BI Аналитик', None)),
            # компания известна только у одной и не названа во второй
            (('site:avito', 'https://career.avito.com/vacancies/analitika/123/', 'Продуктовый аналитик', 'Авито'),
             ('tg:nodatanojobs', 'https://t.me/nodatanojobs/900', 'Продуктовый аналитик', None)),
            # одно название у разных компаний
            (('site:habr', 'https://career.habr.com/vacancies/1000100001', 'Аналитик данных', 'МТС Банк'),
             ('site:habr', 'https://career.habr.com/vacancies/1000100002', 'Аналитик данных', 'Dodo Engineering')),
            # две разные карточки одного сайта с одинаковым названием
            (('site:ostrovok', 'https://career.ostrovok.ru/vacancy/3484', 'Product Analyst', 'Островок'),
             ('site:ostrovok', 'https://career.ostrovok.ru/vacancy/3473', 'Product Analyst', 'Островок')),
        ]
        for first, second in cases:
            with self.subTest(first=first[2], second=second[2]):
                self.assertFalse(merged(verdict(*first), verdict(*second)))


if __name__ == '__main__':
    unittest.main()
