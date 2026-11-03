"""VK M3 系列的 2.4G 接收器：共用 USB ID，型号只由 0x10 身份页的型号代码决定。"""
import unittest
from catalog import backend_for, device_profile, recognize


class M3LiteReceiverTests(unittest.TestCase):
    def test_catalog_row_routes_the_receiver_to_the_m220_backend(self):
        profile = device_profile(0x249a, 0x5c2f)
        self.assertEqual(profile['name'], 'VK M3 系列')
        self.assertEqual(profile['brand'], 'valkyrie')
        self.assertEqual(profile['kind'], 'mouse')
        self.assertTrue(profile['receiver'])
        self.assertEqual(profile['backend'], 'valkyrie_m220')
        self.assertEqual(backend_for(0x249a, 0x5c2f), 'valkyrie_m220')

    def test_brand_comes_from_the_model_catalog_not_the_oem_vendor_id(self):
        brand, evidence = recognize(0x249a, 0x5c2f, 'XCTECH', 'Wireless-Receiver')
        self.assertEqual(brand['id'], 'valkyrie')
        self.assertEqual(evidence, 'VID/PID 型号目录')

    def test_adjacent_unknown_product_id_stays_unrecognized(self):
        self.assertIsNone(device_profile(0x249a, 0x5c30))
        self.assertIsNone(recognize(0x249a, 0x5c30, 'XCTECH', 'Wireless-Receiver')[0])


if __name__ == '__main__':
    unittest.main()
