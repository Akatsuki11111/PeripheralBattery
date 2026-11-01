import base64,hashlib,json,os,struct,subprocess,tempfile,time,unittest,io,sys
from pathlib import Path
from unittest.mock import patch,MagicMock
from update_config import save_config,load_config,validate
from signed_binary import MAGIC,verify_binary
from update_signing import canonical_json
from hidden_process import HiddenProcess
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
import updates

app=QApplication.instance() or QApplication([])


class PrivacyUpdateTests(unittest.TestCase):
    def test_publisher_version_field_cannot_contain_software_name(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        try:
            from publish_binary import validate_version
            validate_version('2.8.0','stable');validate_version('2.8.1-experimental.1','experimental')
            for version in ('v2.8.0','2.8.0 PeripheralBattery','PeripheralBattery-2.8.0','02.8.0','2.8'):
                with self.assertRaises(ValueError):validate_version(version,'stable')
        finally:sys.path.pop(0)

    def test_no_deployment_config_means_no_network(self):
        with patch('update_config.load_config',return_value=None),patch('updates._open_url') as opened:
            self.assertEqual(updates.check_updates('2.8.0',True)['status'],'unconfigured')
        opened.assert_not_called()

    def test_deployment_config_is_protected_and_round_trips(self):
        value=dict(origin='https://updates.example.test',app_key='peripheral-battery',app_secret='test-secret-only')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'PB_DATA_DIR':folder}):
            save_config(value);raw=(Path(folder)/'update-connection.dpapi').read_bytes()
            self.assertNotIn(b'updates.example',raw);self.assertNotIn(b'test-secret',raw)
            self.assertEqual(load_config(),value)
            (Path(folder)/'update-connection.dpapi').write_bytes(b'corrupted')
            with self.assertRaises(ValueError):load_config()

    def test_configuration_rejects_embedded_credentials_and_redirect_paths(self):
        for origin in ('https://user:password@example.test','https://example.test/path','https://example.test?q=1','file:///a','https://example.test#x'):
            with self.assertRaises(ValueError):validate(dict(origin=origin,app_secret='test'))

    def test_request_nonce_is_fresh_and_secret_is_not_transmitted(self):
        with patch('updates._REQUEST_SECRET','test-secret'):
            a=updates.signed_parameters(dict(appKey='peripheral-battery'));b=updates.signed_parameters(dict(appKey='peripheral-battery'))
        self.assertNotEqual(a['nonce'],b['nonce']);self.assertNotIn('test-secret',json.dumps(a))
        expected=hashlib.md5(('peripheral-battery|'+a['timestamp']+'|'+a['nonce']+'|test-secret').encode()).hexdigest()
        self.assertEqual(a['sign'],expected)

    def test_hidden_process_requests_no_console_and_hidden_startup(self):
        child=MagicMock();child.poll.return_value=0
        with patch('hidden_process.subprocess.Popen',return_value=child) as popen:
            process=HiddenProcess();process.start('example.exe',[])
            args=popen.call_args.kwargs
            self.assertTrue(args['creationflags']&subprocess.CREATE_NO_WINDOW)
            self.assertTrue(args['startupinfo'].dwFlags&subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(args['startupinfo'].wShowWindow,0);process.poll()


class BinaryReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name)
        cls.base=b'MZsigned-test-artifact'
        cls.payload=dict(app_key='peripheral-battery',platform='windows',channel='stable',version='2.8.0',
                         version_code=2080000,size=len(cls.base),sha256=hashlib.sha256(cls.base).hexdigest())
        (root/'payload').write_bytes(canonical_json(cls.payload))
        script=r'''
param([string]$InputPath,[string]$OutputPath)
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider(2048)
$rsa.PersistKeyInCsp=$false
try {
 $p=$rsa.ExportParameters($false)
 $signature=$rsa.SignData([IO.File]::ReadAllBytes($InputPath),[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1)
 $result=@{key=@{key_id='test-release';modulus_b64=[Convert]::ToBase64String($p.Modulus);exponent=65537};signature=[Convert]::ToBase64String($signature)}
 [IO.File]::WriteAllText($OutputPath,($result | ConvertTo-Json -Compress -Depth 4),(New-Object Text.UTF8Encoding($false)))
} finally {$rsa.Dispose()}
'''
        (root/'sign.ps1').write_text(script,encoding='utf-8')
        ps=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.run([str(ps),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(root/'sign.ps1'),'-InputPath',str(root/'payload'),'-OutputPath',str(root/'result')],check=True,capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        result=json.loads((root/'result').read_text(encoding='utf-8-sig'));cls.key=result['key']
        cls.envelope=dict(algorithm='rsa-pkcs1-sha256',key_id='test-release',payload=cls.payload,signature=result['signature'])
        encoded=json.dumps(cls.envelope,separators=(',',':')).encode()
        cls.data=cls.base+encoded+struct.pack('<I',len(encoded))+MAGIC
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_real_footer_signature_is_verified_without_changelog_code(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'test.exe';file.write_bytes(self.data)
            self.assertEqual(verify_binary(file,self.key,self.payload),self.payload)

    def test_content_signature_and_footer_tampering_are_rejected(self):
        variants=[b'MZunsigned',self.data[:-1],self.data[:-len(MAGIC)-4]+b'\xff'*4+MAGIC]
        for index in (3,len(self.base)+50):
            data=bytearray(self.data);data[index]^=1;variants.append(bytes(data))
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'test.exe'
            for data in variants:
                file.write_bytes(data)
                with self.assertRaises(ValueError):verify_binary(file,self.key,self.payload)

    def test_version_channel_and_app_binding_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'test.exe';file.write_bytes(self.data)
            for field in ('app_key','platform','channel','version','version_code'):
                expected={**self.payload,field:'wrong'}
                with self.assertRaises(ValueError):verify_binary(file,self.key,expected)

    def test_plain_release_notes_are_separate_from_signature_metadata(self):
        with patch('updates.SERVER_ORIGIN','https://updates.example.test'):
            info=updates._signed_release(dict(hasUpdate=True,versionName='2.8.0',versionCode=2080000,size=len(self.data),
                 channel='stable',downloadUrl='/api/v1/update/download/99',changelog='修复界面和隐私问题。',updateLink='pb-signed-exe:v1'),'stable')
        self.assertFalse(info['signature_verified']);self.assertTrue(info['signature_pending'])

    def test_numeric_server_version_and_channel_map_to_the_experimental_build(self):
        with patch('updates.SERVER_ORIGIN','https://updates.example.test'):
            info=updates._signed_release(dict(hasUpdate=True,versionName='2.8.3',versionCode=2080301,size=len(self.data),
                 channel='experimental',downloadUrl='/api/v1/update/download/99',changelog='界面修复',updateLink='pb-signed-exe:v1'),'experimental')
        self.assertEqual(info['latest'],'v2.8.3-experimental.1');self.assertTrue(info['prerelease'])

    def test_new_download_must_pass_rsa_before_replacing_an_existing_file(self):
        origin='https://updates.example.test'
        info=dict(status='available',latest='v2.8.0',signature_verified=False,signature_pending=True,
                  size=len(self.data),release_id=99,version_code=2080000,channel='stable',
                  download_url=origin+'/api/v1/update/download/99')
        class Response(io.BytesIO):
            def geturl(self):return info['download_url']
        with tempfile.TemporaryDirectory() as folder,patch('updates.SERVER_ORIGIN',origin),\
             patch('updates.check_updates',return_value=info),patch('updates._public_key',return_value=self.key):
            target=Path(folder)/'new.exe';target.write_bytes(b'existing')
            bad=bytearray(self.data);bad[5]^=1
            with patch('updates._open_url',return_value=Response(bytes(bad))),self.assertRaises(ValueError):
                updates.download_update('2.7.0',False,'v2.8.0',target,lambda *args:None)
            self.assertEqual(target.read_bytes(),b'existing');self.assertFalse(target.with_suffix('.part').exists())
            with patch('updates._open_url',return_value=Response(self.data)):
                result=updates.download_update('2.7.0',False,'v2.8.0',target,lambda *args:None)
            self.assertEqual(target.read_bytes(),self.data);self.assertEqual(result['sha256'],hashlib.sha256(self.data).hexdigest())
