"""Publish one final EXE to VersionHub with a pinned-key signed manifest.

No password or private key is embedded in this file. Import publish_release
with an in-memory authenticated Session, or pass login JSON through stdin.
Do not use shell arguments, release notes or checked-in files for credentials.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from server_release_api import APP_KEY,BASE_URL,Session,ServerError

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from update_signing import canonical_json,verify_envelope

MARKER='PB-SIGNED-MANIFEST:'


def signed_notes(notes,envelope):
    encoded=base64.b64encode(json.dumps(envelope,ensure_ascii=False,separators=(',',':')).encode('utf-8')).decode('ascii')
    text=notes.rstrip()+'\n'+MARKER+encoded
    if len(text)>2000:raise ValueError('Signed changelog exceeds the server 2000-character limit')
    return text


def publish_release(session,file,version,version_code,channel,notes,*,app_id=2,key_path=None,key_id=None,progress=None):
    if channel not in ('stable','experimental'):raise ValueError('Expected stable or experimental channel')
    if MARKER in notes:raise ValueError('Human notes must not contain a manifest marker')
    file=Path(file).resolve()
    if not file.is_file():raise ValueError('Release EXE is missing')
    with file.open('rb') as stream:
        if stream.read(2)!=b'MZ':raise ValueError('Release artifact is not a Windows executable')
    digest=hashlib.sha256(file.read_bytes()).hexdigest();size=file.stat().st_size
    public_key=json.loads((ROOT/'assets/update-public-key.json').read_text(encoding='utf-8'))
    key_id=key_id or public_key['key_id']
    if key_id!=public_key['key_id']:raise ValueError('Signing key selector differs from the client pinned key')
    key_path=Path(key_path) if key_path else Path.home()/'.peripheral-battery/signing/update-key.dpapi'
    if not key_path.is_file():raise ValueError('Protected publisher signing key is missing')
    app=session.app(app_id)
    if app.get('appKey')!=APP_KEY or app.get('status')!=1 or 'windows' not in str(app.get('platforms','')).split(','):
        raise ServerError('Unexpected application identity or platform')
    # Preflight the maximum-sized ID before creating a server draft.
    payload=dict(app_key=APP_KEY,platform='windows',channel=channel,version=version,version_code=int(version_code),
                 release_id=2**63-1,download_path='/api/v1/update/download/'+str(2**63-1),size=size,sha256=digest)
    signed_notes(notes,dict(algorithm='rsa-pkcs1-sha256',key_id=key_id,payload=payload,signature='A'*344))
    draft=session.upload_draft(app_id,file,version,int(version_code),channel,notes,progress)
    if draft['status']==1:
        # An idempotent retry may encounter the exact already-published file.
        result=session.public_check(channel)
        if result.get('versionName')!=version:raise ServerError('Existing release is not the channel head')
        final=result.get('changelog','').rstrip().splitlines()[-1]
        if not final.startswith(MARKER):raise ServerError('Existing release has no signed manifest')
        envelope=json.loads(base64.b64decode(final[len(MARKER):],validate=True))
        verified=verify_envelope(envelope,public_key)
        if verified.get('sha256')!=digest or verified.get('release_id')!=draft['id']:
            raise ServerError('Existing published manifest differs')
        return dict(version=version,channel=channel,release_id=draft['id'],size=size,sha256=digest,reused=True)
    if draft['status']!=0:raise ServerError('Existing version is not a draft; refusing to change it')
    payload.update(release_id=draft['id'],download_path='/api/v1/update/download/'+str(draft['id']))
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    staging=ROOT/'build/release-staging';staging.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as folder:
        folder=Path(folder);input_path=folder/'payload.json';output_path=folder/'envelope.json';check_key=folder/'public.json'
        input_path.write_bytes(canonical_json(payload))
        result=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                               '-File',str(ROOT/'tools/sign_update_manifest.ps1'),'-InputPath',str(input_path),
                               '-OutputPath',str(output_path),'-KeyPath',str(key_path),'-PublicKeyOutput',str(check_key),
                               '-KeyId',key_id],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode!=0:raise ServerError('Protected release-signing helper failed')
        emitted_key=json.loads(check_key.read_text(encoding='utf-8-sig'))
        if emitted_key!=public_key:raise ServerError('Private signing key does not match client pinned key')
        envelope=json.loads(output_path.read_text(encoding='utf-8-sig'))
    if verify_envelope(envelope,public_key)!=payload:raise ServerError('Local release signature verification failed')
    changelog=signed_notes(notes,envelope)
    session.edit_draft_notes(draft,changelog)
    matches=[row for row in session.versions(app_id) if row['id']==draft['id']]
    if len(matches)!=1 or matches[0]['changelog']!=changelog or matches[0]['status']!=0:
        raise ServerError('Server draft did not preserve the exact signed manifest')
    session.publish(draft['id'])
    public=session.public_check(channel)
    if (public.get('versionName')!=version or public.get('versionCode')!=int(version_code) or
            public.get('size')!=size or public.get('downloadUrl')!=payload['download_path'] or public.get('changelog')!=changelog):
        raise ServerError('Published public update response differs from signed release')
    # Only public metadata is written. Credentials and private key material stay out.
    report=dict(version=version,channel=channel,release_id=draft['id'],size=size,sha256=digest,
                download_url=BASE_URL+payload['download_path'],manifest=envelope)
    (staging/('versionhub-published-'+version+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return {key:value for key,value in report.items() if key!='manifest'}


def main():
    parser=argparse.ArgumentParser(description='Publish a signed PeripheralBattery release to VersionHub')
    parser.add_argument('--file',required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--version-code',required=True,type=int)
    parser.add_argument('--channel',required=True,choices=('stable','experimental'))
    parser.add_argument('--notes-file',required=True)
    parser.add_argument('--credentials-stdin',action='store_true',required=True,help='Read login JSON from stdin; never from arguments or disk')
    args=parser.parse_args()
    credentials=json.loads(sys.stdin.read(4096))
    if set(credentials)!={'username','password'}:raise ValueError('Expected username/password JSON on stdin')
    session=Session();session.login(credentials.pop('username'),credentials.pop('password'));credentials.clear()
    def progress(received,total):
        bucket=received*10//total
        if bucket!=progress.last:progress.last=bucket;print('Upload '+str(min(bucket*10,100))+'%',flush=True)
    progress.last=-1
    report=publish_release(session,args.file,args.version,args.version_code,args.channel,
                           Path(args.notes_file).read_text(encoding='utf-8'),progress=progress)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
