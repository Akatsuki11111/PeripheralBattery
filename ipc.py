"""Small user/session scoped command channel. It accepts no paths or arbitrary code."""
import ctypes
import hashlib
import os


def server_name():
    session=ctypes.c_uint()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session))
    identity=os.environ.get('USERDOMAIN','')+'\\'+os.environ.get('USERNAME','')
    return 'PeripheralBattery.v2.'+hashlib.sha256(identity.encode()).hexdigest()[:20]+'.'+str(session.value)


def command(data):
    return {b'show\n':'show',b'ping\n':'ping',b'quit\n':'quit'}.get(bytes(data))
