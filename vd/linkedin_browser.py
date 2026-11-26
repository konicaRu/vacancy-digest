"""Visible DOM scanner; authentication stays manual in the isolated Chrome profile."""
from __future__ import annotations

import ctypes
import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit, parse_qs


def relative_date(label, now):
    m=re.search(r'(\d+)\s*(мин\.?|мес\.?|ч\.?|дн\.?|нед\.?|г\.?|minutes?|months?|mo|hours?|days?|weeks?|years?|yrs?|[mhdwy])(?=\s|[.•]|$)',label,re.I)
    if not m:return None
    unit=m.group(2).lower()
    if unit.startswith(('мес','mo')):seconds=30*86400
    elif unit.startswith(('г','y')):seconds=365*86400
    else:seconds=60 if unit.startswith(('мин','min')) or unit=='m' else 3600 if unit.startswith(('ч','hour')) or unit=='h' else 604800 if unit.startswith(('нед','week')) or unit=='w' else 86400
    return now-timedelta(seconds=int(m.group(1))*seconds)


def public_link(value):
    value=value.strip()
    p=urlsplit(value)
    if p.scheme!='https' or p.username:return None
    if p.hostname=='lnkd.in':return value
    if p.hostname in ('www.linkedin.com','linkedin.com') and p.path.startswith(('/posts/','/feed/update/')):return value
    return None


def _clipboard_sequence():
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def _open_clipboard(user):
    # Another program (clipboard history, a messenger) may hold the clipboard for a moment.
    for attempt in range(10):
        if user.OpenClipboard(None):return
        if attempt<9:time.sleep(0.1)
    raise RuntimeError('Буфер занят')


def _copied_link():
    # Called only after our copy-post-link UI action changed the clipboard sequence.
    from ctypes import wintypes
    user,kernel=ctypes.windll.user32,ctypes.windll.kernel32
    user.GetClipboardData.argtypes=[wintypes.UINT];user.GetClipboardData.restype=wintypes.HANDLE
    kernel.GlobalLock.argtypes=[wintypes.HGLOBAL];kernel.GlobalLock.restype=wintypes.LPVOID
    kernel.GlobalUnlock.argtypes=[wintypes.HGLOBAL]
    _open_clipboard(user)
    handle=None;pointer=None
    try:
        handle=user.GetClipboardData(13)
        pointer=kernel.GlobalLock(handle) if handle else None
        return public_link(ctypes.wstring_at(pointer)) if pointer else None
    finally:
        if pointer:kernel.GlobalUnlock(handle)
        user.CloseClipboard()


def _permalink(page,card):
    from .sources.linkedin_posts import post_identity
    # LinkedIn can leave the previous post menu open after copying its link.
    page.keyboard.press('Escape')
    try:
        card.get_by_role('button',name=re.compile('Открыть меню управления|Open control menu',re.I)).first.click(timeout=5000)
    except Exception as exc:
        raise RuntimeError('Не открылось меню поста: '+str(exc).replace('\n',' ')[:500]) from exc
    sequence=_clipboard_sequence()
    copy_link=page.get_by_text(re.compile(r'^(Скопировать ссылку на публикацию|Copy link to post)$',re.I))
    try:
        try:
            copy_link.wait_for(state='visible',timeout=800)
        except Exception:
            # The menu may appear just after the wait timed out. Reset it before
            # retrying: clicking an already open menu button would close it.
            page.keyboard.press('Escape')
            card.get_by_role('button',name=re.compile('Открыть меню управления|Open control menu',re.I)).first.click(timeout=5000)
        copy_link.click(timeout=5000)
    except Exception as exc:
        raise RuntimeError('Нет команды копирования ссылки: '+str(exc).replace('\n',' ')[:500]) from exc
    until=time.monotonic()+3
    while _clipboard_sequence()==sequence and time.monotonic()<until:page.wait_for_timeout(100)
    if _clipboard_sequence()==sequence:raise RuntimeError('Не удалось скопировать ссылку поста')
    link=_copied_link()
    if not link:raise RuntimeError('Скопирована не публичная ссылка LinkedIn')
    if urlsplit(link).hostname!='lnkd.in':return post_identity(link)
    detail=page.context.new_page()
    try:
        detail.goto(link,wait_until='domcontentloaded',timeout=15000)
        return post_identity(detail.url)
    finally:
        detail.close()
        page.bring_to_front()


def _main(page,path='/search/results/content/',allow_empty=False):
    parsed=urlsplit(page.url)
    if parsed.hostname!='www.linkedin.com' or parsed.path!=path:
        raise RuntimeError('LinkedIn требует ручной вход или показал защитную страницу')
    main=page.get_by_role('main')
    main.wait_for(state='visible',timeout=12000)
    try:
        page.wait_for_function("""() => {
            const m=document.querySelector('main');
            return m && (m.querySelector('[data-testid="expandable-text-box"]') || /Поиск не дал результатов|No results found|No results/.test(m.innerText));
        }""",timeout=15000)
    except Exception as exc:
        # A recruiter's own page (URL already checked above) without post cards: no or hidden posts.
        if allow_empty and 'Timeout' in type(exc).__name__:
            return None
        raise
    return main


