"""Visible DOM scanner; authentication stays manual in the isolated Chrome profile."""
from __future__ import annotations

import ctypes
import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit, parse_qs


def relative_date(label, now):
    m=re.search(r'(\d+)\s*(мин\.?|ч\.?|дн\.?|нед\.?|minutes?|hours?|days?|weeks?|[mhdw])(?=\s|[.•]|$)',label,re.I)
    if not m:return None
    unit=m.group(2).lower()
    seconds=60 if unit.startswith(('мин','min')) or unit=='m' else 3600 if unit.startswith(('ч','hour')) or unit=='h' else 604800 if unit.startswith(('нед','week')) or unit=='w' else 86400
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


def _copied_link():
    # Called only after our copy-post-link UI action changed the clipboard sequence.
    from ctypes import wintypes
    user,kernel=ctypes.windll.user32,ctypes.windll.kernel32
    user.GetClipboardData.argtypes=[wintypes.UINT];user.GetClipboardData.restype=wintypes.HANDLE
    kernel.GlobalLock.argtypes=[wintypes.HGLOBAL];kernel.GlobalLock.restype=wintypes.LPVOID
    kernel.GlobalUnlock.argtypes=[wintypes.HGLOBAL]
    if not user.OpenClipboard(None):raise RuntimeError('Буфер занят')
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


def _main(page):
    parsed=urlsplit(page.url)
    if parsed.hostname!='www.linkedin.com' or parsed.path!='/search/results/content/':
        raise RuntimeError('LinkedIn требует ручной вход или показал защитную страницу')
    main=page.get_by_role('main')
    main.wait_for(state='visible',timeout=12000)
    page.wait_for_function("""() => {
        const m=document.querySelector('main');
        return m && (m.querySelector('[data-testid="expandable-text-box"]') || /Поиск не дал результатов|No results found|No results/.test(m.innerText));
    }""",timeout=15000)
    return main


def scan(page,command):
    deadline=time.monotonic()+int(command.get('timeout_sec',75))
    page.set_default_timeout(5000)
    tag=command['hashtag']
    from .sources.linkedin_posts import unique_tags
    unique_tags([tag])
    days=int(command.get('days',7))
    date_filter='past-24h' if days<=1 else 'past-week' if days<=7 else 'past-month'
    url='https://www.linkedin.com/search/results/content/?'+urlencode(
        {'keywords':tag,'datePosted':'"'+date_filter+'"','sortBy':'"date_posted"'})
    page.goto(url,wait_until='domcontentloaded',timeout=25000)
    main=_main(page)
    if not main.locator('[data-testid="expandable-text-box"]').count() and re.search(
            'Поиск не дал результатов|No results found|No results',main.inner_text()):
        return {'posts':[],'complete':True,'scanned':0,'errors':[]}
    limit=max(1,min(int(command.get('max_posts',8)),20))
    max_scrolls=max(0,min(int(command.get('max_scrolls',1)),3))
    seen=set(command.get('seen_ids',[]));visited=set();posts=[];errors=[];scanned=0;known=0
    # The card limit applies to new posts only: already known cards still cost a permalink copy,
    # but must not hide fresh posts further down the results. Scrolls and the deadline bound the rest.
    for scroll in range(max_scrolls+1):
        cards=main.locator('[role="listitem"]').filter(has=page.locator('[data-testid="expandable-text-box"]'))
        for index in range(cards.count()):
            card=cards.nth(index)
            token=card.get_attribute('componentkey') or str(index)
            if token in visited:continue
            if len(posts)>=limit or time.monotonic()>deadline:break
            visited.add(token);scanned+=1
            if card.get_attribute('componentkey'):
                # Search cards can reorder after a new-tab visit. Never bind text to an nth index.
                card=main.locator('[role="listitem"][componentkey='+json.dumps(token)+']')
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
        if len(posts)>=limit or time.monotonic()>deadline:break
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
    if len(posts)>=limit:errors.append(f'Достигнут лимит {limit} карточек; выдача просмотрена частично')
    if time.monotonic()>deadline:errors.append('Исчерпан бюджет времени тега')
    if len(posts)<limit and time.monotonic()<=deadline:
        errors.append('Достигнут лимит прокруток; полнота выдачи не подтверждена')
    return {'posts':posts,'complete':not errors,'scanned':scanned,'seen':known,'errors':errors}
