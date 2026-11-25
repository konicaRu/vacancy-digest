"""Bounded browser-backed LinkedIn Posts; no authentication automation or mail access."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs

import yaml

from ..models import Item, SourceResult

SOURCE = 'linkedin:posts'
ROLE = re.compile(r'(?:(?:senior|middle\+?|junior|lead|intern|trainee|старший|ведущий|младший)\s+)?'
                  r'(?:product\s+analyst|data\s+analyst|bi[ -]+analyst|business\s+analyst|system\s+analyst|'
                  r'продуктов\w*\s+аналитик\w*|аналитик\w*\s+данных|bi[ -]+аналитик\w*|'
                  r'системн\w*\s+аналитик\w*|бизнес[ -]+аналитик\w*)', re.I)
HIRING = re.compile(r'ищем|ваканси|приглашаем|открыт\w*\s+(?:позици|ваканси)|в поиске|\bhiring\b',re.I)
CLOSED = re.compile(r'(?:ваканси\w*|позици\w*)\s+(?:уже\s+)?закрыт|набор\s+заверш|больше\s+не\s+ищем|'
                    r'пока\s+достаточно.*набрали|\bclosed\b|\bзакрыта\b',re.I)


def unique_tags(tags):
    result=[]; seen=set()
    for tag in tags:
        # A query is 1-6 space-separated words; each word may carry a leading '#'.
        # Anything else (quotes, '&', tabs, newlines) could alter the search URL, so it is rejected.
        words=[word for word in str(tag).split(' ') if word]
        if not 1<=len(words)<=6 or not all(re.fullmatch(r'#?\w+',word) for word in words):
            raise ValueError('Неверный запрос LinkedIn')
        tag=' '.join(words)
        if tag.casefold() not in seen:
            result.append(tag);seen.add(tag.casefold())
    return result


PROFILE=re.compile(r'https://www\.linkedin\.com/(in|company)/([A-Za-z0-9%_.~-]+)/?')


def profile_page(url):
    """Страница постов профиля: у человека «Все действия» (по времени), у компании «Публикации»."""
    match=PROFILE.fullmatch(str(url).strip())
    if not match: raise ValueError('Неверная ссылка на профиль LinkedIn')
    kind,slug=match.groups()
    base=f'https://www.linkedin.com/{kind}/{slug}/'
    return (base+'recent-activity/all/',True) if kind=='in' else (base+'posts/',False)


def post_identity(url):
    p=urlsplit(url)
    if p.scheme!='https' or not (p.hostname=='linkedin.com' or (p.hostname or '').endswith('.linkedin.com')) or p.username:
        raise ValueError('Не публичная ссылка LinkedIn')
    text=unquote(parse_qs(p.query).get('highlightedUpdateUrn',[''])[0])
    match=re.search(r'urn:li:activity:(\d{15,22})',text)
    if not match: match=re.search(r'(?:activity|share|ugcPost)[:-](\d{15,22})',unquote(p.path))
    if not match or not p.path.startswith(('/posts/','/feed/update/')):
        raise ValueError('Нет постоянного ID публикации')
    key=match.group(1)
    return key,f'https://www.linkedin.com/feed/update/urn:li:activity:{key}/'


def normalize_post(post):
    key,url=post_identity(post['url'])
    text=post.get('text','').strip()
    if not text or not post.get('complete'): return []
    matches=list(ROLE.finditer(text))
    if not matches: return []
    # Split only explicit role headings, not mentions of experience in a paragraph.
    headings=[m for m in matches if re.fullmatch(r'[\s\W\d]*',text[text.rfind('\n',0,m.start())+1:m.start()])]
    def title_for(match):
        start=match.start()
        prefix=text[text.rfind('\n',0,start)+1:start]
        grade_prefix=re.search(r'(?:junior|intern|trainee|стаж[её]р|младш\w*)\s*[/|+()\s-]*$',prefix,re.I)
        if grade_prefix:start-=len(grade_prefix.group(0))
        line=text[start:].split('\n',1)[0].strip().rstrip('.')
        # Keep grade/role qualifiers, but not the employer or product description after the role.
        return re.split(r'\s+(?:на|в|во|для|in|at|for|into)\s+',line,maxsplit=1,flags=re.I)[0]
    sections=[]
    if len(headings)>1:
        preamble=text[:text.rfind('\n',0,headings[0].start())+1].strip()
        for index,m in enumerate(headings):
            end=headings[index+1].start() if index+1<len(headings) else len(text)
            sections.append((title_for(m),'\n'.join(filter(None,(preamble,text[m.start():end].strip())))))
    else:
        sections=[(title_for(matches[0]),text)]
    output=[]
    for i,(title,body) in enumerate(sections):
        company_match=re.search(r'\bв\s+([A-Z][A-Za-z0-9.-]{1,40})\b',body)
        company=company_match.group(1).rstrip('.') if company_match else None
        published=None
        if post.get('published_at'):
            try: published=datetime.fromisoformat(post['published_at'])
            except ValueError: pass
        links=[link for link in post.get('links',[]) if len(sections)==1 or link in body]
        output.append(Item(SOURCE,'linkedin_posts',key if len(sections)==1 else f'{key}:{i+1}',url,body,
                           published_at=published,hint_title=title,links=links,
                           employer=company,author=post.get('author'),text_complete=True))
    return output


def filter_reason(item):
    text=item.text
    without_tags=re.sub(r'https?://\S+|#[\w]+','',text)
    letters=re.findall(r'[A-Za-zА-Яа-яЁё]',without_tags)
    russian=len(re.findall(r'[А-Яа-яЁё]',without_tags))
    if russian<25 or russian/max(len(letters),1)<.3: return 'язык: недостаточно русского текста'
    if not item.text_complete: return 'неполный текст LinkedIn'
    if CLOSED.search(text): return 'вакансия закрыта'
    if not HIRING.search(text) and not re.match(r'^(?:Senior|Middle|Junior|Lead|Data|Product|BI|Аналитик|Продуктов)',text):
        return 'нет признаков найма'
    if re.search(r'ищу\s+(?:работу|новую\s+работу)|open\s+to\s+work',text,re.I) and not HIRING.search(text):
        return 'резюме соискателя'
    if re.search(r'(?:рф|росси\w*)[^\n.!]{0,35}не\s+рассматрива|не\s+рассматрива[^\n.!]{0,35}(?:рф|росси)',text,re.I):
        return 'явное исключение РФ'
    if re.search(r'обязательн\w*[^\n.]{0,30}гибрид|гибрид[^\n.]{0,70}(?:посещен|обязательн|дня\s+в\s+неделю)',text,re.I):
        return 'обязательный гибрид'
    if re.search(r'обязательн\w*\s+посещен\w*\s+офис|(?:mandatory|required)\s+hybrid|'
                 r'hybrid[^\n.]{0,70}(?:days?\s*[/а-я\w -]*week|in[- ]office|mandatory|required)',text,re.I):
        return 'обязательный гибрид'
    return ''


def collect(cfg, root, is_seen, bookmark, *, request=None, now=None, seen_ids=None):
    now=now or datetime.now()
    result=SourceResult(SOURCE)
    tags=unique_tags(cfg.get('hashtags',[]))
    recruiters=list(cfg.get('recruiters') or [])
    if cfg.get('recruiters_file'):
        # Names of real people stay in a local file (data/ is not in git), not in the public config.
        path=Path(root)/cfg['recruiters_file']
        try:
            recruiters+=yaml.safe_load(path.read_text(encoding='utf-8')) or []
        except (OSError,yaml.YAMLError) as exc:
            result.error=f'Список рекрутеров LinkedIn не прочитан: {path.name}: {type(exc).__name__}';return result
    if not tags and not recruiters: result.error='Не заданы хэштеги и рекрутеры LinkedIn';return result
    if request is None:
        from ..linkedin_bridge import BrowserBridge
        request=BrowserBridge(root,cfg).request
    posts={};successful=0;warnings=[]
    timeout=cfg.get('total_timeout_by_date',{}).get(now.date().isoformat(),cfg.get('total_timeout_sec',360))
    deadline=time.monotonic()+timeout
    stats={'tags':{},'unique_posts':0}
    days=cfg.get('lookback_days_first_run',7)

    def take(label,command,counts):
        """One browser request; its new complete posts are merged under `label`."""
        nonlocal successful
        try:
            response=request(dict(command,seen_ids=list(set(seen_ids or []) | set(posts))))
            successful+=1
            counts['viewed']=response.get('scanned',0)
            counts['seen']=response.get('seen',0)
            if response.get('undated'): counts['undated']=response['undated']
            if not response.get('complete',False): warnings.append(f'{label}: частичная выдача')
            for error in response.get('errors',[]): warnings.append(f'{label}: {error}');counts['errors']+=1
            for row in response.get('posts',[]):
                try: key,url=post_identity(row['url'])
                except (ValueError,KeyError): counts['incomplete']+=1;continue
                if is_seen(SOURCE,key): counts['seen']+=1;continue
                if not row.get('complete'): counts['incomplete']+=1;continue
                if key in posts:
                    posts[key]['tags'].append(label)
                    continue
                row=dict(row,url=url,tags=[label]);posts[key]=row;counts['new']+=1
            if counts['incomplete']:warnings.append(f'{label}: неполных постов {counts["incomplete"]}')
        except Exception as exc:
            counts['errors']+=1;warnings.append(f'{label}: {type(exc).__name__}: {str(exc)[:160]}')

    for tag in tags:
        counts={'viewed':0,'new':0,'seen':0,'incomplete':0,'errors':0}
        stats['tags'][tag]=counts
        if time.monotonic()>deadline:
            counts['errors']+=1;warnings.append(f'{tag}: TimeoutError: Исчерпан бюджет LinkedIn');continue
        take(tag,{'action':'scan_posts','hashtag':tag,'days':days,
                  'max_posts':cfg.get('max_posts_per_tag',8),
                  'max_scrolls':cfg.get('max_scrolls_per_tag',1),
                  'timeout_sec':min(75, max(1, int(deadline-time.monotonic())))},counts)

    # Recruiters have their own budget, so hashtag searches cannot starve them (and vice versa).
    if recruiters: stats['recruiters']={}
    recruiters_deadline=time.monotonic()+cfg.get('recruiters_timeout_sec',420)
    for entry in recruiters:
        url=entry.get('url','') if isinstance(entry,dict) else str(entry)
        name=(entry.get('name') if isinstance(entry,dict) else None) or url
        counts={'viewed':0,'new':0,'seen':0,'incomplete':0,'errors':0}
        stats['recruiters'][name]=counts
        label=f'рекрутер: {name}'
        try:
            profile_page(url)
            if time.monotonic()>recruiters_deadline: raise TimeoutError('Исчерпан бюджет рекрутеров LinkedIn')
        except (ValueError,TimeoutError) as exc:
            counts['errors']+=1;warnings.append(f'{label}: {type(exc).__name__}: {exc}');continue
        take(label,{'action':'scan_profile','profile':url,'days':days,
                    'max_posts':cfg.get('max_posts_per_recruiter',5),'max_scrolls':0,
                    'timeout_sec':min(cfg.get('recruiter_timeout_sec',25),
                                      max(1,int(recruiters_deadline-time.monotonic())))},counts)
    for key,row in posts.items():
        try:
            items=normalize_post(row)
        except (ValueError, TypeError, KeyError) as exc:
            warnings.append(f'Публикация {key}: неполные данные ({type(exc).__name__})')
            continue
        for item in items:item.discovery_tags=row['tags']
        result.items.extend(items)
        result.seen_ids.append(key)
    stats['unique_posts']=len(posts);result.stats=stats
    if not successful: result.error='LinkedIn не прочитан: '+'; '.join(warnings)[:1000]
    elif warnings: result.warning='; '.join(warnings)[:1400]
    else: result.new_bookmark=now.isoformat(timespec='seconds')
    return result
