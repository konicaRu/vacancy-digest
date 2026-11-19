import json
import tempfile
import unittest
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest import mock

from vd.sources import linkedin_posts as lp
from vd.classify import classify_all
from vd.models import Item, Verdict, SourceResult
from vd.duplicates import analyze
from vd import linkedin_browser as browser
from vd.linkedin_bridge import BrowserBridge
from vd.store import Store
from vd import digest, mailer
from types import SimpleNamespace
import main

NOW = datetime(2026, 11, 19, 15)
URL = 'https://www.linkedin.com/posts/recruiter_role-share-7529156724621250560-AbCd/?highlightedUpdateUrn=urn%3Ali%3Aactivity%3A7529156726835658753&utm_source=x&rcm=private'
BODY = '''Всем привет! Ищем Senior Product Analyst в Prequel.
Задачи: A/B-тесты, исследования, SQL, Python, витрины и качество данных.
Требования: от 4 лет опыта в продуктовой аналитике.
Полная удалёнка, офис в Черногории по желанию.'''


def post(key='7529156726835658753',text=BODY,complete=True):
    return dict(id=key,url=f'https://www.linkedin.com/feed/update/urn:li:activity:{key}/',
                author='Recruiter',text=text,complete=complete,published_at=NOW.isoformat(),
                links=['https://career.example/jobs/100'])


class ParsingTests(unittest.TestCase):
    def test_browser_relative_dates_and_card_body_do_not_include_profile(self):
        self.assertEqual(browser.relative_date('6 ч. • Отредактировано',NOW),NOW-timedelta(hours=6))
        self.assertEqual(browser.relative_date('2 дн.',NOW),NOW-timedelta(days=2))
        self.assertIsNone(browser.relative_date('неизвестно',NOW))

    def test_clipboard_link_rejects_unrelated_origins_and_resolves_linkedin_wrapper(self):
        self.assertEqual(browser.public_link('https://lnkd.in/p/abc'),'https://lnkd.in/p/abc')
        self.assertIsNone(browser.public_link('https://private.example/secret'))
    def test_canonical_post_identity_removes_tracking_and_personal_rcm(self):
        key,url=lp.post_identity(URL)
        self.assertEqual(key,'7529156726835658753')
        self.assertEqual(url,'https://www.linkedin.com/feed/update/urn:li:activity:7529156726835658753/')
        for value in ('https://evil.test/posts/foo-activity-1234567890123456789-x',
                      'https://www.linkedin.com/in/person/', 'https://lnkd.in/p/abc'):
            with self.assertRaises(ValueError): lp.post_identity(value)

    def test_tags_casefolded_independent_hiring_not_duplicated(self):
        self.assertEqual(lp.unique_tags(['#hiring','#ProductAnalyst','#productanalyst','#AnalyticsJobs','#HIRING']),
                         ['#hiring','#ProductAnalyst','#AnalyticsJobs'])

    def test_same_post_under_two_tags_read_once_and_emits_author(self):
        calls=[]
        def request(command):
            calls.append(command['hashtag'])
            return {'posts':[post()],'complete':True,'scanned':1,'errors':[]}
        result=lp.collect({'hashtags':['#hiring','#ProductAnalyst','#HIRING']},Path('.'),lambda *_:False,
                          None,request=request,now=NOW)
        self.assertEqual(calls,['#hiring','#ProductAnalyst'])
        self.assertEqual(len(result.items),1)
        self.assertEqual(result.items[0].author,'Recruiter')
        self.assertIn('7529156726835658753',result.seen_ids)
        self.assertEqual(set(result.stats['tags']),{'#hiring','#ProductAnalyst'})

    def test_partial_text_not_seen_and_source_warning_not_empty_success(self):
        r=lp.collect({'hashtags':['#hiring']},Path('.'),lambda *_:False,None,
                     request=lambda _: {'posts':[post(complete=False)],'complete':False,'scanned':1,'errors':['truncated']},now=NOW)
        self.assertEqual(r.items,[])
        self.assertEqual(r.seen_ids,[])
        self.assertTrue(r.warning)
        self.assertIsNone(r.new_bookmark)

    def test_auth_failure_is_error_and_other_tag_partial_success_survives(self):
        def request(command):
            if command['hashtag']=='#hiring': raise RuntimeError('manual login required')
            return {'posts':[post()],'complete':True,'scanned':1,'errors':[]}
        r=lp.collect({'hashtags':['#hiring','#ProductAnalyst']},Path('.'),lambda *_:False,None,request=request,now=NOW)
        self.assertEqual(len(r.items),1)
        self.assertTrue(r.warning)
        self.assertIsNone(r.new_bookmark)
        failed=lp.collect({'hashtags':['#hiring']},Path('.'),lambda *_:False,None,request=request,now=NOW)
        self.assertTrue(failed.error)

    def test_multiple_jobs_split_without_sharing_geography(self):
        text='''Вакансии:
Senior Data Analyst
Задачи: SQL, отчётность. Удалённая работа.
Senior Product Analyst
Задачи: A/B, метрики. Работа только из Казахстана, офис.'''
        items=lp.normalize_post(post(text=text))
        self.assertEqual(len(items),2)
        self.assertNotEqual(items[0].external_id,items[1].external_id)
        verdicts,_=classify_all(items,{},None)
        self.assertEqual([v.bucket for v in verdicts],['main','drop'])

    def test_numbered_job_headings_keep_remote_restrictions_separate(self):
        text='''Вакансии:
1. Senior Data Analyst
Задачи: SQL, отчётность и обработка данных. Полная удалённая работа.
2) Senior Product Analyst
Задачи: A/B, метрики. Работа только из Казахстана, офис.'''
        items=lp.normalize_post(post(text=text))
        self.assertEqual(len(items),2)
        verdicts,_=classify_all(items,{},None)
        self.assertEqual([v.bucket for v in verdicts],['main','drop'])

    def test_common_preamble_restrictions_apply_to_every_position(self):
        text='Работа только из Казахстана.\nВакансии:\nSenior Data Analyst\nЗадачи: SQL, отчётность и обработка данных. Полная удалённая работа.\nSenior Product Analyst\nЗадачи: A/B, продуктовые метрики, исследования. Полная удалённая работа.'
        verdicts,_=classify_all(lp.normalize_post(post(text=text)),{},None)
        self.assertEqual([v.bucket for v in verdicts],['drop','drop'])


