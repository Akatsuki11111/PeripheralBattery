import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import json,logging,tempfile,time,unittest
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from models import Device
from settings import DeviceStore,Settings
from jobs import ScanController
from notifications import collect_low_alerts
from ui import DeviceCard
import windows,worker

app=QApplication.instance() or QApplication([])


def battery(key,percent=10,**changes):
    return replace(Device(key,'Scyrox','SCYROX Mouse',percent=percent,charging=False,connected=True,
                          observed_at=time.time()),**changes)


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_boolean_cannot_be_loaded_as_integer_threshold(self):
        path=self.path/'settings.json';path.write_text(json.dumps({'low_threshold':True,'refresh_seconds':True}))
        prefs=Settings(path);self.assertEqual(prefs.get('low_threshold'),20);self.assertEqual(prefs.get('refresh_seconds'),15)

    def test_card_name_stays_stable_on_refresh(self):
        d=battery('a');card=DeviceCard(d);self.assertEqual(card.name_label.text(),'Mouse')
        card.update_device(replace(d,percent=9));self.assertEqual(card.name_label.text(),'Mouse')

    def test_removed_receivers_are_hidden_even_when_offline_display_is_enabled(self):
        from catalog import visible_devices
        removed=replace(battery('removed'),present=False,connected=False,receiver=True)
        sleeping=replace(battery('sleeping'),connected=False,percent=None,receiver=True)
        self.assertEqual(visible_devices([removed,sleeping],{'show_offline':True}),[sleeping])
        self.assertEqual(visible_devices([removed,sleeping],{'show_offline':False}),[])

    def test_finish_is_idempotent_during_synchronous_cancellation(self):
        store=Mock();store.snapshot.return_value=[]
        controller=ScanController(store,Settings(self.path/'settings.json'),logging.getLogger('test'))
        changes=[];controller.busyChanged.connect(changes.append);controller.busy=True
        controller._finish();controller._finish()
        store.save.assert_called_once();self.assertEqual(changes,[False]);controller.shutdown()

    def test_queue_prioritizes_least_recently_started_and_respects_backoff(self):
        store=DeviceStore(self.path/'devices.json');controller=ScanController(store,Settings(self.path/'settings.json'),logging.getLogger('test'))
        controller.inventory=[{'backend':'razer','device':{'identity':key}} for key in ('a','b','c','d')]
        controller.last_attempt={'a':100,'b':200};controller.failures={'d':(1,time.monotonic()+100)}
        with patch.object(controller,'_pump'):controller._start_queries()
        self.assertEqual([g['device']['identity'] for g in controller.queue],['c','a','b'])
        controller.shutdown()

    def test_alerts_are_grouped_and_removed_devices_do_not_leak(self):
        alerts=set();devices=[battery('a'),battery('b',20)]
        self.assertEqual([d.key for d in collect_low_alerts(devices,alerts,20)],['a','b'])
        self.assertEqual(collect_low_alerts(devices,alerts,20),[])
        collect_low_alerts([replace(devices[1],percent=40)],alerts,20);self.assertEqual(alerts,set())
        self.assertEqual([d.key for d in collect_low_alerts(devices,alerts,20)],['a','b'])

    def test_provider_enumeration_is_restored_after_failure(self):
        from battery_backends import hidlist
        original=hidlist.enumerate;provider=Mock();provider.poll.side_effect=ValueError('provider failed')
        module=Mock();module.RazerProvider.return_value=provider
        group={'device':battery('a').to_dict(),'infos':[],'backend':'razer'}
        with patch('worker.importlib.import_module',return_value=module):
            with self.assertRaises(ValueError):worker.probe(group)
        self.assertIs(hidlist.enumerate,original)

    def test_export_redacts_values_without_breaking_json_escaping(self):
        import app as application
        fake_home=Path('C:/Users/Name"Quoted')
        value={'devices':[{'note':str(fake_home/'file')+' \\"quoted\\"'}]}
        with patch('app.Path.home',return_value=fake_home):result=application.redact_export(value)
        self.assertEqual(json.loads(json.dumps(result)),result)
        self.assertTrue(result['devices'][0]['note'].startswith('%USERPROFILE%'))

    def test_tray_changes_roll_back_if_second_record_changes(self):
        entries={'one':{'ExecutablePath':('C:/app.exe',windows.winreg.REG_SZ),'IsPromoted':(0,windows.winreg.REG_DWORD)},
                 'two':{'ExecutablePath':('C:/app.exe',windows.winreg.REG_SZ),'IsPromoted':(0,windows.winreg.REG_DWORD)}}
        counts={'two':0}
        @contextmanager
        def open_key(root,path,*args):yield path.rsplit('\\',1)[-1]
        def query(key,name):
            if key=='two' and name=='ExecutablePath':
                counts['two']+=1
                if counts['two']==2:return ('C:/other.exe',windows.winreg.REG_SZ)
            if name not in entries[key]:raise FileNotFoundError()
            return entries[key][name]
        def write(key,name,reserved,kind,value):entries[key][name]=(value,kind)
        with patch('windows.tray_records',return_value=[('one','C:/app.exe'),('two','C:/app.exe')]),\
             patch('windows.winreg.OpenKey',side_effect=open_key),patch('windows.winreg.QueryValueEx',side_effect=query),\
             patch('windows.winreg.SetValueEx',side_effect=write):
            with self.assertRaises(OSError):windows.set_tray_promoted(True,'C:/app.exe')
        self.assertEqual(entries['one']['IsPromoted'],(0,windows.winreg.REG_DWORD))
        self.assertEqual(entries['two']['IsPromoted'],(0,windows.winreg.REG_DWORD))


if __name__=='__main__':unittest.main()
