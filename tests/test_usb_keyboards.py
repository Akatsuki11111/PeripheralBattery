import unittest
from unittest.mock import patch
from catalog import visible_devices,device_profile
from inventory import enumerate_groups
from models import Device,lowest


def enumerate_keyboard(name,manufacturer,vid,pid,extra=(),bus=1):
    base=dict(path=b'test-keyboard',vendor_id=vid,product_id=pid,product_string=name,
        manufacturer_string=manufacturer,bus_type=bus,usage_page=1,usage=6)
    interfaces=[base]+[{**base,'path':bytes([10+n]),**values} for n,values in enumerate(extra)]
    meta=dict(container='device',physical='USB\\test',friendly='',manufacturer='')
    with patch('inventory.hid.enumerate',return_value=interfaces),patch('inventory.raw_input_paths',return_value={}),\
         patch('inventory.usb_audio_infos',return_value=[]),patch('inventory.metadata',return_value=meta):
        groups=enumerate_groups()
    return groups[0] if groups else None


class UsbKeyboardTests(unittest.TestCase):
    def test_requested_brands_and_membrane_keyboards_are_visible_without_claiming_batteryless(self):
        fixtures=[('ATK RS7','ATK',0x1111,'ATK'),('IQUNIX EZ63','IQUNIX',0x1112,'IQUNIX'),
          ('MCHOSE Magnetic Keyboard','MCHOSE',0x5253,'MCHOSE'),('ROG Falchion','ASUSTeK',0x0b05,'ROG'),
          ('DAREU keyboard','DAREU',0x1113,'DAREU'),('NuPhy Air','NuPhy',0x19f5,'NuPhy'),
          ('VGN Keyboard','VGN',0x1114,'VGN'),('USB Keyboard','A4TECH',0x09da,'A4Tech'),
          ('USB Keyboard','Logitech',0x046d,'Logitech'),('USB Keyboard','HP',0x03f0,'HP')]
        for n,(name,manufacturer,vid,brand) in enumerate(fixtures):
            with self.subTest(name=name):
                group=enumerate_keyboard(name,manufacturer,vid,0x7f00+n)
                device=Device.from_dict(group['device'])
                self.assertEqual(device.brand,brand);self.assertEqual(device.kind,'keyboard')
                self.assertTrue(device.usb_keyboard);self.assertEqual(device.power_mode,'unknown')
                self.assertIsNone(device.percent);self.assertIn('供电待确认',device.status)
                self.assertEqual(visible_devices([device],{}),[device]);self.assertIsNone(lowest([device]))

    def test_generic_keyboard_with_mouse_collection_and_unknown_brand_stays_visible(self):
        group=enumerate_keyboard('USB Device','',0x1771,0x1234,[{'usage_page':1,'usage':2}])
        device=Device.from_dict(group['device'])
        self.assertEqual(device.kind,'keyboard');self.assertTrue(device.usb_keyboard)
        self.assertEqual(device.brand,'Unknown');self.assertEqual(visible_devices([device],{}),[device])

    def test_known_k120_is_wired_and_has_no_probe(self):
        group=enumerate_keyboard('USB Keyboard','Logitech',0x046d,0xc31c)
        device=Device.from_dict(group['device']);self.assertEqual(device.power_mode,'wired')
        self.assertEqual(device.status,'有线连接');self.assertIsNone(device.percent);self.assertEqual(group['backend'],'')
        self.assertTrue(device_profile(0x046d,0xc31c)['wired'])

    def test_receiver_bluetooth_and_scanner_are_not_called_wired_keyboards(self):
        receiver=Device.from_dict(enumerate_keyboard('USB Receiver','',0x1999,0x1234)['device'])
        self.assertTrue(receiver.receiver);self.assertFalse(receiver.usb_keyboard);self.assertEqual(receiver.power_mode,'unknown')
        bt=Device.from_dict(enumerate_keyboard('Bluetooth Keyboard','',0x1999,0x1235,bus=2)['device'])
        self.assertFalse(bt.usb_keyboard);self.assertNotEqual(bt.power_mode,'wired')
        scanner=Device.from_dict(enumerate_keyboard('Barcode Scanner','HP',0x03f0,0x1236)['device'])
        self.assertFalse(scanner.usb_keyboard);self.assertEqual(visible_devices([scanner],{}),[])

    def test_explicit_mchose_keyboard_does_not_get_mouse_status_command(self):
        group=enumerate_keyboard('MCHOSE Magnetic Keyboard','MCHOSE',0x5253,0x1234)
        self.assertEqual(group['backend'],'');self.assertTrue(group['device']['usb_keyboard'])

    def test_unplugged_keyboard_hidden_and_values_remain_unknown(self):
        group=enumerate_keyboard('IQUNIX keyboard','IQUNIX',0x1999,0x1234)
        record={**group['device'],'present':False,'percent':None,'connected':False}
        self.assertEqual(visible_devices([Device.from_dict(record)],{'show_offline':True}),[])
        self.assertFalse(Device.from_dict({**record,'kind':'mouse','usb_keyboard':True}).usb_keyboard)


if __name__=='__main__':unittest.main()
