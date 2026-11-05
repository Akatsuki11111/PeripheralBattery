import os,time,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from settings import Settings
from models import Device
from desktop_overlay import DesktopOverlay,SIZES
from ui import Flyout
from startup import StartupState
from classification import apply_mode
app=QApplication.instance() or QApplication([])

class DesktopTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.prefs=Settings(Path(self.tmp.name)/'settings.json');self.overlay=DesktopOverlay(self.prefs)
  self.devices=[Device('a','Razer','Mouse',percent=65,connected=True,observed_at=time.time()),Device('b','NuPhy','Keyboard','keyboard',power_mode='wired',connected=True)]
 def tearDown(self):self.overlay.hide();self.overlay.deleteLater();app.processEvents();self.tmp.cleanup()
 def test_disabled_by_default_and_rendering_modes_keep_live_values(self):
  self.overlay.sync(self.devices);self.assertFalse(self.overlay.isVisible())
  for mode in ('detailed','compact'):
   self.prefs.set('desktop_mode',mode);self.overlay.sync(self.devices);app.processEvents()
   self.assertTrue(self.overlay.isVisible());self.assertFalse(self.overlay.grab().isNull());self.assertEqual(self.overlay.devices[0].display_percent,65)
   self.assertEqual(self.overlay.devices[1].reading_text,'有线');self.assertIsNone(self.overlay.devices[1].display_percent)
 def test_sizes_increase_and_compact_is_narrower(self):
  widths=[]
  for size in SIZES:
   self.prefs.set('desktop_size',size);self.prefs.set('desktop_mode','detailed');self.overlay.sync(self.devices);wide=self.overlay.width()
   self.prefs.set('desktop_mode','compact');self.overlay.sync(self.devices);self.assertLess(self.overlay.width(),wide);widths.append(wide)
  self.assertEqual(widths,sorted(widths))
 def test_disconnected_removed_devices_disappear_and_hidden_stay_hidden(self):
  self.prefs.set('desktop_mode','detailed');self.overlay.sync([replace(self.devices[0],present=False),self.devices[1]])
  self.assertEqual([d.key for d in self.overlay.devices],['b'])
  self.prefs.set('hidden',['b']);self.overlay.sync(self.devices);self.assertEqual([d.key for d in self.overlay.devices],['a'])
 def test_sleep_and_unknown_never_turn_into_fake_percentages(self):
  cached=replace(self.devices[0],percent=None,connected=False,receiver=True,last_percent=64,last_observed_at=time.time())
  self.prefs.set('desktop_mode','compact');self.overlay.sync([cached,Device('x','Unknown','Unknown mouse',power_mode='battery')]);app.processEvents()
  self.assertTrue(self.overlay.devices[0].cached);self.assertEqual(self.overlay.devices[0].display_percent,64)
  self.assertIsNone(self.overlay.devices[1].display_percent);self.assertFalse(self.overlay.grab().isNull())
 def test_many_devices_stay_in_screen_and_position_is_clamped(self):
  self.prefs.set('desktop_mode','detailed');self.prefs.set('desktop_size','large');self.overlay.move(-100000,-100000)
  self.overlay.sync([replace(self.devices[0],key=str(i)) for i in range(100)])
  screen=app.primaryScreen().availableGeometry();self.assertLessEqual(self.overlay.height(),screen.height())
  self.assertGreaterEqual(self.overlay.x(),screen.left());self.assertGreaterEqual(self.overlay.y(),screen.top())
 def test_settings_survive_reopening_and_invalid_sizes_are_rejected(self):
  self.prefs.set('desktop_mode','compact');self.prefs.set('desktop_size','large');self.prefs.set('desktop_position',[30,50])
  reopened=Settings(self.prefs.path);self.assertEqual(reopened.get('desktop_position'),[30,50]);self.assertEqual(reopened.get('desktop_size'),'large')
  with self.assertRaises(ValueError):self.prefs.set('desktop_size','huge')
 def test_close_disables_the_overlay_instead_of_reappearing_on_refresh(self):
  self.prefs.set('desktop_mode','detailed');self.overlay.sync(self.devices);self.overlay.close();self.overlay.sync(self.devices)
  self.assertFalse(self.overlay.isVisible());self.assertEqual(self.prefs.get('desktop_mode'),'off')

class FooterTests(unittest.TestCase):
 def test_power_buttons_persist_without_opening_details_and_can_be_reversed(self):
  with tempfile.TemporaryDirectory() as tmp,patch('startup.state',return_value=StartupState(False,False,False,False)):
   prefs=Settings(Path(tmp)/'settings.json');f=Flyout(prefs);f.pinned=True
   device=Device('usb','Unknown','USB Keyboard','keyboard',usb_keyboard=True,transport='USB',power_mode='unknown')
   f.rebuild([device],[])
   f.preferencesChanged.connect(lambda:f.rebuild([apply_mode(device,prefs.get('device_modes',{}).get('usb'))],[]))
   f.show_at_tray();app.processEvents();self.assertEqual(f.width(),350)
   card=f.cards['usb'];self.assertFalse(card.power_row.isHidden())
   QTest.mouseClick(card.power_buttons['wired'],Qt.MouseButton.LeftButton);app.processEvents()
   self.assertEqual(prefs.get('device_modes')['usb'],'wired');self.assertIsNone(f.selected);self.assertEqual(f.cards['usb'].d.reading_text,'有线')
   QTest.mouseClick(card.power_buttons['battery'],Qt.MouseButton.LeftButton);app.processEvents()
   self.assertEqual(prefs.get('device_modes')['usb'],'battery');self.assertFalse(card.power_row.isHidden());self.assertIsNone(f.selected)
   actions = (f.toggle, f.refresh_choice, f.desktop_button, f.test_button, f.update_button, f.theme_button)
   self.assertEqual(len({button.geometry().center().y() for button in actions}), 1)
   self.assertTrue(all(left.geometry().right() < right.geometry().left() for left, right in zip(actions, actions[1:])))
   f.hide();f.deleteLater();app.processEvents()
