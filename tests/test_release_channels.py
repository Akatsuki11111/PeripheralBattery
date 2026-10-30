import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile,time,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from models import Device
from settings import Settings,DeviceStore,atomic_json
from startup import StartupState
from ui import Flyout
from worker import execute,probe

app=QApplication.instance() or QApplication([])


class ReleaseChannelTests(unittest.TestCase):
    def test_stable_removes_experiment_controls_and_experimental_keeps_them(self):
        with tempfile.TemporaryDirectory() as tmp,patch('startup.state',return_value=StartupState(False,False,False,False)):
            for enabled in (False,True):
                with patch('ui.EXPERIMENTAL_ENABLED',enabled):
                    flyout=Flyout(Settings(Path(tmp)/'settings.json'))
                    self.assertEqual(flyout.research_button is not None,enabled)
                    self.assertEqual(flyout.learning_button is not None,enabled)
                    flyout.hide();flyout.deleteLater();app.processEvents()

    def test_stable_worker_rejects_experiment_operations_before_import(self):
        with patch('worker.EXPERIMENTAL_ENABLED',False):
            for operation in ('research-sample','research-inspect'):
                with self.assertRaisesRegex(ValueError,'正式版'):execute({'operation':operation})
            with self.assertRaisesRegex(ValueError,'正式版'):probe({'device':{},'infos':[],'backend':'learned'})

    def test_stable_ignores_cached_experimental_values_and_incoming_mapping(self):
        with tempfile.TemporaryDirectory() as tmp,patch('settings.EXPERIMENTAL_ENABLED',False):
            path=Path(tmp)/'devices.json'
            d=Device('experimental','NuPhy','Keyboard','keyboard',42,False,True,True,
                     observed_at=time.time(),last_seen=time.time(),confidence='experimental',identity='exp',
                     last_percent=42,last_observed_at=time.time())
            atomic_json(path,[d.to_dict()]);store=DeviceStore(path)
            self.assertIsNone(store.snapshot()[0].percent);self.assertIsNone(store.snapshot()[0].last_percent)
            store.reconcile([Device('experimental','NuPhy','Keyboard','keyboard',identity='exp')])
            store.apply_readings('exp',[dict(percent=53,confidence='experimental',connected=True)])
            self.assertIsNone(store.snapshot()[0].percent);self.assertIsNone(store.snapshot()[0].last_percent)
