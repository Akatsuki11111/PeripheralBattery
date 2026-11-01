import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from updates import version_key
from installer import stage_info,prepare_update,replace_targets,apply_update


class UpdatesTests(unittest.TestCase):
    def test_numeric_order_and_prerelease_semantics(self):
        self.assertGreater(version_key('v2.10.0'),version_key('v2.9.0'))
        self.assertGreater(version_key('2.4.0'),version_key('2.4.0-rc.10'))
        self.assertGreater(version_key('2.4.0-rc.10'),version_key('2.4.0-rc.2'))
        self.assertIsNone(version_key('v2.4'))

    def test_installer_preparation_revalidates_and_preserves_settings(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'PB_DATA_DIR':folder}):
            root=Path(folder);stage=root/'updates'/('a'*32+'.exe');stage.parent.mkdir();stage.write_bytes(b'new')
            origin=root/'PeripheralBattery.exe';origin.write_bytes(b'old');settings=root/'settings.json';settings.write_text('unchanged')
            info={'path':str(stage),'sha256':hashlib.sha256(b'new').hexdigest(),'version':'v2.5.0'}
            self.assertEqual(stage_info(info),stage)
            with patch('installer.sys.frozen',True,create=True),patch('installer.sys.executable',str(origin)),patch('installer.subprocess.Popen') as launch:
                prepare_update(info);self.assertEqual(launch.call_args.args[0][1],'--apply-update')
            self.assertEqual(settings.read_text(),'unchanged');self.assertEqual(origin.read_bytes(),b'old')
            stage.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):stage_info(info)

    def test_file_replacement_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'new.exe';stage.write_bytes(b'new');a=root/'a.exe';b=root/'b.exe';a.write_bytes(b'old');b.write_bytes(b'old')
            replace_targets(stage,[a,b]);self.assertEqual(a.read_bytes(),b'new');self.assertEqual(b.read_bytes(),b'new')
            a.write_bytes(b'old');b.write_bytes(b'old');real=os.replace
            def fail(src,target):
                if Path(target)==b and str(src).endswith('.new'):raise OSError('locked')
                return real(src,target)
            with patch('installer.os.replace',side_effect=fail),patch('installer.time.monotonic',side_effect=[0,0,31]):
                with self.assertRaises(OSError):replace_targets(stage,[a,b])
            self.assertEqual(a.read_bytes(),b'old');self.assertEqual(b.read_bytes(),b'old')

    def test_helper_replaces_only_test_targets_and_restarts(self):
        import json
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'PB_DATA_DIR':folder}):
            root=Path(folder);stage=root/'updates'/('a'*32+'.exe');stage.parent.mkdir();stage.write_bytes(b'new')
            origin=root/'PeripheralBattery.exe';origin.write_bytes(b'old')
            fixed=root/'bin/PeripheralBattery.exe';fixed.parent.mkdir();fixed.write_bytes(b'old')
            config=root/'settings.json';config.write_text('preserve')
            request=stage.parent/('b'*32+'.install.json')
            request.write_text(json.dumps({'download':{'path':str(stage),'sha256':hashlib.sha256(b'new').hexdigest(),'version':'v2.5.0'},'origin':str(origin),'pid':0}))
            with patch('installer.subprocess.Popen') as launch:self.assertEqual(apply_update(request),0)
            self.assertEqual(origin.read_bytes(),b'new');self.assertEqual(fixed.read_bytes(),b'new');self.assertEqual(config.read_text(),'preserve')
            self.assertEqual(launch.call_args.args[0],[str(origin)]);self.assertFalse(request.exists())
