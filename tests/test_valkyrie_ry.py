import unittest
from unittest.mock import patch,Mock
from valkyrie_ry import parse_status,parse_identity,status_packet,identity_packet,query_receiver,validate_interface


def status(level=67,online=True,mask=2,ready=True,boot=False):
    data=bytearray(65);data[0]=0;data[1]=int(ready);data[3]=level
    data[5]=0 if online else 1;data[6]=int(ready);data[7]=mask;data[9]=int(boot)
    return bytes(data)


def identity(model_id=3090):
    data=bytearray(65);data[1]=0x8f;data[2:6]=model_id.to_bytes(4,'little');return bytes(data)


class FakeDevice:
    def __init__(self,responses):self.responses=iter(responses);self.writes=[];self.closed=False
    def open_path(self,path):self.path=path
    def close(self):self.closed=True
    def send_feature_report(self,packet):self.writes.append(bytes(packet));return len(packet)
    def get_feature_report(self,rid,length):return next(self.responses)


class ValkyrieRyTests(unittest.TestCase):
    def test_f7_layout_strips_report_zero(self):
        s=parse_status(status());self.assertTrue(s.online);self.assertEqual(s.percent,67)
        self.assertTrue(s.can_send);self.assertTrue(s.can_read);self.assertEqual(len(s.payload),64)
        self.assertEqual(parse_status(status()[1:]).percent,67)

    def test_disconnected_receiver_does_not_reuse_level_or_sentinel(self):
        self.assertIsNone(parse_status(status(255,False)).percent)
        self.assertFalse(parse_status(status(mask=1)).online)
        self.assertFalse(parse_status(status(boot=True)).online)
        self.assertFalse(parse_status(status(mask=0)).online)

    def test_online_zero_is_valid_but_out_of_range_is_not(self):
        self.assertEqual(parse_status(status(0)).percent,0)
        with self.assertRaises(ValueError):parse_status(status(101))
        with self.assertRaises(ValueError):parse_status(status(mask=8))

    def test_packets_have_official_payload_and_bit7_checksum(self):
        self.assertEqual(len(status_packet()),65);self.assertEqual(status_packet()[:2],b'\0\xf7')
        packet=identity_packet();self.assertEqual(packet[1],0x8f);self.assertEqual(packet[8],0x70)
        self.assertEqual(sum(packet[1:9])&255,255)

    def test_identity_must_echo_command_and_valid_uint32(self):
        self.assertEqual(parse_identity(identity()),3090)
        for data in (status(),identity(0),identity(0xffffffff),identity()[:20]):
            with self.assertRaises(ValueError):parse_identity(data)

    def test_wrong_receiver_or_collection_never_opens_device(self):
        for info in ({'vendor_id':0x3151,'product_id':0x9999},
                     {'vendor_id':0x3151,'product_id':0x5045,'usage_page':1,'usage':2,'interface_number':0}):
            with self.assertRaises(ValueError):validate_interface(info)

    def test_fresh_identity_flow_uses_only_documented_queries(self):
        device=FakeDevice([status(),status(),status(),identity(),status(68)])
        with patch('valkyrie_ry.validate_interface'),patch('valkyrie_ry.time.sleep'):
            result=query_receiver({'path':b'fake'},lambda:device)
        self.assertEqual(result['model_id'],3090);self.assertEqual(result['model'][1],'VK M5 Lite')
        self.assertEqual(result['status'].percent,68)
        self.assertIsNone(result['charging']);self.assertTrue(device.closed)
        self.assertEqual([p[1] for p in device.writes],[0xf7,0xf7,0xf6,0x8f,0xf7,0xfc,0xf7])
        self.assertTrue(all(len(p)==65 for p in device.writes))

    def test_offline_has_no_identity_and_does_not_route_commands(self):
        device=FakeDevice([status(255,False)])
        with patch('valkyrie_ry.validate_interface'),patch('valkyrie_ry.time.sleep'):
            result=query_receiver({'path':b'fake'},lambda:device)
        self.assertIsNone(result['model_id']);self.assertIsNone(result['model']);self.assertTrue(device.closed)
        self.assertEqual([p[1] for p in device.writes],[0xf7])

    def test_unrecognized_identity_is_not_branded_as_valkyrie(self):
        device=FakeDevice([status(),status(),status(),identity(123456),status()])
        with patch('valkyrie_ry.validate_interface'),patch('valkyrie_ry.time.sleep'):
            result=query_receiver({'path':b'fake'},lambda:device)
        self.assertEqual(result['model_id'],123456);self.assertIsNone(result['model'])

    def test_link_lost_while_waiting_for_identity_is_not_live(self):
        device=FakeDevice([status(),status(),status(91,False)])
        with patch('valkyrie_ry.validate_interface'),patch('valkyrie_ry.time.sleep'):
            with self.assertRaisesRegex(ValueError,'offline'):query_receiver({'path':b'fake'},lambda:device)
        self.assertTrue(device.closed)

    def test_link_lost_after_identity_drops_cached_percent(self):
        device=FakeDevice([status(90),status(90),status(90),identity(),status(90,False)])
        with patch('valkyrie_ry.validate_interface'),patch('valkyrie_ry.time.sleep'):
            result=query_receiver({'path':b'fake'},lambda:device)
        self.assertEqual(result['model_id'],3090);self.assertFalse(result['status'].online)
        self.assertIsNone(result['status'].percent)

    def test_usb_id_is_not_polled_or_assumed_to_be_full(self):
        factory=Mock()
        info={'vendor_id':0x374a,'product_id':0xa318,'interface_number':2,
              'usage_page':0xffff,'usage':2,'path':b'usb-mouse'}
        with self.assertRaisesRegex(ValueError,'receiver ID'):query_receiver(info,factory)
        factory.assert_not_called()

    def test_each_receiver_collection_dimension_is_required(self):
        base={'vendor_id':0x3151,'product_id':0x5045,'interface_number':2,'usage_page':0xffff,'usage':2,'path':b'x'}
        for changes in ({'interface_number':1},{'usage_page':1},{'usage':1}):
            factory=Mock()
            with self.assertRaisesRegex(ValueError,'collection'):query_receiver({**base,**changes},factory)
            factory.assert_not_called()

    def test_mismatched_reply_stops_and_closes_device(self):
        device=FakeDevice([status(),status(),status(),status()])
        with patch('valkyrie_ry.validate_interface'),patch('valkyrie_ry.time.sleep'):
            with self.assertRaises(ValueError):query_receiver({'path':b'fake'},lambda:device)
        self.assertTrue(device.closed)