class FilteringTests(unittest.TestCase):
    def verdict(self,text):
        items=lp.normalize_post(post(text=text))
        self.assertTrue(items)
        return classify_all(items,{},None)[0][0]

    def test_russian_body_english_role_full_remote_accepted_without_rf(self):
        v=self.verdict(BODY)
        self.assertEqual(v.bucket,'main')
        self.assertTrue(v.title.startswith('Senior Product Analyst'))
        self.assertEqual(v.company,'Prequel')

    def test_english_body_russian_tag_is_not_russian_vacancy(self):
        v=self.verdict('We are hiring Senior Data Analyst. Work remotely. SQL and Python. #вакансия')
        self.assertEqual(v.bucket,'drop')
        self.assertIn('язык',v.drop_reason)

    def test_office_junior_closed_and_no_rf_are_rejected(self):
        for text in (BODY.replace('Senior','Junior'), BODY+'\nUPD: вакансия закрыта.',
                     BODY.replace('Полная удалёнка, офис в Черногории по желанию.','Только офис в Москве.'),
                     BODY+'\nКандидатов из РФ не рассматриваем.',
                     BODY+'\nОбязательный гибрид с посещением офиса два дня в неделю.',
                     BODY+'\nHybrid: 2 days/week in office.',
                     BODY+'\nОбязательное посещение офиса два дня в неделю.'):
            with self.subTest(text=text): self.assertEqual(self.verdict(text).bucket,'drop')

    def test_unknown_format_is_unknown_not_remote(self):
        self.assertEqual(self.verdict(BODY.split('Полная удалёнка')[0]).bucket,'unknown_format')

    def test_grade_suffixes_are_retained_and_rejected(self):
        for title in ['Data Analyst (Junior)','Data Analyst (стажёр)','Junior / Middle Data Analyst']:
            with self.subTest(title=title):
                self.assertEqual(self.verdict(BODY.replace('Senior Product Analyst',title)).bucket,'drop')

    def test_product_description_after_role_is_not_an_unrelated_job_title(self):
        text=BODY.replace('Senior Product Analyst в Prequel.','Senior Product Analyst на наши ai фото/видео редакторы.')
        profile={'title_queries':[{'include':['product analyst'],'exclude':['фот']}], 'exclude_grades':['junior','intern']}
        verdicts,_=classify_all(lp.normalize_post(post(text=text)),profile,None)
        self.assertEqual(verdicts[0].bucket,'main')

    def test_jobseeker_and_generic_recruiter_posts_not_vacancies(self):
        for text in ('Я Senior Data Analyst. Ищу работу. Удалённо. Опыт SQL Python пять лет.',
                     'Я рекрутер. Senior Product Analyst — востребованная профессия. Удалённо работают многие.'):
            self.assertEqual(self.verdict(text).bucket,'drop')


