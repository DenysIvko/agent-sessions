"""Build a self-contained Mac app and a drag-to-Applications disk image."""

from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
subprocess.run([sys.executable, str(ROOT / "macos/build.py"), "--bundle-backend"], check=True, cwd=ROOT)
stage = ROOT / "build/dmg"
if stage.exists():
    shutil.rmtree(stage)
stage.mkdir()
shutil.copytree(ROOT / "build/Agent Sessions.app", stage / "Agent Sessions.app")
(stage / "Applications").symlink_to("/Applications")
shutil.copy2(ROOT / "LICENSE", stage / "LICENSE.txt")
shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", stage / "THIRD_PARTY_NOTICES.txt")
output = ROOT / "dist"
output.mkdir(exist_ok=True)
arch = "arm64" if platform.machine() == "arm64" else "x64"
image = output / f"Agent-Sessions-macOS-{arch}.dmg"
if image.exists():
    image.unlink()
subprocess.run(["hdiutil", "create", "-volname", "Agent Sessions", "-srcfolder", str(stage),
                "-ov", "-format", "UDZO", str(image)], check=True)
print(image)
