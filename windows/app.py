"""Windows system tray application; its bundled server serves the full dashboard."""

import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QLockFile, QObject, QRunnable, QSettings, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                              QScrollArea, QSystemTrayIcon, QTabBar, QVBoxLayout, QWidget)

from app_config import DATA_DIR, VERSION
from server import Handler, Snapshot, ThreadingHTTPServer
from session_monitor import OUTCOMES, SessionMonitor, all_sessions
from updates import checker
from product_analytics import Analytics

BASE = "http://127.0.0.1:4318"
SOURCES = {"codex": "Codex", "claude": "Claude Code", "antigravity": "Antigravity"}
POLL_STATUS = "Updates automatically every 3 seconds"
RECONNECT_STATUS = "Dashboard reconnecting..."


def icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#7DD3C2"))
    for x, y in [(8, 8), (36, 8), (8, 36), (36, 36)]:
        painter.drawRoundedRect(x, y, 20, 20, 5, 5)
    painter.end()
    return QIcon(pixmap)


def identity_color(kind, id):
    value = int.from_bytes(hashlib.sha256(f"{kind}:{id}".encode()).digest()[:4], "big")
    return QColor.fromHslF((value % 359) / 360, [0.58, 0.66, 0.74][(value + 359) // 360 % 3], 0.72).name()


class Spinner(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(18, 18)
        self.angle = 0
        self.setAccessibleName("Running")
        self.setToolTip("This session is still running")
        timer = QTimer(self)
        timer.timeout.connect(self.tick)
        timer.start(50)

    def tick(self):
        self.angle = (self.angle + 20) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#74ACFF"), 2))
        painter.drawArc(2, 2, 14, 14, self.angle * 16, 270 * 16)


class Signals(QObject):
    done = Signal(object, object)

    def __init__(self, callback):
        # Keep the receiver alive after QRunnable auto-deletion, until UI delivery.
        super().__init__(QApplication.instance())
        self.callback = callback
        self.done.connect(self.deliver)

    @Slot(object, object)
    def deliver(self, result, error):
        try:
            self.callback(result, error)
        finally:
            self.deleteLater()


class Task(QRunnable):
    def __init__(self, work, callback):
        super().__init__()
        self.work = work
        self.signals = Signals(callback)

    def run(self):
        try:
            result = self.work()
            error = None
        except Exception as exception:
            result, error = None, str(exception)
        self.signals.done.emit(result, error)


def request(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(BASE + path, data=data, headers={"Content-Type": "application/json", "X-Session-Dashboard": "1"})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


class TrayWindow(QWidget):
    def __init__(self, app, snapshot=None):
        super().__init__(None, Qt.WindowType.Popup)
        self.app = app
        self.snapshot = snapshot or {"sessions": []}
        self.settings = QSettings("Agent Sessions", "Agent Sessions")
        try:
            reviews = json.loads(self.settings.value("reviews", "{}"))
            if set(reviews) != {"pending", "reviewed"} or not all(isinstance(v, dict) for v in reviews.values()):
                reviews = None
        except (ValueError, TypeError):
            reviews = None
        self.monitor = SessionMonitor(reviews)
        self.inflight = False
        self.pending_actions = set()
        self.update_info = None
        self.analytics_available = False
        self.opened_tracked = False
        self.setWindowTitle("Agent Sessions")
        self.resize(470, 610)
        self.setStyleSheet("""
            QWidget { background: #202329; color: #E8EAEE; font: 12px 'Segoe UI'; }
            QPushButton { border: 0; padding: 7px; border-radius: 5px; }
            QPushButton:hover { background: #363C45; }
            QLineEdit { background: #16191E; border: 1px solid #424957; border-radius: 6px; padding: 7px; }
            QTabBar::tab { background: #2B3038; padding: 9px 18px; }
            QTabBar::tab:selected { background: #3E5D70; }
            QScrollArea { border: 0; }
        """)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        heading = QLabel("Agent Sessions")
        heading.setStyleSheet("font-size: 16px; font-weight: 600")
        header.addWidget(heading)
        header.addStretch()
        web = QPushButton("Open Web Dashboard")
        web.setToolTip("Open the full dashboard with source, project and status filters")
        web.clicked.connect(self.open_dashboard)
        header.addWidget(web)
        layout.addLayout(header)
        self.summary = QLabel("Connecting...")
        layout.addWidget(self.summary)
        self.tabs = QTabBar()
        for title, hint in [("New", "Running work and results awaiting review"),
                            ("All", "Today's activity plus saved favorites"),
                            ("Favorites", "Starred sessions across all days")]:
            self.tabs.setTabToolTip(self.tabs.addTab(title), hint)
        self.tabs.setExpanding(True)
        self.tabs.setAccessibleName("Session view")
        self.tabs.currentChanged.connect(self.render)
        self.tabs.tabBarClicked.connect(lambda index: self.track('view_selected', view=('new', 'all', 'favorites')[index]))
        layout.addWidget(self.tabs)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sessions")
        self.search.setAccessibleName("Search sessions")
        self.search.setToolTip("Search the selected tab by title, project, source, branch or ID")
        self.search.textChanged.connect(self.render)
        self.last_search = ''
        self.search.editingFinished.connect(self.search_finished)
        layout.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)
        self.footer = QLabel(POLL_STATUS)
        self.footer.setWordWrap(True)
        bottom = QHBoxLayout()
        bottom.addWidget(self.footer, 1)
        help_button = QPushButton("Help")
        help_button.setToolTip("Open the quick tour of the tray and dashboard")
        help_button.clicked.connect(self.open_tutorial)
        bottom.addWidget(help_button)
        layout.addLayout(bottom)
        self.tray = QSystemTrayIcon(icon(), self)
        self.tray.setToolTip("Agent Sessions")
        self.tray.activated.connect(self.activated)
        self.tray.messageClicked.connect(self.notification_clicked)
        menu = QMenu()
        menu.addAction("Show Sessions", self.show_new)
        menu.addAction("Open Web Dashboard", self.open_dashboard)
        menu.addAction("Quick Tour", self.open_tutorial)
        menu.addAction("Usage Analytics...", self.open_privacy)
        notifications = QAction("Completion notifications", menu)
        notifications.setCheckable(True)
        notifications.setChecked(self.settings.value("notifications", True, bool))
        notifications.toggled.connect(self.toggle_notifications)
        menu.addAction(notifications)
        self.update_action = menu.addAction("Check for Updates", self.update_menu_clicked)
        menu.addAction(f"Version {VERSION}").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Quit", app.quit)
        self.tray.setContextMenu(menu)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.check_updates)
        self.update_timer.setInterval(6 * 60 * 60 * 1000)
        self.render()

    def start(self):
        self.tray.show()
        self.timer.start(3000)
        self.update_timer.start()
        self.poll()
        QTimer.singleShot(15000, self.check_updates)

    def activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.hide() if self.isVisible() else self.show_new()

    def show_new(self):
        self.track('tray_opened')
        self.tabs.setCurrentIndex(0)
        self.search.clear()
        self.last_search = ''
        area = self.app.primaryScreen().availableGeometry()
        self.resize(min(470, area.width()), min(610, area.height()))
        self.move(area.right() - self.width(), area.bottom() - self.height())
        self.show()
        self.activateWindow()

    def poll(self):
        if self.inflight:
            return
        self.inflight = True
        QThreadPool.globalInstance().start(Task(lambda: request('/api/sessions'), self.received))

    def received(self, data, error):
        self.inflight = False
        if error or not data or data.get("service") != "agent-sessions":
            self.footer.setText(RECONNECT_STATUS)
            return
        if self.footer.text() in (RECONNECT_STATUS, self.snapshot.get("error")):
            self.footer.setText(POLL_STATUS)
        self.snapshot = data
        self.analytics_available = data.get('analytics', {}).get('configured', False)
        if not self.opened_tracked:
            self.track('app_opened')
            self.opened_tracked = True
        finished = self.monitor.update(data)
        self.save_reviews()
        scrollbar = self.scroll.verticalScrollBar()
        position = scrollbar.value()
        self.render()
        scrollbar.setValue(position)
        if self.settings.value("notifications", True, bool):
            for session in finished:
                self.track('notification_requested', kind='completion')
                self.tray.showMessage(f"{SOURCES[session['source']]} {OUTCOMES[session['status']]}",
                                      f"{session['project']}\n{session['title']}", QSystemTrayIcon.MessageIcon.Information, 6000)

    def save_reviews(self):
        self.settings.setValue("reviews", json.dumps(self.monitor.reviews))

    def render(self):
        new = self.monitor.new_sessions(self.snapshot)
        pools = [new, all_sessions(self.snapshot), self.snapshot.get("favoriteSessions", [])]
        for index, title in enumerate(("New", "All", "Favorites")):
            self.tabs.setTabText(index, f"{title} ({len(pools[index])})")
        running = sum(bool(s.get("running")) for s in pools[1])
        self.summary.setText(f"{len(new)} new · {running} running · {len(self.snapshot.get('sessions', []))} today")
        if self.snapshot.get("error"):
            self.footer.setText(self.snapshot['error'])
        query = self.search.text().strip().lower()
        rows = [s for s in pools[self.tabs.currentIndex()] if not query or query in ' '.join(
            [s['title'], s['project'], SOURCES[s['source']], s['id'], s.get('branch') or '']).lower()]
        rows.sort(key=lambda s: (not s.get('running'), not s.get('unread'), -(s.get('activityAt') or 0), s['id']))
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        for session in rows:
            row = QWidget()
            line = QHBoxLayout(row)
            if session.get('running'):
                line.addWidget(Spinner())
            else:
                dot = QLabel("●")
                dot.setStyleSheet(f"color: {identity_color('session', session['id'])}")
                line.addWidget(dot)
            details = QVBoxLayout()
            title = QPushButton(session['title'])
            title.setStyleSheet("text-align: left; font-weight: 600")
            action = f"Open in {SOURCES[session['source']]}" if session.get('url') else "Copy resume command to paste in your terminal"
            title.setToolTip(session['title'] + '\n' + action)
            title.clicked.connect(lambda checked=False, s=session: self.open_session(s))
            details.addWidget(title)
            subtitle = QLabel(f"{SOURCES[session['source']]} · {session['project']}")
            subtitle.setStyleSheet(f"color: {identity_color('project', session.get('projectId') or session['project'])}; font-size: 10px")
            details.addWidget(subtitle)
            line.addLayout(details, 1)
            for text, label, endpoint in [("★" if session.get('favorite') else "☆", "Favorite", '/api/favorite'), ("Archive", "Archive", '/api/archive')]:
                button = QPushButton(text)
                button.setAccessibleName(f"{label} {session['title']}")
                button.setToolTip(("Remove from favorites" if session.get('favorite') else "Keep in favorites across days")
                                  if endpoint == '/api/favorite' else
                                  "Hide from Agent Sessions, even if source archival fails. Running work continues.")
                button.setEnabled(session['id'] not in self.pending_actions)
                button.clicked.connect(lambda checked=False, s=session, e=endpoint: self.action(s, e))
                line.addWidget(button)
            box.addWidget(row)
        if not rows:
            box.addWidget(QLabel("No matching sessions" if query else "Nothing here yet"))
        box.addStretch()
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        self.scroll.setWidget(content)

    def action(self, session, endpoint):
        if session['id'] in self.pending_actions:
            return
        self.pending_actions.add(session['id'])
        self.render()
        payload = {"id": session['id']}
        if endpoint == '/api/favorite':
            payload['favorite'] = not session.get('favorite')
        def done(data, error):
            self.pending_actions.discard(session['id'])
            if not error:
                if endpoint == '/api/favorite':
                    self.track('favorite_changed', source=session['source'], enabled=payload['favorite'])
                else:
                    self.track('session_archived', source=session['source'])
            else:
                self.track('action_failed', source=session['source'],
                           action='favorite' if endpoint == '/api/favorite' else 'archive', reason='request_failed')
            self.footer.setText(error or ("Archived in Agent Sessions" if endpoint == '/api/archive' else "Favorite saved"))
            self.poll()
        QThreadPool.globalInstance().start(Task(lambda: request(endpoint, payload), done))

    def open_session(self, session):
        url = session.get('url') or ''
        method = 'open'
        if url.startswith(('codex://threads/', 'claude://epitaxy/', 'claude://resume?session=')):
            self.track('session_open_requested', source=session['source'], method='link')
            opened = QDesktopServices.openUrl(QUrl(url))
            self.track('session_open_result', source=session['source'], method='link', result='accepted' if opened else 'failed')
            if not opened:
                self.footer.setText(f"Install {SOURCES[session['source']]} to open this session")
                return
        elif session.get('resumeCommand'):
            method = 'copy'
            self.track('session_open_requested', source=session['source'], method='copy')
            self.app.clipboard().setText(session['resumeCommand'])
            self.track('session_open_result', source=session['source'], method='copy', result='copied')
            self.footer.setText("Resume command copied. Paste it in your terminal.")
        else:
            self.track('session_open_result', source=session['source'], method='link', result='unavailable')
            return
        self.monitor.mark_reviewed(session)
        self.save_reviews()
        self.track('session_reviewed', source=session['source'], method=method)
        self.render()

    def search_finished(self):
        query = self.search.text()
        if query != self.last_search:
            self.track('filter_used', filter='search', selection='applied' if query else 'cleared')
            self.last_search = query

    def open_dashboard(self):
        self.track('navigation_requested', destination='dashboard')
        QDesktopServices.openUrl(QUrl(BASE))

    def open_tutorial(self):
        self.track('navigation_requested', destination='tutorial')
        QDesktopServices.openUrl(QUrl(BASE + '/?tutorial=1'))
        self.hide()

    def open_privacy(self):
        self.track('navigation_requested', destination='privacy')
        QDesktopServices.openUrl(QUrl(BASE + '/?privacy=1'))
        self.hide()

    def track(self, event, **properties):
        if self.analytics_available:
            payload = {'event': event, 'properties': {'surface': 'tray', **properties}}
            QThreadPool.globalInstance().start(Task(lambda: request('/api/analytics', payload), lambda *_: None))

    def toggle_notifications(self, enabled):
        self.settings.setValue('notifications', enabled)
        self.track('notifications_toggled', enabled=enabled)

    def notification_clicked(self):
        self.track('notification_clicked')
        self.show_new()

    def update_menu_clicked(self):
        if self.update_info:
            self.track('update_download_requested')
            QDesktopServices.openUrl(QUrl(self.update_info['downloadURL']))
        else:
            self.check_updates(manual=True)

    def check_updates(self, manual=False):
        if self.update_info:
            return
        trigger = 'manual' if manual else 'automatic'
        self.track('update_check_requested', trigger=trigger)
        def done(data, error):
            result = 'failed' if error or not data or data.get('checkStatus') == 'failed' else 'available' if data.get('available') else 'current'
            self.track('update_check_result', trigger=trigger, result=result)
            if data and data.get('available'):
                self.track('update_available')
                self.update_info = data
                self.update_action.setText(f"Download Update {data['version']}")
                if self.settings.value('notifiedVersion') != data['version']:
                    self.track('notification_requested', kind='update')
                    self.tray.showMessage("Agent Sessions update available",
                                          f"Version {data['version']} is ready. Open the tray menu to download.")
                    self.settings.setValue('notifiedVersion', data['version'])
        QThreadPool.globalInstance().start(Task(checker.check, done))


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA_DIR / 'tray.lock'))
    if not lock.tryLock(0):
        return
    server = None
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 4318), Handler)
        server.analytics = Analytics()
        server.snapshot = Snapshot(analytics=server.analytics)
        threading.Thread(target=server.snapshot.refresh, daemon=True).start()
        threading.Thread(target=server.serve_forever, daemon=True).start()
    except OSError:
        # Reuse the local service only after validating it in the first poll.
        pass
    window = TrayWindow(app)
    window.start()
    app.exec()
    if server:
        server.analytics.close()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
