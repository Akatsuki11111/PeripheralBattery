"""Detached release signature carried in a bounded EXE footer, not release notes."""
import hashlib,json,struct
from pathlib import Path
from update_signing import verify_envelope

MAGIC=b'PB_RELEASE_RSA_V1'
FIELDS={'app_key','platform','channel','version','version_code','size','sha256'}


def verify_binary(path,public_key,expected):
    path=Path(path);size=path.stat().st_size;footer_size=len(MAGIC)+4
    if size<footer_size:raise ValueError('安装包缺少发布签名')
    with path.open('rb') as stream:
        stream.seek(-footer_size,2);tail=stream.read(footer_size)
        if tail[4:]!=MAGIC:raise ValueError('安装包缺少发布签名')
        length=struct.unpack('<I',tail[:4])[0]
        if not 1<=length<=8192 or length+footer_size>=size:raise ValueError('安装包签名格式无效')
        stream.seek(-(length+footer_size),2)
        try:envelope=json.loads(stream.read(length))
        except (ValueError,UnicodeError):raise ValueError('安装包签名格式无效') from None
        payload=verify_envelope(envelope,public_key)
        if set(payload)!=FIELDS or type(payload.get('size')) is not int or payload['size']!=size-length-footer_size:
            raise ValueError('安装包签名绑定无效')
        if any(payload.get(k)!=expected.get(k) for k in ('app_key','platform','channel','version','version_code')):
            raise ValueError('安装包版本、通道或应用签名不符')
        stream.seek(0);digest=hashlib.sha256();remaining=payload['size']
        while remaining:
            block=stream.read(min(131072,remaining))
            if not block:raise ValueError('安装包不完整')
            digest.update(block);remaining-=len(block)
        if digest.hexdigest()!=payload.get('sha256'):raise ValueError('安装包内容校验失败')
    return payload
