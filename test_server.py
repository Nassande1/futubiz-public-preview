import json
import socket
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import server

QUOTE = {"symbol": "volatility_100", "label": "Volatility 100", "asset_class": "synthetic", "price": 1031.47, "precision": 2, "extra": "discarded"}

class Upstream(BaseHTTPRequestHandler):
    body = b'{}'
    status = 200
    headers = {}
    def do_GET(self):
        self.send_response(self.status)
        for key, value in self.headers.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(self.body)
        except BrokenPipeError:
            pass
    def log_message(self, *args): pass

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.app = server.make_server('127.0.0.1', 0, Path(__file__).parent / 'public')
        cls.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (cls.up, cls.app)]
        for t in cls.threads: t.start()
        cls.old_url = server.QUOTES_URL
        server.QUOTES_URL = f'http://127.0.0.1:{cls.up.server_port}/api/v1/quotes'

    @classmethod
    def tearDownClass(cls):
        server.QUOTES_URL = cls.old_url
        for s in (cls.up, cls.app): s.shutdown(); s.server_close()
        for t in cls.threads: t.join()

    def setUp(self):
        Upstream.status, Upstream.headers = 200, {}
        Upstream.body = json.dumps({'quotes': [QUOTE]}).encode()

    def request(self, path='/api/quotes', method='GET'):
        c = HTTPConnection('127.0.0.1', self.app.server_port, timeout=3)
        c.request(method, path)
        r = c.getresponse()
        body, headers, status = r.read(), dict(r.getheaders()), r.status
        c.close()
        return status, headers, body

    def test_success_and_filtered_fields(self):
        status, h, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['quotes'], [{k:v for k,v in QUOTE.items() if k != 'extra'}])
        self.assertEqual(h['Cache-Control'], 'no-store')
        self.assertEqual(h['X-Content-Type-Options'], 'nosniff')
        self.assertNotIn('Access-Control-Allow-Origin', h)

    def test_empty_list(self):
        Upstream.body = b'{"quotes":[]}'
        self.assertEqual(json.loads(self.request()[2])['quotes'], [])

    def test_bad_data_rejected(self):
        for raw in (b'not-json', b'{"quotes":[{}]}', b'{"quotes":[{"price":NaN}]}', b'{"quotes":{}}'):
            with self.subTest(raw=raw):
                Upstream.body = raw
                self.assertEqual(self.request()[0], 502)

    def test_limits(self):
        for body in (b' ' * (server.MAX_UPSTREAM_BYTES + 1), json.dumps({'quotes': [QUOTE] * (server.MAX_QUOTES + 1)}).encode(), json.dumps({'quotes': [dict(QUOTE, label='x' * 201)]}).encode()):
            with self.subTest(size=len(body)):
                Upstream.body = body
                self.assertEqual(self.request()[0], 502)

    def test_upstream_failure_and_redirect(self):
        Upstream.status = 503
        self.assertEqual(self.request()[0], 502)
        Upstream.status = 302
        Upstream.headers = {'Location': 'http://127.0.0.1:1/'}
        self.assertEqual(self.request()[0], 502)

    def test_timeout(self):
        with patch.object(server, 'load_quotes', side_effect=socket.timeout()):
            status, _, body = self.request()
            self.assertEqual(status, 504)
            self.assertIn('timed out', json.loads(body)['error'])

    def test_page_assets_traversal_and_method(self):
        status, headers, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'PRACTICE TERMINAL', body)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('/app.js')[0], 200)
        self.assertEqual(self.request('/%2e%2e/server.py')[0], 404)
        self.assertEqual(self.request('/api/quotes?foo=bar')[0], 400)
        self.assertEqual(self.request('/api/unknown')[0], 404)
        self.assertEqual(self.request('/api/quotes', 'POST')[0], 405)

if __name__ == '__main__': unittest.main()
