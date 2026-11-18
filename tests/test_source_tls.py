"""Real TLS handshakes against a loopback server; all keys here are TEST ONLY."""
import ssl
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import requests
from urllib3.util import connection

from vd import sources

FIXTURES = Path(__file__).parent / 'fixtures' / 'tls'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'verified')

    def log_message(self, *_):
        pass


class SourceTLSTests(unittest.TestCase):
    def start_server(self, certificate='server.pem'):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(FIXTURES / certificate, FIXTURES / 'server.key')
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.addCleanup(cleanup)
        connect = connection.create_connection
        # Route only the socket to loopback; Requests keeps the real SNI/hostname.
        patch = mock.patch.object(connection, 'create_connection',
                                  side_effect=lambda address, *a, **kw: connect(server.server_address, *a, **kw))
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(sources, 'RUSSIAN_CA', FIXTURES / 'ca.pem', create=True)
        patch.start()
        self.addCleanup(patch.stop)
        session = sources.make_session()
        session.trust_env = False
        self.addCleanup(session.close)
        return session

    def test_both_bank_origins_accept_valid_chain_from_extra_ca(self):
        session = self.start_server()
        for url in ('https://www.tbank.ru/', 'https://job.alfabank.ru/'):
            with self.subTest(url=url):
                self.assertEqual(session.get(url, timeout=3).text, 'verified')

    def test_extra_ca_does_not_apply_to_other_hosts_or_prefix_lookalikes(self):
        session = self.start_server()
        for url in ('https://example.test/', 'https://www.tbank.ru.evil.test/'):
            with self.subTest(url=url), self.assertRaises(requests.exceptions.SSLError):
                session.get(url, timeout=3)

    def test_bank_still_rejects_hostname_mismatch(self):
        session = self.start_server('wrong-host.pem')
        with self.assertRaises(requests.exceptions.SSLError):
            session.get('https://www.tbank.ru/', timeout=3)

    def test_bank_still_rejects_unknown_self_signed_certificate(self):
        session = self.start_server('untrusted.pem')
        with self.assertRaises(requests.exceptions.SSLError):
            session.get('https://www.tbank.ru/', timeout=3)

    def test_explicit_ca_override_is_respected_after_successful_connection(self):
        session = self.start_server()
        self.assertEqual(session.get('https://www.tbank.ru/', timeout=3).status_code, 200)
        with self.assertRaises(requests.exceptions.SSLError):
            session.get('https://www.tbank.ru/', verify=requests.certs.where(), timeout=3)
