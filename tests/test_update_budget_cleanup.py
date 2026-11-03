import io,json,tempfile,time,os,unittest
from pathlib import Path
from unittest.mock import patch
from settings import atomic_json
from maintenance import cleanup_cache
from updates import _read_metadata
from scheduling import UpdateTimer
from PySide6.QtWidgets import QApplication
app=QApplication.instance() or QApplication([])

class BackgroundTests(unittest.TestCase):
 def test_background_metadata_is_bounded_and_paced(self):
  with patch('updates.time.sleep') as sleep:
   self.assertEqual(_read_metadata(io.BytesIO(b'x'*2000),True),b'x'*2000);self.assertEqual(sleep.call_count,4)
   with self.assertRaises(ValueError):_read_metadata(io.BytesIO(b'x'*16385),True)
 def test_two_hour_timer_has_one_live_schedule_and_no_catchup_loop(self):
  calls=[];timer=UpdateTimer(lambda:calls.append(True));self.assertTrue(timer.isSingleShot());self.assertEqual(timer.interval(),1200)
  timer.tick();self.assertEqual(calls,[True]);self.assertEqual(timer.interval(),7200000);self.assertTrue(timer.isActive());timer.stop()

class CleanupTests(unittest.TestCase):
 def test_successful_stage_is_removed_without_deleting_an_uninstalled_download(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'bin').mkdir();(root/'updates').mkdir()
   (root/'bin/PeripheralBattery.exe').write_bytes(b'current')
   installed_stage=root/'updates'/('a'*32+'.exe');installed_stage.write_bytes(b'current')
   pending=root/'updates'/('b'*32+'.exe');pending.write_bytes(b'newcopy')
   atomic_json(root/'updates/last-result.json',{'ok':True})
   cleanup_cache(root);self.assertFalse(installed_stage.exists());self.assertTrue(pending.exists())
 def test_cleanup_only_stale_owned_caches_and_preserves_active_installer(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);now=time.time();old=now-90000
   def file(name,data=b'old'):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);os.utime(p,(old,old));return p
   expired=file('updates/'+'a'*32+'.exe');worker=file('workers/'+'b'*32+'.progress.json')
   active=file('updates/'+'c'*32+'.exe');fresh=file('workers/'+'d'*32+'.request.json');os.utime(fresh,(now,now))
   foreign=file('updates/user-backup.exe');settings=file('settings.json');mapping=file('research-map.json');secret=file('update-connection.dpapi')
   atomic_json(root/'updates'/('e'*32+'.install.json'),{'download':{'path':str(active)}})
   report=cleanup_cache(root,now);self.assertEqual(report['removed'],2);self.assertEqual(report['reclaimed_bytes'],6)
   for p in (active,fresh,foreign,settings,mapping,secret):self.assertTrue(p.exists())
   self.assertFalse(expired.exists());self.assertFalse(worker.exists())
 def test_failed_install_backup_is_kept_until_a_success_is_recorded(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);backup=root/'bin'/('PeripheralBattery.exe.'+'f'*32+'.bak');backup.parent.mkdir();backup.write_bytes(b'backup')
   old=time.time()-90000;os.utime(backup,(old,old));atomic_json(root/'updates/last-result.json',{'ok':False})
   cleanup_cache(root);self.assertTrue(backup.exists())
   atomic_json(root/'updates/last-result.json',{'ok':True});cleanup_cache(root);self.assertFalse(backup.exists())
