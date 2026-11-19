import sys,time,unittest,tempfile
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,'outputs/PeripheralBattery')
from protocols import parse_nova5_usb,parse_nova5
from unittest.mock import patch
from worker import probe
from models import Device
from settings import DeviceStore
from catalog import visible_devices,device_profile,related_keys,device_mode

class ChargingTests(unittest.TestCase):
 def setUp(self):
  now=time.time()
  self.cable=Device('usb','SteelSeries','Arctis Nova 5',kind='headset',vid=0x1038,pid=0x2230,percent=57,charging=True,connected=True,observed_at=now,battery_support='supported')
  self.radio=replace(self.cable,key='radio',pid=0x2232,receiver=True,connected=False,percent=None,charging=None)
 def test_usb_reads_offline_radio_battery(self):
  self.assertEqual(parse_nova5_usb([0xb0,2,2,57,1]+[0]*11),(True,57,True,False))
  self.assertEqual(parse_nova5_usb([0xb0,2,2,99,2]+[0]*11),(True,99,None,False))
  self.assertEqual(parse_nova5_usb([0xb0,2,2,100,0]+[0]*11),(True,100,False,False))
  for data in ([0xb0,2,2,255,1]+[0]*11,[0xb0,2,2,57,9]+[0]*11,[0]*16):
   with self.assertRaises(ValueError):parse_nova5_usb(data)
 def test_nova_full_usb_status_survives_worker_and_hides_offline_receiver(self):
  captured=bytes.fromhex('b0 02 02 64 02')+bytes(59)
  group={'device':self.cable.to_dict(),'infos':[],'backend':'nova5_usb'}
  with patch('worker.read_local',return_value=parse_nova5_usb(captured)):
   reading=probe(group)[0]
  full=Device.from_dict({**self.cable.to_dict(),**reading,'key':'usb'})
  self.assertTrue(full.usable)
  self.assertEqual((full.percent,full.charging,full.charge_complete,full.status),(100,False,True,'已充满'))
  for rx in (self.radio,replace(self.radio,connected=None),
             replace(self.radio,connected=True,percent=26,observed_at=0)):
   self.assertEqual(visible_devices([rx,full],{'show_offline':True}),[full])
  other=replace(self.radio,connected=True,percent=70)
  self.assertEqual(len(visible_devices([other,full],{})),2)
  restored=Device.from_dict({**full.to_dict(),'connected':None})
  self.assertFalse(restored.charge_complete)

 def test_nova_receiver_stays_hidden_during_enum_and_failed_reads(self):
  pending=replace(self.radio,connected=None,confidence='unknown')
  self.assertEqual(visible_devices([pending,self.radio],{}),[])
  self.assertEqual(visible_devices([pending],{'show_offline':True}),[pending])
  online=replace(self.radio,connected=True,percent=26)
  self.assertEqual(visible_devices([online],{}),[online])
 def test_atk_cable_hides_only_inactive_matching_receiver(self):
  cable=replace(self.cable,brand='ATK',kind='mouse',vid=0x373b,pid=0x129e,charging=False)
  radio=replace(cable,key='radio',pid=0x124f,receiver=True,connected=False,percent=None,
                protocol_model_id=0x129e,last_percent=86,last_observed_at=cable.observed_at)
  self.assertEqual(visible_devices([radio,cable],{}),[cable])
  other=replace(radio,protocol_model_id=1)
  self.assertEqual(len(visible_devices([other,cable],{})),2)
  active=replace(radio,connected=True,percent=85)
  self.assertEqual(len(visible_devices([active,cable],{})),2)
 def test_device_profile(self):self.assertEqual(device_profile(0x1038,0x2230)['backend'],'nova5_usb')
 def test_offline_receiver_collapses_even_show_offline(self):
  self.assertEqual(visible_devices([self.radio,self.cable],{'show_offline':True}),[self.cable])
 def test_online_receiver_matches_battery_despite_charge_flag_or_refresh_skew(self):
  active=replace(self.radio,connected=True,percent=57,charging=True)
  for level in (55,56,57,58,59):
   for charge in (False,None,True):
    with self.subTest(level=level,charging=charge):
     peer=replace(active,percent=level,charging=charge,observed_at=self.cable.observed_at-60)
     self.assertEqual(visible_devices([peer,self.cable],{}),[self.cable])
  for changed in (replace(active,percent=52),replace(active,observed_at=self.cable.observed_at-91)):
   self.assertEqual(len(visible_devices([changed,self.cable],{})),2)

 def test_captured_nova_frames_have_different_charge_flags_and_one_card(self):
  usb=parse_nova5_usb(bytes.fromhex('b0 03 02 2b 01')+bytes(59))
  radio=parse_nova5(bytes.fromhex('b0 03 02 2b 03')+bytes(59))
  self.assertEqual(usb[:3],(True,43,True))
  self.assertEqual(radio[:3],(True,43,False))
  with tempfile.TemporaryDirectory() as tmp:
   store=DeviceStore(Path(tmp)/'devices.json')
   cable=replace(self.cable,identity='usb',percent=None,connected=None,charging=None,observed_at=0)
   peer=replace(self.radio,identity='radio',connected=None)
   store.reconcile([cable,peer])
   with patch('worker.read_local',return_value=radio[:3]+('',)):
    store.apply_readings('radio',probe({'device':peer.to_dict(),'infos':[],'backend':'nova5'}))
   self.assertEqual([d.key for d in visible_devices(store.snapshot(),{'show_offline':True})],['radio'])
   with patch('worker.read_local',return_value=usb):
    store.apply_readings('usb',probe({'device':cable.to_dict(),'infos':[],'backend':'nova5_usb'}))
   shown=visible_devices(store.snapshot(),{'show_offline':True})
   self.assertEqual([(d.key,d.percent,d.status) for d in shown],[('usb',43,'正在充电')])
   store.reconcile([peer])
   shown=visible_devices(store.snapshot(),{'show_offline':True})
   self.assertEqual([d.key for d in shown],['radio'])
   self.assertEqual(shown[0].last_percent,43)

 def test_known_pairs_use_live_usb_even_after_full_or_stop_charging(self):
  for vid,usb_pid,radio_pid in ((0x1038,0x2230,0x2232),(0x1532,0x00c0,0x00c1),(0x24ae,0x46a7,0x14a7)):
   with self.subTest(vid=vid):
    usb=replace(self.cable,vid=vid,pid=usb_pid,percent=100,charging=False)
    rx=replace(self.radio,vid=vid,pid=radio_pid,connected=True,percent=99,charging=None)
    self.assertEqual(visible_devices([rx,usb],{'show_offline':True}),[usb])

 def test_pending_or_failed_usb_falls_back_to_live_receiver(self):
  rx=replace(self.radio,connected=True,percent=57,charging=False)
  pending=replace(self.cable,connected=None,percent=None,observed_at=0,charging=None)
  failed=replace(pending,last_percent=56,last_observed_at=rx.observed_at,query_state='timeout')
  for cable in (pending,failed):
   self.assertEqual(visible_devices([cable,rx],{'show_offline':True}),[rx])
  old=replace(failed,last_observed_at=rx.observed_at-91)
  self.assertEqual(len(visible_devices([old,rx],{'show_offline':True})),2)
  different=replace(failed,last_percent=12)
  self.assertEqual(len(visible_devices([different,rx],{'show_offline':True})),2)

 def test_conflicting_serial_or_explicit_association_prevents_automatic_merge(self):
  usb=replace(self.cable,serial_hash='one')
  rx=replace(self.radio,serial_hash='two')
  self.assertEqual(len(visible_devices([usb,rx],{'show_offline':True})),2)
  prefs={'show_offline':True,'device_links':{'usb':'linked:one','radio':'linked:two'}}
  self.assertEqual(len(visible_devices([self.cable,self.radio],prefs)),2)
  # Explicitly pairing different endpoint serials is an informed user choice.
  prefs['device_links']['radio']='linked:one'
  self.assertEqual(visible_devices([usb,rx],prefs),[usb])

 def test_trusted_identity_does_not_require_battery_readings_to_agree(self):
  usb=replace(self.cable,serial_hash='same')
  rx=replace(self.radio,serial_hash='same',connected=True,percent=12)
  self.assertEqual(visible_devices([usb,rx],{}),[usb])
  bluetooth=replace(usb,transport='Bluetooth')
  self.assertEqual(len(visible_devices([bluetooth,self.radio],{'show_offline':True})),2)

 def test_ambiguous_or_hidden_does_not_merge(self):
  second=replace(self.cable,key='another')
  self.assertEqual(len(visible_devices([self.radio,self.cable,second],{'show_offline':True})),3)
  self.assertEqual(visible_devices([self.radio,self.cable],{'show_offline':True,'hidden':['usb']}),[self.radio])
 def test_other_brands_require_same_reliable_serial(self):
  usb=replace(self.cable,brand='Other',vid=1,pid=1,serial_hash='abc')
  rx=replace(self.radio,brand='Other',vid=1,pid=2,serial_hash='abc')
  self.assertEqual(visible_devices([rx,usb],{'show_offline':True}),[usb])
  self.assertEqual(len(visible_devices([replace(rx,serial_hash=''),usb],{'show_offline':True})),2)
  self.assertEqual(len(visible_devices([replace(rx,serial_hash='different'),usb],{'show_offline':True})),2)
 def test_viper_charge_hides_cached_or_unconfirmed_receiver(self):
  usb=replace(self.cable,brand='Razer',name='Razer Viper V3 Pro',kind='mouse',vid=0x1532,pid=0x00C0)
  rx=replace(self.radio,brand=usb.brand,name=usb.name,kind=usb.kind,vid=0x1532,pid=0x00C1,
             last_percent=56,last_observed_at=usb.observed_at)
  for connection in (False,None):
   self.assertEqual(visible_devices([replace(rx,connected=connection),usb],{}),[usb])
  self.assertEqual(visible_devices([rx],{}),[rx])
  other=replace(usb,key='second',charging=False)
  self.assertEqual(len(visible_devices([rx,usb,other],{})),3)
  other_rx=replace(rx,key='second-receiver',connected=True,percent=72,charging=False)
  self.assertEqual(len(visible_devices([rx,usb,other_rx],{})),3)
 def test_linked_endpoints_share_preference_and_preserve_distinct_same_model_devices(self):
  cable=replace(self.cable,brand='Rapoo',kind='mouse',vid=0x24ae,pid=0x46a7,serial_hash='mouse-a')
  radio=replace(cable,key='radio',pid=0x14a7,receiver=True,charging=False)
  other=replace(radio,key='other',serial_hash='mouse-b',percent=82)
  self.assertEqual(visible_devices([cable,radio,other],{}),[cable,other])
  self.assertEqual(set(related_keys(radio,[cable,radio,other],{})[1:]),{'usb','radio'})
  self.assertEqual(device_mode(radio,[cable,radio,other],{'device_modes':{'usb':'battery'}}),'battery')
  collision=replace(other,serial_hash='mouse-a')
  self.assertEqual(set(related_keys(radio,[cable,radio,collision],{})),{'radio'})

 def test_unplug_or_stale_usb_does_not_hide_receiver(self):
  for usb in (replace(self.cable,present=False),replace(self.cable,observed_at=0)):
   self.assertIn(self.radio,visible_devices([self.radio,usb],{'show_offline':True}))

if __name__=='__main__':unittest.main()