def scan(page,command):
    deadline=time.monotonic()+int(command.get('timeout_sec',75))
    page.set_default_timeout(5000)
    from .sources.linkedin_posts import profile_page, unique_tags
    days=int(command.get('days',7))
    profile='profile' in command
    if profile:
        # A recruiter's own page: a person's activity is newest first, a company's posts are sorted
        # by popularity. The date is read before the (slow) link copy; old posts are never opened.
        url,stop_on_old=profile_page(command['profile'])
    else:
        tag=command['hashtag']
        unique_tags([tag])
        date_filter='past-24h' if days<=1 else 'past-week' if days<=7 else 'past-month'
        url='https://www.linkedin.com/search/results/content/?'+urlencode(
            {'keywords':tag,'datePosted':'"'+date_filter+'"','sortBy':'"date_posted"'})
    page.goto(url,wait_until='domcontentloaded',timeout=25000)
    main=_main(page,urlsplit(url).path,allow_empty=profile)
    if main is None:
        return {'posts':[],'complete':True,'scanned':0,'seen':0,'errors':[],'undated':0,'empty':True}
    if not main.locator('[data-testid="expandable-text-box"]').count() and re.search(
            'Поиск не дал результатов|No results found|No results',main.inner_text()):
        return {'posts':[],'complete':True,'scanned':0,'errors':[]}
    limit=max(1,min(int(command.get('max_posts',8)),20))
    max_scrolls=max(0,min(int(command.get('max_scrolls',1)),3))
    seen=set(command.get('seen_ids',[]));visited=set();posts=[];errors=[];scanned=0;known=0
    reached_old=False;undated=0;exhausted=False;shown=None
    # The card limit applies to new posts only: already known cards still cost a permalink copy,
    # but must not hide fresh posts further down the results. Scrolls and the deadline bound the rest.
    for scroll in range(max_scrolls+1):
        cards=main.locator('[role="listitem"]').filter(has=page.locator('[data-testid="expandable-text-box"]'))
        if shown is not None and cards.count()<=shown:
            exhausted=True;break  # the scroll added no cards: every result has been read
        shown=cards.count()
        for index in range(cards.count()):
            card=cards.nth(index)
            token=card.get_attribute('componentkey') or str(index)
            if token in visited:continue
            if len(posts)>=limit or time.monotonic()>deadline:break
            visited.add(token);scanned+=1
            if card.get_attribute('componentkey'):
                # Search cards can reorder after a new-tab visit. Never bind text to an nth index.
                card=main.locator('[role="listitem"][componentkey='+json.dumps(token)+']')
            if profile:
                first=card.locator('[data-testid="expandable-text-box"]').nth(0).inner_text(timeout=5000)
                posted=relative_date(card.inner_text().split(first[:50],1)[0],datetime.now())
                if posted is None:
                    undated+=1;continue
                if posted<datetime.now()-timedelta(days=days):
                    if stop_on_old:
                        reached_old=True;break
                    continue
            stage='ссылка'
            try:
                key,permalink=_permalink(page,card)
                if key in seen:
                    known+=1
                    continue
                boxes=card.locator('[data-testid="expandable-text-box"]')
                stage='полный текст'
                texts=[]
                for body_index in range(boxes.count()):
                    body=boxes.nth(body_index)
                    expand=body.locator('[data-testid="expandable-text-button"]')
                    if expand.count() and expand.first.is_visible():expand.first.click(timeout=4000)
                    if expand.count() and expand.first.is_visible():raise RuntimeError('Текст остался свёрнутым')
                    part=body.inner_text(timeout=5000)
                    if part and part not in texts:texts.append(part)
                # Keep a reposter's closing note/restrictions as well as the quoted vacancy.
                text='\n\n'.join(texts)
                header=card.inner_text().split(text[:50],1)[0]
                published=relative_date(header,datetime.now())
                if published and published<datetime.now()-timedelta(days=days):continue
                authors=card.locator('a[href*="/in/"], a[href*="/company/"]')
                author=next((authors.nth(i).inner_text().split('\n')[0].strip() for i in range(authors.count())
                             if authors.nth(i).inner_text().strip()),'')
                links=boxes.locator('a[href]').evaluate_all('els=>els.map(e=>e.href)')
                normalized=[]
                for link in links:
                    p=urlsplit(link)
                    if p.hostname=='www.linkedin.com' and p.path=='/safety/go/':link=parse_qs(p.query).get('url',[link])[0]
                    if urlsplit(link).scheme=='https':normalized.append(link)
                posts.append(dict(id=key,url=permalink,author=author,text=text,complete=True,
                                  published_at=published.isoformat(timespec='seconds') if published else None,
                                  links=normalized))
            except Exception as exc:
                errors.append(stage+': '+type(exc).__name__+': '+str(exc).split('\n')[0][:600])
                page.keyboard.press('Escape')
        if reached_old or len(posts)>=limit or time.monotonic()>deadline:break
        if scroll<max_scrolls:
            cards.last.evaluate("""el=>{
                for(let node=el.parentElement;node;node=node.parentElement){
                    if(node.scrollHeight>node.clientHeight+1 && /auto|scroll/.test(getComputedStyle(node).overflowY)){
                        node.scrollTop=node.scrollHeight;return;
                    }
                }
                document.scrollingElement.scrollTop=document.scrollingElement.scrollHeight;
            }""")
            page.wait_for_timeout(1500)
    if profile:
        # A person's page read up to an old post is complete; a company page is bounded by its limits.
        if not reached_old and len(posts)>=limit:errors.append(f'Достигнут лимит {limit} карточек профиля')
        if not reached_old and time.monotonic()>deadline:errors.append('Исчерпан бюджет времени профиля')
        return {'posts':posts,'complete':not errors,'scanned':scanned,'seen':known,'errors':errors,
                'undated':undated}
    if len(posts)>=limit:errors.append(f'Достигнут лимит {limit} карточек; выдача просмотрена частично')
    if time.monotonic()>deadline:errors.append('Исчерпан бюджет времени тега')
    if len(posts)<limit and time.monotonic()<=deadline and not exhausted:
        errors.append('Достигнут лимит прокруток; полнота выдачи не подтверждена')
    return {'posts':posts,'complete':not errors,'scanned':scanned,'seen':known,'errors':errors}
