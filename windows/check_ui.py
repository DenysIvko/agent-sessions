"""Exercise Windows tray controls with fictional data and no visible window."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from demo import snapshot
from product_analytics import validate_event
from windows.app import POLL_STATUS, RECONNECT_STATUS, TrayWindow

app = QApplication.instance() or QApplication([])
with tempfile.TemporaryDirectory() as directory:
    settings = QSettings(str(Path(directory) / 'test.ini'), QSettings.Format.IniFormat)
    with patch('windows.app.QSettings', return_value=settings):
        view = TrayWindow(app, snapshot())
    assert view.tabs.currentIndex() == 0
    assert view.tabs.count() == 3
    with patch('windows.app.QDesktopServices.openUrl') as open_url:
        help_button = next(b for b in view.findChildren(QPushButton) if b.text() == 'Help')
        help_button.click()
        assert open_url.call_args.args[0].toString().endswith('/?tutorial=1')
        assert not view.isVisible()
        tour_action = next(a for a in view.tray.contextMenu().actions() if a.text() == 'Quick Tour')
        tour_action.trigger()
        assert open_url.call_count == 2
        privacy_action = next(a for a in view.tray.contextMenu().actions() if a.text() == 'Usage Analytics...')
        privacy_action.trigger()
        assert open_url.call_args.args[0].toString().endswith('/?privacy=1')
        assert not view.isVisible()
    with patch.object(view, 'track') as track:
        view.tabs.tabBarClicked.emit(2)
        track.assert_called_once_with('view_selected', view='favorites')
        track.reset_mock()
        notifications = next(a for a in view.tray.contextMenu().actions() if a.text() == 'Completion notifications')
        notifications.trigger()
        track.assert_called_once_with('notifications_toggled', enabled=False)
        notifications.trigger()
    for index, label in enumerate(['New', 'All', 'Favorites']):
        view.tabs.setCurrentIndex(index)
        assert view.tabs.tabText(index).startswith(label)
        expected = 2 if index == 2 else 6
        buttons = [b for b in view.scroll.widget().findChildren(QPushButton) if b.accessibleName().startswith('Archive ')]
        assert len(buttons) == expected, (label, len(buttons))
        clicked = []
        with patch.object(view, 'action', side_effect=lambda s, e: clicked.append((s['id'], e))):
            buttons[0].click()
        assert clicked and clicked[0][1] == '/api/archive'
    view.tabs.setCurrentIndex(0)
    view.search.setText('Antigravity')
    assert len([b for b in view.scroll.widget().findChildren(QPushButton) if b.accessibleName().startswith('Archive ')]) == 2
    view.search.clear()
    view.resize(470, 610)
    view.ensurePolished()
    view.layout().activate()
    if '--screenshot' in sys.argv:
        from PySide6.QtGui import QPixmap
        output = Path(sys.argv[sys.argv.index('--screenshot') + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        pixmap = QPixmap(view.size())
        QWidget.render(view, pixmap)
        assert pixmap.save(str(output))
    print('Windows tray: tabs, running sessions, favorites, search and archive callbacks passed.')

    current = snapshot()
    running = current['sessions'][0]
    finished_at = int(current['checkedAt']) + 1
    completed = {**running, 'running': False, 'status': 'completed', 'endedAt': finished_at}
    next_poll = {**current, 'checkedAt': finished_at + 1,
                 'sessions': [completed, *current['sessions'][1:]]}
    with patch.object(view.tray, 'showMessage') as notify:
        view.received(current, None)
        view.received(next_poll, None)
        view.received(next_poll, None)
        notify.assert_called_once()
        assert not view.isVisible(), 'A completion notification opened the popup'

    update = {'available': True, 'version': '99.0.0',
              'downloadURL': 'https://example.invalid/qa-installer.exe'}
    with (patch('windows.app.checker.check', return_value=update) as check,
          patch('windows.app.QThreadPool') as pool,
          patch('windows.app.QDesktopServices.openUrl') as open_url,
          patch.object(view.tray, 'showMessage') as notify):
        pool.globalInstance.return_value.start.side_effect = lambda task: task.run()
        view.check_updates()
        view.check_updates()
        check.assert_called_once()
        notify.assert_called_once()
        assert view.update_action.text() == 'Download Update 99.0.0'
        open_url.assert_not_called()
        view.tabs.setCurrentIndex(2)
        view.tray.messageClicked.emit()
        assert view.isVisible() and view.tabs.currentIndex() == 0
        open_url.assert_not_called()
        view.update_action.trigger()
        assert open_url.call_args.args[0].toString() == update['downloadURL']
        open_url.assert_called_once()

    many_rows = [{**completed, 'id': f'qa-{index}', 'title': f'QA Windows disposable {index}'}
                 for index in range(40)]
    populated = {**next_poll, 'sessions': many_rows}
    view.tabs.setCurrentIndex(1)
    view.received(populated, None)
    app.processEvents()
    scroll = view.scroll.verticalScrollBar()
    assert scroll.maximum() > 0
    position = scroll.maximum() // 2
    scroll.setValue(position)
    view.received(None, 'QA simulated outage')
    assert view.footer.text() == RECONNECT_STATUS
    view.received(populated, None)
    assert view.footer.text() == POLL_STATUS
    assert scroll.value() == position
    view.received({**populated, 'error': 'QA source unavailable'}, None)
    assert view.footer.text() == 'QA source unavailable'
    view.received(populated, None)
    assert view.footer.text() == POLL_STATUS
    view.hide()
    print('Windows tray: notifications, explicit update link, reconnect status and scroll passed.')

    events = []
    def capture(event, **properties):
        validate_event(event, {'surface': 'tray', **properties})
        events.append((event, properties))
    session = {**completed, 'id': 'qa-action', 'source': 'codex', 'url': 'codex://threads/qa-action'}
    with (patch.object(view, 'track', side_effect=capture), patch.object(view, 'poll'),
          patch('windows.app.QThreadPool') as pool, patch('windows.app.request', return_value={}) as request,
          patch('windows.app.QDesktopServices.openUrl', return_value=False) as open_url):
        pool.globalInstance.return_value.start.side_effect = lambda task: task.run()
        view.open_dashboard()
        view.open_tutorial()
        view.open_privacy()
        view.search.setText('private project and search')
        view.search_finished()
        view.search_finished()
        view.search.clear()
        view.search_finished()
        assert len([e for e in events if e[0] == 'filter_used']) == 2
        view.open_session(session)
        assert events[-1] == ('session_open_result', {'source': 'codex', 'method': 'link', 'result': 'failed'})
        open_url.return_value = True
        view.open_session(session)
        assert events[-1] == ('session_reviewed', {'source': 'codex', 'method': 'open'})
        view.open_session({**session, 'url': None, 'resumeCommand': 'qa-only-placeholder'})
        assert events[-2] == ('session_open_result', {'source': 'codex', 'method': 'copy', 'result': 'copied'})
        view.open_session({**session, 'url': None, 'resumeCommand': None})
        assert events[-1][1]['result'] == 'unavailable'
        view.action(session, '/api/favorite')
        assert events[-1][0] == 'favorite_changed'
        view.action(session, '/api/archive')
        assert events[-1][0] == 'session_archived'
        request.side_effect = OSError('private path and credentials')
        for endpoint, action in [('/api/favorite', 'favorite'), ('/api/archive', 'archive')]:
            view.action(session, endpoint)
            assert events[-1] == ('action_failed', {'source': 'codex', 'action': action, 'reason': 'request_failed'})
        view.update_info = None
        with patch('windows.app.checker.check', return_value={'available': False, 'checkStatus': 'failed'}):
            view.update_menu_clicked()
        assert events[-2:] == [('update_check_requested', {'trigger': 'manual'}),
                              ('update_check_result', {'trigger': 'manual', 'result': 'failed'})]
        with patch('windows.app.checker.check', return_value={'available': False, 'checkStatus': 'ok'}):
            view.check_updates()
        assert events[-1] == ('update_check_result', {'trigger': 'automatic', 'result': 'current'})
    assert 'private' not in str(events) and 'qa-action' not in str(events)
    print('Windows analytics: actions, failures, navigation, search deduplication, review and update results passed.')
