import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from catalog import backend_for,recognize
from models import Device
from settings import DeviceStore,Settings
from worker import probe
from research import sample
from valkyrie_ry import parse_status,MODEL_IDS


def response(online=True,model_id=3090):
    raw=bytearray(65);raw[3]=67;raw[5]=0 if online else 1;raw[6]=1;raw[7]=2
    return {'status':parse_status(raw),'model_id':model_id if online else None,
            'model':MODEL_IDS.get(model_id) if online else None,'charging':None}


def group():
    d=Device('rx','Unknown','2.4G Wireless Mouse','mouse',vid=0x3151,pid=0x5045,
             receiver=True,identity='a'*24,fingerprint='rx')
    return {'device':d.to_dict(),'backend':'valkyrie_ry','infos':[{'path':'00','vendor_id':0x3151,'product_id':0x5045,
            'interface_number':2,'usage_page':0xffff,'usage':2}]}


class M5IntegrationTests(unittest.TestCase):
    def test_shared_receiver_is_not_statically_assigned_to_a_brand(self):
        self.assertIsNone(recognize(0x3151,0x5045,'','2.4G Wireless Mouse')[0])
        self.assertEqual(backend_for(0x3151,0x5045),'valkyrie_ry')
        self.assertEqual(backend_for(0x374a,0xa318),'valkyrie_ry_usb')

    def test_known_live_model_is_confirmed_but_offline_percent_is_not_used(self):
        for online in (True,False):
            with patch('valkyrie_ry.query_receiver',return_value=response(online)):r=probe(group())[0]
            self.assertEqual(r['percent'],67 if online else None);self.assertEqual(r['connected'],online)
            self.assertIsNone(r['charging'])
            if online:self.assertEqual(r['brand'],'VALKYRIE');self.assertEqual(r['protocol_model_id'],3090)

    def test_unknown_model_clears_old_receiver_battery_and_history_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DeviceStore(Path(tmp)/'devices.json');g=group();store.reconcile([Device.from_dict(g['device'])])
            for mid in (3090,9901):
                with patch('valkyrie_ry.query_receiver',return_value=response(True,mid)):r=probe(g)[0]
                store.apply_readings('a'*24,[r]);d=store.snapshot()[0]
                if mid==3090:self.assertEqual(d.last_percent,67)
                else:self.assertIsNone(d.percent);self.assertIsNone(d.last_percent);self.assertFalse(d.cached)

    def test_sleep_keeps_verified_model_and_original_sampling_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DeviceStore(Path(tmp)/'devices.json');g=group();store.reconcile([Device.from_dict(g['device'])])
            with patch('valkyrie_ry.query_receiver',return_value=response()):store.apply_readings('a'*24,probe(g))
            stamp=store.snapshot()[0].last_observed_at
            store.reconcile([Device.from_dict(g['device'])]);g['device']=store.snapshot()[0].to_dict()
            with patch('valkyrie_ry.query_receiver',return_value=response(False)):store.apply_readings('a'*24,probe(g))
            store.reconcile([Device.from_dict(group()['device'])]);d=store.snapshot()[0]
            self.assertEqual(d.brand,'VALKYRIE');self.assertEqual(d.last_observed_at,stamp)
            self.assertEqual(d.reading_text,'67%');self.assertIn(d.last_read_time,d.status)

    def test_usb_never_fills_100_or_claims_charge_flag(self):
        g=group();g['backend']='valkyrie_ry_usb';g['device']['name']='VK M5 Lite'
        r=probe(g)[0];self.assertIsNone(r['percent']);self.assertIsNone(r['charging']);self.assertEqual(r['power_mode'],'battery')

    def test_experiment_uses_verified_protocol_and_rejects_radio_offline(self):
        g=group()
        with patch('research.enumerate_groups',return_value=[g]),patch('valkyrie_ry.query_receiver',return_value=response()):
            r=sample('a'*24);self.assertTrue(r['protocol_verified']);self.assertTrue(r['remote_confirmed']);self.assertEqual(r['percent'],67)
        with patch('research.enumerate_groups',return_value=[g]),patch('valkyrie_ry.query_receiver',return_value=response(False)):
            with self.assertRaisesRegex(ValueError,'远端鼠标离线'):sample('a'*24)

    def test_protocol_result_ends_experiment_and_can_return_or_close(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QObject,Signal
        from research_ui import ResearchDrawer
        from startup import StartupState
        from ui import Flyout
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp,patch('startup.state',return_value=StartupState(False,False,False,False)):
            f=Flyout(Settings(Path(tmp)/'settings.json'));controller=SimpleNamespace(inventory=[],busy=False,research_active=False)
            drawer=ResearchDrawer(f,controller);drawer.stage=1;drawer.identity='a'*24;drawer.generation=1
            packet={'timestamp':time.time(),'length':64,'hex':'00 '*64,'percent':67,'charging':None,
                    'name':'VK M5 Lite','protocol_verified':True,'remote_confirmed':True}
            drawer.completed(None,{'ok':True,'sample':packet},1,1)
            self.assertEqual(drawer.stage,6);self.assertIn('67%',drawer.text.text());self.assertTrue(drawer.long_button.isHidden())
            drawer.previous();self.assertEqual(drawer.stage,0);drawer.close();f.close_windows();app.processEvents()
