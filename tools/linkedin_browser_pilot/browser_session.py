"""Local interactive pilot. User handles all authentication; no account data export."""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parents[2] / 'out' / 'linkedin-browser-playwright'
BASE.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BASE / 'packages'))
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def write_json(name, value):
    path = BASE / name
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def page_state(context):
    # Do not capture form values, cookies, storage, screenshots or account feed text.
    return [{'url': p.url, 'title': p.title()} for p in context.pages if not p.is_closed()]


def run():
    write_json('status.json', {'status': 'starting', 'pid': os.getpid()})
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(BASE / 'profile'), channel='chrome', headless=False,
            no_viewport=True, accept_downloads=False, chromium_sandbox=True,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            navigation_error = None
            try:
                page.goto('https://www.linkedin.com/', wait_until='domcontentloaded', timeout=30000)
            except PlaywrightTimeoutError:
                navigation_error = 'Navigation timeout; inspect the visible browser.'
            write_json('status.json', {'status': 'waiting_for_manual_login', 'pid': os.getpid(),
                                      'pages': page_state(context), 'navigation_error': navigation_error})
            last_request = None
            # Event pumping keeps the browser interactive; no polling of user page contents.
            while context.pages:
                page = next((p for p in context.pages if not p.is_closed()), None)
                if page is None:
                    break
                command_file = BASE / 'command.json'
                if command_file.exists():
                    try:
                        command = json.loads(command_file.read_text(encoding='utf-8-sig'))
                    except (ValueError, OSError):
                        page.wait_for_timeout(500)
                        continue
                    request_id = command.get('id')
                    if request_id and request_id != last_request:
                        last_request = request_id
                        try:
                            action = command.get('action')
                            if action == 'state':
                                result = {'pages': page_state(context)}
                            elif action == 'search':
                                url = command.get('url', '')
                                parsed = urlsplit(url)
                                if (parsed.scheme != 'https' or parsed.hostname != 'www.linkedin.com'
                                        or parsed.path != '/search/results/content/' or parsed.username):
                                    raise ValueError('Only LinkedIn content-search navigation is allowed.')
                                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                                result = {'pages': page_state(context)}
                            elif action in ('read_results', 'inspect_dom'):
                                parsed = urlsplit(page.url)
                                if parsed.hostname != 'www.linkedin.com' or parsed.path != '/search/results/content/':
                                    raise ValueError('Read results only on the content-search page, never login/feed.')
                                main = page.get_by_role('main')
                                if action == 'inspect_dom':
                                    write_json('response.json', {'id': request_id, 'ok': True,
                                                                'url': page.url, 'html': main.inner_html()[:240000]})
                                    continue
                                links = main.locator('a[href]').evaluate_all(
                                    "els => els.filter(e => e.getClientRects().length).map(e => ({text:(e.innerText || e.getAttribute('aria-label') || '').slice(0,160),url:e.href})).filter(e=>e.url.startsWith('https://'))")
                                result = {'url': page.url, 'text': main.inner_text(timeout=5000)[:16000],
                                          'links': links[:150]}
                            elif action == 'close':
                                write_json('response.json', {'id': request_id, 'ok': True, 'closed': True})
                                break
                            elif action in ('scan_posts', 'scan_profile'):
                                import importlib
                                sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
                                from vd import linkedin_browser
                                result = importlib.reload(linkedin_browser).scan(page, command)
                            else:
                                raise ValueError('Unsupported action')
                            write_json('response.json', {'id': request_id, 'ok': True, **result})
                        except Exception as exc:
                            write_json('response.json', {'id': request_id, 'ok': False,
                                                        'error': type(exc).__name__ + ': ' + str(exc)[:300]})
                page.wait_for_timeout(500)
        finally:
            context.close()
            write_json('status.json', {'status': 'closed', 'pid': os.getpid()})


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        write_json('status.json', {'status': 'error', 'error': type(exc).__name__ + ': ' + str(exc)[:700]})
        raise
