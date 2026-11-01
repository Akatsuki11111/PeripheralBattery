"""Sign release binaries and publish plain human release notes. No embedded endpoint."""
import argparse,hashlib,json,os,re,struct,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from update_signing import canonical_json,verify_envelope
from signed_binary import MAGIC,verify_binary
from server_release_api import Session,APP_KEY,ServerError


def validate_version(version,channel):
    if channel not in ('stable','experimental'):raise ValueError('Invalid channel')
    if not isinstance(version,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[a-z0-9]+(?:[.-][a-z0-9]+)*)?',version):
        raise ValueError('Use only a SemVer number; no software name or v prefix')
    if channel=='stable' and '-' in version:raise ValueError('Stable version cannot have a prerelease suffix')


def sign_artifact(file,output,version,code,channel,key_path=None):
    validate_version(version,channel);file=Path(file);output=Path(output)
    base=file.read_bytes()
    if base[:2]!=b'MZ' or base.endswith(MAGIC):raise ValueError('Expected an unsigned Windows build')
    payload=dict(app_key=APP_KEY,platform='windows',channel=channel,version=version,
                 version_code=int(code),size=len(base),sha256=hashlib.sha256(base).hexdigest())
    key=json.loads((ROOT/'assets/update-public-key.json').read_text(encoding='utf-8'))
    key_path=Path(key_path) if key_path else Path.home()/'.peripheral-battery/signing/update-key.dpapi'
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);input_path=tmp/'payload.json';out=tmp/'signed.json';public=tmp/'public.json'
        input_path.write_bytes(canonical_json(payload))
        process=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/sign_update_manifest.ps1'),
            '-InputPath',str(input_path),'-OutputPath',str(out),'-PublicKeyOutput',str(public),
            '-KeyPath',str(key_path),'-KeyId',key['key_id']],capture_output=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
        if process.returncode:raise ValueError('Protected signing operation failed')
        if json.loads(public.read_text(encoding='utf-8-sig'))!=key:raise ValueError('Signing key does not match pinned key')
        envelope=json.loads(out.read_text(encoding='utf-8-sig'))
    if verify_envelope(envelope,key)!=payload:raise ValueError('Release signature verification failed')
    raw=json.dumps(envelope,ensure_ascii=False,separators=(',',':')).encode()
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(base+raw+struct.pack('<I',len(raw))+MAGIC)
    verify_binary(output,key,payload)
    return dict(version=version,channel=channel,size=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest())


def publish_release(session,file,version,version_code,channel,notes,app_id=2):
    validate_version(version,channel)
    if not isinstance(notes,str) or not 0<len(notes)<=2000 or any(t in notes for t in ('PB-SIGNED-MANIFEST:','modulus_b64','BEGIN PRIVATE KEY')):
        raise ValueError('Release notes must be plain human text')
    file=Path(file)
    if file.name!='PeripheralBattery.exe':raise ValueError('Upload PeripheralBattery.exe; supply version separately')
    key=json.loads((ROOT/'assets/update-public-key.json').read_text(encoding='utf-8'))
    expected=dict(app_key=APP_KEY,platform='windows',channel=channel,version=version,version_code=int(version_code))
    verify_binary(file,key,expected)
    server_version=version.split('-',1)[0]
    draft=session.upload_draft(app_id,file,server_version,int(version_code),channel,notes)
    if draft['status']==0:session.edit_draft_notes(draft,notes);session.publish(draft['id'])
    elif draft['status']!=1:raise ServerError('Unexpected existing release state')
    public=session.public_check(channel)
    if public.get('versionName')!=server_version or public.get('changelog')!=notes or public.get('updateLink')!='pb-signed-exe:v1':
        raise ServerError('Published metadata differs from expected plain release notes')
    return dict(version=version,server_version=server_version,channel=channel,release_id=draft['id'],size=file.stat().st_size)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--file',required=True);parser.add_argument('--version',required=True)
    parser.add_argument('--version-code',required=True,type=int);parser.add_argument('--channel',required=True,choices=('stable','experimental'))
    parser.add_argument('--notes-file',required=True);parser.add_argument('--credentials-stdin',action='store_true',required=True)
    args=parser.parse_args();credentials=json.load(sys.stdin);session=Session();session.login(credentials['username'],credentials['password'])
    result=publish_release(session,args.file,args.version,args.version_code,args.channel,Path(args.notes_file).read_text(encoding='utf-8'))
    print(json.dumps(result))

if __name__=='__main__':main()
