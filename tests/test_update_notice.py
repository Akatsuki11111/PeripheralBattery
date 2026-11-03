import os,tempfile,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from settings import Settings,VERSION,atomic_json
from startup import StartupState
from ui import Flyout
app=QApplication.instance() or QApplication([])


class UpdateNoticeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'PB_DATA_DIR':self.tmp.name});self.env.start()
  self.startup=patch('startup.state',return_value=StartupState(False,False,False,False));self.startup.start();self.windows=[]
 def tearDown(self):
  for window in self.windows:window.close_windows();window.deleteLater()
  app.processEvents();self.startup.stop();self.env.stop();self.tmp.cleanup()
 def window(self):
  f=Flyout(Settings(Path(self.tmp.name)/'settings.json'));self.windows.append(f);return f
 def test_blue_badge_only_appears_for_available_update(self):
  f=self.window();f.show_at_tray();app.processEvents();job=object();f.update_job=job
  f.update_checked(job,{'ok':True,'update':{'status':'available','latest':'v9.0.0'}})
  self.assertFalse(f.update_badge.isHidden());self.assertEqual(f.update_badge.text(),'新版本可更新')
  self.assertGreaterEqual(f.update_badge.y(),0);self.assertLess(f.update_badge.y(),f.update_button.y())
  f.update_candidate=None;job=object();f.update_job=job;f.update_checked(job,{'ok':True,'update':{'status':'current'}})
  self.assertTrue(f.update_badge.isHidden())
 def test_automatic_recheck_never_starts_download_or_install(self):
  f=self.window();f.update_candidate={'latest':'v9.0.0'}
  with patch('jobs.WorkerJob') as factory,patch.object(f,'download_update') as download:
   f.check_update(automatic=True)
   self.assertTrue(factory.call_args.args[0]['background'])
  download.assert_not_called()
  f.update_job=None;f.update_candidate=None;f.needs_update_config=True
  with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName') as dialog:f.check_update(automatic=True)
  dialog.assert_not_called()
 def test_current_update_notice_is_short_and_dismissal_persists(self):
  atomic_json(Path(self.tmp.name)/'updates/last-result.json',dict(ok=True,version='v'+VERSION,at=time.time()))
  f=self.window();self.assertFalse(f.release_notice.isHidden())
  self.assertEqual(len(f.release_notice_text.text().splitlines()),3)
  f.dismiss_release_notice();self.assertTrue(f.release_notice.isHidden())
  self.assertTrue(self.window().release_notice.isHidden())
 def test_background_check_never_installs_an_already_downloaded_file(self):
  f=self.window();f.download_ready={'path':'not-a-real-installer'};installed=[];f.installUpdateRequested.connect(installed.append)
  f.check_update(automatic=True);self.assertFalse(installed);self.assertIsNone(f.update_job)
 def test_old_version_or_failed_update_does_not_show_success_notice(self):
  for result in (dict(ok=True,version='v0.0.1'),dict(ok=False,version='v'+VERSION)):
   atomic_json(Path(self.tmp.name)/'updates/last-result.json',{**result,'at':time.time()})
   self.assertTrue(self.window().release_notice.isHidden())
