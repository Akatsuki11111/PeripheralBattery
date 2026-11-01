import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from pathlib import Path
import tempfile,time,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from models import Device
from ui import Flyout,adaptive_height
from icons import tray_icon,BrandIcon
from settings import Settings
from startup import StartupState
app=QApplication.instance() or QApplication([])


class UiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.settings=Settings(Path(self.tmp.name)/'settings.json')
        self.startup=patch('startup.state',return_value=StartupState(False,False,False,False));self.startup.start()
        self.flyout=Flyout(self.settings);self.flyout.pinned=True
        self.devices=[Device('x','Razer','Razer Viper V3 Pro','mouse',56,False,True,True,observed_at=time.time()),
                      Device('y','SteelSeries','SteelSeries Arctis Nova 5','headset',32,False,True,True,observed_at=time.time())]
        self.flyout.rebuild(self.devices,[]);self.flyout.show_at_tray();app.processEvents()
    def tearDown(self):
        self.flyout.hide();self.flyout.deleteLater();app.processEvents();self.startup.stop();self.tmp.cleanup()
    def test_card_opens_detail_and_escape_returns(self):
        QTest.mouseClick(self.flyout.cards['x'],Qt.MouseButton.LeftButton);self.assertEqual(self.flyout.selected,'x')
        QTest.keyClick(self.flyout,Qt.Key.Key_Escape);self.assertEqual(self.flyout.stack.currentIndex(),0)
        QTest.keyClick(self.flyout,Qt.Key.Key_Escape);self.assertFalse(self.flyout.isVisible())
    def test_toggle_failure_stops_animation_and_restores_thumb(self):
        with patch('startup.set_enabled',side_effect=PermissionError('test')):
            self.flyout.toggle.setFocus();QTest.keyClick(self.flyout.toggle,Qt.Key.Key_Space);QTest.qWait(220)
        self.assertFalse(self.flyout.toggle.isChecked());self.assertEqual(self.flyout.toggle.position,0)
        self.assertEqual(self.flyout.statusline.text(),'开机自启设置失败')
    def test_toggle_enable_uses_reported_state(self):
        with patch('startup.set_enabled',return_value=StartupState(True,True,True,False,message='已开启')) as save:
            self.flyout.toggle.setChecked(True);save.assert_called_once_with(True)
        self.assertTrue(self.flyout.toggle.isChecked());self.assertEqual(self.flyout.toggle.position,1)
    def test_card_and_detail_widgets_survive_refresh(self):
        card=self.flyout.cards['x'];self.flyout.show_detail('x');value=self.flyout.detail_labels['当前电量']
        static=self.flyout.detail_labels['设备类型'];static.setSelection(0,2)
        devices=[replace(self.devices[0],percent=42),self.devices[1]];self.flyout.rebuild(devices,[])
        self.assertIs(card,self.flyout.cards['x']);self.assertIs(value,self.flyout.detail_labels['当前电量'])
        self.assertEqual(value.text(),'42%');self.assertEqual(static.selectedText(),'鼠标')
    def test_height_adapts_to_visible_count_and_caps_for_screen(self):
        heights=[adaptive_height(n,1100) for n in (2,3,6)]
        self.assertTrue(heights[0]<heights[1]<heights[2]);self.assertLessEqual(adaptive_height(100,700),680)
        first=self.flyout.height();self.flyout.rebuild(self.devices+[replace(self.devices[0],key='z')],[])
        self.assertGreater(self.flyout.height(),first)
        self.settings.set('hidden',['z']);self.flyout.rebuild(self.flyout.devices,[]);self.assertEqual(self.flyout.height(),first)
    def test_hide_offline_and_show_offline_preference(self):
        devices=[self.devices[0],replace(self.devices[1],connected=False,percent=None)]
        self.flyout.rebuild(devices,[]);self.assertEqual(len(self.flyout.cards),1)
        self.settings.set('show_offline',True);self.flyout.rebuild(devices,[]);self.assertEqual(len(self.flyout.cards),2)
    def test_unknown_to_live_reading_restores_contrast_and_charging(self):
        unknown=replace(self.devices[0],percent=None,connected=None,observed_at=0)
        self.flyout.rebuild([unknown],[]);card=self.flyout.cards['x'];self.assertEqual(card.value_label.objectName(),'muted')
        self.flyout.rebuild([replace(self.devices[0],charging=True)],[])
        self.assertEqual(card.value_label.objectName(),'');self.assertTrue(card.bar.charging)
    def test_wired_keyboard_ui_shows_not_applicable(self):
        wired=Device.from_dict({**self.devices[0].to_dict(),'key':'wired','brand':'MelGeek','kind':'keyboard','power_mode':'wired'})
        self.flyout.rebuild([wired],[]);card=self.flyout.cards['wired']
        self.assertEqual(card.value_label.text(),'有线');self.assertTrue(card.bar.isHidden())
        self.flyout.show_detail('wired');self.assertEqual(self.flyout.detail_labels['当前电量'].text(),'不适用（有线供电）')

    def test_sleep_time_is_visible_on_card_and_live_reading_clears_it(self):
        d=replace(self.devices[0],percent=None,connected=False,last_percent=56,last_observed_at=time.time()-180)
        self.flyout.rebuild([d],[]);card=self.flyout.cards[d.key]
        self.assertIn(d.last_read_time,card.status_label.text())
        self.assertEqual(card.value_label.text(),'56%');self.assertTrue(card.bar.stale)
        self.flyout.rebuild([self.devices[0]],[]);self.assertNotIn('上次',card.status_label.text())

    def test_gamepad_grade_and_native_icon_render_without_a_fake_percent(self):
        d=replace(self.devices[0],key='pad',kind='gamepad',brand='BETOP',name='北通鲲鹏',percent=None,battery_grade='中')
        self.flyout.rebuild([d],[]);self.assertEqual(self.flyout.cards['pad'].value_label.text(),'中')
        self.flyout.show_detail('pad');self.assertIn('非百分比',self.flyout.detail_labels['当前电量'].text())
        self.assertEqual(self.flyout.cards['pad'].bar.grade,'中');self.assertFalse(self.flyout.cards['pad'].bar.stale)
        self.assertIn('分档电量',self.flyout.summary.text())
        for size in (16,20,32,64):self.assertFalse(tray_icon(d).pixmap(size,size).isNull())
    def test_native_icon_sizes_and_all_brand_icons(self):
        from catalog import brands
        for info in brands():
            logo=BrandIcon(info['name'],'mouse');self.assertFalse(logo.grab().isNull());logo.deleteLater()
        for dark in (False,True):
            with patch('windows.is_dark',return_value=dark),patch('windows.is_taskbar_dark',return_value=dark):
                self.flyout.apply_theme();self.assertFalse(self.flyout.grab().isNull())
                for percent in (0,9,20,56,100):
                    icon=tray_icon(replace(self.devices[0],percent=percent))
                    for size in (16,20,24,32,64):self.assertFalse(icon.pixmap(size,size).isNull())

    def test_history_voltage_chart_and_export_clear(self):
        import json
        d=replace(self.devices[0],voltage_mv=3800,source='nordic52')
        self.flyout.history.record(d);self.flyout.rebuild([d],[]);self.flyout.show_detail(d.key)
        self.assertEqual(self.flyout.detail_labels['当前电压'].text(),'3800 mV')
        self.assertFalse(self.flyout.history_chart.grab().isNull())
        target=Path(self.tmp.name)/'export.json'
        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'JSON')):
            self.flyout.export_history(d)
        self.assertEqual(len(json.loads(target.read_text(encoding='utf-8'))['samples']),1)
        self.flyout.clear_history(d.key);self.assertEqual(self.flyout.history.samples(d.key),[])


if __name__=='__main__':unittest.main()
