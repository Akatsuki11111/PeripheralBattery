# Third-party components

This program uses Python 3.14.6 (PSF license), PySide6-Essentials / Shiboken 6.12.0 and the corresponding Qt shared libraries (LGPL-3.0 / GPL / commercial licensing alternatives, per package metadata), and hidapi 0.15.0 (license alternatives in its included license files). PyInstaller 6.22.3 supplies the executable bootloader (GPL with its exception permitting applications to be distributed under their own license). The dependencies remain their respective authors' work.

Dependency license texts are in `licenses/`. This application's complete Python source is supplied in the same folder and in the source ZIP; the exact pinned dependencies are in `requirements.txt`. Qt and Python are dynamically linked inside the self-extracting executable. To change a dependency, install the replacement into a Python virtual environment and rebuild with the documented PyInstaller command, or run the source directly. This program imposes no restriction on modifying these libraries or debugging such modifications.

Upstream source locations:

- https://github.com/python/cpython/tree/v3.14.6
- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/
- https://github.com/libusb/hidapi
- https://github.com/trezor/cython-hidapi
- https://github.com/pyinstaller/pyinstaller

Selected status providers from [HaloBattery](https://github.com/HeyOkay/HaloBattery/tree/2251f0534a8e886c9692ead42056059b4f69d8c0/providers) are distributed under MIT; the original copyright/license is in `battery_backends/LICENSE`, with provenance and local changes in `battery_backends/UPSTREAM.md`. Upstream GUI/updater/network features are not included. Nordic52 factual frame/model information was referenced from [mouse_tray](https://github.com/Fan4Metal/mouse_tray/blob/5dfb40d0fcbf98b8d14aa2ba47a7ed6768c466d7/mouse_tray/drivers/chipset/nordic52.py); the strict local codec is implemented separately.

Brand images belong to their respective owners and are used to identify the connected hardware. Razer, SteelSeries and Scyrox marks were extracted from installed driver icons. Other marks were obtained from the brands' official sites or [Simple Icons](https://simpleicons.org/) (CC0). Exact asset URLs are recorded in `assets/brands/SOURCES.json` and `catalog.json`. Rounded tile treatment, scale and contrast are adapted locally. Missing assets fall back to brand text. No affiliation or endorsement is implied. Windows Segoe fonts are read from the operating system and are not included. Public protocol references are linked in 使用说明.md. Proprietary vendor application source code is not included.
