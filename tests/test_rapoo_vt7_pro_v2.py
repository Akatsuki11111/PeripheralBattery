import unittest
from unittest.mock import patch

from catalog import backend_for, device_profile
from inventory import model_name
from rapoo_vt7_pro_v2 import RECEIVER_PID, USB_PID, parse_status, read_status


WIRELESS = bytes.fromhex('07 40 03 40 06 40 06 01 54 00 03 01 00 a7 46 10 02 02 b8')
CABLE = bytes.fromhex('07 42 03 40 06 40 06 02 56 00 03 01 00 a7 46 10 02 02 00')


class RapooTests(unittest.TestCase):
    def test_hardware_status_captures(self):
        for packet, pid, expected in ((WIRELESS, RECEIVER_PID, (True, 84, False)),
                                      (CABLE, USB_PID, (True, 86, True)),
                                      (CABLE, RECEIVER_PID, (False, None, None))):
            status = parse_status(packet, pid)
            self.assertEqual((status.online, status.percent, status.charging), expected)
        for index, bad in ((0, 6), (7, 0), (8, 255), (13, 0)):
            packet = bytearray(WIRELESS)
            packet[index] = bad
            self.assertIsNone(parse_status(bytes(packet), RECEIVER_PID))
        self.assertIsNone(parse_status(WIRELESS[:-1], RECEIVER_PID))
        self.assertIsNone(parse_status(WIRELESS, 0x14A6))

    def test_scope_by_product_and_vendor_collection(self):
        info = dict(vendor_id=0x24ae, product_id=RECEIVER_PID, interface_number=1,
                    usage_page=0xff00, usage=2, path=b'control')
        with patch('rapoo_vt7_pro_v2.hid.device') as create:
            with self.assertRaises(ValueError):
                read_status([{**info, 'usage_page': 1}], RECEIVER_PID)
            create.assert_not_called()
            handle = create.return_value
            handle.read.side_effect = [WIRELESS[:4], WIRELESS]
            self.assertEqual(read_status([info], RECEIVER_PID).percent, 84)
            handle.open_path.assert_called_once_with(b'control')
            handle.close.assert_called_once()

    def test_catalog_replaces_generic_names_for_the_two_verified_ids(self):
        for pid in (RECEIVER_PID, USB_PID):
            profile = device_profile(0x24ae, pid)
            self.assertEqual(model_name(profile, 'Rapoo Gaming Device'), 'Rapoo VT7 PRO V2')
            self.assertEqual(backend_for(0x24ae, pid), 'rapoo_vt7_pro_v2')
        self.assertEqual(backend_for(0x24ae, 0x14A6), '')
