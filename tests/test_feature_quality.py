from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from feature_reports import Caps,FeatureReadError,get_feature


class FeatureQualityTests(unittest.TestCase):
    def setUp(self):
        self.info={'path':b'fake-vendor-device','interface_number':2,'usage_page':0xffff,'usage':2}
        self.caps=Caps();self.caps.UsagePage=0xffff;self.caps.Usage=2;self.caps.FeatureLength=4
        self.channels=[dict(report_id=rid,length=4,interface=2,usage_page=0xffff,usage=2,collection='one') for rid in (7,8,9)]
        self.packets={7:b'\x07\0\0\0',8:b'\x08\xff\xff\xff',9:b'\x09\0\x37\0'}
        self.reads=[]

    @contextmanager
    def opened(self,path):
        def read(handle,buf,length):
            rid=buf[0];self.reads.append(rid);data=self.packets[rid]
            if data is None:return False
            for i,value in enumerate(data):buf[i]=value
            return True
        yield 1,SimpleNamespace(HidD_GetFeature=read),None,self.caps

    def get(self,**kwargs):
        with patch('feature_reports.opened',self.opened),patch('feature_reports.channels_for',return_value=self.channels):
            return get_feature([self.info],**kwargs)

    def test_default_preserves_first_successful_get_semantics(self):
        data,channel=self.get()
        self.assertEqual(data,self.packets[7]);self.assertEqual(channel['report_id'],7)
        self.assertEqual(self.reads,[7])

    def test_initial_selection_skips_padding_and_tries_declared_channels(self):
        data,channel=self.get(reject_blank=True)
        self.assertEqual(data,self.packets[9]);self.assertEqual(channel['report_id'],9)
        self.assertEqual(self.reads,[7,8,9])

    def test_all_declared_reports_padding_gets_distinct_reason(self):
        self.packets[9]=b'\x09\0\0\0'
        with self.assertRaises(FeatureReadError) as caught:self.get(reject_blank=True)
        self.assertEqual(caught.exception.code,'uninitialized_report')
        self.assertEqual([a['report_id'] for a in caught.exception.details[0]['attempts']],[7,8,9])

    def test_locked_channel_never_switches_to_another_valid_report(self):
        with self.assertRaises(FeatureReadError) as caught:self.get(expected=self.channels[0],reject_blank=True)
        self.assertEqual(caught.exception.code,'uninitialized_report');self.assertEqual(self.reads,[7])

    def test_nonblank_report_with_zero_field_is_not_rejected(self):
        self.packets[7]=b'\x07\0\x01\0'
        data,channel=self.get(reject_blank=True)
        self.assertEqual(data,self.packets[7]);self.assertEqual(self.reads,[7])

    def test_mixed_access_failure_and_padding_preserve_read_failure(self):
        self.packets[7]=None;self.packets[9]=b'\x09\0\0\0'
        with patch('feature_reports.C.get_last_error',return_value=5):
            with self.assertRaises(FeatureReadError) as caught:self.get(reject_blank=True)
        self.assertEqual(caught.exception.code,'feature_read_failed')
        self.assertEqual(caught.exception.details[0]['attempts'][0]['windows_error'],5)

    def test_changed_locked_channel_remains_channel_changed(self):
        expected={**self.channels[0],'collection':'changed'}
        with self.assertRaises(FeatureReadError) as caught:self.get(expected=expected,reject_blank=True)
        self.assertEqual(caught.exception.code,'channel_changed');self.assertEqual(self.reads,[])
