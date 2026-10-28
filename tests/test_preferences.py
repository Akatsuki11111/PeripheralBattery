import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import json,logging,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PySide6.QtWidgets import QApplication,QComboBox
from PySide6.QtTest import QTest
from settings import Settings,DeviceStore,REFRESH_INTERVALS
from classification import wired_evidence,as_wired,bind_groups,apply_saved_modes
from models import Device,lowest
from catalog import device_profile,visible_devices
from scheduling import RefreshTimer
from ui import Flyout
from dialogs import CatalogDialog
from jobs import ScanController
from startup import StartupState
app=QApplication.instance() or QApplication([])


def device(key='a',**changes):
    return Device.from_dict({**dict(key=key,identity=key,fingerprint='same-model',brand='Unknown',
        name='USB Keyboard',kind='keyboard',last_seen=time.time()),**changes})


class SupplyTests(unittest.TestCase):
    def test_unknown_usb_and_missing_battery_do_not_prove_batteryless(self):
        usb=[{'bus_type':1}]
        for name in ('USB Mouse','Wired Keyboard','Wireless Receiver','NuPhy Air75 Wired'):
            self.assertFalse(wired_evidence(None,name,usb))
        self.assertTrue(wired_evidence(None,'USB Batteryless Keyboard',usb))
    def test_wireless_and_bluetooth_evidence_blocks_name_rule(self):
        self.assertFalse(wired_evidence(None,'Wireless Batteryless Keyboard',[{'bus_type':1}]))
        self.assertFalse(wired_evidence({'wired':True},'Keyboard',[{'bus_type':2}]))
        self.assertFalse(wired_evidence(None,'Batteryless Keyboard',[{'bus_type':1}],'logitech'))
    def test_known_wired_profiles_do_not_enable_battery_protocol(self):
        for vid,pid in ((0x046d,0xc08b),(0x1532,0x008a),(0x1532,0x006e),(0x3854,0x040f)):
            profile=device_profile(vid,pid);self.assertTrue(profile['wired']);self.assertEqual(profile['backend'],'')
            self.assertTrue(wired_evidence(profile,profile['name'],[{'bus_type':1}]))
    def test_manual_wired_is_visible_and_excludes_stale_battery(self):
        with tempfile.TemporaryDirectory() as folder:
            store=DeviceStore(Path(folder)/'devices.json');store.reconcile([device(percent=20,connected=True,observed_at=time.time())])
            apply_saved_modes(store,{'device_modes':{'a':'wired'}});d=store.snapshot()[0]
            self.assertEqual(d.status,'有线连接');self.assertIsNone(d.percent);self.assertIsNone(lowest([d]))
            self.assertEqual(visible_devices([d],{}),[d])
    def test_device_override_survives_port_migration_and_auto_restores(self):
        with tempfile.TemporaryDirectory() as folder:
            store=DeviceStore(Path(folder)/'devices.json');store.reconcile([device()])
            moved=device('new-port');group={'device':moved.to_dict(),'infos':[],'backend':'razer'}
            store.reconcile([moved]);bound=bind_groups([group],store,{'device_modes':{'a':'wired'}})
            self.assertEqual(bound[0]['device']['key'],'a');self.assertEqual(bound[0]['backend'],'')
            self.assertEqual(store.devices['a'].power_mode,'wired')
            store.reconcile([moved]);bound=bind_groups([group],store,{'device_modes':{}})
            self.assertEqual(bound[0]['backend'],'razer');self.assertEqual(store.devices['a'].power_mode,'unknown')
    def test_audio_only_usb_headset_is_enumerated(self):
        from inventory import enumerate_groups
        audio=dict(path=b'USB\\VID_7777&PID_0001\\test',vendor_id=0x7777,product_id=1,
            product_string='USB Headset',manufacturer_string='',bus_type=1,audio_interface=True,usage_page=0,usage=0)
        meta=dict(container='container',physical='USB\\test',friendly='',manufacturer='')
        with patch('inventory.hid.enumerate',return_value=[]),patch('inventory.raw_input_paths',return_value={}),patch('inventory.usb_audio_infos',return_value=[audio]),patch('inventory.metadata',return_value=meta):
            groups=enumerate_groups()
        self.assertEqual(len(groups),1);self.assertEqual(groups[0]['device']['kind'],'headset')
    def test_audio_and_hid_interfaces_are_consolidated(self):
        from inventory import enumerate_groups
        audio=dict(path=b'USB\\VID_7777&PID_0001\\test',vendor_id=0x7777,product_id=1,
            product_string='USB Headset',manufacturer_string='',bus_type=1,audio_interface=True,usage_page=0,usage=0)
        hid={**audio,'path':b'fake-hid','audio_interface':False,'usage_page':12,'usage':1}
        meta=dict(container='container',physical='USB\\test',friendly='',manufacturer='')
        with patch('inventory.hid.enumerate',return_value=[hid]),patch('inventory.raw_input_paths',return_value={}),patch('inventory.usb_audio_infos',return_value=[audio]),patch('inventory.metadata',return_value=meta):
            groups=enumerate_groups()
        self.assertEqual(len(groups),1);self.assertEqual(len(groups[0]['infos']),2)


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'settings.json';self.settings=Settings(self.path)
    def tearDown(self):self.tmp.cleanup()
    def test_interval_roundtrip_and_rejection(self):
        for seconds in REFRESH_INTERVALS:
            self.settings.set('refresh_seconds',seconds);self.assertEqual(Settings(self.path).get('refresh_seconds'),seconds)
        for value in (0,-5,10,120,True,'5'):
            with self.assertRaises(ValueError):self.settings.set('refresh_seconds',value)
    def test_invalid_saved_interval_falls_back_to_15(self):
        for value in (True,7,'5',None):
            self.path.write_text(json.dumps({'refresh_seconds':value}),encoding='utf-8')
            self.assertEqual(Settings(self.path).get('refresh_seconds'),15)
    def test_live_timer_reconfiguration_preserves_single_timer(self):
        timer=RefreshTimer(lambda:None,15);timer.start()
        for seconds in REFRESH_INTERVALS:
            timer.set_seconds(seconds);self.assertTrue(timer.isActive());self.assertEqual(timer.interval(),seconds*1000)
        timer.stop()
    def test_busy_queries_do_not_overlap_and_force_change_is_deferred(self):
        store=DeviceStore(Path(self.tmp.name)/'devices.json')
        controller=ScanController(store,self.settings,logging.getLogger('test'))
        controller.busy=True
        with patch('jobs.WorkerJob') as spawn:
            controller.refresh();controller.refresh(True);spawn.assert_not_called()
        self.assertTrue(controller.pending_force)
        with patch.object(controller,'refresh') as refresh:
            controller._finish();QTest.qWait(20);refresh.assert_called_once_with(True)
        controller.shutdown()
    def test_audio_hotplug_triggers_inventory_when_hid_paths_do_not_change(self):
        store=DeviceStore(Path(self.tmp.name)/'devices.json');controller=ScanController(store,self.settings,logging.getLogger('test'))
        controller.inventory=[{}];controller.last_inventory=time.monotonic();controller.paths=(frozenset({'hid'}),frozenset())
        with patch('battery_backends.hidlist.interface_paths',return_value=frozenset({'hid'})),patch('jobs.usb_audio_device_ids',return_value=frozenset({'new-usb-headset'})),patch('jobs.WorkerJob') as spawn:
            controller.refresh();self.assertEqual(spawn.call_args.args[0]['operation'],'inventory')
            controller.jobs.clear();controller.stopping=True
    def test_ui_interval_selector_applies_live_and_persists(self):
        with patch('startup.state',return_value=StartupState(False,False,False,False)):
            flyout=Flyout(self.settings);timer=RefreshTimer(lambda:None,15);timer.start()
            flyout.preferencesChanged.connect(lambda:timer.set_seconds(self.settings.get('refresh_seconds')))
            for seconds in REFRESH_INTERVALS:
                flyout.refresh_choice.setCurrentIndex(flyout.refresh_choice.findData(seconds))
                self.assertEqual(timer.interval(),seconds*1000);self.assertEqual(Settings(self.path).get('refresh_seconds'),seconds)
            dialog=CatalogDialog([],self.settings,flyout)
            dialog.preferencesChanged.connect(lambda:flyout.rebuild([],[]))
            choice=dialog.findChild(QComboBox,'refreshInterval');choice.setCurrentIndex(choice.findData(5))
            self.assertEqual(flyout.refresh_choice.currentData(),5)
            timer.stop();dialog.deleteLater();flyout.deleteLater();app.processEvents()
    def test_manual_supply_dropdown_saves_and_clears_override(self):
        with patch('startup.state',return_value=StartupState(False,False,False,False)):
            flyout=Flyout(self.settings);flyout.rebuild([device()],[]);flyout.show_detail('a')
            choice=flyout.findChild(QComboBox,'deviceMode');choice.setCurrentIndex(choice.findData('wired'))
            self.assertEqual(Settings(self.path).get('device_modes'),{'a':'wired'})
            choice.setCurrentIndex(0);self.assertEqual(Settings(self.path).get('device_modes'),{})
            flyout.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
