"""Exercise Windows tray controls with fictional data and no visible window."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QPushButton
from demo import snapshot
from windows.app import TrayWindow

app = QApplication.instance() or QApplication([])
with tempfile.TemporaryDirectory() as directory:
    settings = QSettings(str(Path(directory) / 'test.ini'), QSettings.Format.IniFormat)
    with patch('windows.app.QSettings', return_value=settings):
        view = TrayWindow(app, snapshot())
    assert view.tabs.currentIndex() == 0
    assert view.tabs.count() == 3
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
        view.render(pixmap)
        assert pixmap.save(str(output))
    print('Windows tray: tabs, running sessions, favorites, search and archive callbacks passed.')
