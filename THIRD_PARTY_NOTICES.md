# Third-party notices

Agent Sessions source is MIT licensed. Third-party components keep their own
licenses. No affiliation with OpenAI, Anthropic, Google, Microsoft, or Apple is implied.

| Component | License | Source |
| --- | --- | --- |
| color-hash 2.0.2 | MIT | https://github.com/zenozeng/color-hash |
| Python runtime | PSF License | https://www.python.org/downloads/source/ |
| psutil | BSD 3-Clause | https://github.com/giampaolo/psutil |
| tzlocal | MIT | https://github.com/regebro/tzlocal |
| tzdata | Apache 2.0; IANA data is public domain | https://github.com/python/tzdata |
| Qt / PySide6 / Shiboken6 (Windows) | LGPL 3.0 and applicable Qt module notices | https://code.qt.io/pyside/pyside-setup.git/ |
| PyInstaller bootloader | GPL 2.0 with distribution exception | https://github.com/pyinstaller/pyinstaller |

Runtime license texts are included in the installed `licenses` directory.
The web's color-hash license is also in `public/vendor/color-hash-2.0.2/`.
Windows builds dynamically link Qt DLLs. You may replace these libraries with
compatible modified versions and reverse engineer the application for debugging
such modifications, as permitted by the LGPL. Rebuild instructions and dependency
versions are provided in this repository. There is no restriction on installing
your own build, and no signing key is needed to run a modified build.
