# -*- mode: python ; coding: utf-8 -*-
"""Small Windows Widgets build; keep this file beside app.py."""
from pathlib import Path
import json,os,re
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_submodules
import sys

root=Path(SPECPATH)
sys.path.insert(0,str(root))
channel=os.environ.get('PB_BUILD_CHANNEL','stable')
if channel not in ('stable','experimental'):raise ValueError('Invalid build channel')
version='2.5.0' if channel=='stable' else '2.5.1-experimental.1'
generated=Path(CONF['workpath'])/'channel';generated.mkdir(parents=True,exist_ok=True)
(generated/'release.json').write_text(json.dumps(dict(version=version,channel=channel)),encoding='utf-8')
version_text=(root/'version_info.txt').read_text(encoding='utf-8')
numeric='2,5,0,0' if channel=='stable' else '2,5,1,1'
version_text=re.sub(r'filevers=\([^)]*\),prodvers=\([^)]*\)',f'filevers=({numeric}),prodvers=({numeric})',version_text)
version_text=re.sub(r"(StringStruct\('(?:FileVersion|ProductVersion)',')[^']*",lambda m:m[1]+version,version_text)
(generated/'version_info.txt').write_text(version_text,encoding='utf-8')
excluded=['PySide6.QtQuick','PySide6.QtQml','PySide6.QtPdf','PySide6.QtOpenGL',
          'PySide6.QtOpenGLWidgets','PySide6.QtTest']
if channel=='stable':excluded+=['research','research_ui','long_learning','learning_jobs','learning_ui']
a=Analysis([str(root/'app.py')],pathex=[str(root)],
    datas=[(str(generated/'release.json'),'.'),(str(root/'assets'),'assets'),(str(root/'catalog.json'),'.'),
           (str(root/'licenses'),'licenses'),(str(root/'THIRD_PARTY_NOTICES.md'),'.'),
           (str(root/'battery_backends/LICENSE'),'battery_backends')],
    hiddenimports=collect_submodules('battery_backends'),
    excludes=excluded,optimize=2)

# Qt's generic hooks collect plugins for applications using QML, OpenGL and PDF.
# This application paints raster Widgets, loads SVG/PNG/ICO brand assets, and
# uses QtNetwork only for QLocalSocket IPC. HTTPS uses Python's ssl/urllib.
plugin_allow={'platforms/qwindows.dll',
              'imageformats/qsvg.dll','imageformats/qico.dll','imageformats/qjpeg.dll',
              'iconengines/qsvgicon.dll','styles/qmodernwindowsstyle.dll',
              'styles/qwindowsvistastyle.dll'}
def needed(name):
    path=name.replace('\\','/');base=path.rsplit('/',1)[-1].lower()
    if '/plugins/' in path:return path.split('/plugins/',1)[1].lower() in plugin_allow
    if base=='opengl32sw.dll' or base.startswith(('qt6quick','qt6qml','qt6pdf','qt6opengl')):return False
    return True
a.binaries=[row for row in a.binaries if needed(row[0])]
a.datas=[row for row in a.datas if '/translations/' not in row[0].replace('\\','/') or row[0].endswith('qtbase_zh_CN.qm')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='PeripheralBattery',console=False,
        debug=False,strip=False,upx=False,icon=str(root/'assets/app.ico'),
        version=str(generated/'version_info.txt'))
