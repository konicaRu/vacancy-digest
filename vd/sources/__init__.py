import ssl
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

RUSSIAN_CA = Path(__file__).resolve().parent.parent / 'certs' / 'russian-trusted-root-ca.pem'

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class _RussianCAAdapter(HTTPAdapter):
    """Additional CA for bank origins only; chain and hostname checks stay enabled."""

    def __init__(self):
        self.context = ssl.create_default_context(cafile=requests.certs.where())
        self.context.load_verify_locations(cafile=str(RUSSIAN_CA))
        super().__init__()

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host, pool = super().build_connection_pool_key_attributes(request, verify, cert)
        if verify is True:
            pool['ssl_context'] = self.context
        return host, pool


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"})
    bank_adapter = _RussianCAAdapter()
    s.mount('https://www.tbank.ru/', bank_adapter)
    s.mount('https://job.alfabank.ru/', bank_adapter)
    s.mount('https://hr.tochka.com/', bank_adapter)
    s.mount('https://www.nspk.ru/', bank_adapter)
    return s
