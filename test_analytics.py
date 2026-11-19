import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from product_analytics import Analytics, EVENTS, FILTER_SELECTIONS, validate_event
from server import Handler, Snapshot, ThreadingHTTPServer

CONFIG = {'key': 'phc_fixture', 'host': 'https://eu.i.posthog.com'}


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'analytics.json'

    def analytics(self, **kwargs):
        analytics = Analytics(path=self.path, config=CONFIG, **kwargs)
        self.addCleanup(analytics.close)
        return analytics

    def test_default_on_preference_and_random_identity_survive_restart(self):
        first = self.analytics()
        self.assertEqual(first.status(), {'enabled': True, 'configured': True, 'demo': False})
        first.set_enabled(False)
        second = self.analytics()
        self.assertFalse(second.status()['enabled'])
        self.assertEqual(first.installation_id, second.installation_id)
        with patch('product_analytics.os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                second.set_enabled(True)
        self.assertFalse(second.status()['enabled'])
        self.assertFalse(self.analytics().status()['enabled'])
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)
        self.path.write_text('{broken')
        self.assertFalse(self.analytics().status()['enabled'])

    def test_disabled_demo_and_unconfigured_never_initialize_sdk(self):
        disabled = self.analytics()
        disabled.set_enabled(False)
        demo = self.analytics(demo=True)
        unconfigured = Analytics(path=self.path, config={})
        with patch('posthog.Posthog') as sdk:
            for analytics in [disabled, demo, unconfigured]:
                analytics.capture('dashboard_opened', {'surface': 'web'})
                self.assertIsNone(analytics.worker)
            sdk.assert_not_called()

    def test_event_contract_rejects_private_text_and_unknown_properties(self):
        for event, properties in [
            ('private title', {'surface': 'web'}),
            ('dashboard_opened', {'surface': 'web', 'path': '/private/project'}),
            ('filter_used', {'surface': 'web', 'filter': 'private search'}),
            ('session_archived', {'surface': 'web', 'source': {'title': 'private'}}),
            ('favorite_changed', {'surface': 'tray', 'source': 'codex', 'enabled': 1}),
            ('tutorial_dismissed', {'surface': 'web', 'step': True}),
            ('filter_used', {'surface': 'web', 'filter': 'project', 'selection': '/private/project'}),
            ('filter_used', {'surface': 'web', 'filter': 'search', 'selection': 'codex'}),
            ('action_failed', {'surface': 'tray', 'source': 'codex', 'action': 'archive', 'reason': 'secret error'}),
            ('source_status_changed', {'surface': 'backend', 'source': 'claude', 'status': 'error', 'path': '/private'}),
        ]:
            with self.subTest(event=event), self.assertRaises(ValueError):
                validate_event(event, properties)

    def test_every_event_and_filter_choice_accepts_only_its_declared_properties(self):
        for event, schema in EVENTS.items():
            props = {key: False if allowed is bool else next(iter(allowed)) for key, allowed in schema.items()}
            props['surface'] = 'web'
            if event == 'filter_used':
                props['selection'] = next(iter(FILTER_SELECTIONS[props['filter']]))
            with self.subTest(event=event):
                validate_event(event, props)
                with self.assertRaises(ValueError):
                    validate_event(event, {**props, 'session_id': 'private'})
                for key in props:
                    with self.assertRaises(ValueError):
                        validate_event(event, {k: v for k, v in props.items() if k != key})
        for kind, choices in FILTER_SELECTIONS.items():
            for selection in choices:
                validate_event('filter_used', {'surface': 'web', 'filter': kind, 'selection': selection})

    def test_source_health_tracks_initial_state_and_changes_not_polls_or_private_errors(self):
        capture = Mock(side_effect=validate_event)
        snapshot = Snapshot(Path(self.directory.name) / 'favorites.json', analytics=Mock(capture=capture))
        row = {'id': 'private-session', 'source': 'codex', 'title': 'private title'}
        with (patch('server.read_sessions', return_value={'sessions': [row]}) as codex,
              patch.object(snapshot.claude, 'read', return_value=[]),
              patch('server.read_antigravity_sessions', return_value=[]), patch('builtins.print')):
            snapshot.refresh_once()
            snapshot.refresh_once()
            self.assertEqual(capture.call_count, 3)
            codex.side_effect = OSError('/private/path with credentials')
            snapshot.refresh_once()
            snapshot.refresh_once()
            self.assertEqual(capture.call_count, 4)
            codex.side_effect = None
            snapshot.refresh_once()
            self.assertEqual(capture.call_count, 5)
        self.assertEqual([call.args[1]['status'] for call in capture.call_args_list],
                         ['data', 'empty', 'empty', 'error', 'data'])
        self.assertNotIn('private', str(capture.call_args_list))

    def test_source_archive_reports_background_outcomes_and_keeps_local_hide(self):
        capture = Mock(side_effect=validate_event)
        snapshot = Snapshot(Path(self.directory.name) / 'favorites.json', analytics=Mock(capture=capture))
        row = {'id': 'private-session', 'source': 'codex', 'title': 'private title'}
        with patch('server.archive_session') as archive, patch('builtins.print'):
            snapshot._archive_in_source(row)
            archive.side_effect = RuntimeError('private credentials in error')
            snapshot._archive_in_source(row)
        self.assertEqual([c.args[1]['result'] for c in capture.call_args_list], ['completed', 'failed'])
        for index, (extra, result) in enumerate([
            ({'running': True}, 'skipped_running'),
            ({'source': 'antigravity'}, 'unsupported'),
            ({}, 'skipped_unavailable'),
        ]):
            session = {**row, **extra, 'id': str(index)}
            snapshot.data = {'sessions': [session], 'sourceErrors': {'codex': 'private failure'}}
            snapshot.archive(session['id'])
            self.assertEqual(snapshot.data['sessions'], [])
            self.assertEqual(capture.call_args.args[1]['result'], result)
        self.assertNotIn('private', str(capture.call_args_list))

    def test_actual_sdk_wire_payload_strips_context_and_disables_person_processing(self):
        analytics = self.analytics()
        sent = threading.Event()
        batches = []
        def send(_key, host, batch, **kwargs):
            self.assertEqual(host, CONFIG['host'])
            batches.extend(batch)
            sent.set()
        with (patch('posthog.client._send_v1_batch', side_effect=send),
              patch('posthog.client.system_context', return_value={'cwd': '/private', 'email': 'private@example.invalid'})):
            analytics.capture('favorite_changed', {'surface': 'tray', 'source': 'claude', 'enabled': True})
            self.assertTrue(sent.wait(5))
            analytics.queue.join()
        event = batches[0]
        self.assertEqual(set(event), {'event', 'distinct_id', 'properties', 'options', 'timestamp', 'uuid'})
        self.assertEqual(event['distinct_id'], analytics.installation_id)
        self.assertEqual(event['options'], {'process_person_profile': False})
        self.assertEqual(set(event['properties']), {'surface', 'source', 'enabled', 'app_version', 'platform', '$geoip_disable', '$ip'})
        self.assertTrue(event['properties']['$geoip_disable'])
        self.assertEqual(event['properties']['$ip'], '0.0.0.0')
        self.assertNotIn('private', json.dumps(event))

    def test_opt_out_discards_pending_events_even_after_reenable(self):
        analytics = self.analytics()
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        with patch('posthog.client._send_v1_batch') as send:
            send.side_effect = lambda *_args, **_kwargs: (started.set(), release.wait(5))
            analytics.capture('dashboard_opened', {'surface': 'web'})
            self.assertTrue(started.wait(5))
            analytics.capture('tray_opened', {'surface': 'tray'})
            analytics.set_enabled(False)
            analytics.set_enabled(True)
            release.set()
            analytics.queue.join()
            self.assertEqual(send.call_count, 1)

    def test_local_api_validates_events_and_shares_preferences(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.analytics = self.analytics(demo=True)
        server.snapshot = Snapshot(Path(self.directory.name) / 'favorites.json')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        headers = {'Content-Type': 'application/json', 'X-Session-Dashboard': '1'}
        try:
            def post(path, payload, extra=None):
                return urlopen(Request(base + path, data=json.dumps(payload).encode(), headers=extra or headers))
            with post('/api/analytics/preferences', {'enabled': False}) as response:
                self.assertFalse(json.load(response)['enabled'])
            with urlopen(base + '/api/sessions') as response:
                self.assertFalse(json.load(response)['analytics']['enabled'])
            with post('/api/analytics', {'event': 'dashboard_opened', 'properties': {'surface': 'web'}}) as response:
                self.assertEqual(response.status, 200)
            for payload, extra, expected in [
                ({'event': 'private', 'properties': {}}, headers, 400),
                ({'event': 'dashboard_opened', 'properties': {'surface': 'web', 'title': 'private'}}, headers, 400),
                ({}, {**headers, 'Origin': 'https://attacker.example'}, 403),
                ({}, {'Content-Type': 'application/json'}, 403),
            ]:
                with self.assertRaises(HTTPError) as error:
                    post('/api/analytics', payload, extra)
                self.assertEqual(error.exception.code, expected)
                error.exception.close()
            self.assertFalse(self.path.exists(), 'Demo mode wrote analytics preferences')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
