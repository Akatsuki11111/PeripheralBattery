import sys,time,unittest
from dataclasses import replace
sys.path.insert(0,'outputs/PeripheralBattery')
from protocols import parse_nova5_usb
from unittest.mock import patch
from worker import probe
from models import Device
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
  other=replace(self.radio,connected=True,percent=100)
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
 def test_online_receiver_needs_matching_charge_and_battery(self):
  active=replace(self.radio,connected=True,percent=57,charging=True)
  self.assertEqual(visible_devices([active,self.cable],{}),[self.cable])
  for changed in (replace(active,percent=56),replace(active,charging=False),replace(active,charging=None)):
   self.assertEqual(len(visible_devices([changed,self.cable],{})),2)
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

 def test_unplug_or_noncharging_does_not_merge(self):
  for usb in (replace(self.cable,present=False),replace(self.cable,charging=False),replace(self.cable,observed_at=0)):
   self.assertIn(self.radio,visible_devices([self.radio,usb],{'show_offline':True}))

if __name__=='__main__':unittest.main()
