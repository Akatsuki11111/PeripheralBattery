import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile,time,unittest
from unittest.mock import patch,MagicMock
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtTest import QTest
from settings import Settings
from startup import StartupState
from models import Device
from ui import Flyout
import windows
app=QApplication.instance() or QApplication([])


class WindowLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.settings=Settings(Path(self.tmp.name)/'settings.json')
        self.state=patch('startup.state',return_value=StartupState(False,False,False,False));self.state.start()
        self.flyout=Flyout(self.settings);self.flyout.pinned=True
        self.flyout.rebuild([Device('a','Razer','Mouse',percent=50,connected=True,observed_at=time.time())],[])
        self.flyout.show_at_tray();app.processEvents()
    def tearDown(self):
        self.flyout.close_windows();self.flyout.deleteLater();app.processEvents();self.state.stop();self.tmp.cleanup()
    def test_manager_hides_flyout_and_is_independent_nonmodal_window(self):
        self.flyout.open_catalog();dialog=self.flyout.catalog_dialog
        self.assertFalse(self.flyout.isVisible());self.assertTrue(dialog.isVisible());self.assertTrue(self.flyout.isEnabled())
        self.assertFalse(dialog.isModal());self.assertIsNone(dialog.parentWidget())
        self.assertFalse(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_mouse_click_does_not_leave_info_button_focus_outline(self):
        QTest.mouseClick(self.flyout.info_button,Qt.MouseButton.LeftButton);app.processEvents()
        self.assertTrue(self.flyout.catalog_dialog.isVisible())
        self.flyout.catalog_dialog.close();app.processEvents();self.flyout.show_at_tray();app.processEvents()
        self.assertFalse(self.flyout.info_button.hasFocus());self.assertFalse(self.flyout.refresh.hasFocus())

    def test_refresh_does_not_reopen_a_hidden_window(self):
        self.flyout.hide();self.flyout.rebuild(self.flyout.devices,[]);QTest.qWait(180)
        self.assertFalse(self.flyout.isVisible())

    def test_rebuilding_same_devices_keeps_geometry_and_card_widgets(self):
        geometry=self.flyout.geometry();card=self.flyout.cards['a']
        for _ in range(3):self.flyout.rebuild(self.flyout.devices,[])
        self.assertEqual(self.flyout.geometry(),geometry);self.assertIs(self.flyout.cards['a'],card)
    def test_escape_and_close_button_release_manager_without_reopening_popup(self):
        self.flyout.open_catalog();QTest.keyClick(self.flyout.catalog_dialog,Qt.Key.Key_Escape);app.processEvents()
        self.assertIsNone(self.flyout.catalog_dialog);self.assertFalse(self.flyout.isVisible())
        self.flyout.open_catalog();self.flyout.catalog_dialog.close();app.processEvents()
        self.assertIsNone(self.flyout.catalog_dialog);self.assertFalse(self.flyout.isVisible())
    def test_done_button_closes_window(self):
        self.flyout.open_catalog();dialog=self.flyout.catalog_dialog
        button=next(b for b in dialog.findChildren(QPushButton) if b.text()=='完成')
        QTest.mouseClick(button,Qt.MouseButton.LeftButton);app.processEvents()
        self.assertIsNone(self.flyout.catalog_dialog)
    def test_reopen_raises_same_manager_and_does_not_create_overlay(self):
        self.flyout.open_catalog();dialog=self.flyout.catalog_dialog;self.flyout.open_catalog()
        self.assertIs(self.flyout.catalog_dialog,dialog);self.assertFalse(self.flyout.isVisible())
    def test_device_details_open_after_manager_closes_and_can_be_dismissed(self):
        self.flyout.open_catalog();self.flyout.catalog_dialog.open_detail('a');QTest.qWait(30)
        self.assertIsNone(self.flyout.catalog_dialog);self.assertTrue(self.flyout.isVisible());self.assertTrue(self.flyout.isEnabled())
        self.assertEqual(self.flyout.selected,'a')
        QTest.keyClick(self.flyout,Qt.Key.Key_Escape);QTest.keyClick(self.flyout,Qt.Key.Key_Escape)
        self.assertFalse(self.flyout.isVisible())


class TrayVisibilityTests(unittest.TestCase):
    def test_only_matching_owned_record_is_promoted(self):
        with patch('windows.tray_records',return_value=[('owned','C:/app.exe')]),patch('windows.winreg.OpenKey',return_value=MagicMock()),patch('windows.winreg.QueryValueEx',return_value=('C:/app.exe',windows.winreg.REG_SZ)),patch('windows.winreg.SetValueEx') as write:
            self.assertEqual(windows.set_tray_promoted(True,'C:/app.exe'),1)
            self.assertEqual(write.call_args.args[1:],('IsPromoted',0,windows.winreg.REG_DWORD,1))
    def test_changed_record_is_not_written(self):
        with patch('windows.tray_records',return_value=[('owned','C:/app.exe')]),patch('windows.winreg.OpenKey',return_value=MagicMock()),patch('windows.winreg.QueryValueEx',return_value=('C:/other.exe',windows.winreg.REG_SZ)),patch('windows.winreg.SetValueEx') as write:
            with self.assertRaises(OSError):windows.set_tray_promoted(True,'C:/app.exe')
            write.assert_not_called()
    def test_missing_record_falls_back_instead_of_creating_foreign_entry(self):
        with patch('windows.tray_records',return_value=[]):
            with self.assertRaises(OSError):windows.set_tray_promoted(True,'C:/app.exe')


if __name__=='__main__':unittest.main()
