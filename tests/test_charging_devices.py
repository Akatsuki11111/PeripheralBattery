import sys,time,unittest
from dataclasses import replace
sys.path.insert(0,'outputs/PeripheralBattery')
from protocols import parse_nova5_usb
from models import Device
from catalog import visible_devices,device_profile

class ChargingTests(unittest.TestCase):
 def setUp(self):
  now=time.time()
  self.cable=Device('usb','SteelSeries','Arctis Nova 5',kind='headset',vid=0x1038,pid=0x2230,percent=57,charging=True,connected=True,observed_at=now,battery_support='supported')
  self.radio=replace(self.cable,key='radio',pid=0x2232,receiver=True,connected=False,percent=None,charging=None)
 def test_usb_reads_offline_radio_battery(self):
  self.assertEqual(parse_nova5_usb([0xb0,2,2,57,1]+[0]*11),(True,57,True,''))
  for data in ([0xb0,2,2,255,1]+[0]*11,[0xb0,2,2,57,9]+[0]*11,[0]*16):
   with self.assertRaises(ValueError):parse_nova5_usb(data)
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
 def test_unplug_or_noncharging_does_not_merge(self):
  for usb in (replace(self.cable,present=False),replace(self.cable,charging=False),replace(self.cable,observed_at=0)):
   self.assertIn(self.radio,visible_devices([self.radio,usb],{'show_offline':True}))

if __name__=='__main__':unittest.main()
