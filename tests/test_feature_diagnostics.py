import ctypes as C
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from feature_reports import Caps,FeatureReadError,get_feature,inspect_features,channels_for
from inventory import model_name
from catalog import recognize,device_profile
from models import Device
from research import research_devices,inspect_device


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.info={'path':b'private-device-path','interface_number':2,'usage_page':0xff01,'usage':1}
        self.caps=Caps();self.caps.UsagePage=0xff01;self.caps.Usage=1

    @contextmanager
    def opened(self,path):yield 1,self.hid,None,self.caps

    def test_missing_vendor_collection_does_not_open_input_device(self):
        with patch('feature_reports.opened') as opened:
            with self.assertRaises(FeatureReadError) as caught:get_feature([{'usage_page':1,'usage':2}])
        self.assertEqual(caught.exception.code,'no_vendor_collection');opened.assert_not_called()

    def test_no_feature_and_oversize_have_distinct_reasons(self):
        self.hid=SimpleNamespace()
        for length,code in ((0,'no_feature_report'),(515,'feature_length_limit')):
            self.caps.FeatureLength=length
            with patch('feature_reports.opened',self.opened):
                with self.assertRaises(FeatureReadError) as caught:get_feature([self.info])
            self.assertEqual(caught.exception.code,code)
            self.assertEqual(caught.exception.details[0]['feature_length'],length)

    def test_access_failure_not_misreported_as_absent_feature(self):
        with patch('feature_reports.opened',side_effect=OSError('Windows error 5')):
            with self.assertRaises(FeatureReadError) as caught:get_feature([self.info])
        self.assertEqual(caught.exception.code,'descriptor_unavailable')
        self.assertIn('5',caught.exception.details[0]['error'])

    def test_read_failure_keeps_report_id_and_windows_error(self):
        self.caps.FeatureLength=4;self.hid=SimpleNamespace(HidD_GetFeature=lambda *args:False)
        with patch('feature_reports.opened',self.opened),patch('feature_reports.channels_for',return_value=[{'report_id':7,'length':4}]),patch('feature_reports.C.get_last_error',return_value=5):
            with self.assertRaises(FeatureReadError) as caught:get_feature([self.info])
        self.assertEqual(caught.exception.code,'feature_read_failed')
        self.assertEqual(caught.exception.details[0]['attempts'][0]['windows_error'],5)

    def test_descriptor_inspection_never_reads_reports(self):
        self.hid=SimpleNamespace(HidD_GetFeature=lambda *args:self.fail('Must not read any report'))
        with patch('feature_reports.opened',self.opened):result=inspect_features([self.info])
        self.assertEqual(result[0]['status'],'no_feature_report')
        self.assertNotIn('path',json.dumps(result))

    def test_vendor_feature_can_declare_a_standard_child_usage(self):
        self.caps.FeatureLength=65;self.caps.FeatureValues=1
        class Fn:
            def __call__(self,kind,entries,count,preparsed):
                if kind!=2:raise AssertionError('Only Feature capabilities')
                raw=bytearray(72);raw[:3]=bytes([1,0,8]);C.memmove(entries,bytes(raw),72);return 0x110000
        hid=SimpleNamespace(HidP_GetValueCaps=Fn())
        self.assertEqual(channels_for(self.info,hid,None,self.caps)[0]['report_id'],8)

    def test_exact_official_model_replaces_only_generic_product_name(self):
        profile=device_profile(0x374a,0xa329)
        self.assertEqual(model_name(profile,'Wireless-Receiver'),'VK M5 PRO')
        self.assertEqual(model_name(profile,'Real model string'),'Real model string')
        self.assertEqual(recognize(0x374a,0xa329)[0]['name'],'VALKYRIE')
        self.assertIsNone(recognize(0x374a,0xffff)[0])
        self.assertNotEqual((recognize(0x3151,0x4026)[0] or {}).get('name'),'VALKYRIE')

    def test_unknown_receiver_can_be_selected_without_brand_guess(self):
        d=Device('unknown','Unknown','Wireless-Receiver',receiver=True)
        self.assertEqual(research_devices([d]),[d])
        self.assertFalse(research_devices([Device('input','Unknown','USB Mouse')]))

    def test_exported_metadata_has_no_paths_serials_or_raw_input(self):
        group={'device':{'identity':'a'*24,'name':'Wireless-Receiver','brand':'Unknown','vid':0x374a,'pid':0xa329,'kind':'mouse','receiver':True},'backend':'',
               'infos':[{**self.info,'path':self.info['path'].hex(),'serial_number':'PRIVATE_SERIAL','manufacturer_string':'OEM'}]}
        with patch('device_inspection.enumerate_groups',return_value=[group]),patch('feature_reports.inspect_features',return_value=[]):result=inspect_device('a'*24)
        encoded=json.dumps(result)
        self.assertNotIn('private-device-path',encoded);self.assertNotIn('PRIVATE_SERIAL',encoded);self.assertNotIn('serial_number',encoded)
        self.assertEqual(result['valkyrie_candidates'][0]['valkyrie_names'],['VK M5 PRO'])
