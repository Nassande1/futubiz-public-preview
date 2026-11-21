import os
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
import server

class LimitTests(unittest.TestCase):
    def setUp(self):
        self.app = server.make_server('127.0.0.1', 0, Path(__file__).parent / 'public')
        self.app.trust_render_proxy = False
        self.thread = threading.Thread(target=self.app.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.app.shutdown()
        self.app.server_close()
        self.thread.join()

    def request(self, path='/', headers=None):
        c = HTTPConnection('127.0.0.1', self.app.server_port, timeout=3)
        try:
            c.request('GET', path, headers=headers or {})
            r = c.getresponse(); status = r.status; r.read()
            return status
        finally:
            c.close()

    def test_client_limit_and_spoofed_forwarded_headers(self):
        with patch.object(server, 'CLIENT_LIMIT', 3):
            for i in range(3):
                self.assertEqual(self.request(headers={'X-Forwarded-For': f'1.1.1.{i}', 'CF-Connecting-IP': f'2.2.2.{i}'}), 200)
            self.assertEqual(self.request(headers={'X-Forwarded-For': '8.8.8.8'}), 429)

    def test_render_keys_separate_clients_and_missing_fails_closed(self):
        self.app.trust_render_proxy = True
        with patch.object(server, 'CLIENT_LIMIT', 1):
            self.assertEqual(self.request(headers={'CF-Connecting-IP': '1.1.1.1'}), 200)
            self.assertEqual(self.request(headers={'CF-Connecting-IP': '1.1.1.1'}), 429)
            self.assertEqual(self.request(headers={'CF-Connecting-IP': '8.8.8.8'}), 200)
            self.assertEqual(self.request(), 200)
            self.assertEqual(self.request(headers={'CF-Connecting-IP': 'invalid'}), 429)

    def test_client_quote_limit(self):
        with patch.object(server, 'CLIENT_QUOTE_LIMIT', 2), patch.object(server, 'load_quotes', return_value=[]):
            self.assertEqual(self.request('/api/quotes'), 200)
            self.assertEqual(self.request('/api/quotes'), 200)
            self.assertEqual(self.request('/api/quotes'), 429)
            self.assertEqual(self.request('/'), 200)

    def test_global_upstream_limit(self):
        with patch.object(server, 'GLOBAL_QUOTE_LIMIT', 2), patch.object(server, 'load_quotes', return_value=[]):
            self.assertEqual(self.request('/api/quotes'), 200)
            self.assertEqual(self.request('/api/quotes'), 200)
            self.assertEqual(self.request('/api/quotes'), 503)

    def test_upstream_slots_and_release(self):
        for _ in range(server.MAX_UPSTREAM_INFLIGHT):
            self.assertTrue(self.app.limits.upstream.acquire(False))
        try:
            with patch.object(server, 'load_quotes') as loader:
                self.assertEqual(self.request('/api/quotes'), 503)
                loader.assert_not_called()
        finally:
            for _ in range(server.MAX_UPSTREAM_INFLIGHT): self.app.limits.upstream.release()
        with patch.object(server, 'load_quotes', return_value=[]):
            self.assertEqual(self.request('/api/quotes'), 200)

    def test_bucket_capacity_and_expiration(self):
        limits = server.Limits()
        with patch.object(server, 'MAX_CLIENTS', 1), patch.object(server.time, 'monotonic', return_value=100):
            self.assertTrue(limits.client('a'))
            self.assertFalse(limits.client('b'))
        with patch.object(server.time, 'monotonic', return_value=161):
            self.assertTrue(limits.client('b'))

    def test_connection_slots_bound(self):
        for _ in range(server.MAX_CONNECTIONS):
            self.assertTrue(self.app.connections.acquire(False))
        try:
            self.assertFalse(self.app.connections.acquire(False))
        finally:
            for _ in range(server.MAX_CONNECTIONS): self.app.connections.release()

if __name__ == '__main__': unittest.main()
