import unittest
from unittest.mock import patch

from atk_zero_plus import RECEIVER_PID, USB_PID, read_status, request_frame


def capture(text):
    return bytes.fromhex(text).ljust(64, bytes(1))


LINK_UP = capture('08 72 00 3a 00 81 01 01')
LINK_DOWN = capture('08 72 00 3a 00 81 01 00')
IDENTITY = capture('08 72 00 3a 00 4a 06 00 08 01 00 00 00')
WIRELESS = capture('08 72 00 3a 00 07 01 56 08 01')
USB = capture('08 72 00 3a 00 07 01 64 d8 10')
CHARGING = capture('08 72 00 3a 00 0f 01 01')
DISCHARGING = capture('08 72 00 3a 00 0f 01 00 08 01')


class AtkZeroTests(unittest.TestCase):
    def read(self,pid,frames):
        info = dict(path=b'control', vendor_id=0x373b, product_id=pid,
                    interface_number=3, usage_page=0xff05, usage=1)
        with patch('atk_zero_plus.hid.device') as create:
            handle = create.return_value
            handle.write.side_effect = len
            handle.read.side_effect = frames
            status = read_status([info],pid)
            handle.close.assert_called_once()
            return status,handle.write.call_count

    def test_exact_checksum_and_target(self):
        self.assertEqual(request_frame(7,True)[:8], bytes.fromhex('08 7d 72 02 00 01 07 01'))
        self.assertEqual(request_frame(7,False)[:8], bytes.fromhex('08 7c 72 02 00 00 07 01'))
        with self.assertRaises(KeyError):
            request_frame(0x82,True)

    def test_verified_cable_and_radio_captures(self):
        wireless,_ = self.read(RECEIVER_PID,[LINK_UP,IDENTITY,LINK_UP,WIRELESS,DISCHARGING])
        cable,_ = self.read(USB_PID,[IDENTITY,USB,CHARGING])
        self.assertEqual((wireless.model,wireless.percent,wireless.charging),(USB_PID,86,False))
        self.assertEqual((cable.model,cable.percent,cable.charging),(USB_PID,100,True))

    def test_disconnected_and_unknown_receiver_never_expose_battery(self):
        offline,count = self.read(RECEIVER_PID,[LINK_DOWN])
        self.assertEqual((offline.online,offline.percent,count),(False,None,1))
        unverified,count = self.read(RECEIVER_PID,[LINK_UP,IDENTITY[:8]+bytes(56)])
        self.assertEqual((unverified.online,unverified.percent,count),(True,None,2))
