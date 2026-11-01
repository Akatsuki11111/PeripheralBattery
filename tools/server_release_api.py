"""VersionHub release-management helper; no embedded credentials or keys.

Management methods require an explicit caller action. This module itself does
not create, upload, edit, publish or delete anything. Login tokens stay in RAM.
"""
from __future__ import annotations

import hashlib
import os,time
import http.client
import json
from pathlib import Path
import urllib.parse
import uuid

BASE_URL=os.environ.get('PB_RELEASE_ORIGIN','')
APP_KEY='peripheral-battery'
APP_FIELDS=('id','name','appKey','platforms','description','forceBelowCode','status',
            'quotaMb','keepVersions','signEnabled','signedUrlEnabled','signedUrlMinutes',
            'storageUsed','versionCount','latestVersion','latestPublishTime')
VERSION_FIELDS=('id','appId','versionName','versionCode','platform','channel','forceUpdate',
                'changelog','fileName','fileSize','md5','status','grayPercent','grayTargets',
                'updateTitle','updateButtonText','updateLink','publishTime','scheduleTime')
UPDATE_FIELDS=('hasUpdate','versionName','versionCode','forceUpdate','changelog','md5','size',
               'downloadUrl','publishTime','channel','updateTitle','updateButtonText','updateLink')


def sanitized(value,fields):
    return {key:value.get(key) for key in fields}


class ServerError(RuntimeError):
    pass


