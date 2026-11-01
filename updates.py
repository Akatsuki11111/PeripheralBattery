"""Optional deployment-configured updates; authenticated requests and signed EXEs."""
import base64
import binascii
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode,urlsplit
from update_signing import verify_envelope

SERVER_ORIGIN=''
RELEASES_URL=''
API_URL=''
APP_KEY='peripheral-battery'
PLATFORM='windows'
MANIFEST_MARKER='PB-SIGNED-MANIFEST:'
MAX_DOWNLOAD_SIZE=256*1024*1024
PAYLOAD_FIELDS={'app_key','platform','channel','version','version_code','release_id','download_path','size','sha256'}


def version_key(tag):
    match=re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?',str(tag))
    if not match:return None
    pre=match[4]
    return tuple(int(match[i]) for i in (1,2,3))+(1 if pre is None else 0,tuple((0,int(s)) if s.isdigit() else (1,s) for s in pre.split('.')) if pre else ())


def _json(raw):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('更新信息含重复字段')
            result[key]=value
        return result
    def invalid_constant(value):raise ValueError('更新信息含无效数字')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid_constant)
    except (UnicodeError,TypeError,json.JSONDecodeError) as error:raise ValueError('更新服务器返回格式无效') from error


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        # VersionHub serves binaries directly; refuse redirects before receiving
        # bytes from any unbound endpoint or origin.
        return None


def _open_url(request,timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request,timeout=timeout)


def _public_key():
    path=Path(__file__).with_name('assets')/'update-public-key.json'
    try:
        raw=path.read_bytes()
        if len(raw)>4096:raise ValueError('更新发布公钥文件过大')
        key=_json(raw)
    except OSError as error:raise ValueError('缺少固定的更新发布公钥') from error
    if type(key) is not dict:raise ValueError('更新发布公钥无效')
    return key


def _download_url(value,release_id):
    path='/api/v1/update/download/'+str(release_id)
    expected=SERVER_ORIGIN+path
    if value not in (path,expected):raise ValueError('更新下载地址与已签名版本不符')
    parsed=urlsplit(expected)
    if parsed.scheme not in ('http','https') or parsed.netloc!=urlsplit(SERVER_ORIGIN).netloc or parsed.query or parsed.fragment:
        raise ValueError('更新下载地址异常')
    return expected


