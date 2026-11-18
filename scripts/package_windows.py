"""Build the self-contained Windows app; compile installer.iss with Inno Setup next."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
if sys.platform != "win32":
    raise SystemExit("Build Windows packages on Windows (or run the GitHub Actions packaging job).")
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "AgentSessions", "--distpath", str(ROOT / "build/windows"),
    "--workpath", str(ROOT / "build/pyinstaller-windows"), "--specpath", str(ROOT / "build"),
    "--paths", str(ROOT), "--add-data", f"{ROOT / 'public'};public", "--add-data", f"{ROOT / 'VERSION'};.",
    "--collect-data", "tzdata", str(ROOT / "windows/app.py")], check=True, cwd=ROOT)
subprocess.run([sys.executable, str(ROOT / 'scripts/collect_licenses.py'),
                str(ROOT / 'build/windows/AgentSessions/licenses'), '--windows'], check=True)