class LifetimeTests(unittest.TestCase):
    def test_different_linkedin_posts_with_generic_titles_are_not_confirmed_twins(self):
        a=lp.normalize_post(post());b=lp.normalize_post(post('7529156726835658799'))
        for item in a+b:item.links=[]
        verdicts,_=classify_all(a+b,{},None)
        analyze(verdicts,[],NOW,permanent_confirmed=True)
        self.assertEqual([v.bucket for v in verdicts],['main','main'])

    def test_two_accepted_positions_in_one_post_are_not_merged_by_publication_url(self):
        text='Вакансии:\nSenior Data Analyst\nЗадачи: SQL, отчётность. Удалённая работа.\nSenior Product Analyst\nЗадачи: A/B, продуктовые метрики, исследования. Удалённая работа.'
        items=lp.normalize_post(post(text=text))
        verdicts,_=classify_all(items,{},None)
        analyze(verdicts,[],NOW)
        self.assertEqual([v.bucket for v in verdicts],['main','main'])

    def test_confirmed_employer_identity_never_reappears_after_31_days(self):
        old=post()
        items=lp.normalize_post(old)
        verdicts,_=classify_all(items,{},None)
        rows=analyze(verdicts,[],NOW)
        rows[0].update(reported_at=NOW.isoformat(),status='new')
        again=lp.normalize_post(post('7529156726835658799',text=BODY.replace('Prequel','Prequel')))
        v,_=classify_all(again,{},None)
        analyze(v,rows,NOW+timedelta(days=61),permanent_confirmed=True)
        self.assertEqual(v[0].bucket,'drop')

    def test_weak_semantic_match_is_not_hidden_forever(self):
        a=lp.normalize_post(post());a[0].links=[]
        old,_=classify_all(a,{},None); rows=analyze(old,[],NOW)
        rows[0].update(reported_at=NOW.isoformat(),status='new')
        b=lp.normalize_post(post('7529156726835658799'));b[0].links=[]
        new,_=classify_all(b,{},None)
        analyze(new,rows,NOW+timedelta(days=61),permanent_confirmed=True)
        self.assertEqual(new[0].bucket,'main')


