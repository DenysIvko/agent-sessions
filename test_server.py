import json
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from product_analytics import Analytics
from server import Handler, Snapshot, ThreadingHTTPServer, TIMEZONE, read_sessions


class SessionsTest(unittest.TestCase):
    def test_real_source_selection_and_status_transitions(self):
        now = datetime(2026, 11, 16, 12, tzinfo=TIMEZONE).timestamp()
        midnight = datetime(2026, 11, 16, tzinfo=TIMEZONE).timestamp()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.codex-global-state.json').write_text(json.dumps({
                'electron-thread-read-state-v1': {'unreadByIdentity': {
                    'one-account': {'local:mac': ['legacy', 'read', 'archived'], 'durable:remote': ['remote']}
                }},
                'local-projects': {'legacy-project': {'name': 'Shared name'}},
                'thread-project-assignments': {'read': {'projectId': 'legacy-project'}},
                'app-server-project-id-by-legacy-project-id-by-host': {
                    f'local:{root}': {'legacy-project': 'native-project'}
                },
            }))
            db = sqlite3.connect(root / 'state_5.sqlite')
            db.executescript('''
                CREATE TABLE threads(id TEXT, name TEXT, title TEXT, cwd TEXT, model TEXT,
                    source TEXT, thread_source TEXT, archived INTEGER, updated_at INTEGER,
                    git_branch TEXT, project_id TEXT);
                CREATE TABLE thread_read_receipts(thread_id TEXT, first_unread_turn TEXT);
                CREATE TABLE projects(id TEXT, name TEXT);
                CREATE TABLE project_roots(project_id TEXT, path TEXT);
                CREATE TABLE thread_spawn_edges(child_thread_id TEXT, parent_thread_id TEXT);
            ''')
            db.executemany('INSERT INTO projects VALUES (?, ?)',
                           [('native-project', 'Shared name'), ('different-project', 'Shared name')])
            db.execute("INSERT INTO project_roots VALUES ('native-project', '/project')")
            ids = ['running', 'stale', 'legacy', 'read', 'unread', 'archived', 'child', 'remote',
                   'old-unread', 'midnight', 'future', 'message', 'overnight', 'failed', 'stopped', 'other-source']
            for id in ids:
                db.execute('INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (id, '', id, '/project', 'model', 'exec' if id == 'other-source' else 'vscode',
                            'automation' if id == 'legacy' else 'user', int(id == 'archived'),
                            now, 'feature', None))
            db.execute("UPDATE threads SET project_id='native-project' WHERE id='running'")
            db.execute("UPDATE threads SET project_id='different-project' WHERE id='other-source'")
            db.execute("UPDATE threads SET cwd='/unassigned' WHERE id='midnight'")
            db.executemany('INSERT INTO thread_read_receipts VALUES (?, ?)',
                           [('read', None), ('unread', 'turn'), ('running', 'turn')]
                           + [(id, 'turn') for id in ['old-unread', 'midnight', 'future', 'message', 'overnight']])
            db.execute("INSERT INTO thread_spawn_edges VALUES ('child', 'running')")
            db.commit()
            db.close()
            history = sqlite3.connect(root / 'thread_history_1.sqlite')
            history.execute('CREATE TABLE thread_turns(thread_id TEXT, turn_id TEXT, status TEXT, started_at INTEGER, rollout_ordinal INTEGER, completed_at INTEGER)')
            history.execute('CREATE TABLE thread_items(thread_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, started_at_ms INTEGER, completed_at_ms INTEGER)')
            for id in ids:
                start = midnight - 1 if id in ['running', 'old-unread', 'message', 'overnight'] else now - 60
                if id == 'midnight':
                    start = midnight
                if id == 'future':
                    start = midnight + 86400
                status = 'inProgress' if id in ['running', 'stale', 'child'] else 'completed'
                if id in ['failed', 'stopped']:
                    status = 'failed' if id == 'failed' else 'interrupted'
                history.execute('INSERT INTO thread_turns VALUES (?, ?, ?, ?, ?, ?)',
                                (id, 'turn', status, start, 1,
                                 midnight + 1 if id == 'overnight' else None))
            history.execute("INSERT INTO thread_items VALUES ('message', 1, ?, NULL, NULL)", ((now - 10) * 1000,))
            history.commit()
            snapshot = read_sessions(root, {'running', 'child', 'read'}, now)
            sessions = {s['id']: s for s in snapshot['sessions']}
            self.assertEqual(snapshot['date'], '2026-11-16')
            # Local midnight is still the previous UTC date. Metadata-only updates
            # and tomorrow's timestamps must not pass the actual activity filter.
            self.assertEqual(set(sessions), {'running', 'stale', 'legacy', 'read', 'unread', 'remote',
                                            'midnight', 'message', 'overnight', 'failed', 'stopped', 'other-source'})
            self.assertTrue(sessions['running']['running'])
            self.assertTrue(sessions['running']['unread'])
            self.assertEqual(sessions['running']['agents'], 1)
            self.assertEqual(sessions['legacy']['kind'], 'Scheduled')
            self.assertFalse(sessions['read']['unread'])
            self.assertFalse(sessions['remote']['unread'])
            self.assertFalse(sessions['stale']['running'])
            self.assertEqual(sessions['read']['status'], 'completed')
            self.assertEqual(sessions['failed']['status'], 'failed')
            self.assertEqual(sessions['stopped']['status'], 'interrupted')
            self.assertEqual(sessions['overnight']['startedAt'], midnight - 1)
            self.assertEqual(sessions['overnight']['endedAt'], midnight + 1)
            self.assertIsNone(sessions['stale']['endedAt'])
            # Native, migrated, and workspace-root assignments share one identity.
            self.assertEqual(sessions['running']['projectId'], 'native-project')
            self.assertEqual(sessions['read']['projectId'], 'native-project')
            self.assertEqual(sessions['legacy']['projectId'], 'native-project')
            self.assertEqual(sessions['midnight']['projectId'], 'workspace:/unassigned')
            self.assertEqual(sessions['other-source']['project'], sessions['read']['project'])
            self.assertNotEqual(sessions['other-source']['projectId'], sessions['read']['projectId'])

            # A completed latest turn supersedes an old in-progress turn.
            history.execute("INSERT INTO thread_turns VALUES ('running','new-turn','completed',?,2,?)", (now - 5, now))
            history.commit()
            sessions = {s['id']: s for s in read_sessions(root, {'running', 'child'}, now)['sessions']}
            self.assertFalse(sessions['running']['running'])
            self.assertTrue(sessions['running']['unread'])
            # Reading a completed session changes its badge, not its inclusion.
            self.assertEqual(sessions['running']['startedAt'], now - 5)
            self.assertEqual(sessions['running']['endedAt'], now)
            self.assertEqual(sessions['running']['turnId'], 'new-turn')
            with closing(sqlite3.connect(root / 'state_5.sqlite')) as db, db:
                db.execute("UPDATE thread_read_receipts SET first_unread_turn=NULL WHERE thread_id='running'")
            after_read = {s['id']: s for s in read_sessions(root, {'running'}, now)['sessions']}
            self.assertIn('running', after_read)
            self.assertFalse(after_read['running']['running'])
            self.assertFalse(after_read['running']['unread'])
            self.assertEqual(after_read['running']['status'], 'completed')
            with closing(sqlite3.connect(root / 'state_5.sqlite')) as db, db:
                db.execute("UPDATE projects SET name='Renamed project' WHERE id='native-project'")
            renamed = {s['id']: s for s in read_sessions(root, set(), now)['sessions']}
            self.assertEqual(renamed['read']['project'], 'Renamed project')
            self.assertEqual(renamed['read']['projectId'], sessions['read']['projectId'])
            # The next calendar day rolls over without restarting the server.
            tomorrow = read_sessions(root, set(), midnight + 86400)
            self.assertEqual({s['id'] for s in tomorrow['sessions']}, {'future'})
            kept = {s['id']: s for s in read_sessions(root, set(), midnight + 86400,
                    include_ids={'read', 'old-unread', 'archived'})['sessions']}
            self.assertEqual(set(kept), {'future', 'read', 'old-unread'})
            self.assertFalse(kept['read']['isToday'])
            self.assertFalse(kept['old-unread']['isToday'])
            self.assertTrue(kept['future']['isToday'])
            history.close()

    def test_loopback_api_rejects_cross_origin_and_arbitrary_files(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.analytics = Analytics(demo=True)
        server.snapshot = Snapshot()
        server.snapshot.data = {'sessions': [], 'checkedAt': 123}
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/sessions') as response:
                self.assertEqual(json.load(response)['sessions'], [])
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            for path in ['/', '/?tutorial=1', '/app.js', '/styles.css', '/sessions.mjs', '/colors.mjs', '/tutorial.mjs',
                         '/vendor/color-hash-2.0.2/color-hash.mjs']:
                with urlopen(base + path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertGreater(len(response.read()), 0)
                    self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
            navigation = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
            for path in ['/', '/?tutorial=1']:
                with urlopen(Request(base + path, headers=navigation)) as response:
                    self.assertEqual(response.status, 200)
            for path, headers, status in [
                ('/api/sessions', navigation, 403),
                ('/api/sessions?tutorial=1', navigation, 403),
                ('/api/sessions', {'Host': 'attacker.example'}, 403),
                ('/api/sessions', {'Origin': 'https://attacker.example'}, 403),
                ('/api/sessions', {'Sec-Fetch-Site': 'cross-site'}, 403),
                ('/../../.codex/auth.json', {}, 404),
            ]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + path, headers=headers))
                self.assertEqual(error.exception.code, status)
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
