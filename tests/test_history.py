from dataclasses import replace
import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from history import HistoryStore,MAX_POINTS,RETENTION
from models import Device
from protocols import parse_nordic52
from worker import probe
from settings import DeviceStore


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.history=HistoryStore(Path(self.tmp.name)/'history.json');self.now=time.time()
    def tearDown(self):self.tmp.cleanup()
    def device(self,at,percent=70,**changes):
        return replace(Device('a','ATK','Mouse',percent=percent,charging=False,connected=True,observed_at=at,
            monotonic_at=time.monotonic(),source='nordic52',voltage_mv=3800),**changes)
    def fill(self,count=121):
        for i in range(count):
            at=self.now-(count-1-i)*60
            self.history.record(self.device(at,90-i//5),at)
        return self.device(self.now,90-(count-1)//5)
    def test_five_minute_ring_bounds_and_retention(self):
        for i in range(MAX_POINTS+12):
            at=self.now-(MAX_POINTS+11-i)*300
            self.history.record(self.device(at),at)
        rows=self.history.samples('a',self.now)
        self.assertEqual(len(rows),MAX_POINTS)
        self.assertTrue(all(self.now-RETENTION<=r['at']<=self.now for r in rows))
        self.assertGreater(self.now-rows[0]['at'],6*86400)
    def test_newest_sample_in_bucket_keeps_voltage(self):
        at=int(self.now//300)*300+1
        self.history.record(self.device(at),at);self.history.record(self.device(at+1,69,voltage_mv=3790),at+1)
        self.assertEqual(len(self.history.samples('a',at+1)),1);self.assertEqual(self.history.samples('a',at+1)[0]['voltage_mv'],3790)
    def test_cache_and_unconfirmed_values_are_never_added(self):
        for changes in ({'present':False},{'connected':None},{'confidence':'unknown'},{'power_mode':'wired'},{'kind':'auxiliary'}):
            self.history.record(self.device(self.now,**changes),self.now)
        self.assertEqual(self.history.samples('a'),[])
    def test_estimate_requires_duration_and_drop(self):
        self.assertIsNone(self.history.estimate(self.fill(6)).hours)
        self.history.forget('a');d=self.fill();estimate=self.history.estimate(d)
        self.assertAlmostEqual(estimate.rate,12,places=1);self.assertAlmostEqual(estimate.hours,5.5,places=1)
    def test_flat_charging_unknown_and_approximate_do_not_predict(self):
        d=self.fill()
        for changes in ({'charging':True},{'charging':None},{'approximate':'分档'},{'connected':False}):
            self.assertIsNone(self.history.estimate(replace(d,**changes)).hours)
        self.history.forget('a')
        for i in range(121):
            at=self.now-(120-i)*60
            self.history.record(self.device(at,70),at)
        self.assertIsNone(self.history.estimate(replace(d,percent=70)).hours)
    def test_disconnect_preserves_previous_usage_without_bridging_the_gap(self):
        d=self.fill();self.history.record(replace(d,connected=False,percent=None),self.now+1)
        later=replace(d,observed_at=self.now+2)
        self.history.record(later,self.now+2)
        self.assertEqual(self.history.estimate(later,self.now+2).active_seconds,7200)
        self.assertTrue(self.history.samples('a',self.now+2)[-1]['break'])

    def test_multiple_days_estimate_uses_online_time_and_same_transport(self):
        start=self.now-2*86400
        for day in range(3):
            for minute in range(21):
                at=start+day*86400-(20-minute)*60
                device=self.device(at,96-day-minute//20)
                self.history.record(device,at)
        estimate=self.history.estimate(device,self.now)
        self.assertEqual(estimate.active_seconds,3600)
        self.assertEqual(estimate.rate,3)
        self.assertEqual(estimate.hours,31)
        self.assertIsNone(self.history.estimate(replace(device,transport='Bluetooth'),self.now).hours)

    def test_legacy_rows_remain_visible_and_restart_does_not_bridge_usage(self):
        legacy={'version':1,'devices':{'a':[{'at':self.now-600,'percent':75,'charging':False}]}}
        self.history.path.write_text(json.dumps(legacy),encoding='utf-8')
        restored=HistoryStore(self.history.path)
        self.assertEqual(restored.samples('a',self.now)[0]['percent'],75)
        device=self.device(self.now,70)
        restored.record(device,self.now)
        self.assertEqual(restored.estimate(device,self.now).active_seconds,0)
        restored.end_session()
        restored.record(replace(device,observed_at=self.now+60),self.now+60)
        self.assertEqual(restored.estimate(device,self.now+60).active_seconds,0)
    def test_long_gap_source_change_and_large_increase_reset(self):
        d=self.fill()
        for changes in ({'observed_at':self.now+1800},{'source':'different'},{'percent':100}):
            h=HistoryStore(Path(self.tmp.name)/'new.json');h.series={'a':self.history.samples('a')}
            at=changes.get('observed_at',self.now+1);h.record(replace(d,observed_at=at,**{k:v for k,v in changes.items() if k!='observed_at'}),at)
            current=replace(d,observed_at=at,**{k:v for k,v in changes.items() if k!='observed_at'})
            self.assertEqual(h.estimate(current,at).active_seconds,7200)
            if 'source' in changes:
                self.assertIsNone(h.estimate(current,at).hours)
    def test_roundtrip_corrupt_future_and_backwards_clock(self):
        self.fill();self.history.save(True);loaded=HistoryStore(self.history.path)
        self.assertEqual(loaded.samples('a'),self.history.samples('a'))
        before=loaded.samples('a');loaded.record(self.device(self.now-500,40),self.now);self.assertEqual(loaded.samples('a'),before)
        self.history.path.write_text('{broken');self.assertEqual(HistoryStore(self.history.path).series,{})
        self.assertIsNone(HistoryStore.validate({'at':float('nan')},self.now))
        self.assertIsNone(HistoryStore.validate({'at':self.now+1,'percent':70},self.now))
    def test_voltage_validation_and_wired_cleanup(self):
        d=self.device(self.now)
        for voltage in (True,'3800',-1,10000,float('nan')):
            self.assertIsNone(Device.from_dict({**d.to_dict(),'voltage_mv':voltage}).voltage_mv)
        self.assertIsNone(Device.from_dict({**d.to_dict(),'power_mode':'wired'}).voltage_mv)
    def test_nordic_voltage_survives_worker_and_is_not_firmware(self):
        frame=[8,4,0,0,0,2,35,0,0x0e,0x94]+[0]*7;frame[-1]=(0x55-sum(frame[:-1]))&255
        self.assertEqual(parse_nordic52(frame)[3],3732)
        group={'device':self.device(self.now).to_dict(),'infos':[],'backend':'nordic52'}
        with patch('worker.read_local',return_value=parse_nordic52(frame)):
            r=probe(group)[0];self.assertEqual(r['voltage_mv'],3732);self.assertEqual(r['firmware'],'')
    def test_device_store_collects_probes_and_forget_removes_history(self):
        store=DeviceStore(Path(self.tmp.name)/'devices.json');d=replace(self.device(self.now),identity='a')
        store.reconcile([d]);self.assertEqual(store.history.samples('a'),[])
        store.apply_readings('a',[{'percent':60,'connected':True,'observed_at':self.now}]);self.assertEqual(len(store.history.samples('a')),1)
        store.save();restored=DeviceStore(store.path);self.assertIsNone(restored.devices['a'].percent);self.assertEqual(len(restored.history.samples('a')),1)
        store.forget('a');self.assertFalse(store.history.samples('a'))


if __name__=='__main__':unittest.main()
