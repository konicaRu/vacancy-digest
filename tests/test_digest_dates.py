import unittest
from datetime import date, datetime, timezone

from vd import digest
from vd.models import Item, Verdict


class DigestDateTests(unittest.TestCase):
    def render(self, published_at, *, kind='site', source='site:avito', bucket='main'):
        item = Item(source=source, kind=kind, external_id='1', url='https://example.com/job/1',
                    text='Data Analyst', published_at=published_at)
        verdict = Verdict(item=item, title='Data Analyst', company='Example',
                          is_vacancy=True, bucket=bucket)
        return digest.build([verdict], {source: 1}, {}, {'llm_off': True},
                            run_date=date(2026, 11, 12))[1:]

    def test_publication_date_in_html_and_text_is_not_digest_date(self):
        for bucket in ('main', 'unknown_format', 'network'):
            with self.subTest(bucket=bucket):
                html, text = self.render(datetime(2026, 11, 8), bucket=bucket)
                self.assertIn('Размещено: 08.11.2026', html)
                self.assertIn('Размещено: 08.11.2026', text)
                self.assertNotIn('Размещено: 12.11.2026', html)

    def test_missing_date_is_explicit_in_both_versions(self):
        html, text = self.render(None)
        self.assertIn('Дата размещения не указана', html)
        self.assertIn('Дата размещения не указана', text)

    def test_telegram_timestamp_is_displayed_in_moscow_time(self):
        html, text = self.render(datetime(2026, 11, 7, 22, 30, tzinfo=timezone.utc),
                                 kind='telegram', source='tg:test')
        self.assertIn('Размещено: 08.11.2026', html)
        self.assertIn('Размещено: 08.11.2026', text)

    def test_bundle_date_is_not_claimed_as_original_vacancy_date(self):
        html, text = self.render(datetime(2026, 11, 8), kind='digest_link', source='tg:test')
        self.assertIn('Дата подборки: 08.11.2026', html)
        self.assertIn('Дата подборки: 08.11.2026', text)
        self.assertNotIn('Размещено: 08.11.2026', html)
