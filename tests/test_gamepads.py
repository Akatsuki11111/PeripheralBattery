from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import tempfile,time,unittest,zlib
from pathlib import Path
from catalog import kind_for,recognize,visible_devices
from gamepads import unique_match,wgi_battery,parse_passive,query_gamepad
from inventory import enumerate_groups
from models import Device,lowest
from settings import DeviceStore


class GamepadTests(unittest.TestCase):
    def test_mixed_gamepad_keyboard_collections_remain_one_controller(self):
        base=dict(vendor_id=0x413d,product_id=0x2104,manufacturer_string='Microsoft',
                  product_string='XBOX 360 For Windows',bus_type=1,interface_number=0)
        infos=[dict(base,path=b'pad',usage_page=1,usage=5),dict(base,path=b'keys',usage_page=1,usage=6)]
        meta=dict(container='same-pad',physical='same-pad',friendly='',manufacturer='')
        with patch('inventory.hid.enumerate',return_value=infos),patch('inventory.usb_audio_infos',return_value=[]),\
             patch('inventory.raw_input_paths',return_value={}),patch('inventory.metadata',return_value=meta):groups=enumerate_groups()
        self.assertEqual(len(groups),1);g=groups[0]
        self.assertEqual(g['backend'],'gamepad');self.assertEqual(g['device']['kind'],'gamepad')
        self.assertFalse(g['device']['usb_keyboard']);self.assertIn('彩虹 2',g['device']['name'])
        self.assertEqual(g['controller_count'],1);self.assertEqual(g['device']['brand'],'BIGBIG WON')

    def test_controller_usages_and_requested_brand_identification(self):
        for usage in (4,5,8):self.assertEqual(kind_for('USB Input',[dict(usage_page=1,usage=usage)]),'gamepad')
        for vid,pid,name in [(0x20bc,0x5134,'BETOP'),(0x413d,0x2104,'BIGBIG WON')]:
            self.assertEqual(recognize(vid,pid,'Microsoft','Controller')[0]['name'],name)

    def test_native_control_and_xinput_nodes_merge_only_with_a_shared_parent(self):
        from inventory import merge_controller_collections
        def groups(shared):
            return {(0x20dd,0x5134,'a'):{'infos':[{'vendor_id':0x20dd}],'metadata':[{'physical':'a'}]},
                    (0x20bc,0x5134,'b'):{'infos':[{'vendor_id':0x20bc}],'metadata':[{'physical':'a' if shared else 'b'}]}}
        self.assertEqual(len(merge_controller_collections(groups(False))),2)
        merged=merge_controller_collections(groups(True));self.assertEqual(len(merged),1)
        self.assertEqual(len(next(iter(merged.values()))['infos']),2)

    def test_shared_oem_vid_is_not_assigned_to_betop(self):
        self.assertNotEqual((recognize(0x20bc,0xffff,'','USB Device')[0] or {}).get('id'),'betop')

    def test_unique_identity_not_slot_order(self):
        rows=[dict(vid=1,pid=2,slot=0),dict(vid=3,pid=4,slot=1)]
        self.assertEqual(unique_match(rows,3,4,1)['slot'],1)
        self.assertIsNone(unique_match(rows,1,2,2));self.assertIsNone(unique_match(rows*2,1,2,1))
        self.assertIsNone(unique_match([dict(vid=0,pid=0,slot=0)],1,2,1))

    def test_wgi_capacity_validation_charging_and_fake_full(self):
        row=dict(status='Discharging',remain=1000,full=1000,wireless=False,rate=None)
        self.assertIsNone(wgi_battery(row,{'battery_type':1}))
        self.assertEqual(wgi_battery({**row,'remain':430,'status':'Charging'},{'battery_type':1}),(43,True))
        self.assertEqual(wgi_battery({**row,'remain':0,'wireless':True}),(0,False))
        for change in ({'remain':True},{'full':0},{'remain':-1},{'remain':1001},{'remain':float('nan')},
                       {'full':float('inf')},{'status':'NotPresent'},{'remain':None}):
            self.assertIsNone(wgi_battery({**row,**change}))

    def query(self,slots=(),wgi=(),count=1):
        base=Device('pad','BETOP','北通鲲鹏','gamepad',vid=0x20bc,pid=0x5134,receiver=True)
        with patch('gamepads.passive_battery',return_value=None),patch('gamepads.xinput_snapshot',return_value=slots),\
             patch('battery_backends.wgi.query',return_value=[SimpleNamespace(raw=r) for r in wgi]):
            return Device.from_dict({**base.to_dict(),**query_gamepad({'device':base.to_dict(),'controller_count':count},[])})

    def test_wired_xinput_receiver_never_becomes_100_percent_or_batteryless(self):
        d=self.query([dict(vid=0x20bc,pid=0x5134,battery_type=1,battery_level=3)])
        self.assertIsNone(d.percent);self.assertEqual(d.power_mode,'unknown');self.assertIn('WIRED',d.note)
        self.assertEqual(visible_devices([d],{}),[d]);self.assertIsNone(lowest([d]))

    def test_xinput_four_grades_never_invent_percentages(self):
        for level,label in enumerate(('耗尽','低','中','高')):
            d=self.query([dict(vid=0x20bc,pid=0x5134,battery_type=2,battery_level=level)])
            self.assertEqual(d.reading_text,label);self.assertIsNone(d.percent);self.assertIsNone(lowest([d]))
            self.assertEqual(replace(d,connected=False).reading_text,'—')

    def test_wgi_wins_when_exact_and_non_synthetic(self):
        slots=[dict(vid=0x20bc,pid=0x5134,battery_type=1,battery_level=3)]
        rows=[dict(vid=0x20bc,pid=0x5134,status='Charging',remain=410,full=1000,wireless=False)]
        d=self.query(slots,rows);self.assertEqual(d.percent,41);self.assertTrue(d.charging);self.assertTrue(d.usable)

    def test_ambiguous_two_controllers_never_get_single_slot_battery(self):
        d=self.query([dict(vid=0x20bc,pid=0x5134,battery_type=2,battery_level=1)],count=2)
        self.assertIsNone(d.percent);self.assertEqual(d.battery_grade,'');self.assertIn('错配',d.note)

    def test_sony_report_layout_errors_and_bluetooth_crc(self):
        packet=bytearray(64);packet[0]=1;packet[53]=0x13
        self.assertEqual(parse_passive(0x054c,0x0ce6,packet)[:2],(35,True))
        packet[53]=0xa3;self.assertIsNone(parse_passive(0x054c,0x0ce6,packet))
        packet[53]=0x2a;self.assertEqual(parse_passive(0x054c,0x0ce6,packet)[:2],(100,False))
        self.assertIsNone(parse_passive(0x054c,0x0ce6,packet[:10]))
        bt=bytearray(78);bt[0]=0x31;bt[54]=0x04
        bt[-4:]=zlib.crc32(b'\xa1'+bt[:74]).to_bytes(4,'little')
        self.assertEqual(parse_passive(0x054c,0x0ce6,bt,True)[0],45)
        bt[-1]^=1;self.assertIsNone(parse_passive(0x054c,0x0ce6,bt,True))

    def test_switch_simple_report_and_8bitdo_padding_are_not_empty_batteries(self):
        p=bytearray(49);p[0]=0x30;p[2]=0x70
        self.assertEqual(parse_passive(0x057e,0x2009,p)[:2],(75,True))
        p[0]=0x3f;self.assertIsNone(parse_passive(0x057e,0x2009,p))
        p[0]=4;p[14]=0;self.assertIsNone(parse_passive(0x2dc8,0x6009,p))
        p[14]=0x95;self.assertEqual(parse_passive(0x2dc8,0x6009,p)[:2],(21,True))
        self.assertIsNone(parse_passive(0x1234,0x6009,p))

    def test_coarse_reading_is_labelled_and_excluded_from_lowest(self):
        d=Device('pad','Sony','DualSense','gamepad',35,False,True,observed_at=time.time(),approximate='十档')
        self.assertTrue(d.usable);self.assertEqual(d.reading_text,'约35%');self.assertIsNone(lowest([d]))
        from notifications import collect_low_alerts
        self.assertEqual(collect_low_alerts([replace(d,percent=5)],set(),20),[])

    def test_sleep_timestamp_stays_at_last_valid_sample_across_refresh_and_restart(self):
        stamp=time.time()-120
        d=Device('pad','BETOP','Pad','gamepad',40,False,True,True,observed_at=stamp,identity='pad')
        with tempfile.TemporaryDirectory() as tmp:
            store=DeviceStore(Path(tmp)/'devices.json');store.reconcile([d])
            for _ in range(2):store.apply_readings('pad',[dict(percent=None,connected=False,observed_at=time.time())])
            sleeping=store.snapshot()[0];self.assertEqual(sleeping.last_observed_at,stamp)
            self.assertIn(sleeping.last_read_time,sleeping.status);self.assertEqual(sleeping.reading_text,'40%')
            self.assertEqual(visible_devices([sleeping],{}),[sleeping]);store.save()
            restored=DeviceStore(store.path).snapshot()[0];self.assertEqual(restored.last_observed_at,stamp)
            # Restored devices remain absent until a fresh inventory sees them.
            self.assertIn(restored.last_read_time,replace(restored,present=True,connected=None).status)
            self.assertEqual(visible_devices([replace(restored,present=False)],{}),[])
