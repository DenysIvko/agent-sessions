import json
from pathlib import Path
import subprocess
import threading
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from product_analytics import Analytics
from server import Handler, Snapshot, ThreadingHTTPServer, read_session_ids, write_session_ids
from session_actions import archive_session

SID = '00000000-0000-4000-8000-000000000001'


class ActionsTest(unittest.TestCase):
    def test_codex_uses_source_command_and_reports_failure(self):
        session = {'id': SID, 'source': 'codex', 'running': False}
        with patch('session_actions.shutil.which', return_value='/bin/codex'), patch('session_actions.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '', '')
            self.assertEqual(archive_session(session), 'Archived in Codex.')
            self.assertEqual(run.call_args.args[0], ['/bin/codex', 'archive', SID])
            run.return_value = subprocess.CompletedProcess([], 1, '', 'source refused')
            with self.assertRaisesRegex(RuntimeError, 'source refused'):
                archive_session(session)
            run.reset_mock()
            for bad in [{**session, 'running': True}, {**session, 'agents': 1}, {**session, 'id': '../other'}]:
                with self.assertRaises(ValueError):
                    archive_session(bad)
            run.assert_not_called()

    def test_claude_delegates_to_native_archive_and_preserves_permission_error(self):
        with patch('session_actions.sys.platform', 'darwin'), patch.object(Path, 'is_file', return_value=True), patch('session_actions.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'message': 'Archived in Claude Code.'}), '')
            self.assertEqual(archive_session({'source': 'claude', 'id': 'claude:' + SID}), 'Archived in Claude Code.')
            self.assertEqual(run.call_args.args[0][-2:], ['--archive-claude', SID])
            run.return_value.stdout = json.dumps({'ok': False, 'message': 'Accessibility access is required.'})
            with self.assertRaisesRegex(RuntimeError, 'Accessibility'):
                archive_session({'source': 'claude', 'id': 'claude:local_' + SID})

    def start_server(self, sessions, source_errors=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.analytics = Analytics(demo=True)
        server.snapshot = Snapshot(Path(directory.name) / 'favorites.json')
        server.snapshot.data = {'sessions': sessions, 'sourceErrors': source_errors or {}}
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def close():
            server.shutdown()
            server.server_close()
            worker.join()
        self.addCleanup(close)
        self.snapshot = server.snapshot
        self.base = f'http://127.0.0.1:{server.server_port}'

    def request(self, payload, headers=None):
        return Request(self.base + '/api/archive', data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json', 'X-Session-Dashboard': '1', **(headers or {})})

    def test_archive_api_blocks_cross_site_unknown_and_invalid_targets(self):
        self.start_server([{'id': SID, 'source': 'codex', 'running': False}])
        with patch('server.archive_session') as archive:
            for payload, headers, status in [
                ({'id': SID}, {'Origin': 'https://attacker.example'}, 403),
                ({'id': SID}, {'Host': 'attacker.example'}, 403),
                ({'id': SID}, {'Sec-Fetch-Site': 'cross-site'}, 403),
                ({'id': SID}, {'X-Session-Dashboard': ''}, 403),
                ({'id': SID}, {'Content-Type': 'text/plain'}, 403),
                ({'id': 'unknown'}, {}, 400), ([], {}, 400), ({'id': 3}, {}, 400),
                ({'id': 'x' * 600}, {}, 400),
            ]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(self.request(payload, headers))
                self.assertEqual(error.exception.code, status)
                error.exception.close()
            archive.assert_not_called()
        self.assertFalse(self.snapshot.archives_path.exists())

    def test_source_failures_still_succeed_locally_without_waiting_for_either_source(self):
        sessions = [{'id': SID, 'source': 'codex'}, {'id': 'claude:' + SID, 'source': 'claude'}]
        self.start_server(sessions)
        for session in sessions:
            with self.subTest(source=session['source']):
                started, release = threading.Event(), threading.Event()
                def fail(_):
                    started.set()
                    release.wait(3)
                    raise RuntimeError('source refused')
                with patch('server.archive_session', side_effect=fail) as archive:
                    try:
                        with urlopen(self.request({'id': session['id']}), timeout=1) as response:
                            self.assertEqual(json.load(response), {'message': 'Archived in Agent Sessions.'})
                        self.assertTrue(started.wait(1))
                        with urlopen(self.base + '/api/sessions') as response:
                            self.assertNotIn(session['id'], [s['id'] for s in json.load(response)['sessions']])
                        self.assertIn(session['id'], read_session_ids(self.snapshot.archives_path))
                        # Repeated clicks must not launch another source action.
                        with urlopen(self.request({'id': session['id']})) as response:
                            self.assertEqual(response.status, 200)
                    finally:
                        release.set()
                        with self.snapshot.archive_lock:
                            pass
                    archive.assert_called_once_with(session)

    def test_running_child_agents_and_offline_sources_can_be_hidden_without_source_actions(self):
        sessions = [{'id': 'running', 'source': 'codex', 'running': True},
                    {'id': 'children', 'source': 'codex', 'agents': 1},
                    {'id': 'offline', 'source': 'claude'}]
        self.start_server(sessions, {'claude': 'unavailable'})
        with patch('server.archive_session') as archive:
            for session in sessions:
                with urlopen(self.request({'id': session['id']})) as response:
                    self.assertEqual(response.status, 200)
            archive.assert_not_called()
        self.assertEqual(self.snapshot.data['sessions'], [])
        self.assertEqual(read_session_ids(self.snapshot.archives_path), {'running', 'children', 'offline'})

    def test_local_archives_survive_restart_refresh_and_claude_id_changes_including_favorites(self):
        session = {'id': 'claude:desktop', 'source': 'claude', 'relatedIds': ['claude:terminal'], 'running': True}
        self.start_server([session])
        write_session_ids(self.snapshot.favorites_path, {'claude:terminal'})
        self.snapshot.data['favoriteSessions'] = [session]
        self.snapshot.archive(session['id'])
        self.assertEqual(self.snapshot.data['favoriteSessions'], [])
        restarted = Snapshot(self.snapshot.favorites_path)
        imported = {**session, 'id': 'claude:new-desktop', 'running': False}
        for row in [session, imported, {'id': 'claude:terminal', 'source': 'claude', 'isToday': False}]:
            with patch('server.read_sessions', return_value={'sessions': []}), \
                    patch.object(restarted.claude, 'read', return_value=[row]):
                data = restarted.refresh_once()
            self.assertEqual(data['sessions'], [])
            self.assertEqual(data['favoriteSessions'], [])

    def test_local_write_failure_keeps_session_and_does_not_attempt_source_archive(self):
        session = {'id': SID, 'source': 'codex'}
        self.start_server([session])
        with patch('server.write_session_ids', side_effect=OSError('disk full')), patch('server.archive_session') as archive:
            with self.assertRaises(HTTPError) as error:
                urlopen(self.request({'id': SID}))
            self.assertIn('disk full', error.exception.read().decode())
            error.exception.close()
            archive.assert_not_called()
        self.assertEqual(self.snapshot.data['sessions'], [session])
        self.assertFalse(self.snapshot.archives_path.exists())


if __name__ == '__main__':
    unittest.main()