class BridgeTests(unittest.TestCase):
    def test_live_unresponsive_controller_is_not_started_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge=BrowserBridge(Path(tmp),{})
            (bridge.base/'status.json').write_text(json.dumps({'status':'waiting_for_manual_login','pid':1234}))
            with mock.patch.object(bridge,'_send',side_effect=TimeoutError('busy')), \
                 mock.patch('vd.linkedin_bridge._process_alive',return_value=True), \
                 mock.patch('vd.linkedin_bridge.subprocess.Popen') as start:
                with self.assertRaises(RuntimeError):bridge.request({'action':'state'})
                start.assert_not_called()

    def test_stale_response_is_ignored_and_fresh_response_matches_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'out/linkedin-browser-playwright';base.mkdir(parents=True)
            (base/'response.json').write_text(json.dumps({'id':'old','ok':True,'posts':['stale']}))
            def worker():
                until=time.monotonic()+3
                while time.monotonic()<until:
                    command=base/'command.json'
                    if command.exists():
                        try: data=json.loads(command.read_text())
                        except ValueError:continue
                        (base/'response.json').write_text(json.dumps({'id':data['id'],'ok':True,'posts':[]}))
                        return
                    time.sleep(.01)
            thread=threading.Thread(target=worker);thread.start()
            bridge=BrowserBridge(root,{'autostart':False,'request_timeout_sec':1})
            result=bridge.request({'action':'state'})
            thread.join()
            self.assertEqual(result['posts'],[])
            with bridge._request_lock():pass

    def test_lock_and_timeout_fail_safely_without_reading_stale_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'out/linkedin-browser-playwright';base.mkdir(parents=True)
            bridge=BrowserBridge(root,{'autostart':False,'request_timeout_sec':.05})
            with self.assertRaises(TimeoutError):bridge.request({'action':'state'})
            with bridge._request_lock():
                with self.assertRaises(RuntimeError):bridge.request({'action':'state'})
            # An old file cannot block the next owner after timeout or process exit.
            with mock.patch.object(bridge,'_send',return_value={'ok':True}):
                self.assertTrue(bridge.request({'action':'state'})['ok'])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'state.sqlite');self.addCleanup(self.store.close)
        self.cfg={'sources':{'telegram':{'expand_digests':False},'linkedin_posts':{'enabled':True,'hashtags':['#hiring','#ProductAnalyst']}},
                  'run':{'workdays_only':False,'permanent_confirmed_dedup':True},'llm':{'enabled':False},
                  'mail':{'send_when_empty':True,'to':'test@example.com'}}

    def pipeline(self,dry=False,failure=False,auth=False):
        args=SimpleNamespace(stats=False,force=True,dry_run=dry,no_llm=True)
        response={'posts':[post()],'complete':True,'scanned':1,'errors':[]}
        with mock.patch.object(main,'ROOT',self.root),mock.patch.object(main,'_now',return_value=NOW), \
             mock.patch.object(main,'make_fetcher',return_value=lambda _:''), \
             mock.patch.object(BrowserBridge,'request',side_effect=RuntimeError('ручной вход') if auth else None,return_value=response), \
             mock.patch.object(mailer,'send',side_effect=mailer.SendError('offline') if failure else None,return_value='test') as send:
            code=main._run(args,self.cfg,self.store)
            return code,send.call_count

    def test_success_real_collect_pipeline_commits_and_next_run_does_not_repeat(self):
        self.assertEqual(self.pipeline()[0],0)
        self.assertTrue(self.store.is_seen(lp.SOURCE,'7529156726835658753'))
        self.assertEqual(self.store.conn.execute('SELECT count(*) FROM publications').fetchone()[0],1)
        self.assertEqual(len(self.store.seen_ids_for(lp.SOURCE)),1)
        self.pipeline()
        stats=json.loads(self.store.conn.execute('SELECT stats_json FROM runs ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.assertEqual(stats['picked'],0)
        self.assertIn('tags',stats['sources'][lp.SOURCE])

    def test_dry_and_send_failure_do_not_commit_seen_or_archive(self):
        for dry,failure in [(True,False),(False,True)]:
            with self.subTest(dry=dry):
                code,sends=self.pipeline(dry=dry,failure=failure)
                self.assertEqual(code,1 if failure else 0)
                if dry:self.assertEqual(sends,0)
                self.assertFalse(self.store.is_seen(lp.SOURCE,'7529156726835658753'))
                self.assertEqual(self.store.duplicate_history(),[])
                self.assertIsNone(self.store.get_bookmark(lp.SOURCE))

    def test_source_login_error_is_recorded_without_crashing_digest(self):
        self.assertEqual(self.pipeline(auth=True)[0],0)
        stats=json.loads(self.store.conn.execute('SELECT stats_json FROM runs ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.assertIn(lp.SOURCE,stats['failed'])
        self.assertIsNone(self.store.get_bookmark(lp.SOURCE))

    def test_scheduled_source_starts_tomorrow_but_dry_run_can_verify_today(self):
        self.cfg['sources']['linkedin_posts']['start_date']='2026-11-20'
        with mock.patch.object(main,'_now',return_value=NOW), \
             mock.patch.object(lp,'collect',return_value=SourceResult(lp.SOURCE)) as collect:
            self.assertEqual(main.collect_all(self.cfg,self.store,lambda _:''),[])
            collect.assert_not_called()
            self.assertEqual(len(main.collect_all(self.cfg,self.store,lambda _:'',dry_run=True)),1)
        with mock.patch.object(main,'_now',return_value=NOW+timedelta(days=1)), \
             mock.patch.object(lp,'collect',return_value=SourceResult(lp.SOURCE)):
            self.assertEqual(len(main.collect_all(self.cfg,self.store,lambda _:'')),1)

    def test_author_and_tag_statistics_in_both_digest_versions(self):
        verdicts,_=classify_all(lp.normalize_post(post()),{},None)
        metrics={lp.SOURCE:{'tags':{'#hiring':{'viewed':3,'new':1,'vacancies':1,'passed':1,'seen':2,'errors':0,'incomplete':0}}}}
        _,html,text=digest.build(verdicts,{lp.SOURCE:1},{},{'llm_off':True},source_info=metrics)
        for body in [html,text]:
            self.assertIn('Recruiter',body)
            self.assertIn('#hiring',body)
            self.assertIn('просмотрено 3',body)
