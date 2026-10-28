from pathlib import Path
import subprocess,sys,tempfile,unittest,winreg
from unittest.mock import patch,MagicMock
import startup


class StartupTests(unittest.TestCase):
    def test_command_parses_quoted_path_and_arguments(self):
        args=['C:/Program Files/App/PeripheralBattery.exe','--background']
        self.assertEqual(startup.split_command(subprocess.list2cmdline(args)),args)
    def test_equivalent_ignores_windows_path_case(self):
        self.assertTrue(startup.equivalent('C:\\Apps\\PB.exe --background','c:\\apps\\pb.exe --background'))
        self.assertFalse(startup.equivalent('C:\\Apps\\PB.exe --background','C:\\Apps\\PB.exe --quit'))
    def test_old_valid_path_reports_enabled_instead_of_off(self):
        with patch('startup.winreg.OpenKey',return_value=MagicMock()),patch('startup.winreg.QueryValueEx',side_effect=[
            ('"C:/old/PeripheralBattery.exe" --background',winreg.REG_SZ),FileNotFoundError()]),patch('startup.Path.is_file',return_value=True):
            current=startup.legacy_state();self.assertTrue(current.enabled);self.assertIn('旧路径',current.message)
    def test_missing_binary_reports_invalid(self):
        with patch('startup.winreg.OpenKey',return_value=MagicMock()),patch('startup.winreg.QueryValueEx',side_effect=[
            ('C:/missing.exe --background',winreg.REG_SZ),FileNotFoundError()]),patch('startup.Path.is_file',return_value=False):
            current=startup.legacy_state();self.assertFalse(current.enabled);self.assertFalse(current.valid)
    def test_task_manager_block_is_detected(self):
        with patch('startup.winreg.OpenKey',return_value=MagicMock()),patch('startup.winreg.QueryValueEx',side_effect=[
            ('C:/app.exe --background',winreg.REG_SZ),(b'\x03'+bytes(11),winreg.REG_BINARY)]),patch('startup.Path.is_file',return_value=True):
            current=startup.legacy_state();self.assertTrue(current.blocked);self.assertFalse(current.enabled)
    def test_auto_repair_respects_task_manager_disable(self):
        current=startup.StartupState(True,False,True,True)
        with patch('startup.state',return_value=current),patch('startup.set_enabled') as save:
            startup.repair_if_requested({'autostart_requested':True});save.assert_not_called()
    def test_explicit_enable_registers_owned_task_and_deletes_only_owned_legacy_value(self):
        current=startup.StartupState(True,True,True,False)
        with patch('startup.ensure_installed'),patch('startup.state',return_value=current),patch('startup.task_request') as request,patch('startup.winreg.OpenKey',return_value=MagicMock()),patch('startup.winreg.DeleteValue') as delete:
            startup.set_enabled(True);self.assertEqual(request.call_args.args,('enable',));self.assertEqual(delete.call_args.args[1],startup.RUN_NAME)

    def task(self,**changes):
        args=startup.split_command(startup.expected_command());sid='S-1-5-21-test'
        import xml.sax.saxutils as escape
        xml=f'''<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><Description>{startup.TASK_OWNER}</Description></RegistrationInfo>
        <Principals><Principal><UserId>{sid}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
        <Triggers><LogonTrigger><UserId>{sid}</UserId></LogonTrigger></Triggers>
        <Settings><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries></Settings>
        <Actions><Exec><Command>{escape.escape(args[0])}</Command><Arguments>{escape.escape(subprocess.list2cmdline(args[1:]))}</Arguments></Exec></Actions></Task>'''
        return dict(present=True,enabled=True,xml=xml,sid=sid,name='PeripheralBattery-'+sid,**changes)

    def test_task_configuration_validates_trigger_user_and_privilege(self):
        task=self.task()
        with patch('startup.task_request',return_value=task),patch('startup.Path.is_file',return_value=True):
            self.assertTrue(startup.state().enabled)
            task['xml']=task['xml'].replace('LeastPrivilege','HighestAvailable');self.assertFalse(startup.state().valid)

    def test_disabled_task_is_respected_and_old_run_is_not_reported_enabled(self):
        task=self.task();task['enabled']=False
        with patch('startup.task_request',return_value=task),patch('startup.Path.is_file',return_value=True):
            self.assertTrue(startup.state().blocked);self.assertFalse(startup.state().enabled)
        with patch('startup.task_request',return_value={'present':False}),patch('startup.legacy_state',return_value=startup.StartupState(True,True,True,False)):
            self.assertFalse(startup.state().enabled);self.assertIn('迁移',startup.state().message)

    def test_system_xml_can_omit_default_privilege_and_use_account_in_trigger(self):
        task=self.task();task['account']='DESKTOP\\PC'
        task['xml']=task['xml'].replace('<RunLevel>LeastPrivilege</RunLevel>','').replace(
            '<LogonTrigger><UserId>'+task['sid'],'<LogonTrigger><UserId>'+task['account'])
        with patch('startup.task_request',return_value=task),patch('startup.Path.is_file',return_value=True):
            self.assertTrue(startup.state().enabled)
            task['xml']=task['xml'].replace('DESKTOP\\PC','DESKTOP\\SomeoneElse');self.assertFalse(startup.state().valid)

    def test_off_does_not_stop_running_application_or_touch_other_tasks(self):
        with patch('startup.task_request') as request,patch('startup.winreg.OpenKey',side_effect=FileNotFoundError()),patch('startup.state',return_value=startup.StartupState(False,False,False,False)):
            startup.set_enabled(False);request.assert_called_once_with('disable')

    def test_profile_path_does_not_depend_on_msix_appdata(self):
        import os
        with patch.dict(os.environ,{'LOCALAPPDATA':'C:/HostPrivate'},clear=False),patch('settings.os.environ.get',side_effect=lambda key,*default:None if key=='PB_DATA_DIR' else os.environ[key] if key in os.environ else default[0] if default else None):
            self.assertNotIn('HostPrivate',str(startup.install_path()))


if __name__=='__main__':unittest.main()
