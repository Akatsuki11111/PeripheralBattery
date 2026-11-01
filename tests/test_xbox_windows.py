"""Protocol/interface simulations; these do not claim physical Xbox testing."""
from dataclasses import replace
import ctypes as C
import json
from pathlib import Path
import tempfile,time,unittest
from unittest.mock import patch,MagicMock
from battery_backends.wgi import parse,PS_SCRIPT
from controller_windows import bluetooth_properties,bluetooth_connected,bluetooth_state,is_bluetooth
from gamepads import (augment_inventory,query_gamepad,parse_xbox_bluetooth,
                      xbox_bluetooth_battery,same_model,wgi_battery)
from models import Device,lowest
from settings import DeviceStore


def snapshot(rows=(),slots=()):
    return dict(wgi=list(rows),slots=list(slots),at=time.time(),mono=time.monotonic())


def group(pid=0x0b13):
    d=Device('pad','Xbox','Xbox Series','gamepad',vid=0x045e,pid=pid,identity='pad',receiver=True)
    return dict(device=d.to_dict(),infos=[],backend='gamepad',controller_count=1)


class XboxWindowsTests(unittest.TestCase):
    def query(self,g,s):
        with patch('gamepads.passive_battery',return_value=None),patch('controller_windows.bluetooth_properties',return_value=dict(percent=None,address=None,le=True)),\
             patch('controller_windows.bluetooth_state',return_value=dict(connected=None,percent=None)),patch('gamepads.xbox_bluetooth_battery',return_value=None):
            g={**g,'controller_snapshot':s}
            return Device.from_dict({**g['device'],**query_gamepad(g,[])})

    def test_bluetooth_levels_differ_from_xinput_empty(self):
        for n,label in enumerate(('低','中','高','满')):
            r=parse_xbox_bluetooth(bytes((4,0x84|n)))
            self.assertEqual(r['battery_grade'],label);self.assertIsNone(r['charging'])
        for value in (b'',b'\x04',b'\x01\x87',b'\x04\x07',b'\x04\xa7',b'\x04\xc7'):
            self.assertIsNone(parse_xbox_bluetooth(value))

    def test_external_power_is_neither_full_nor_charging(self):
        r=parse_xbox_bluetooth(b'\x04\x93')
        self.assertEqual(r['battery_grade'],'');self.assertIsNone(r['charging']);self.assertTrue(r['external_power'])
        r=parse_xbox_bluetooth(b'\x04\x9a')
        self.assertEqual(r['battery_grade'],'高');self.assertTrue(r['charging'])
        self.assertFalse(parse_xbox_bluetooth(b'\x04\x8a')['charging'])

    def test_bluetooth_query_never_sends_output_or_rumble(self):
        device=MagicMock();device.read.return_value=[];device.get_input_report.return_value=[4,0x87]
        info=dict(vendor_id=0x045e,product_id=0x0b13,usage_page=1,usage=5,path=b'pad',bus_type=2)
        with patch('hid.device',return_value=device):result=xbox_bluetooth_battery([info])
        self.assertEqual(result['battery_grade'],'满');device.get_input_report.assert_called_once_with(4,2)
        device.write.assert_not_called();device.send_feature_report.assert_not_called();device.close.assert_called_once()

    def test_unknown_vendor_and_non_gamepad_collection_not_opened(self):
        with patch('hid.device') as create:
            self.assertIsNone(xbox_bluetooth_battery([dict(vendor_id=1,product_id=0x0b13)]))
            self.assertIsNone(xbox_bluetooth_battery([dict(vendor_id=0x045e,product_id=0x0b13,usage_page=1,usage=6)]))
        create.assert_not_called()

    def test_model_families_and_gip_alias(self):
        self.assertTrue(same_model((0x045e,0x0b12),(0x045e,0x0b13)))
        self.assertTrue(same_model((0x045e,0x02ff),(0x045e,0x0b13)))
        self.assertTrue(same_model((0x045e,0x02ea),(0x045e,0x0b20)))
        self.assertFalse(same_model((0x045e,0x0b20),(0x045e,0x0b22)))
        self.assertFalse(same_model((0x045e,0x0719),(0x045e,0x0b13)))
        self.assertFalse(same_model((0x1234,0x0b12),(0x045e,0x0b13)))

    def test_usb_bt_alias_can_retrieve_xinput_grade(self):
        d=self.query(group(),snapshot(slots=[dict(vid=0x045e,pid=0x0b12,battery_type=2,battery_level=2)]))
        self.assertEqual(d.reading_text,'中');self.assertTrue(d.fresh_grade);self.assertIsNone(lowest([d]))

    def test_alias_is_rejected_with_two_same_model_units(self):
        g={**group(),'controller_family_count':2}
        d=self.query(g,snapshot(slots=[dict(vid=0x045e,pid=0x0b12,battery_type=2,battery_level=2)]))
        self.assertFalse(d.fresh_grade);self.assertIsNone(d.percent)

    def test_no_hid_nodes_still_enumerates_two_wgi_units(self):
        rows=[dict(vid=0x045e,pid=0x0b12,id_hash=x,name='Xbox',wireless=True) for x in ('a','b')]
        groups=augment_inventory([],snapshot(rows))
        self.assertEqual(len(groups),2);self.assertEqual(len({g['device']['key'] for g in groups}),2)
        self.assertEqual({g['controller_family_count'] for g in groups},{2})

    def test_native_id_routes_its_own_capacity_with_equal_vid_pid(self):
        rows=[dict(vid=0x045e,pid=0x0b12,id_hash=x,name='Xbox',wireless=True,status='Discharging',remain=n,full=100) for x,n in [('a',25),('b',75)]]
        s=snapshot(rows);groups=augment_inventory([],s)
        self.assertEqual([self.query(g,s).percent for g in groups],[25,75])

    def test_native_duplicates_cannot_borrow_single_xinput_slot(self):
        rows=[dict(vid=0x045e,pid=0x0b12,id_hash=x,name='Xbox',wireless=True) for x in ('a','b')]
        s=snapshot(rows,[dict(slot=0,vid=0x045e,pid=0x0b12,battery_type=2,battery_level=1)])
        for g in augment_inventory([],s):self.assertFalse(self.query(g,s).fresh_grade)

    def test_wgi_and_hid_alias_do_not_duplicate_device(self):
        s=snapshot([dict(vid=0x045e,pid=0x0b12,id_hash='a',name='Xbox')])
        self.assertEqual(len(augment_inventory([group()],s)),1)

    def test_identical_hid_units_can_use_independent_native_reports(self):
        rows=[dict(vid=0x045e,pid=0x0b12,id_hash=x,name='Xbox',wireless=True,status='Discharging',remain=n,full=100) for x,n in [('a',25),('b',75)]]
        s=snapshot(rows);groups=augment_inventory([group(0x0b12),group(0x0b12)],s)
        self.assertEqual(len(groups),2);self.assertEqual([self.query(g,s).percent for g in groups],[25,75])

    def test_unknown_xinput_slot_is_displayed_without_persisting_identity(self):
        s=snapshot(slots=[dict(slot=2,vid=0,pid=0,battery_type=3,battery_level=1)])
        groups=augment_inventory([],s);self.assertEqual(len(groups),1)
        d=self.query(groups[0],s);self.assertEqual(d.reading_text,'低');self.assertFalse(d.battery_cache)
        saved=DeviceStore._with_last(d,d);self.assertIsNone(saved.last_percent);self.assertEqual(saved.last_battery_grade,'')
        self.assertFalse(replace(saved,connected=False).cached)

    def test_unknown_xinput_battery_type_does_not_validate_level(self):
        for typ in (0,1,255,99):
            d=self.query(group(0x0b12),snapshot(slots=[dict(vid=0x045e,pid=0x0b12,battery_type=typ,battery_level=3)]))
            self.assertFalse(d.fresh_grade);self.assertIsNone(d.percent)

    def test_snapshot_is_requeried_and_timestamp_is_not_invented(self):
        s=snapshot([dict(vid=0x045e,pid=0x0b12,status='Charging',remain=60,full=100,wireless=True)])
        s['at']-=2;s['mono']-=2
        d=self.query(group(0x0b12),s);self.assertEqual(d.observed_at,s['at'])
        old={**s,'mono':time.monotonic()-10}
        with patch('gamepads.windows_snapshot',return_value=s) as query:
            self.query(group(0x0b12),old)
        query.assert_called_once()

    def test_grade_sleep_cache_keeps_original_time_after_restart(self):
        stamp=time.time()-120
        d=replace(Device.from_dict(group()['device']),battery_grade='中',connected=True,confidence='confirmed',observed_at=stamp)
        with tempfile.TemporaryDirectory() as folder:
            store=DeviceStore(Path(folder)/'devices.json');store.reconcile([d])
            store.apply_readings('pad',[dict(percent=None,battery_grade='',connected=False,observed_at=time.time())])
            sleeping=store.snapshot()[0];self.assertEqual(sleeping.reading_text,'中');self.assertTrue(sleeping.cached)
            self.assertEqual(sleeping.last_observed_at,stamp);self.assertIn(sleeping.last_read_time,sleeping.status)
            store.save();restored=DeviceStore(store.path).snapshot()[0]
            self.assertEqual(replace(restored,present=True).reading_text,'中');self.assertFalse(restored.cached)
            self.assertEqual(restored.last_observed_at,stamp)

    def test_realtime_grade_replaces_old_percent_and_vice_versa(self):
        d=replace(Device.from_dict(group()['device']),battery_grade='低',last_percent=70,connected=True,confidence='confirmed',observed_at=time.time())
        grade=DeviceStore._with_last(d,d);self.assertIsNone(grade.last_percent)
        current=replace(grade,percent=25,battery_grade='')
        percent=DeviceStore._with_last(current,grade);self.assertEqual(percent.last_percent,25);self.assertEqual(percent.last_battery_grade,'')

    def test_explicit_charging_capacity_overrides_wired_sentinel(self):
        row=dict(status='Charging',remain=1000,full=1000,wireless=False,rate=None)
        self.assertEqual(wgi_battery(row,dict(battery_type=1)),(100,True))
        self.assertIsNone(wgi_battery({**row,'status':'Discharging'}))

    def test_missing_wgi_identity_cannot_be_assigned_to_multiple_slots(self):
        s=snapshot([dict(vid=0,pid=0,remain=40,full=100,status='Discharging')],
                   [dict(slot=i,vid=0,pid=0,battery_type=255) for i in range(2)])
        for g in augment_inventory([],s):self.assertIsNone(self.query(g,s).percent)

    def test_wgi_parser_hashes_native_id_and_keeps_raw_controller(self):
        row=dict(id='opaque-not-a-pnp-path',vid=0x045e,pid=0x0b12,name='Xbox',is_gamepad=False,status='Discharging',remain=40,full=100)
        rows=parse(json.dumps(dict(controllers=[row,row])),[])
        self.assertEqual(len(rows),1);self.assertNotIn('id',rows[0].raw);self.assertEqual(len(rows[0].raw['id_hash']),24)
        self.assertEqual(rows[0].level,40);self.assertIn('Gamepads',PS_SCRIPT)
        self.assertNotIn('continue }',PS_SCRIPT)

    def test_wgi_malformed_snapshots_do_not_crash(self):
        for raw in ('[]','null','{"controllers":true}','broken'):
            self.assertIsNone(parse(raw,[]))
        self.assertEqual(parse(json.dumps(dict(controllers=[None,dict(vid=True,pid=1)])),[]),[])
        self.assertIsNone(bluetooth_connected('invalid;command',False))

    def test_bluetooth_path_detection_does_not_treat_usb_pad_as_bluetooth(self):
        self.assertTrue(is_bluetooth([],0x045e,0x0b13))
        self.assertTrue(is_bluetooth([dict(path=b'\\\\?\\hid#service-00001812-0000')]))
        self.assertFalse(is_bluetooth([dict(path=b'USB\\VID_045E',bus_type=1)],0x045e,0x0b12))

    def test_windows_bluetooth_battery_requires_current_connection(self):
        g=group();s=snapshot()
        def query(connected):
            with patch('gamepads.passive_battery',return_value=None),patch('controller_windows.bluetooth_properties',return_value=dict(percent=80,address='AABBCCDDEEFF',le=True)),\
                 patch('controller_windows.bluetooth_state',return_value=dict(connected=connected,percent=None)),patch('gamepads.xbox_bluetooth_battery',return_value=None):
                return query_gamepad({**g,'controller_snapshot':s},[])
        self.assertEqual(query(True)['percent'],80)
        self.assertIsNone(query(False)['percent']);self.assertFalse(query(False)['connected'])
        self.assertIsNone(query(None)['percent'])

    def test_aep_battery_property_is_used_when_pnp_has_no_level(self):
        g=group()
        with patch('gamepads.passive_battery',return_value=None),patch('controller_windows.bluetooth_properties',return_value=dict(percent=None,address='AABBCCDDEEFF',le=True)),\
             patch('controller_windows.bluetooth_state',return_value=dict(connected=True,percent=65)):
            r=query_gamepad({**g,'controller_snapshot':snapshot()},[])
        self.assertEqual(r['percent'],65);self.assertIn('Windows',r['source'])

    def test_bluetooth_state_validates_unknown_sentinel_and_bool(self):
        for connected,percent,expected in [(True,70,70),(True,101,None),(False,70,None),(None,70,None),(True,True,None),(True,7.5,None)]:
            proc=MagicMock(stdout=json.dumps(dict(connected=connected,percent=percent)).encode(),returncode=0)
            with patch('controller_windows.subprocess.run',return_value=proc):r=bluetooth_state('AABBCCDDEEFF',True)
            self.assertEqual(r['percent'],expected)

    def test_cfgmgr_walk_is_bound_to_pad_not_pc_or_radio(self):
        class Api:
            def CM_Locate_DevNodeW(self,node,path,flags):node._obj.value=1;return 0
            def CM_Get_Device_IDW(self,node,text,length,flags):
                n=node.value if hasattr(node,'value') else node
                text.value={1:'HID\\PAD',2:'BTHLEDEVICE\\DEV_AABBCCDDEEFF',3:'USB\\HOST_RADIO'}[n];return 0
            def CM_Get_DevNode_PropertyW(self,node,key,kind,buffer,size,flags):
                if node.value==2:kind._obj.value=3;size._obj.value=1;buffer[0]=65;return 0
                return 1
            def CM_Get_Parent(self,parent,node,flags):parent._obj.value=node.value+1;return 0
        with patch('controller_windows.cfgmgr',return_value=Api()):r=bluetooth_properties([dict(path=b'hid#pad#unit')])
        self.assertEqual(r['percent'],65);self.assertEqual(r['address'],'AABBCCDDEEFF');self.assertTrue(r['le'])