def _signed_release(data,channel):
    if type(data) is not dict or type(data.get('hasUpdate')) is not bool:
        raise ValueError('更新服务器返回格式无效')
    if not data['hasUpdate']:return None
    changelog=data.get('changelog')
    if type(changelog) is not str or len(changelog)>4096:
        raise ValueError('更新发布签名缺失或格式无效')
    lines=changelog.rstrip('\r\n').splitlines()
    if MANIFEST_MARKER not in changelog and data.get('updateLink')=='pb-signed-exe:v1':
        return _binary_release(data,channel)
    if not lines or not lines[-1].startswith(MANIFEST_MARKER) or changelog.count(MANIFEST_MARKER)!=1:
        raise ValueError('旧格式更新发布签名位置无效')
    encoded=lines[-1][len(MANIFEST_MARKER):]
    if len(encoded)>4096:raise ValueError('更新发布签名过大')
    try:
        raw=base64.b64decode(encoded,validate=True)
        if base64.b64encode(raw).decode('ascii')!=encoded:raise ValueError('更新签名编码不规范')
        envelope=_json(raw)
    except (ValueError,binascii.Error) as error:raise ValueError('更新发布签名编码无效') from error
    payload=verify_envelope(envelope,_public_key())
    if type(payload) is not dict or set(payload)!=PAYLOAD_FIELDS:
        raise ValueError('已签名更新字段不完整')
    if payload['app_key']!=APP_KEY or payload['platform']!=PLATFORM or payload['channel']!=channel:
        raise ValueError('更新签名不属于当前软件、平台或通道')
    version=payload['version']
    key=version_key(version)
    if type(version) is not str or version.startswith('v') or key is None or channel=='stable' and key[3]==0:
        raise ValueError('已签名更新版本号无效')
    for name in ('version_code','release_id','size'):
        if type(payload[name]) is not int or not 0<payload[name]<2**63:
            raise ValueError('已签名更新数值无效')
    if payload['size']>MAX_DOWNLOAD_SIZE:raise ValueError('安装文件大小不在支持范围')
    if type(payload['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}',payload['sha256']):
        raise ValueError('更新缺少已签名 SHA256')
    expected_path='/api/v1/update/download/'+str(payload['release_id'])
    if payload['download_path']!=expected_path:raise ValueError('更新版本编号与下载路径不符')
    if (data.get('versionName')!=version or type(data.get('versionCode')) is not int or
            data['versionCode']!=payload['version_code'] or data.get('channel')!=channel or
            type(data.get('size')) is not int or data['size']!=payload['size']):
        raise ValueError('更新服务器信息与发布签名不符')
    download_url=_download_url(data.get('downloadUrl'),payload['release_id'])
    return {'latest':'v'+version,'url':RELEASES_URL,'prerelease':channel=='experimental',
            'download_url':download_url,'size':payload['size'],'sha256':payload['sha256'],
            'release_id':payload['release_id'],'version_code':payload['version_code'],
            'channel':channel,'signature_verified':True}


def _binary_release(data,channel):
    version=data.get('versionName');key=version_key(version)
    if type(version) is not str or version.startswith('v') or key is None or channel=='stable' and key[3]==0:
        raise ValueError('更新版本号无效')
    for field in ('versionCode','size'):
        if type(data.get(field)) is not int or not 0<data[field]<2**63:raise ValueError('更新数值无效')
    if data['size']>MAX_DOWNLOAD_SIZE or data.get('channel')!=channel:raise ValueError('更新大小或通道无效')
    value=data.get('downloadUrl');path=urlsplit(value).path if isinstance(value,str) else ''
    match=re.fullmatch(r'/api/v1/update/download/([1-9][0-9]*)',path)
    if not match:raise ValueError('更新下载标识无效')
    rid=int(match[1]);url=_download_url(value,rid)
    return dict(latest='v'+version,url='',prerelease=channel=='experimental',download_url=url,
                size=data['size'],release_id=rid,version_code=data['versionCode'],channel=channel,
                signature_verified=False,signature_pending=True)


def configure_runtime():
    from update_config import load_config
    global SERVER_ORIGIN,API_URL,RELEASES_URL,APP_KEY,_REQUEST_SECRET
    config=load_config()
    if config is None:return False
    SERVER_ORIGIN=config['origin'];API_URL=SERVER_ORIGIN+'/api/v1/update/check'
    RELEASES_URL='';APP_KEY=config['app_key'];_REQUEST_SECRET=config['app_secret']
    return True


_REQUEST_SECRET=''


def signed_parameters(values):
    if not _REQUEST_SECRET:raise ValueError('缺少本机更新请求签名配置')
    stamp=str(int(time.time()*1000));nonce=uuid.uuid4().hex
    sign=hashlib.md5((APP_KEY+'|'+stamp+'|'+nonce+'|'+_REQUEST_SECRET).encode('utf-8')).hexdigest()
    return {**values,'timestamp':stamp,'nonce':nonce,'sign':sign}


def _fetch_channel(current,channel):
    # Query the published head and compare SemVer locally. No device identity,
    # inventory, management token, appSecret or password is sent.
    url=API_URL+'?'+urlencode(signed_parameters(dict(appKey=APP_KEY,platform=PLATFORM,versionCode=0,channel=channel)))
    request=urllib.request.Request(url,headers={'Accept':'application/json','Accept-Encoding':'identity',
                                               'User-Agent':'PeripheralBattery/'+current})
    with _open_url(request,timeout=7) as response:
        if response.geturl()!=url:raise ValueError('更新服务器发生未允许的重定向')
        raw=response.read(65537)
        if len(raw)>65536:raise ValueError('更新服务器返回数据过大')
    result=_json(raw)
    if type(result) is not dict or type(result.get('code')) is not int or result['code']!=0:
        raise ValueError('更新服务器未返回有效发布信息')
    return _signed_release(result.get('data'),channel)


def check_updates(current,include_prereleases=True):
    from settings import RELEASE_CHANNEL
    if not configure_runtime():return {'status':'unconfigured','message':'未配置更新服务，请导入部署者提供的更新配置','url':''}
    local=version_key(current)
    if local is None:raise ValueError('当前版本格式无效')
    try:
        candidates=[]
        for channel in (('stable','experimental') if include_prereleases else ('stable',)):
            release=_fetch_channel(current,channel)
            if release:candidates.append(release)
    except urllib.error.HTTPError as error:
        if error.code in (301,302,303,307,308):raise ValueError('更新服务器返回重定向，已停止检查') from error
        if error.code in (403,429):raise ValueError('更新服务器暂时限制请求，请稍后重试') from error
        raise ValueError('更新服务器检查失败，HTTP '+str(error.code)) from error
    except (urllib.error.URLError,TimeoutError,OSError) as error:
        raise ValueError('无法连接版本管理服务器，请检查网络后重试') from error
    if not candidates:return {'status':'no_release','message':'服务器暂无所选通道的发布版本','url':RELEASES_URL}
    chosen=max(candidates,key=lambda row:version_key(row['latest']))
    key=version_key(chosen['latest'])
    promotes_stable=key==local and RELEASE_CHANNEL=='experimental' and not chosen['prerelease'] and key[3]==1
    if key<=local and not promotes_stable:
        status='current' if key==local else 'ahead'
        return {**chosen,'status':status,'message':'当前已是所选通道最新版本' if status=='current' else '当前版本较新，服务器最新为 '+chosen['latest']}
    return {**chosen,'status':'available','message':'发现新版 '+chosen['latest']+(' · 发布签名已验证' if chosen.get('signature_verified') else ' · 下载后验证安装包签名')}


def download_update(current,include_prereleases,tag,destination,progress):
    info=check_updates(current,include_prereleases)
    if info.get('status')!='available' or info.get('latest')!=tag:
        raise ValueError('发布版本已改变，请重新检查更新')
    if not (info.get('signature_verified') is True or info.get('signature_pending') is True):raise ValueError('更新校验方式无效，拒绝下载')
    digest=info.get('sha256')
    if info.get('signature_verified') and (type(digest) is not str or not re.fullmatch('[a-f0-9]{64}',digest)):raise ValueError('缺少可信 SHA256，未下载')
    if type(info.get('size')) is not int or not 0<info['size']<=MAX_DOWNLOAD_SIZE:
        raise ValueError('安装文件大小不在支持范围')
    release_id=info.get('release_id')
    if type(release_id) is not int or not 0<release_id<2**63:raise ValueError('更新版本编号无效')
    url=_download_url(info.get('download_url'),release_id)
    target=Path(destination);part=target.with_suffix('.part');total=0;hasher=hashlib.sha256()
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        request=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'PeripheralBattery/'+current})
        with _open_url(request,timeout=20) as response,part.open('wb') as stream:
            if response.geturl()!=url:raise ValueError('下载地址发生未允许的重定向')
            progress(0,info['size'])
            while True:
                block=response.read(128*1024)
                if not block:break
                total+=len(block)
                if total>info['size']:raise ValueError('下载大小与已签名发布信息不符')
                stream.write(block);hasher.update(block);progress(total,info['size'])
        if total!=info['size']:raise ValueError('下载文件大小不符，未安装')
        if info.get('signature_pending'):
            from signed_binary import verify_binary
            verify_binary(part,_public_key(),dict(app_key=APP_KEY,platform=PLATFORM,channel=info['channel'],
                          version=tag.removeprefix('v'),version_code=info['version_code']))
        elif hasher.hexdigest()!=digest:raise ValueError('下载文件与已签名 SHA256 不符，未安装')
        os.replace(part,target)
        return {'path':str(target),'sha256':hasher.hexdigest(),'version':tag,'size':total}
    except Exception:
        part.unlink(missing_ok=True);raise
