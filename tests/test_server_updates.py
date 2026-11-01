import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
from urllib.parse import parse_qs,urlsplit
import updates

FIXTURES=Path(__file__).with_name('fixtures')
PUBLIC_KEY=json.loads((FIXTURES/'update-test-public-key.json').read_text(encoding='utf-8'))
ENVELOPE=json.loads((FIXTURES/'update-manifest.json').read_text(encoding='utf-8'))
PAYLOAD=ENVELOPE['payload']


def release(envelope=None,**changes):
    envelope=copy.deepcopy(ENVELOPE if envelope is None else envelope)
    payload=envelope['payload']
    encoded=base64.b64encode(json.dumps(envelope,ensure_ascii=False,separators=(',',':')).encode()).decode()
    row=dict(hasUpdate=True,versionName=payload['version'],versionCode=payload['version_code'],channel=payload['channel'],
             size=payload['size'],downloadUrl=payload['download_path'],md5='untrusted-and-unused',
             changelog='测试更新说明\n'+updates.MANIFEST_MARKER+encoded)
    row.update(changes);return row


def response_json(data):
    return json.dumps({'code':0,'message':'ok','data':data},ensure_ascii=False).encode()


class Response(io.BytesIO):
    def __init__(self,raw,url):super().__init__(raw);self.url=url
    def geturl(self):return self.url


class ServerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.key_patch=patch('updates._public_key',return_value=PUBLIC_KEY);self.key_patch.start()
    def tearDown(self):self.key_patch.stop()

    def test_real_signed_manifest_is_verified_and_bound(self):
        info=updates._signed_release(release(),'stable')
        self.assertEqual(info['latest'],'v2.6.0');self.assertTrue(info['signature_verified'])
        self.assertEqual(info['sha256'],hashlib.sha256(b'new').hexdigest())
        self.assertEqual(info['download_url'],updates.SERVER_ORIGIN+'/api/v1/update/download/999999')

    def test_absent_or_misplaced_signature_rejects_even_with_md5(self):
        for notes in ('plain notes',updates.MANIFEST_MARKER+'invalid',release()['changelog']+'\nafter signature',
                      release()['changelog']+'\n'+release()['changelog']):
            with self.subTest(notes=notes[:30]),self.assertRaises(ValueError):
                updates._signed_release(release(changelog=notes),'stable')

    def test_modified_payload_signature_or_unknown_key_is_rejected(self):
        for field,value in [('sha256','0'*64),('version','9.0.0'),('channel','experimental')]:
            envelope=copy.deepcopy(ENVELOPE);envelope['payload'][field]=value
            with self.assertRaises(ValueError):updates._signed_release(release(envelope),'stable')
        envelope=copy.deepcopy(ENVELOPE);envelope['signature']='A'+envelope['signature'][1:]
        with self.assertRaises(ValueError):updates._signed_release(release(envelope),'stable')
        envelope=copy.deepcopy(ENVELOPE);envelope['key_id']='not-the-pinned-key'
        with self.assertRaises(ValueError):updates._signed_release(release(envelope),'stable')

    def test_outer_version_size_channel_and_id_cannot_override_signature(self):
        changes=[dict(versionName='9.0.0'),dict(versionCode=3),dict(versionCode=True),dict(channel='experimental'),
                 dict(size=4),dict(size=True),dict(downloadUrl='/api/v1/update/download/1')]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                updates._signed_release(release(**change),'stable')
        with self.assertRaises(ValueError):updates._signed_release(release(),'experimental')

    def test_download_addresses_cannot_switch_origin_or_use_query_fragment(self):
        paths=['https://github.com/test.exe','http://evil.example/a.exe',
               updates.SERVER_ORIGIN+'@evil.example/api/v1/update/download/999999',
               '//updates.example.invalid:8089/api/v1/update/download/999999',
               '/api/v1/update/download/999999?token=x','/api/v1/update/download/999999#fragment']
        for value in paths:
            with self.subTest(value=value),self.assertRaises(ValueError):
                updates._signed_release(release(downloadUrl=value),'stable')

    def test_payload_is_bound_to_current_app_platform_and_valid_numbers(self):
        # Bindings are tested separately from signature math; a valid signer
        # cannot accidentally authorize the wrong app/platform/channel.
        for change in [dict(app_key='other-app'),dict(platform='android'),dict(channel='default'),
                       dict(version_code=True),dict(release_id=0),dict(size=0),dict(size=updates.MAX_DOWNLOAD_SIZE+1),
                       dict(sha256='missing'),dict(download_path='/elsewhere'),dict(version='bad')]:
            payload={**PAYLOAD,**change}
            with self.subTest(change=change),patch('updates.verify_envelope',return_value=payload),self.assertRaises(ValueError):
                updates._signed_release(release(),'stable')

    def test_both_channels_are_compared_by_semver_and_stable_never_downgrades(self):
        stable=updates._signed_release(release(),'stable')
        experimental={**stable,'latest':'v2.6.1-experimental.1','prerelease':True,'channel':'experimental'}
        def fetch(current,channel):return stable if channel=='stable' else experimental
        with patch('updates._fetch_channel',side_effect=fetch) as check,patch('settings.RELEASE_CHANNEL','stable'):
            result=updates.check_updates('2.5.0',False)
            self.assertEqual(result['latest'],'v2.6.0');self.assertEqual(check.call_count,1)
            self.assertEqual(updates.check_updates('2.5.0',True)['latest'],'v2.6.1-experimental.1')
            self.assertEqual(updates.check_updates('2.6.1-experimental.1',False)['status'],'ahead')
            self.assertEqual(updates.check_updates('2.6.0',False)['status'],'current')

    def test_old_numeric_experimental_can_promote_to_same_stable_version(self):
        stable=updates._signed_release(release(),'stable')
        with patch('updates._fetch_channel',return_value=stable),patch('settings.RELEASE_CHANNEL','experimental'):
            self.assertEqual(updates.check_updates('2.6.0',False)['status'],'available')

    def test_empty_channels_are_not_errors_and_no_github_fallback_exists(self):
        with patch('updates._fetch_channel',return_value=None) as fetch:
            self.assertEqual(updates.check_updates('2.5.0',True)['status'],'no_release')
            self.assertEqual(fetch.call_count,2)
        self.assertIsNone(updates._signed_release({'hasUpdate':False,'versionName':None},'stable'))

    def test_metadata_request_is_fixed_and_contains_no_identity_or_credentials(self):
        captured=[]
        def open_url(request,timeout):
            captured.append(request)
            return Response(response_json(release()),request.full_url)
        with patch('updates._open_url',side_effect=open_url):result=updates._fetch_channel('2.5.0','stable')
        self.assertEqual(result['latest'],'v2.6.0');request=captured[0]
        parsed=urlsplit(request.full_url);self.assertEqual(parsed.scheme+'://'+parsed.netloc,updates.SERVER_ORIGIN)
        self.assertEqual(parse_qs(parsed.query),dict(appKey=['peripheral-battery'],platform=['windows'],versionCode=['0'],channel=['stable']))
        text=json.dumps(dict(request.headers)).lower()
        for word in ('satoken','password','authorization','deviceid','appsecret','github'):self.assertNotIn(word,text)

    def test_metadata_redirect_malformed_response_and_duplicates_fail_closed(self):
        def redirected(request,timeout):return Response(response_json(release()),'http://evil.example')
        with patch('updates._open_url',side_effect=redirected),self.assertRaises(ValueError):updates._fetch_channel('2.5.0','stable')
        for raw in (b'not JSON',b'{"code":0,"code":1,"data":{}}',b'{"code":false,"data":{}}',b'x'*65537):
            with patch('updates._open_url',side_effect=lambda request,timeout:Response(raw,request.full_url)),self.assertRaises(ValueError):
                updates._fetch_channel('2.5.0','stable')
        req=updates.urllib.request.Request(updates.SERVER_ORIGIN)
        self.assertIsNone(updates._NoRedirect().redirect_request(req,None,302,'redirect',{},'http://evil.example'))

    def test_failed_server_does_not_fall_back_to_github(self):
        with patch('updates._open_url',side_effect=urllib.error.URLError('offline')) as opened,self.assertRaisesRegex(ValueError,'版本管理服务器'):
            updates.check_updates('2.5.0',True)
        self.assertEqual(opened.call_count,1)
        self.assertTrue(opened.call_args.args[0].full_url.startswith(updates.SERVER_ORIGIN))

    def test_download_verifies_signed_sha_and_reports_progress(self):
        info={**updates._signed_release(release(),'stable'),'status':'available'};events=[]
        def opened(request,timeout):return Response(b'new',request.full_url)
        with tempfile.TemporaryDirectory() as folder,patch('updates.check_updates',return_value=info),patch('updates._open_url',side_effect=opened):
            target=Path(folder)/'new.exe';result=updates.download_update('2.5.0',False,'v2.6.0',target,lambda n,total:events.append((n,total)))
            self.assertEqual(target.read_bytes(),b'new');self.assertEqual(result['sha256'],PAYLOAD['sha256'])
            self.assertEqual(events[0],(0,3));self.assertEqual(events[-1],(3,3))

    def test_corrupt_truncated_oversized_or_redirected_download_never_replaces_file(self):
        info={**updates._signed_release(release(),'stable'),'status':'available'}
        for content,url in [(b'bad',None),(b'ne',None),(b'new!',None),(b'new','http://evil.example/file')]:
            with tempfile.TemporaryDirectory() as folder,patch('updates.check_updates',return_value=info),\
                 patch('updates._open_url',side_effect=lambda request,timeout:Response(content,url or request.full_url)):
                target=Path(folder)/'new.exe';target.write_bytes(b'existing')
                with self.assertRaises(ValueError):updates.download_update('2.5.0',False,'v2.6.0',target,lambda *args:None)
                self.assertEqual(target.read_bytes(),b'existing');self.assertFalse(target.with_suffix('.part').exists())

    def test_unverified_manifest_or_changed_release_cannot_start_download(self):
        base={**updates._signed_release(release(),'stable'),'status':'available'}
        for change in [dict(latest='v2.7.0'),dict(signature_verified=False),dict(sha256=''),dict(download_url='http://evil.example/a')]:
            with tempfile.TemporaryDirectory() as folder,patch('updates.check_updates',return_value={**base,**change}),\
                 patch('updates._open_url') as opened,self.assertRaises(ValueError):
                updates.download_update('2.5.0',False,'v2.6.0',Path(folder)/'x.exe',lambda *args:None)
            opened.assert_not_called()
