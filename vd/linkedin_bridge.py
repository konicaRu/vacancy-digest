"""File IPC to the local Chrome pilot. No cookies or credentials cross this boundary."""
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def _process_alive(pid):
    if os.name != 'nt':
        return True  # Never reclaim another process's lock on an unsupported platform.
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        return ctypes.get_last_error()!=87  # Access denied is not proof of a dead process.
    try:
        status=wintypes.DWORD()
        return not kernel.GetExitCodeProcess(handle,ctypes.byref(status)) or status.value==259
    finally:
        kernel.CloseHandle(handle)


class BrowserBridge:
    def __init__(self,root,cfg):
        self.root=Path(root).resolve();self.cfg=cfg
        self.base=self.root/'out/linkedin-browser-playwright'
        self.base.mkdir(parents=True,exist_ok=True)
        self.ready=not cfg.get('autostart',True)

    def _send(self,command,timeout):
        request=dict(command,id=uuid.uuid4().hex)
        temporary=self.base/(request['id']+'.tmp')
        temporary.write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
        temporary.replace(self.base/'command.json')
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                response=json.loads((self.base/'response.json').read_text(encoding='utf-8-sig'))
                if response.get('id')==request['id']:
                    if not response.get('ok'):raise RuntimeError(response.get('error','Ошибка браузера LinkedIn'))
                    return response
            except (FileNotFoundError,json.JSONDecodeError):pass
            time.sleep(.1)
        raise TimeoutError('Нет свежего ответа браузера LinkedIn; проверьте окно и ручной вход')

    def _ensure(self):
        if self.ready:return
        try:
            self._send({'action':'state'},2)
        except TimeoutError:
            try:
                status=json.loads((self.base/'status.json').read_text(encoding='utf-8'))
                if status.get('status') not in ('closed','error') and _process_alive(int(status['pid'])):
                    raise RuntimeError('Контроллер LinkedIn занят или не отвечает; второй браузер не запущен')
            except (FileNotFoundError,KeyError,ValueError):
                pass
            worker=self.root/'tools/linkedin_browser_pilot/browser_session.py'
            package=self.base/'packages/playwright'
            if not worker.exists() or not package.exists():
                raise RuntimeError('Playwright пилот не установлен; см. tools/linkedin_browser_pilot/README.md')
            # Startup must never replay an earlier close/search command.
            (self.base/'command.json').write_text('{}',encoding='utf-8')
            with (self.base/'controller.stdout.log').open('a',encoding='utf-8') as out, \
                 (self.base/'controller.stderr.log').open('a',encoding='utf-8') as err:
                subprocess.Popen([sys.executable,str(worker)],cwd=str(self.root),stdout=out,stderr=err,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            time.sleep(1)
            self._send({'action':'state'},45)
        self.ready=True

    @contextmanager
    def _request_lock(self):
        # Keep the same file instance. The OS releases this byte lock even on a crash.
        handle=os.fdopen(os.open(self.base/'request.lock',os.O_CREAT|os.O_RDWR),'r+b')
        acquired=False
        try:
            if os.fstat(handle.fileno()).st_size==0:
                handle.write(b'\0');handle.flush()
            handle.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Браузер LinkedIn уже используется другим запуском') from exc
            acquired=True
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            handle.close()

    def request(self,command):
        with self._request_lock():
            self._ensure()
            return self._send(command,self.cfg.get('request_timeout_sec',120))
