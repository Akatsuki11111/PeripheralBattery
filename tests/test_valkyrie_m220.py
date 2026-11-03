"""M220 身份页解析：全部使用真实应答字节，不虚构电量、充电或在线状态。"""
import unittest
from unittest.mock import patch
import valkyrie_m220
from valkyrie_m220 import Identity, identity_packet, parse_identity, validate_interface
from models import Device
from worker import probe

# 本机 2.4G 接收器实测（鼠标休眠中）与三份独立公开样本的 32 字节身份应答。
LOCAL_ASLEEP = ('10 00 01 0b 4d 32 32 30 84 01 11 01 00 1e 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 96')
REMOTE_78 = '10 00 01 0b 4d 32 32 30 84 01 11 01 00 4e 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 c7'
REMOTE_90 = '10 00 01 0b 4d 32 32 30 84 01 11 01 00 5a 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 d3'
WIRED_100 = '10 00 01 0b 4d 32 32 30 17 03 11 01 01 64 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 73'
REJECTED = '12 02 ff 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00'


def frame(text):
    return bytes.fromhex(text.replace(' ', ''))


def build(payload):
    data = bytearray(payload)
    data[31] = sum(data[4:31]) & 0xff
    return bytes(data)


class M220IdentityTests(unittest.TestCase):
    def test_request_is_the_zero_reported_identity_query(self):
        packet = identity_packet()
        self.assertEqual(len(packet), 33)
        self.assertEqual(packet[:2], bytes([0, 0x10]))
        self.assertEqual(sum(packet[5:32]) & 0xff, packet[32])

    def test_real_replies_decode_the_published_battery_bytes(self):
        cases = ((LOCAL_ASLEEP, 30, False, '0184', 0x00, 0x00), (REMOTE_78, 78, True, '0184', 0x00, 0x01),
                 (REMOTE_90, 90, True, '0184', 0x00, 0x01), (WIRED_100, 100, True, '0317', 0x01, 0x01))
        for text, percent, linked, firmware, status_raw, link_raw in cases:
            identity = parse_identity(frame(text))
            self.assertEqual((identity.percent, identity.linked, identity.firmware,
                              identity.status_raw, identity.link_raw, identity.model_code),
                             (percent, linked, firmware, status_raw, link_raw, b'M220'))

    def test_thirty_three_byte_frame_may_keep_its_report_id(self):
        self.assertEqual(parse_identity(b'\x00' + frame(REMOTE_78)).percent, 78)

    def test_charging_is_never_inferred_from_the_status_byte(self):
        self.assertFalse(hasattr(parse_identity(frame(WIRED_100)), 'charging'))

    def test_rejected_and_corrupted_answers_never_become_a_reading(self):
        asleep = frame(LOCAL_ASLEEP)
        bad = [frame(REJECTED), bytes([asleep[0], 0x02]) + asleep[2:], bytes([0x11]) + asleep[1:],
               asleep[:16], asleep[:31] + b'\x00',
               build(asleep[:3] + b'\x00' + asleep[4:]),
               build(frame(REMOTE_78)[:13] + bytes([101]) + frame(REMOTE_78)[14:]),
               b'\x01' + frame(REMOTE_78)]
        for data in bad:
            with self.assertRaises(ValueError):
                parse_identity(data)

    def test_only_the_verified_model_code_selects_a_supported_mouse(self):
        other = build(frame(REMOTE_78)[:4] + b'E023' + frame(REMOTE_78)[8:])
        identity = parse_identity(other)
        self.assertEqual((identity.model_code, identity.percent), (b'E023', 78))
        self.assertIsNone(valkyrie_m220.MODEL_CODES.get(identity.model_code))

    def test_configuration_collection_is_checked_before_the_query(self):
        info = {'vendor_id': 0x249a, 'product_id': 0x5c2f, 'interface_number': 2, 'usage_page': 1, 'usage': 0}
        validate_interface(info)
        for change in ({'vendor_id': 0x248a}, {'product_id': 0x5c2e}, {'interface_number': 0},
                       {'usage_page': 0xff00}, {'usage': 2}):
            with self.assertRaises(ValueError):
                validate_interface({**info, **change})


def group(backend='valkyrie_m220'):
    # inventory.decode_info expects the same hex-encoded path shape the worker
    # stores between processes, not a plain string.
    def path(text):
        return text.encode().hex()
    return {'device': {'name': 'VK M3 系列', 'brand': 'VALKYRIE', 'kind': 'mouse', 'identity': 'a' * 24},
            'backend': backend,
            'infos': [{'path': path('hid://mi02'), 'vendor_id': 0x249a, 'product_id': 0x5c2f, 'interface_number': 2,
                       'usage_page': 1, 'usage': 0},
                      {'path': path('hid://mi00'), 'vendor_id': 0x249a, 'product_id': 0x5c2f, 'interface_number': 0,
                       'usage_page': 1, 'usage': 2}]}


class M220ProbeTests(unittest.TestCase):
    def test_linked_answer_is_a_confirmed_battery_reading(self):
        with patch('protocols.query', return_value=frame(REMOTE_78)) as read:
            reading = probe(group())[0]
        self.assertEqual(read.call_args[0][1], identity_packet())
        self.assertEqual((reading['percent'], reading['connected'], reading['charging'], reading['confidence'],
                          reading['battery_support'], reading['name'], reading['brand']),
                         (78, True, None, 'confirmed', 'supported', 'VK M3 Lite', 'VALKYRIE'))

    def test_receiver_only_answer_is_never_presented_as_a_live_reading(self):
        with patch('protocols.query', return_value=frame(LOCAL_ASLEEP)):
            reading = probe(group())[0]
        self.assertEqual((reading['percent'], reading['connected'], reading['confidence']), (30, None, 'unknown'))
        self.assertIn('未作为实时读数', reading['note'])
        device = Device.from_dict({**reading, 'key': 'device:' + 'a' * 24, 'vid': 0x249a, 'pid': 0x5c2f})
        self.assertFalse(device.usable)
        self.assertNotIn('30', device.reading_text)

    def test_unverified_model_code_stays_identify_only(self):
        with patch('protocols.query', return_value=build(frame(REMOTE_78)[:4] + b'E023' + frame(REMOTE_78)[8:])):
            reading = probe(group())[0]
        self.assertEqual((reading['percent'], reading['connected'], reading['battery_support'], reading['name']),
                         (None, None, 'identify-only', 'VK M3 系列'))

    def test_missing_or_ambiguous_configuration_interface_is_refused(self):
        for infos in ([], group()['infos'][:1] + [dict(group()['infos'][0], path='hid://other'.encode().hex())]):
            with patch('protocols.query') as read, self.assertRaises(ValueError):
                probe({'device': group()['device'], 'backend': 'valkyrie_m220', 'infos': infos})
            read.assert_not_called()

    def test_identity_dataclass_stays_immutable(self):
        identity = parse_identity(frame(REMOTE_78))
        self.assertIsInstance(identity, Identity)
        with self.assertRaises(Exception):
            identity.percent = 5


if __name__ == '__main__':
    unittest.main()
