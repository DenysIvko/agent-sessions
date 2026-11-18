import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import Handler, Snapshot, ThreadingHTTPServer, read_session_ids, write_session_ids


class FavoritesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'favorites.json'
        self.snapshot = Snapshot(self.path)
        self.codex = {'id': 'codex-one', 'source': 'codex', 'isToday': True}
        self.claude = {'id': 'claude:terminal', 'source': 'claude', 'isToday': True}

    def refresh(self, snapshot=None, codex=None, claude=None):
        snapshot = snapshot or self.snapshot
        with patch('server.read_sessions', return_value={'sessions': [self.codex] if codex is None else codex}), \
                patch.object(snapshot.claude, 'read', return_value=[self.claude] if claude is None else claude):
            return snapshot.refresh_once()

    def test_flags_survive_restart_and_day_rollover_without_expanding_today(self):
        self.refresh()
        for row in [self.codex, self.claude]:
            self.snapshot.set_favorite(row['id'], True)
        self.assertEqual(read_session_ids(self.path), {'codex-one', 'claude:terminal'})
        self.assertTrue(all(s['favorite'] for s in self.snapshot.data['sessions']))
        self.codex['isToday'] = self.claude['isToday'] = False
        restarted = Snapshot(self.path)
        data = self.refresh(restarted)
        self.assertEqual(data['sessions'], [])
        self.assertEqual({s['id'] for s in data['favoriteSessions']}, {'codex-one', 'claude:terminal'})
        restarted.set_favorite('codex-one', False)
        self.assertEqual(read_session_ids(self.path), {'claude:terminal'})
        self.assertEqual([s['id'] for s in restarted.data['favoriteSessions']], ['claude:terminal'])
        # Sources omit archived rows even if their IDs remain in the flags file.
        self.assertEqual(self.refresh(restarted, codex=[], claude=[])['favoriteSessions'], [])

    def test_imported_claude_favorite_can_be_removed_by_its_desktop_id(self):
        write_session_ids(self.path, {'claude:terminal'})
        desktop = {**self.claude, 'id': 'claude:desktop', 'isToday': False, 'relatedIds': ['claude:terminal']}
        data = self.refresh(claude=[desktop])
        self.assertEqual([s['id'] for s in data['favoriteSessions']], ['claude:desktop'])
        self.snapshot.set_favorite('claude:desktop', False)
        self.assertEqual(read_session_ids(self.path), set())
        self.assertEqual(self.snapshot.data['favoriteSessions'], [])

    def test_reader_failure_keeps_old_favorites_and_corruption_does_not_overwrite_flags(self):
        self.refresh()
        self.snapshot.set_favorite('codex-one', True)
        self.codex['isToday'] = False
        self.refresh()
        with patch('server.read_sessions', side_effect=OSError('fixture')), \
                patch.object(self.snapshot.claude, 'read', return_value=[]):
            data = self.snapshot.refresh_once()
        self.assertEqual(data['sessions'], [])
        self.assertEqual([s['id'] for s in data['favoriteSessions']], ['codex-one'])
        self.path.write_text('{partial')
        data = self.refresh()
        self.assertIn('Favorites could not be loaded', data['error'])
        self.assertTrue(data['favoriteSessions'][0]['favorite'])
        with self.assertRaises(ValueError):
            self.snapshot.set_favorite('codex-one', False)
        self.assertEqual(self.path.read_text(), '{partial')

    def test_failed_atomic_write_preserves_existing_file_and_cleans_up(self):
        write_session_ids(self.path, {'existing'})
        with patch('server.os.fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                write_session_ids(self.path, {'replacement'})
        self.assertEqual(read_session_ids(self.path), {'existing'})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_favorite_api_validates_and_shares_state_without_source_actions(self):
        self.refresh()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.snapshot = self.snapshot
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'

        def request(payload, headers=None):
            return Request(base + '/api/favorite', data=json.dumps(payload).encode(), headers={
                'Content-Type': 'application/json', 'X-Session-Dashboard': '1', **(headers or {})})

        try:
            with patch('server.archive_session') as archive:
                for payload, headers, status in [
                    ({'id': 'codex-one', 'favorite': True}, {'Origin': 'https://attacker.example'}, 403),
                    ({'id': 'codex-one', 'favorite': True}, {'Sec-Fetch-Site': 'cross-site'}, 403),
                    ({'id': 'codex-one', 'favorite': True}, {'X-Session-Dashboard': ''}, 403),
                    ({'id': 'unknown', 'favorite': True}, {}, 400),
                    ({'id': 'codex-one', 'favorite': 'true'}, {}, 400),
                    ({'id': 'codex-one', 'favorite': 1}, {}, 400),
                    ({'id': 'codex-one'}, {}, 400),
                ]:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request(payload, headers))
                    self.assertEqual(error.exception.code, status)
                    error.exception.close()
                self.assertFalse(self.path.exists())
                for enabled in [True, False]:
                    with urlopen(request({'id': 'codex-one', 'favorite': enabled})) as response:
                        self.assertEqual(json.load(response), {'favorite': enabled})
                    with urlopen(base + '/api/sessions') as response:
                        data = json.load(response)
                    self.assertEqual(data['sessions'][0]['favorite'], enabled)
                    self.assertEqual(len(data['favoriteSessions']), int(enabled))
                archive.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
