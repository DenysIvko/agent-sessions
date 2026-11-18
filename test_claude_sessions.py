from datetime import datetime
import json
import shlex
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_sessions import ClaudeSessions, TIMEZONE, live_sessions
from server import Snapshot


class ClaudeSessionsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'claude'
        self.desktop = Path(self.directory.name) / 'desktop'
        self.reader = ClaudeSessions(self.root, self.desktop)
        self.now = datetime(2026, 11, 16, 12, tzinfo=TIMEZONE).timestamp()
        self.midnight = datetime(2026, 11, 16, tzinfo=TIMEZONE).timestamp()

    def sid(self, number):
        return f'00000000-0000-4000-8000-{number:012d}'

    def transcript(self, number, rows):
        path = self.root / 'projects' / 'project' / f'{self.sid(number)}.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
        return path

    def user(self, at, **extra):
        return {'type': 'user', 'timestamp': datetime.fromtimestamp(at, TIMEZONE).isoformat(),
                'cwd': '/projects/example', 'gitBranch': 'feat/example', 'isSidechain': False,
                'message': {'content': 'Build the session dashboard'}, **extra}

    def assistant(self, at, stop='end_turn'):
        return {'type': 'assistant', 'timestamp': datetime.fromtimestamp(at, TIMEZONE).isoformat(),
                'message': {'model': 'claude-model', 'stop_reason': stop, 'content': [{'type': 'text', 'text': 'Done'}]}}

    def index(self, number, **extra):
        row = {'sessionId': f'local_{self.sid(number)}', 'cliSessionId': self.sid(number),
               'createdAt': (self.now - 300) * 1000, 'lastActivityAt': (self.now - 60) * 1000,
               'cwd': '/projects/example', 'title': 'Desktop session', 'isArchived': False, **extra}
        path = self.desktop / 'account' / f'local_{self.sid(number)}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row))
        return row

    def read(self, **kwargs):
        return self.reader.read(self.now, live=kwargs.pop('live', (set(), set())), **kwargs)

    def test_old_favorites_follow_desktop_imports_and_stay_hidden_when_archived(self):
        old = self.midnight - 100
        for number in [1, 2, 3, 4]:
            self.transcript(number, [self.user(old), self.assistant(old + 1)])
        self.index(2, createdAt=old * 1000, lastActivityAt=(old + 1) * 1000, priorCliSessionIds=[self.sid(3)])
        self.index(4, createdAt=old * 1000, lastActivityAt=(old + 1) * 1000, isArchived=True)
        self.assertEqual(self.read(), [])
        rows = self.read(include_ids={f'claude:{self.sid(n)}' for n in [1, 3, 4]})
        self.assertEqual({s['sessionId'] for s in rows}, {self.sid(1), f'local_{self.sid(2)}'})
        self.assertTrue(all(not s['isToday'] for s in rows))
        desktop = next(s for s in rows if s['sessionId'].startswith('local_'))
        self.assertIn(f'claude:{self.sid(3)}', desktop['relatedIds'])

    def test_today_is_real_activity_including_older_and_new_sessions(self):
        self.transcript(1, [self.user(self.midnight - 10, message={'content': 'Build caf\u00e9 dashboard'}), self.assistant(self.now - 1)])
        self.transcript(2, [self.user(self.midnight - 10), {'type': 'custom-title', 'customTitle': 'Rename today'}])
        self.transcript(3, [self.user(self.midnight)])
        self.transcript(4, [self.user(self.midnight + 86400)])
        self.transcript(5, [self.user(self.now, isSidechain=True)])
        self.index(6, createdAt=self.now * 1000, lastActivityAt=0)
        self.index(7, createdAt=(self.midnight - 20) * 1000,
                   lastActivityAt=(self.midnight - 10) * 1000, lastFocusedAt=self.now * 1000)
        sessions = {s['sessionId']: s for s in self.read()}
        self.assertEqual(set(sessions), {self.sid(1), self.sid(3), f'local_{self.sid(6)}'})
        self.assertEqual(sessions[self.sid(1)]['title'], 'Build caf\u00e9 dashboard')
        self.assertEqual(sessions[self.sid(1)]['status'], 'completed')
        self.assertIsNone(sessions[self.sid(1)]['unread'])
        self.assertEqual(sessions[self.sid(1)]['source'], 'claude')
        self.assertEqual(sessions[self.sid(1)]['branch'], 'feat/example')
        self.assertIn('claude --resume', sessions[self.sid(1)]['resumeCommand'])
        self.assertEqual(sessions[self.sid(1)]['url'], f'claude://resume?session={self.sid(1)}')
        self.assertNotIn('message', sessions[self.sid(1)])

    def test_desktop_archive_and_prior_ids_prevent_duplicates(self):
        for number in [1, 2, 3, 4]:
            self.transcript(number, [self.user(self.now - 30), self.assistant(self.now - 1)])
        self.index(1, isArchived=True, priorCliSessionIds=[self.sid(2)])
        self.index(3, priorCliSessionIds=[self.sid(4)])
        sessions = self.read()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['sessionId'], f'local_{self.sid(3)}')
        self.assertEqual(sessions[0]['title'], 'Desktop session')
        self.assertEqual(sessions[0]['url'], f'claude://epitaxy/local_{self.sid(3)}')

    def test_terminal_archive_marker_overrides_today_and_favorites_and_can_be_restored(self):
        path = self.transcript(1, [self.user(self.now - 30), self.assistant(self.now - 1)])
        self.assertEqual(len(self.read()), 1)
        marker = path.parent / path.stem / 'archived.json'
        marker.parent.mkdir()
        marker.write_text(json.dumps({'archived': True, 'by': 'sdk'}))
        self.assertEqual(self.read(include_ids={f'claude:{self.sid(1)}'}), [])
        marker.write_text(json.dumps({'archived': False, 'by': 'sdk'}))
        self.assertEqual(len(self.read()), 1)

    def test_loaded_completed_session_is_not_running_but_pending_overnight_is(self):
        self.transcript(1, [self.user(self.midnight - 30)])
        self.transcript(2, [self.user(self.now - 30), self.assistant(self.now - 1)])
        self.transcript(3, [self.user(self.now - 30)])
        sessions = {s['sessionId']: s for s in self.read(live=(set(), {self.sid(1), self.sid(2)}))}
        self.assertTrue(sessions[self.sid(1)]['running'])
        self.assertEqual(sessions[self.sid(1)]['activityAt'], self.now)
        self.assertFalse(sessions[self.sid(2)]['running'])
        self.assertFalse(sessions[self.sid(3)]['running'])

    def test_cache_reuses_unchanged_files_and_recovers_from_partial_append(self):
        path = self.transcript(1, [self.user(self.now - 60)])
        with path.open('a') as stream:
            stream.write('{"type":')
        self.assertEqual(len(self.read()), 1)
        with patch('claude_sessions.read_transcript', side_effect=AssertionError('Unchanged file reread')):
            self.assertEqual(len(self.read()), 1)
        self.transcript(1, [self.user(self.now - 60), self.assistant(self.now)])
        self.assertEqual(self.read()[0]['endedAt'], self.now)
        path.unlink()
        self.assertEqual(self.read(), [])
        self.assertEqual(self.reader.cache, {})

    def test_midnight_rollover_and_missing_install(self):
        self.assertEqual(self.read(), [])
        self.transcript(1, [self.user(self.now), self.assistant(self.now + 1)])
        self.assertEqual(len(self.read()), 1)
        self.assertEqual(self.reader.read(self.midnight + 86400, live=(set(), set())), [])

    def test_resume_command_quotes_workspace_paths(self):
        cwd = "/projects/a user's workspace"
        self.transcript(1, [self.user(self.now, cwd=cwd)])
        command = self.read()[0]['resumeCommand']
        self.assertEqual(shlex.split(command), ['cd', cwd, '&&', 'claude', '--resume', self.sid(1)])

    def test_unknown_message_format_reports_a_source_error(self):
        self.transcript(1, [self.user(self.now, message=['unsupported'])])
        with self.assertRaisesRegex(ValueError, 'Unexpected Claude message format'):
            self.read()

    def test_api_error_is_a_failure_even_with_a_normal_stop_reason(self):
        failed = self.assistant(self.now, stop='stop_sequence')
        failed['isApiErrorMessage'] = True
        failed['message']['model'] = '<synthetic>'
        self.transcript(1, [self.user(self.now - 2), failed,
            {'type': 'system', 'subtype': 'stop_hook_summary',
             'timestamp': datetime.fromtimestamp(self.now + 1, TIMEZONE).isoformat()}])
        self.index(1, completedTurns=1, lastTurnEdgeAt=(self.now + 2) * 1000)
        session = self.read()[0]
        self.assertEqual(session['status'], 'failed')
        self.assertFalse(session['running'])
        self.assertEqual(session['model'], '')

    def test_live_registry_requires_a_matching_claude_process(self):
        registry = self.root / 'sessions'
        registry.mkdir(parents=True)
        (registry / '101.json').write_text(json.dumps({'pid': 101, 'sessionId': self.sid(1), 'status': 'busy'}))
        (registry / '102.json').write_text(json.dumps({'pid': 102, 'sessionId': self.sid(2), 'status': 'busy'}))
        from subprocess import CompletedProcess
        with patch('claude_sessions.sys.platform', 'darwin'), patch('claude_sessions.subprocess.run', side_effect=[
            CompletedProcess([], 0, stdout='101 /home/example/.local/bin/claude\n102 /usr/bin/python3\n'),
            CompletedProcess([], 0, stdout=f'n{self.root}/projects/project/{self.sid(1)}.jsonl\n'),
        ]):
            busy, loaded = live_sessions(self.root)
        self.assertEqual(busy, {self.sid(1)})
        self.assertEqual(loaded, {self.sid(1)})

    def test_one_source_failure_keeps_the_other_live_and_preserves_last_data(self):
        snapshot = Snapshot(Path(self.directory.name) / 'favorites.json')
        old_claude = {'id': 'claude:old', 'source': 'claude', 'favorite': False}
        snapshot.data = {'sessions': [old_claude]}
        codex = {'id': 'codex-new', 'source': 'codex', 'favorite': False}
        with patch('server.read_sessions', return_value={'sessions': [codex]}), \
                patch.object(snapshot.claude, 'read', side_effect=OSError('fixture failure')):
            result = snapshot.refresh_once(self.now)
        self.assertEqual(result['sessions'], [codex, old_claude])
        self.assertIn('Claude Code unavailable', result['error'])
        self.assertEqual(set(result['sourceErrors']), {'claude'})
        self.assertEqual(result['service'], 'agent-sessions')
        new_claude = {'id': 'claude:new', 'source': 'claude', 'favorite': False}
        with patch('server.read_sessions', side_effect=OSError('fixture failure')), \
                patch.object(snapshot.claude, 'read', return_value=[new_claude]):
            result = snapshot.refresh_once(self.now)
        self.assertEqual(result['sessions'], [codex, new_claude])
        self.assertIn('Codex unavailable', result['error'])
        self.assertEqual(set(result['sourceErrors']), {'codex'})


if __name__ == '__main__':
    unittest.main()
