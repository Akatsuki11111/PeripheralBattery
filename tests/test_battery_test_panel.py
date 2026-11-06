import os,time,tempfile,unittest
from dataclasses import replace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from models import Device
from settings import Settings
from startup import StartupState
from ui import Flyout
from learning_jobs import LearningController
from battery_test_ui import BatteryTestPanel
app=QApplication.instance() or QApplication([])


def packet(value=80,stamp=100,charging=None):
    return dict(hex=bytes([7,value,4]).hex(' '),length=3,timestamp=stamp,name='Test mouse',vid=1,pid=2,
                interface=2,usage_page=0xff00,usage=2,backend='feature-get',channel={'report_id':7,'length':3},charging=charging)


class BatteryPanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'PB_DATA_DIR':self.tmp.name});self.env.start()
        self.startup=patch('startup.state',return_value=StartupState(False,False,False,False));self.startup.start()
        self.flyout=Flyout(Settings(Path(self.tmp.name)/'settings.json'));self.flyout.pinned=True
        self.device=Device('test','NuPhy','Test mouse','mouse',identity='a'*24,present=True,confidence='unknown',battery_support='identify-only')
        self.flyout.devices=[self.device]
        self.scanner=SimpleNamespace(busy=False,research_active=False,inventory=[dict(device=self.device.to_dict(),infos=[],backend='')])
        self.learning=LearningController(self.scanner);self.flyout.learning=self.learning;self.flyout.research_controller=self.scanner
        self.panel=BatteryTestPanel(self.flyout,self.scanner);self.panel.show();app.processEvents()
    def tearDown(self):
        self.panel.dispose();self.panel.close();self.panel.deleteLater();self.learning.cancel();self.learning.deleteLater()
        self.flyout.close();self.flyout.deleteLater();app.processEvents();self.startup.stop();self.env.stop();self.tmp.cleanup()

    def test_entry_shares_update_row_and_old_top_actions_absent(self):
        self.flyout.rebuild([self.device],[]);self.flyout.show_at_tray();app.processEvents()
        a=self.flyout.test_button.mapTo(self.flyout,self.flyout.test_button.rect().topLeft())
        b=self.flyout.update_button.mapTo(self.flyout,self.flyout.update_button.rect().topLeft())
        self.assertLess(a.x(),b.x());self.assertLess(abs(a.y()-b.y()),12)

    def test_rapoo_pending_connection_is_selectable_and_survives_refresh(self):
        radio=Device('rapoo','Rapoo','VT7 PRO V2',identity='b'*24,vid=0x24ae,pid=0x14a7,
                     receiver=True,battery_support='supported',connected=None,confidence='unknown',
                     last_percent=84,last_observed_at=time.time())
        self.flyout.devices.append(radio)
        self.scanner.inventory.append(dict(device=radio.to_dict(),infos=[],backend='rapoo_vt7_pro_v2'))
        self.panel.fill_devices()
        self.panel.choices.setCurrentIndex(self.panel.choices.findData(radio.identity))
        self.scanner.inventory.reverse()
        self.panel.fill_devices()
        self.assertEqual(self.panel.choices.currentData(),radio.identity)
        self.assertTrue(self.panel.next.isEnabled())
        self.flyout.devices[-1]=replace(radio,connected=True,percent=84,confidence='confirmed',observed_at=time.time())
        self.panel.fill_devices()
        self.assertEqual(self.panel.choices.currentData(),radio.identity)
        self.panel.choices.setCurrentIndex(self.panel.choices.findData(self.device.identity))
        self.panel.fill_devices()
        self.assertEqual(self.panel.choices.findData(radio.identity),-1)
        self.panel.include_supported.setChecked(True)
        self.assertNotEqual(self.panel.choices.findData(radio.identity),-1)

    def test_precheck_requires_explicit_awake_unplugged_ack(self):
        self.panel.advance();self.assertEqual(self.panel.stage,1);self.assertFalse(self.panel.next.isEnabled())
        self.panel.unplug_ack.setChecked(True);self.assertTrue(self.panel.next.isEnabled())

    def test_verified_percentage_and_grade_end_without_observation(self):
        for reading in (dict(percent=61),dict(percent=None,battery_grade='中')):
            self.panel.stage=1;self.scanner.research_active=True;job=object();self.panel.job=job;self.panel.owns_scanner=True
            self.panel.completed(job,dict(ok=True,sample=dict(name='Known',remote_confirmed=True,**reading)),self.panel.generation,1)
            self.assertEqual(self.panel.stage,6);self.assertFalse(self.scanner.research_active);self.assertTrue(self.panel.long_box.isHidden())

    def test_verified_atk_sample_keeps_raw_evidence(self):
        self.panel.stage=1;job=object();self.panel.job=job
        sample=dict(packet(),name='ATK ZERO+',backend='atk_zero_plus',percent=86,remote_confirmed=True,protocol_verified=True)
        self.panel.completed(job,dict(ok=True,sample=sample),self.panel.generation,1)
        self.assertEqual(self.panel.stage,6)
        self.assertIn(sample['hex'],self.panel.details.toPlainText())

    def test_no_response_stops_precheck_and_does_not_start_observing(self):
        self.panel.stage=1;job=object();self.panel.job=job
        self.panel.completed(job,dict(ok=False,error='设备没有应答'),self.panel.generation,1)
        self.assertEqual(self.panel.stage,1);self.assertIn('没有应答',self.panel.text.text());self.assertFalse(self.learning.session)

    def test_back_cancels_active_query_and_ignores_late_result(self):
        self.panel.stage=2;job=MagicMock();self.panel.job=job;old=self.panel.generation
        self.panel.previous();job.cancel.assert_called_once();self.assertEqual(self.panel.stage,1)
        self.panel.completed(job,dict(ok=True,sample=packet()),old,2);self.assertFalse(self.panel.before)

    def test_manual_plug_confirmation_starts_paired_sampling(self):
        self.panel.stage=3;self.panel.identity='a'*24;self.panel.before=[packet() for _ in range(3)]
        with patch.object(self.panel,'take_sample') as take:self.panel.advance()
        self.assertEqual(self.panel.stage,4);take.assert_called_once()

    def test_background_observation_needs_second_unplug_confirmation(self):
        self.panel.stage=5;self.panel.identity='a'*24;self.panel.before=[packet() for _ in range(3)];self.panel.after=[packet() for _ in range(3)]
        self.panel.start_long();self.assertFalse(self.learning.session)
        self.panel.long_ack.setChecked(True);self.panel.start_long()
        self.assertEqual(self.learning.session['state'],'awaiting_unplug');self.assertTrue(self.learning.session['unplug_confirmed'])
        self.assertEqual(self.panel.pages.currentIndex(),1)
        self.panel.close();self.assertEqual(self.learning.session['state'],'awaiting_unplug')

    def test_reopening_returns_to_same_observation_and_blocks_new_device(self):
        self.learning.start('a'*24,[packet()]*3,[packet()]*3,1,True)
        other=BatteryTestPanel(self.flyout,self.scanner)
        self.assertEqual(other.pages.currentIndex(),1);other.advance();self.assertEqual(other.pages.currentIndex(),1)
        other.dispose();other.close();other.deleteLater()

    def test_unknown_report_resume_requires_explicit_unplug_confirmation(self):
        self.learning.start('a'*24,[packet()]*3,[packet()]*3,1,True);self.learning.pause()
        self.panel.resume_observation();self.assertEqual(self.learning.session['state'],'paused')
        self.panel.resume_ack.setChecked(True);self.panel.resume_observation()
        self.assertEqual(self.learning.session['state'],'awaiting_unplug');self.assertTrue(self.learning.session['unplug_confirmed'])

    def test_read_failure_breaks_elapsed_time_continuity(self):
        self.learning.start('a'*24,[packet()]*3,[packet()]*3,1,True)
        self.learning.session.update(state='observing',usage=[packet(stamp=100)],last_unplugged=True)
        self.learning.completed(None,{'ok':False,'error':'timeout'},self.learning.generation)
        self.learning.completed(None,{'ok':True,'sample':packet(stamp=220)},self.learning.generation)
        self.assertEqual(self.learning.session['elapsed_seconds'],0)
        self.assertTrue(self.learning.session['usage'][-1]['segment_start'])

    def test_unknown_report_after_restart_is_not_counted_until_acknowledged(self):
        self.learning.start('a'*24,[packet()]*3,[packet()]*3,1)
        self.learning.completed(None,{'ok':True,'sample':packet()},self.learning.generation)
        self.assertEqual(self.learning.session['state'],'awaiting_unplug');self.assertFalse(self.learning.session['usage'])

    def test_rejecting_candidate_moves_on_and_confirmation_is_explicit(self):
        candidate=dict(offset=1,current=77,drop=3,changes=3,confidence='中')
        self.learning.session=dict(state='completed',identity='a'*24,before=[packet()]*3,charged=[packet()]*3,
            usage=[],elapsed_seconds=3600,target_seconds=3600)
        with patch('battery_test_ui.analyze',return_value=dict(candidates=[candidate],valid_minutes=60,note='相关性')):
            self.panel.observation_changed();self.assertFalse(self.panel.apply_candidate.isEnabled())
            self.panel.review_ack.setChecked(True);self.assertTrue(self.panel.apply_candidate.isEnabled())
            self.panel.reject_observation();self.assertEqual(self.panel.candidates.count(),0);self.assertFalse(self.panel.apply_candidate.isEnabled())


class KnownResearchTests(unittest.TestCase):
    def test_existing_backend_is_checked_before_unknown_feature_reads(self):
        from research import sample
        group=dict(device=dict(identity='a'*24,vid=0x046d,pid=1,name='Known'),backend='logitech',infos=[])
        with patch('research.enumerate_groups',return_value=[group]),patch('worker.probe',return_value=[dict(percent=60,connected=True,confidence='confirmed')]),patch('feature_reports.get_feature') as feature:
            result=sample('a'*24)
        self.assertTrue(result['protocol_verified']);self.assertEqual(result['percent'],60);feature.assert_not_called()
