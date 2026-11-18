"""Build the self-contained Windows app; compile installer.iss with Inno Setup next."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
if sys.platform != "win32":
    raise SystemExit("Build Windows packages on Windows (or run the GitHub Actions packaging job).")

# PyInstaller scans PATH for DLLs. Other applications can ship DLLs with
# Windows system names, such as icuuc.dll, and supply incompatible exports.
windows = Path(os.environ["SystemRoot"])
build_env = {**os.environ, "PATH": os.pathsep.join(map(str, (windows / "System32", windows)))}
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "AgentSessions", "--distpath", str(ROOT / "build/windows"),
    "--workpath", str(ROOT / "build/pyinstaller-windows"), "--specpath", str(ROOT / "build"),
    "--paths", str(ROOT), "--add-data", f"{ROOT / 'public'};public", "--add-data", f"{ROOT / 'VERSION'};.",
    "--collect-data", "tzdata", str(ROOT / "windows/app.py")], check=True, cwd=ROOT, env=build_env)
subprocess.run([sys.executable, str(ROOT / 'scripts/collect_licenses.py'),
                str(ROOT / 'build/windows/AgentSessions/licenses'), '--windows'], check=True)