class Session:
    def __init__(self):
        self._token=None

    def _connection(self,timeout=25):
        parsed=urllib.parse.urlsplit(BASE_URL)
        if parsed.scheme not in ('http','https') or not parsed.hostname:raise ServerError('Release connection not configured')
        return (http.client.HTTPSConnection if parsed.scheme=='https' else http.client.HTTPConnection)(parsed.hostname,parsed.port,timeout=timeout)

    @staticmethod
    def _decode(response):
        raw=response.read(2_000_001)
        if response.status!=200 or len(raw)>2_000_000:
            raise ServerError(f'Unexpected server response HTTP {response.status}')
        try:data=json.loads(raw)
        except ValueError as error:raise ServerError('Server returned non-JSON data') from error
        if not isinstance(data,dict) or data.get('code')!=0:
            # Do not echo raw authentication or application responses.
            raise ServerError('Version server API error, code '+str(data.get('code') if isinstance(data,dict) else 'invalid'))
        return data.get('data')

    def call(self,path,method='GET',data=None,*,authenticated=True):
        if not isinstance(path,str) or not path.startswith('/api/v1/') or '\r' in path or '\n' in path:
            raise ValueError('Invalid API path')
        body=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8') if data is not None else None
        headers={'Content-Type':'application/json; charset=utf-8','User-Agent':'PeripheralBattery-release'}
        if authenticated:
            if not self._token:raise ServerError('Login required')
            headers['satoken']=self._token
        connection=self._connection()
        try:
            connection.request(method,path,body=body,headers=headers)
            return self._decode(connection.getresponse())
        finally:connection.close()

    def login(self,username,password):
        data=self.call('/api/v1/auth/login','POST',{'username':username,'password':password},authenticated=False)
        if not isinstance(data,dict) or not isinstance(data.get('token'),str) or not data['token']:
            raise ServerError('Login returned no session token')
        self._token=data['token']

    def apps(self):
        data=self.call('/api/v1/app/all')
        if not isinstance(data,list):raise ServerError('Invalid application list')
        return [sanitized(row,APP_FIELDS) for row in data]

    def app(self,app_id):
        return sanitized(self.call('/api/v1/app/detail/'+str(int(app_id))),APP_FIELDS)

    def versions(self,app_id):
        query=urllib.parse.urlencode(dict(appId=int(app_id),pageNum=1,pageSize=100))
        data=self.call('/api/v1/version/list?'+query)
        rows=data.get('list',[]) if isinstance(data,dict) else []
        return [sanitized(row,VERSION_FIELDS) for row in rows]

    def public_check(self,channel,version_code=0):
        query=urllib.parse.urlencode(dict(appKey=APP_KEY,platform='windows',versionCode=int(version_code),channel=channel))
        app=self.call('/api/v1/app/detail/2')
        if app.get('signEnabled')==1:
            stamp=str(int(time.time()*1000));nonce=uuid.uuid4().hex
            sign=hashlib.md5((APP_KEY+'|'+stamp+'|'+nonce+'|'+app['appSecret']).encode()).hexdigest()
            query+='&'+urllib.parse.urlencode(dict(timestamp=stamp,nonce=nonce,sign=sign))
        data=self.call('/api/v1/update/check?'+query,authenticated=False)
        return sanitized(data,UPDATE_FIELDS)

    def upload_draft(self,app_id,file,version,version_code,channel,notes='',progress=None):
        if not self._token:raise ServerError('Login required')
        file=Path(file)
        if not file.is_file() or file.suffix.casefold()!='.exe':raise ValueError('Expected existing EXE')
        if not 0<len(notes)<=2000:raise ValueError('Draft notes must be 1..2000 characters')
        if not 0<len(channel)<=20:raise ValueError('Invalid release channel')
        size=file.stat().st_size
        digest=hashlib.md5(file.read_bytes()).hexdigest()
        versions=self.versions(app_id)
        matches=[r for r in versions if r['versionName']==version and r['platform']=='windows' and r['channel']==channel]
        if matches:
            if len(matches)!=1 or matches[0]['fileSize']!=size or matches[0]['md5']!=digest:
                raise ServerError('Existing version differs; refusing to overwrite')
            return matches[0]
        app=self.app(app_id)
        if app['storageUsed']+size>app['quotaMb']*1024*1024:
            raise ServerError('Application quota exceeded; no old versions deleted')
        boundary='PeripheralBattery'+uuid.uuid4().hex
        import re
        if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):raise ValueError('Server version must contain only major.minor.patch digits')
        fields=dict(appId=str(int(app_id)),versionName=version,versionCode=str(int(version_code)),
                    platform='windows',channel=channel,forceUpdate='0',changelog=notes,grayPercent='100')
        prefix=b''
        for key,value in fields.items():
            prefix+=f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode('utf-8')
        if file.name!='PeripheralBattery.exe':raise ValueError('Upload filename must be PeripheralBattery.exe; supply the version separately')
        prefix+=f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode('ascii')
        suffix=f'\r\n--{boundary}--\r\n'.encode('ascii')
        connection=self._connection(timeout=300)
        try:
            connection.putrequest('POST','/api/v1/version/upload')
            connection.putheader('satoken',self._token)
            connection.putheader('Content-Type','multipart/form-data; boundary='+boundary)
            connection.putheader('Content-Length',str(len(prefix)+size+len(suffix)))
            connection.endheaders();connection.send(prefix)
            sent=0
            with file.open('rb') as stream:
                while block:=stream.read(128*1024):
                    connection.send(block);sent+=len(block)
                    if progress:progress(sent,size)
            connection.send(suffix)
            self._decode(connection.getresponse())
        finally:connection.close()
        matches=[r for r in self.versions(app_id) if r['versionName']==version and r['platform']=='windows' and r['channel']==channel]
        if len(matches)!=1 or matches[0]['fileSize']!=size or matches[0]['md5']!=digest:
            raise ServerError('Uploaded version did not match file metadata')
        if matches[0]['status']!=0:raise ServerError('Expected draft status after upload')
        return matches[0]

    def edit_draft_notes(self,version,notes):
        if version.get('status')!=0:raise ServerError('Refusing to edit non-draft version')
        if not 0<len(notes)<=2000:raise ValueError('Changelog must fit 2000 characters')
        body={key:version.get(key) for key in ('id','versionName','versionCode','platform','channel')}
        body.update(forceUpdate=0,changelog=notes,grayPercent=100,grayTargets=None,
                    updateTitle=None,updateButtonText=None,updateLink='pb-signed-exe:v1')
        return self.call('/api/v1/version/edit','PUT',body)

    def publish(self,version_id):
        return self.call('/api/v1/version/publish/'+str(int(version_id)),'PUT')
