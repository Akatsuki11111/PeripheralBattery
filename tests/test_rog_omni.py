import unittest
from unittest.mock import patch
from rog_omni import parse_pairing,parse_battery,query


def pair(pid=0x1b65,count=1,report=3):
    return [1,0xa0,0,count,0,pid&255,pid>>8,report,5]+[0]*55


def battery(level=78,charge=0):
    return [3,0x12,7,0,0,level,2,20,0x77,0x0f,charge]+[0]*53


class RogOmniTests(unittest.TestCase):
    def test_verified_model_and_channel_are_required(self):
        self.assertTrue(parse_pairing(pair()))
        for frame in (pair(0x1a94),pair(count=2),pair(report=2),pair()[:-1],[0]*64):
            self.assertFalse(parse_pairing(frame))

    def test_battery_and_voltage_from_observed_frame(self):
        self.assertEqual(parse_battery(battery()),(True,78,False,3959))
        self.assertEqual(parse_battery(battery(78,1)),(True,78,True,3959))
        self.assertEqual(parse_battery(battery(0,0)),(False,None,None,None))
        self.assertEqual(parse_battery(battery(0,1)),(True,0,True,3959))

    def test_invalid_errors_and_nonmatching_frames_are_rejected(self):
        for frame in ([0]*64,battery()[:-1],battery(101),[3,0x12,7,0,0,0xff,0xaa]+[0]*57):
            with self.assertRaises(ValueError):parse_battery(frame)
        frame=battery();frame[8:10]=[1,0]
        self.assertIsNone(parse_battery(frame)[3])

    def test_unverified_pairing_never_sends_mouse_battery_query(self):
        infos=[dict(vendor_id=0x0b05,product_id=0x1ace,interface_number=2,usage_page=page,usage=1,path=b'test')
               for page in (0xff02,0xff01)]
        with patch('rog_omni.get_report',return_value=pair(pid=0x1a94)) as read:
            self.assertEqual(query(infos),[]);read.assert_called_once()
        with patch('rog_omni.get_report',side_effect=[pair(),battery()]) as read:
            result=query(infos);self.assertEqual(result[0]['level'],78);self.assertEqual(result[0]['kind'],'mouse');self.assertEqual(read.call_count,2)

    def test_duplicate_vendor_collection_is_rejected(self):
        item=dict(vendor_id=0x0b05,product_id=0x1ace,interface_number=2,usage_page=0xff02,usage=1,path=b'test')
        with self.assertRaises(ValueError):query([item,item])


if __name__=='__main__':unittest.main()
