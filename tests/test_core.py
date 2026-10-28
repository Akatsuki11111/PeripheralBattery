from dataclasses import replace,FrozenInstanceError
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from models import Device,lowest,valid_percent
from protocols import parse_razer,parse_nova5,parse_scyrox,scyrox_packet,parse_nordic52
from settings import DeviceStore,Settings,read_json
from catalog import recognize,backend_for,brands,load_catalog,visible_devices
from ipc import command,server_name
from worker import probe


def mouse(key='a',**values):
    return Device.from_dict(dict(key=key,brand='Razer',name='Mouse',identity=key,fingerprint='model',
        last_seen=time.time(),observed_at=time.time(),percent=56,connected=True,**values))


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=DeviceStore(Path(self.tmp.name)/'devices.json')
    def tearDown(self):self.tmp.cleanup()

    def test_lowest_excludes_unconfirmed_offline_removed_stale(self):
        good=mouse();others=[replace(good,key=str(n),**change) for n,change in enumerate([
            {'connected':False,'percent':0},{'connected':None,'percent':1},{'present':False,'percent':1},
            {'confidence':'unknown','percent':1},{'observed_at':time.time()-901,'percent':1}])]
        self.assertEqual(lowest([good]+others),good);self.assertIsNone(lowest(others))
        self.assertEqual(lowest([replace(good,percent=0)]).percent,0)
    def test_model_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):mouse().percent=1
    def test_percent_rejects_sentinels(self):
        for n in [-1,101,255,True,None,'bad','nan',2.5,float('inf')]:self.assertIsNone(valid_percent(n))
        for n in [0,100,'56']:self.assertIsNotNone(valid_percent(n))
    def test_monotonic_ignores_wall_clock_jump(self):
        d=replace(mouse(),monotonic_at=time.monotonic())
        with patch('models.time.time',return_value=0):self.assertTrue(d.usable)
    def test_razer_snapshot_empty_and_malformed(self):
        data=[{'hasBattery':True,'category':'MOUSE','powerStatus':{'level':56}}]
        text='[2026/10/25 12:00:00.000] info: Device '+json.dumps(data)
        self.assertEqual(len(parse_razer(text,0)[0]),1)
        self.assertEqual(parse_razer(text+'\ninfo: Device []',0)[0],[])
        self.assertIsNone(parse_razer('info: Device [broken',0)[0])
    def test_nova5_offline_does_not_reuse_battery(self):
        data=[0xb0,1,2,53,1]+[0]*59
        self.assertEqual(parse_nova5(data)[:3],(True,53,True))
        data[1]=2;self.assertEqual(parse_nova5(data)[:2],(False,None))
        data[1]=1;data[3]=255
        with self.assertRaises(ValueError):parse_nova5(data)
    def test_scyrox_checksum_status_and_zero(self):
        frame=list(scyrox_packet());frame[6]=1;frame[-1]=sum(frame[:-1])&255
        self.assertEqual(parse_scyrox(frame)[:3],(True,0,False))
        frame[4]=87;frame[5]=1;frame[-1]=sum(frame[:-1])&255
        self.assertEqual(parse_scyrox(frame)[:3],(True,87,True))
        frame[6]=0;frame[-1]=sum(frame[:-1])&255
        self.assertEqual(parse_scyrox(frame)[:2],(False,None))
        frame[-1]^=1
        with self.assertRaises(ValueError):parse_scyrox(frame)
    def test_nordic_voltage_range_and_checksum(self):
        frame=[8,4,0,0,0,2,35,0,0x0e,0x94]+[0]*7;frame[-1]=(0x55-sum(frame[:-1]))&255
        self.assertEqual(parse_nordic52(frame)[:3],(True,35,False))
        frame[8]=frame[9]=0;frame[-1]=(0x55-sum(frame[:-1]))&255
        self.assertEqual(parse_nordic52(frame)[:2],(False,None))
        frame[-1]^=1
        with self.assertRaises(ValueError):parse_nordic52(frame)
    def test_unplug_clears_current_preserves_last(self):
        self.store.reconcile([replace(mouse(),last_percent=56)]);self.store.reconcile([])
        d=self.store.snapshot()[0];self.assertFalse(d.present);self.assertIsNone(d.percent);self.assertEqual(d.last_percent,56)
    def test_port_change_reuses_unique_device_key(self):
        self.store.reconcile([mouse()]);self.store.reconcile([replace(mouse('b'),percent=None,connected=None)])
        self.assertEqual([d.key for d in self.store.snapshot()],['a'])
    def test_same_model_two_units_do_not_merge(self):
        self.store.reconcile([mouse('a'),mouse('b')]);self.store.reconcile([mouse('b'),mouse('c')])
        self.assertEqual(sum(d.present for d in self.store.snapshot()),2)
    def test_distinct_serials_do_not_migrate(self):
        self.store.reconcile([replace(mouse(),serial_hash='serial-a')])
        self.store.reconcile([replace(mouse('b'),serial_hash='serial-b')]);self.assertEqual(len(self.store.snapshot()),2)
    def test_multiple_razer_models_remain_visible(self):
        self.store.reconcile([mouse(),replace(mouse('keyboard'),name='New Razer Keyboard',kind='keyboard',fingerprint='other')])
        self.assertEqual(len(visible_devices(self.store.snapshot(),{})),2)
    def test_restore_never_shows_cached_battery_as_live(self):
        self.store.reconcile([mouse()]);self.store.save();restored=DeviceStore(self.store.path)
        self.assertFalse(restored.snapshot()[0].usable);self.assertIsNone(restored.snapshot()[0].percent)
    def test_old_removed_devices_expire(self):
        self.store.devices={'a':replace(mouse(),last_seen=time.time()-90000)};self.store.reconcile([])
        self.assertEqual(self.store.snapshot(),[])
    def test_pairings_keep_keys_on_inventory_refresh(self):
        base=replace(mouse(),percent=None,connected=None);self.store.reconcile([base])
        self.store.apply_readings('a',[{'key':'slot1','name':'M1','percent':15,'connected':True},
                                       {'key':'slot2','name':'K2','kind':'keyboard','percent':80,'connected':True}])
        keys=set(self.store.devices);self.store.reconcile([base]);self.assertEqual(set(self.store.devices),keys)
        self.store.apply_readings('a',[{'percent':None,'connected':None}]);self.assertEqual(set(self.store.devices),keys)
        self.assertTrue(all(not d.usable for d in self.store.snapshot()))
    def test_broken_settings_and_cache_are_tolerated(self):
        self.store.path.write_text('{broken');self.assertEqual(DeviceStore(self.store.path).snapshot(),[])
        settings=Settings(self.store.path);self.assertEqual(settings.get('low_threshold'),20)
        self.store.path.write_text('x'*1024);self.assertIsNone(read_json(self.store.path,limit=10))
    def test_requested_brands_and_logo_assets_exist(self):
        for name in ['Logitech','Razer','SteelSeries','ZOWIE','ROG','VGN','MCHOSE','EWEADN','ATK','LAMZU','Rapoo','VALKYRIE','NuPhy']:
            brand=next(b for b in brands() if b['name']==name)
            self.assertTrue(brand['logo']);self.assertTrue((Path(__file__).parents[1]/brand['logo']).is_file())
    def test_shared_oem_never_gets_guessed_backend(self):
        self.assertIsNone(recognize(0x3554,0x9999,'Compx','USB Receiver')[0]);self.assertEqual(backend_for(0x3554,0x9999),'')
        brand,evidence=recognize(0x3554,0xf503,'Compx','USB Receiver');self.assertEqual(brand['id'],'vgn')
    def test_manual_brand_does_not_grant_protocol(self):
        self.assertEqual(recognize(0xabcd,1,override='atk')[0]['id'],'atk');self.assertEqual(backend_for(0xabcd,1),'')
    def test_generic_wired_entries_do_not_inflate_default_height(self):
        generic=replace(mouse(),percent=None,connected=None,brand='Unknown',receiver=False,battery_support='identify-only')
        wireless=replace(generic,key='receiver',receiver=True)
        self.assertEqual(visible_devices([generic,wireless],{}),[wireless])
        self.assertEqual(len(visible_devices([generic,wireless],{'show_unreadable':True})),2)
    def test_catalog_has_unique_valid_profiles(self):
        rows=load_catalog()['devices'];pairs=[(r['vid'],r['pid']) for r in rows]
        self.assertEqual(len(set(pairs)),len(pairs))
        for row in rows:self.assertIn(row['brand'],[b['id'] for b in brands()])
    def test_wired_keyboard_is_visible_and_has_no_battery(self):
        wired=Device.from_dict({**mouse().to_dict(),'kind':'keyboard','power_mode':'wired'})
        self.assertEqual(wired.status,'有线连接');self.assertEqual(wired.reading_text,'有线')
        self.assertIsNone(wired.percent);self.assertIsNone(lowest([wired]))
        self.assertEqual(visible_devices([wired],{}),[wired])
    def test_auxiliary_classification_requires_companion_evidence(self):
        from inventory import classify_auxiliary
        self.assertTrue(classify_auxiliary(0x303a,0x4005,'LifeSmart HID Device',['cxair_R240x240_M65536']))
        self.assertFalse(classify_auxiliary(0x303a,0x4005,'LifeSmart HID Device',[]))
        self.assertFalse(classify_auxiliary(0x303a,0x4005,'Custom Keyboard',['cxair_R240x240_M65536']))
        auxiliary=replace(mouse(),kind='auxiliary',percent=None)
        self.assertEqual(visible_devices([auxiliary],{}),[])
        self.assertEqual(visible_devices([auxiliary],{'show_auxiliary':True}),[auxiliary])
    def test_valkyrie_and_nuphy_recognition(self):
        self.assertEqual(recognize(0,0,name='VALKYRIE VK M5 PRO')[0]['id'],'valkyrie')
        self.assertEqual(recognize(0,0,manufacturer='瓦尔基里')[0]['id'],'valkyrie')
        self.assertEqual(recognize(0x19f5,0x3246,name='Keyboard')[0]['id'],'nuphy')
    def test_worker_receiver_only_result_is_not_online(self):
        group={'device':mouse().to_dict(),'infos':[],'backend':'nova5'}
        with patch('worker.read_local',return_value=(False,None,False,'')):
            result=probe(group)[0];self.assertFalse(result['connected']);self.assertIsNone(result['percent'])
    def test_ipc_only_accepts_three_exact_commands(self):
        self.assertEqual(command(b'show\n'),'show');self.assertEqual(command(b'ping\n'),'ping')
        for data in [b'show',b'arbitrary',b'show\nquit\n',b'open C:/x\n']:self.assertIsNone(command(data))
        self.assertIn('PeripheralBattery.v2.',server_name())


if __name__=='__main__':unittest.main()
