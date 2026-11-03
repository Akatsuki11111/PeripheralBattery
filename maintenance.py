"""Reclaim only obsolete, owned cache files; never traverse user directories."""
from pathlib import Path
import re,time,hashlib
from settings import data_dir,read_json

def cleanup_cache(root=None,now=None):
    root=Path(root) if root is not None else data_dir();now=time.time() if now is None else now
    updates=root/'updates';active=set();removed=0;reclaimed=0
    if updates.is_dir():
        for request in list(updates.glob('*.install.json'))[:1000]:
            if not re.fullmatch(r'[a-f0-9]{32}\.install\.json',request.name):continue
            try:
                if now-request.stat().st_mtime<86400:
                    info=read_json(request,{},20000)
                    value=info.get('download',{}).get('path','')
                    if value:active.add(Path(value).resolve())
            except (OSError,TypeError,ValueError):pass
    success=read_json(updates/'last-result.json',{}).get('ok') is True
    installed=root/'bin/PeripheralBattery.exe';installed_hash=None
    patterns={'workers':r'[a-f0-9]{32}\.(request|result|started|progress)\.json',
              'updates':r'[a-f0-9]{32}\.(exe|part|install\.json)',
              'bin':r'PeripheralBattery\.exe\.[a-f0-9]{32}\.(new|bak)'}
    for folder,pattern in patterns.items():
        parent=root/folder
        if not parent.is_dir() or parent.is_symlink():continue
        for path in __import__('itertools').islice(parent.iterdir(),5000):
            if not re.fullmatch(pattern,path.name) or path.is_symlink():continue
            try:
                if path.resolve().parent!=parent.resolve() or path.resolve() in active:continue
                info=path.stat()
                if not path.is_file():continue
                if now-info.st_mtime<86400:
                    # A completed staging EXE is redundant once it matches the
                    # installed copy. Active installer requests still win above.
                    if not (folder=='updates' and path.suffix=='.exe' and success and installed.is_file() and installed.stat().st_size==info.st_size):continue
                    if installed_hash is None:installed_hash=hashlib.sha256(installed.read_bytes()).digest()
                    if hashlib.sha256(path.read_bytes()).digest()!=installed_hash:continue
                if folder=='bin' and not success:continue # Retain failed-install recovery evidence.
                path.unlink();removed+=1;reclaimed+=info.st_size
            except OSError:pass # Locked files are left for a later primary startup.
    return {'removed':removed,'reclaimed_bytes':reclaimed}
