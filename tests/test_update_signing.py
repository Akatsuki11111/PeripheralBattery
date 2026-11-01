import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from update_signing import ALGORITHM,canonical_json,verify_payload,verify_envelope


class CanonicalSigningTests(unittest.TestCase):
    def test_encoding_is_stable_and_unicode_is_signed_as_utf8(self):
        self.assertEqual(canonical_json({'z':5,'a':'更新'}),'{"a":"更新","z":5}'.encode('utf-8'))
        self.assertEqual(canonical_json({'z':5,'a':'更新'}),canonical_json({'a':'更新','z':5}))

    def test_ambiguous_and_unbounded_payloads_are_rejected(self):
        for payload in ({},{'x':1.0},{'x':float('nan')},{1:'bad'},{'x':2**64},{'x':'x'*8193}):
            with self.subTest(payload_type=type(payload)):
                with self.assertRaises(ValueError):canonical_json(payload)
        nested={'x':1}
        for _ in range(10):nested={'x':nested}
        with self.assertRaises(ValueError):canonical_json(nested)


@unittest.skipUnless(sys.platform=='win32','Windows CNG integration')
class WindowsSigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        root=Path(cls.tmp.name)
        cls.payload=dict(app_key='peripheral-battery',platform='windows',channel='stable',version='2.6.0',
                         version_code=2060000,release_id=42,download_path='/api/v1/update/download/42',
                         size=28599966,sha256='1'*64)
        (root/'payload.json').write_bytes(canonical_json(cls.payload))
        # Independent .NET signer. Private material is never persisted or printed.
        script=r'''
param([string]$InputPath,[string]$OutputPath)
$ErrorActionPreference='Stop'
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider(2048)
$rsa.PersistKeyInCsp=$false
try {
 $p=$rsa.ExportParameters($false)
 $signature=$rsa.SignData([IO.File]::ReadAllBytes($InputPath),[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1)
 $result=@{key=@{key_id='test-release';modulus_b64=[Convert]::ToBase64String($p.Modulus);exponent=65537};signature=[Convert]::ToBase64String($signature)}
 [IO.File]::WriteAllText($OutputPath,($result | ConvertTo-Json -Compress -Depth 4),(New-Object Text.UTF8Encoding($false)))
} finally {$rsa.Dispose()}
'''
        (root/'fixture.ps1').write_text(script,encoding='utf-8')
        powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(root/'fixture.ps1'),
                        '-InputPath',str(root/'payload.json'),'-OutputPath',str(root/'result.json')],
                       check=True,capture_output=True,timeout=20,creationflags=0x08000000)
        data=json.loads((root/'result.json').read_text(encoding='utf-8-sig'));cls.key=data['key'];cls.signature=data['signature']

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def envelope(self):
        return dict(algorithm=ALGORITHM,key_id=self.key['key_id'],payload=dict(self.payload),signature=self.signature)

    def test_real_dotnet_signature_is_accepted_by_windows_cng(self):
        self.assertTrue(verify_payload(self.payload,self.signature,self.key))
        self.assertEqual(verify_envelope(self.envelope(),self.key),self.payload)

    def test_any_release_identity_or_hash_tampering_is_rejected(self):
        for name,value in self.payload.items():
            tampered={**self.payload,name:value+1 if type(value) is int else value+'x'}
            with self.subTest(field=name):
                with self.assertRaises(ValueError):verify_payload(tampered,self.signature,self.key)

    def test_bad_signature_bytes_encoding_and_lengths_are_rejected(self):
        raw=bytearray(base64.b64decode(self.signature));raw[-1]^=1
        bad=[base64.b64encode(raw).decode('ascii'),self.signature[:-4],self.signature+'\n','?'*344,'AA==']
        for signature in bad:
            with self.subTest(signature_length=len(signature)):
                with self.assertRaises(ValueError):verify_payload(self.payload,signature,self.key)

    def test_algorithm_key_selector_and_envelope_shape_are_not_negotiable(self):
        for change in ({'algorithm':'none'},{'key_id':'other-publisher'},{'extra':'ignored?'}):
            with self.assertRaises(ValueError):verify_envelope({**self.envelope(),**change},self.key)
        for change in ({'exponent':3},{'modulus_b64':'AA=='},{'key_id':'../key'}):
            with self.assertRaises(ValueError):verify_payload(self.payload,self.signature,{**self.key,**change})

    def test_different_public_modulus_is_rejected(self):
        raw=bytearray(base64.b64decode(self.key['modulus_b64']));raw[-3]^=2
        wrong={**self.key,'modulus_b64':base64.b64encode(raw).decode('ascii')}
        with self.assertRaises(ValueError):verify_payload(self.payload,self.signature,wrong)
