import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from antigravity_sessions import read_sessions
from app_config import VERSION
from session_monitor import SessionMonitor
from updates import RELEASE_URL, release_update, version_tuple

SID = '00000000-0000-4000-8000-000000000001'


class AntigravityTest(unittest.TestCase):
    def test_local_summary_tracks_activity_runs_archives_and_saved_favorites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with sqlite3.connect(root / 'conversation_summaries.db') as connection:
                connection.executescript('''
                    CREATE TABLE conversation_summaries (conversation_id TEXT, title TEXT, step_count INTEGER,
                    last_modified_time TEXT, workspace_uris TEXT, status TEXT, project_id TEXT,
                    parent_conversation_id TEXT, not_fully_idle INTEGER, killed INTEGER, last_user_input_time TEXT);
                    CREATE TABLE conversations_fts (conversation_id TEXT, archived INTEGER);
                ''')
                connection.execute('INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (SID, 'Example', 3, '2026-11-18T11:00:00+00:00', '["file:///example/project"]',
                     'CASCADE_RUN_STATUS_IDLE', 'project', '', 0, 0, '2026-11-18T10:00:00+00:00'))
            from datetime import datetime
            now = datetime.fromisoformat('2026-11-18T12:00:00+00:00').timestamp()
            row = read_sessions(now, root, live=False)[0]
            self.assertEqual(row['project'], 'project')
            self.assertEqual(row['status'], 'completed')
            self.assertIsNone(row['unread'])
            self.assertEqual(row['resumeCommand'], f'agy --conversation {SID}')
            self.assertEqual(read_sessions(now + 86400, root, live=False), [])
            self.assertEqual(len(read_sessions(now + 86400, root, [row['id']], live=False)), 1)
            with sqlite3.connect(root / 'conversation_summaries.db') as connection:
                connection.execute("UPDATE conversation_summaries SET status='CASCADE_RUN_STATUS_RUNNING',not_fully_idle=1")
            self.assertTrue(read_sessions(now + 86400, root, live=True)[0]['running'])
            self.assertIsNone(read_sessions(now, root, live=False)[0]['status'])
            with sqlite3.connect(root / 'conversation_summaries.db') as connection:
                connection.execute('INSERT INTO conversations_fts VALUES (?,1)', (SID,))
            self.assertEqual(read_sessions(now, root, [row['id']], live=True), [])


class UpdateTest(unittest.TestCase):
    def test_semver_and_only_expected_github_assets(self):
        version_tuple(VERSION)
        asset = 'Agent-Sessions-Windows-x64-Setup.exe'
        release = {'tag_name': 'v0.10.0', 'assets': [{'name': asset,
                   'browser_download_url': f'{RELEASE_URL}/download/v0.10.0/{asset}'}]}
        self.assertTrue(release_update(release, '0.9.0', 'win32')['available'])
        self.assertFalse(release_update(release, '0.10.0', 'win32')['available'])
        self.assertFalse(release_update({**release, 'prerelease': True}, '0.9.0', 'win32')['available'])
        self.assertFalse(release_update(release, '0.9.0', 'darwin', 'arm64')['available'])
        release['assets'][0]['browser_download_url'] = 'https://attacker.example/update.exe'
        self.assertFalse(release_update(release, '0.9.0', 'win32')['available'])
        with self.assertRaises(ValueError):
            version_tuple('0.10.0-beta')


class MonitorTest(unittest.TestCase):
    def test_all_sources_notify_once_new_includes_running_and_reviews_persist(self):
        for source in ('codex', 'claude', 'antigravity'):
            monitor = SessionMonitor()
            session = {'id': source + ':id', 'source': source, 'running': True, 'status': 'inProgress',
                       'turnId': 'one', 'startedAt': 90, 'endedAt': None, 'unread': None}
            snapshot = {'checkedAt': 100, 'sessions': [session], 'sourceErrors': {}}
            self.assertEqual(monitor.update(snapshot), [])
            self.assertEqual(monitor.new_sessions(snapshot), [session])
            completed = {**session, 'running': False, 'status': 'completed', 'endedAt': 102}
            snapshot = {**snapshot, 'checkedAt': 103, 'sessions': [completed]}
            self.assertEqual(monitor.update(snapshot), [completed])
            self.assertEqual(monitor.update(snapshot), [])
            self.assertEqual(monitor.new_sessions(snapshot), [completed])
            monitor.mark_reviewed(completed)
            restarted = SessionMonitor(json.loads(json.dumps(monitor.reviews)))
            self.assertEqual(restarted.new_sessions(snapshot), [])
            snapshot['sessions'] = [session]
            self.assertEqual(restarted.new_sessions(snapshot), [session])


if __name__ == '__main__':
    unittest.main()
