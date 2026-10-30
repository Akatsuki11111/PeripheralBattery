"""Public GitHub Releases metadata only. Never downloads or executes programs."""
import json
import re
import urllib.request
import urllib.error
import hashlib
import os
from pathlib import Path
from urllib.parse import quote,urlsplit

REPOSITORY='Akatsuki11111/PeripheralBattery'
RELEASES_URL='https://github.com/'+REPOSITORY+'/releases'
API_URL='https://api.github.com/repos/'+REPOSITORY+'/releases?per_page=100'


def version_key(tag):
    match=re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?',str(tag))
    if not match:return None
    pre=match[4]
    return tuple(int(match[i]) for i in (1,2,3))+(1 if pre is None else 0,tuple((0,int(s)) if s.isdigit() else (1,s) for s in pre.split('.')) if pre else ())


def select_release(rows,current,include_prereleases=True,current_prerelease=False):
    local=version_key(current)
    if local is None:raise ValueError('当前版本格式无效')
    eligible=[]
    for release in rows:
        if not isinstance(release,dict) or release.get('draft') or not release.get('published_at'):continue
        tag=release.get('tag_name','');key=version_key(tag)
        if key is None or not include_prereleases and (release.get('prerelease') or key[3]==0):continue
        eligible.append((key,release))
    if not eligible:return {'status':'no_release','message':'GitHub 暂无所选通道的发布版本','url':RELEASES_URL}
    key,release=max(eligible,key=lambda row:row[0]);tag=release['tag_name']
    url=RELEASES_URL+'/tag/'+quote(tag,safe='')
    result={'latest':tag,'url':url,'prerelease':bool(release.get('prerelease'))}
    promotes_stable=key==local and current_prerelease and not release.get('prerelease') and key[3]==1
    if key<=local and not promotes_stable:
        return {**result,'status':'current' if key==local else 'ahead','message':'当前已是所选通道最新版本' if key==local else '当前版本较新，所选通道最新为 '+tag}
    expected='/'+REPOSITORY+'/releases/download/'+quote(tag,safe='')+'/'
    for asset in release.get('assets',[]):
        name=asset.get('name','');parsed=urlsplit(asset.get('browser_download_url',''))
        if (isinstance(name,str) and re.fullmatch(r'PeripheralBattery-v[0-9A-Za-z.+_-]+\.exe',name) and
            asset.get('state')=='uploaded' and type(asset.get('size')) is int and asset['size']>0 and
            parsed.scheme=='https' and parsed.netloc=='github.com' and not parsed.query and not parsed.fragment and
            parsed.path==expected+quote(name,safe='')):
            digest=asset.get('digest','')
            return {**result,'status':'available','message':'发现新版 '+tag,
                    'download_url':asset['browser_download_url'],'size':asset['size'],
                    'sha256':digest[7:] if isinstance(digest,str) and re.fullmatch('sha256:[a-f0-9]{64}',digest) else ''}
    return {**result,'status':'unavailable','message':'发现新版 '+tag+'，但尚无可用 Windows 程序；可查看发布页'}


def check_updates(current,include_prereleases=True):
    from settings import RELEASE_CHANNEL
    rows=[]
    try:
        for page in range(1,4):
            req=urllib.request.Request(API_URL+'&page='+str(page),headers={'Accept':'application/vnd.github+json','User-Agent':'PeripheralBattery/'+current})
            with urllib.request.urlopen(req,timeout=7) as response:
                if urlsplit(response.geturl()).hostname!='api.github.com':raise ValueError('更新服务地址异常')
                raw=response.read(2_000_001)
                if len(raw)>2_000_000:raise ValueError('更新服务返回数据过大')
                data=json.loads(raw)
                if not isinstance(data,list):raise ValueError('更新服务返回格式无效')
                rows.extend(data)
                if 'rel="next"' not in response.headers.get('Link',''):return select_release(rows,current,include_prereleases,RELEASE_CHANNEL=='experimental')
        raise ValueError('发布记录过多，请直接查看 GitHub Releases')
    except urllib.error.HTTPError as error:
        if error.code in (403,429):raise ValueError('GitHub 暂时限制请求，请稍后重试') from error
        raise ValueError('GitHub 更新检查失败，HTTP '+str(error.code)) from error
    except (urllib.error.URLError,TimeoutError,OSError) as error:raise ValueError('无法连接 GitHub，请检查网络后重试') from error


def download_update(current,include_prereleases,tag,destination,progress):
    info=check_updates(current,include_prereleases)
    if info.get('status')!='available' or info.get('latest')!=tag:raise ValueError('发布版本已改变，请重新检查更新')
    if not info.get('sha256'):raise ValueError('该发布缺少可验证的 SHA256，请在 GitHub 手动下载')
    if not 0<info['size']<=256*1024*1024:raise ValueError('安装文件大小不在支持范围')
    target=Path(destination);part=target.with_suffix('.part');total=0;hasher=hashlib.sha256()
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        req=urllib.request.Request(info['download_url'],headers={'User-Agent':'PeripheralBattery/'+current})
        with urllib.request.urlopen(req,timeout=20) as response,part.open('wb') as stream:
            final=urlsplit(response.geturl())
            if final.scheme!='https' or final.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
                raise ValueError('下载被重定向到非 GitHub 发布地址')
            while True:
                block=response.read(128*1024)
                if not block:break
                total+=len(block)
                if total>info['size']:raise ValueError('下载大小与发布信息不符')
                stream.write(block);hasher.update(block);progress(total,info['size'])
        if total!=info['size'] or hasher.hexdigest()!=info['sha256']:raise ValueError('下载校验失败，未安装')
        os.replace(part,target)
        return {'path':str(target),'sha256':info['sha256'],'version':tag,'size':total}
    except Exception:
        part.unlink(missing_ok=True);raise
