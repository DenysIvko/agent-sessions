"""Include installed dependencies' licenses in each distribution."""

from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys


def collect(destination, windows=False):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ['psutil', 'tzlocal', 'tzdata', 'pyinstaller']:
        package = distribution(name)
        for file in package.files:
            if any(part.lower().startswith(('license', 'copying', 'copyright')) for part in file.parts):
                target = destination / name / Path(*file.parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package.locate_file(file), target)
    source = Path(__file__).resolve().parent.parent / 'licenses'
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


if __name__ == '__main__':
    collect(sys.argv[1], '--windows' in sys.argv)
