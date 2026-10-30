import ctypes as C
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from long_learning import analyze,save_mapping,decode_mapping,mappings
from models import Device,lowest
from settings import DeviceStore
from catalog import visible_devices
from research import research_devices
from feature_reports import Caps,channels_for,get_feature


def packet(level,t,charging=None):
    return {'timestamp':t,'hex':bytes([7,level,1,0]).hex(' '),'length':4,'charging':charging,
            'vid':123,'pid':456,'interface':0,'usage_page':0xff01,'usage':1,'backend':'feature-get',
            'name':'Experimental','channel':{'report_id':7,'length':4,'descriptor':'x','collection':'y'}}


class LongLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict('os.environ',{'PB_DATA_DIR':self.tmp.name});self.env.start()
        self.now=time.time();self.before=[packet(80,self.now+i) for i in range(3)]
        self.charged=[packet(81,self.now+10+i) for i in range(3)]
        self.usage=[packet(80-i//30,self.now+60*i) for i in range(121)]
    def tearDown(self):self.env.stop();self.tmp.cleanup()

    def test_long_monotonic_candidate_remains_experimental(self):
        result=analyze(self.before,self.charged,self.usage)
        self.assertEqual(result['valid_minutes'],120)
        self.assertEqual(result['candidates'][0]['offset'],1);self.assertEqual(result['candidates'][0]['confidence'],'低')
        for s in self.usage:s['charging']=False
        self.assertEqual(analyze(self.before,self.charged,self.usage)['candidates'][0]['confidence'],'中')

    def test_constant_short_and_counter_do_not_qualify(self):
        for usage in ([packet(80,self.now+60*i) for i in range(121)],self.usage[:10],
                      [packet(100-i,self.now+60*i) for i in range(61)]):
            self.assertFalse(analyze(self.before,self.charged,usage)['candidates'])

    def test_recharge_gaps_and_wrong_channel_do_not_create_confidence(self):
        charged=[{**s,'charging':True} for s in self.usage]
        self.assertFalse(analyze(self.before,self.charged,charged)['candidates'])
        short_segments=[{**s,'segment_start':i%30==0} for i,s in enumerate(self.usage)]
        self.assertFalse(analyze(self.before,self.charged,short_segments)['candidates'])
        wrong=[{**s,'channel':{'report_id':8}} for s in self.usage]
        self.assertFalse(analyze(self.before,self.charged,wrong)['candidates'])

    def test_explicit_mapping_persists_evidence_and_checks_framing(self):
        session={'state':'completed','identity':'a'*24,'before':self.before,'charged':self.charged,'usage':self.usage}
        candidate=analyze(self.before,self.charged,self.usage)['candidates'][0]
        save_mapping(session,candidate);mapping=mappings()['a'*24]
        self.assertEqual(decode_mapping(self.usage[-1],mapping),76)
        self.assertTrue((Path(self.tmp.name)/mapping['evidence_file']).is_file())
        for changed in ({**self.usage[-1],'channel':{}},{**self.usage[-1],'hex':'07 ff 01 00'}):
            with self.assertRaises(ValueError):decode_mapping(changed,mapping)
        with self.assertRaises(ValueError):save_mapping({**session,'state':'observing'},candidate)

    def test_offline_and_known_devices_are_not_pending_adaptation(self):
        nova=Device('nova','SteelSeries','Nova 5',vid=0x1038,pid=0x2232,receiver=True,connected=False,battery_support='supported')
        unknown=Device('unknown','NuPhy','Halo',vid=0x19f5,pid=0x3247,receiver=True)
        self.assertEqual(research_devices([nova,unknown]),[unknown])
        self.assertEqual(research_devices([replace(nova,connected=True),unknown]),[unknown])
        self.assertIn(replace(nova,connected=True),research_devices([replace(nova,connected=True)],True))
        self.assertFalse(research_devices([nova],True))

    def test_inactive_mouse_keeps_last_value_and_time_without_live_side_effects(self):
        store=DeviceStore(Path(self.tmp.name)/'devices.json')
        live=Device('m','Razer','Mouse',identity='a',receiver=True,kind='mouse',percent=72,connected=True,observed_at=self.now)
        store.reconcile([live]);store.apply_readings('a',[{'percent':None,'connected':False,'charging':None,'observed_at':self.now+1,'confidence':'unknown'}])
        inactive=store.snapshot()[0]
        self.assertTrue(inactive.cached);self.assertEqual(inactive.reading_text,'72%');self.assertEqual(inactive.last_observed_at,self.now)
        self.assertIn('上次',inactive.status);self.assertIsNone(lowest([inactive]))
        self.assertIn(inactive,visible_devices([inactive],{}))
        store.apply_readings('a',[{'percent':None,'connected':None,'observed_at':self.now+2}])
        self.assertEqual(store.snapshot()[0].last_observed_at,self.now)
        store.save();restored=DeviceStore(store.path).snapshot()[0];self.assertFalse(restored.present)
        self.assertEqual(restored.last_percent,72);self.assertEqual(restored.last_observed_at,self.now)
        self.assertFalse(visible_devices([replace(inactive,present=False)],{'show_offline':True}))
        self.assertFalse(replace(inactive,last_observed_at=self.now-86401).cached)

    def test_experimental_reading_is_not_usable_or_minimum(self):
        d=Device('m','NuPhy','Halo',percent=42,connected=None,observed_at=self.now,confidence='experimental')
        self.assertTrue(d.experimental);self.assertEqual(d.reading_text,'42%?');self.assertIsNone(lowest([d]))
        self.assertIn('实验',d.status);self.assertIn(d,visible_devices([d],{}))

    def test_upgrade_recovers_only_a_matching_real_history_timestamp(self):
        from settings import atomic_json
        d=Device('old','Razer','Mouse',identity='a',last_percent=72,last_seen=self.now,receiver=True,connected=False)
        path=Path(self.tmp.name)/'devices.json';atomic_json(path,[d.to_dict()])
        atomic_json(path.with_name('history.json'),{'version':1,'devices':{'old':[{'at':self.now-300,'percent':72,'source':'razer','charging':False}]}})
        restored=DeviceStore(path);self.assertEqual(restored.snapshot()[0].last_observed_at,self.now-300)
        restored.reconcile([replace(d,connected=None)]);self.assertTrue(restored.snapshot()[0].cached)
        atomic_json(path.with_name('history.json'),{'version':1,'devices':{'old':[{'at':self.now-300,'percent':71}]}})
        self.assertEqual(DeviceStore(path).snapshot()[0].last_observed_at,0)

    def test_worker_mapping_returns_uncertain_reading_not_confirmed_battery(self):
        from worker import probe
        session={'state':'completed','identity':'a'*24,'before':self.before,'charged':self.charged,'usage':self.usage}
        candidate=analyze(self.before,self.charged,self.usage)['candidates'][0];save_mapping(session,candidate)
        group={'backend':'learned','device':{'name':'Experimental','identity':'a'*24},'infos':[]}
        with patch('worker.EXPERIMENTAL_ENABLED',True),patch('research.sample',return_value=self.usage[-1]):reading=probe(group)[0]
        self.assertEqual(reading['confidence'],'experimental');self.assertIsNone(reading['connected']);self.assertEqual(reading['percent'],76)


class FeatureTests(unittest.TestCase):
    def test_sdk_caps_size_and_only_declared_feature_ids(self):
        self.assertEqual(C.sizeof(Caps),64)
        caps=Caps();caps.UsagePage=0xff01;caps.Usage=1;caps.FeatureLength=65;caps.FeatureValues=1
        class Fn:
            def __call__(self,report_type,entries,count,data):
                if report_type!=2:raise AssertionError('Input reports must not be read')
                buf=bytearray(72);buf[:3]=bytes([1,255,7]);C.memmove(entries,bytes(buf),72);return 0x110000
        hid=SimpleNamespace(HidP_GetValueCaps=Fn())
        channels=channels_for({'path':b'path','interface_number':1},hid,None,caps)
        self.assertEqual([c['report_id'] for c in channels],[7]);self.assertEqual(channels[0]['length'],65)
        caps.UsagePage=1;self.assertFalse(channels_for({'path':b'path'},hid,None,caps))

    def test_wrong_pinned_descriptor_never_reads_report(self):
        from contextlib import contextmanager
        calls=[]
        class Hid:
            def HidD_GetFeature(self,*args):calls.append(args);return True
        caps=Caps();caps.UsagePage=0xff01;caps.Usage=1;caps.FeatureLength=4
        @contextmanager
        def opened(path):yield 1,Hid(),None,caps
        info={'path':b'path','usage_page':0xff01}
        with patch('feature_reports.opened',opened),patch('feature_reports.channels_for',return_value=[{'report_id':7,'length':4}]):
            with self.assertRaises(ValueError):get_feature([info],{'report_id':8,'length':4})
        self.assertFalse(calls)
