from dataclasses import asdict
import json,unittest
from unittest.mock import patch,Mock
from classification import wired_evidence,as_wired
from catalog import recognize,backend_for,visible_devices
from models import Device
from inventory import encode_info
from battery_backends.mchose import parse_status,make_request,MchoseProvider
from battery_backends.base import DeviceStatus
from providers import diagnose_mchose
from worker import probe


def response(vid=0x3837,model=0x4150,percent=67,charging=0,report=0x11):
    payload=vid.to_bytes(2,'little')+model.to_bytes(2,'little')+bytes(4)+bytes([9,percent,charging])+bytes(9)
    return bytes([report,0x06^0xff])+bytes(v^0xff for v in payload)


class MchoseKeyboardTests(unittest.TestCase):
    def test_melgeek_pro_plus_requires_full_device_identity(self):
        info=dict(vendor_id=0x0416,product_id=0x0110,manufacturer_string='MelGeek',bus_type=1)
        self.assertTrue(wired_evidence(None,'MADE68PRO+ PL',[info]))
        for changed in ({'vendor_id':0x9999},{'product_id':0x9999},{'manufacturer_string':'Other'},{'bus_type':2}):
            self.assertFalse(wired_evidence(None,'MADE68PRO+ PL',[{**info,**changed}]))
        self.assertFalse(wired_evidence(None,'Other keyboard',[info]))
        self.assertFalse(wired_evidence(None,'MADE68PRO+ PL',[info],receiver=True))
        wired=as_wired(Device('a','MelGeek','MADE68PRO+ PL',kind='keyboard',percent=30), 'exact evidence')
        self.assertEqual(wired.status,'有线连接');self.assertIsNone(wired.percent)
        self.assertEqual(visible_devices([wired],{}),[wired])

    def test_k7_candidate_id_recognition_does_not_mark_usb_batteryless(self):
        for pid in (0x1001,0x4150):
            brand,evidence=recognize(0x3837,pid,name='USB Device')
            self.assertEqual(brand['id'],'mchose');self.assertEqual(backend_for(0x3837,pid),'mchose')
        self.assertFalse(wired_evidence(None,'MCHOSE K7 Ultra',[{'bus_type':1}],backend='mchose'))
        self.assertEqual(backend_for(0x3837,0x4245),'')

    def test_candidate_receiver_with_keyboard_interface_still_uses_mouse_kind(self):
        from inventory import enumerate_groups
        info=dict(path=b'fake',vendor_id=0x3837,product_id=0x1001,product_string='USB Receiver',
                  manufacturer_string='',bus_type=1,usage_page=1,usage=6)
        meta=dict(container='unique',physical='USB\\test',friendly='',manufacturer='')
        with patch('inventory.hid.enumerate',return_value=[info]),patch('inventory.raw_input_paths',return_value={}),\
             patch('inventory.usb_audio_infos',return_value=[]),patch('inventory.metadata',return_value=meta):
            group=enumerate_groups()[0]
        self.assertEqual(group['device']['kind'],'mouse');self.assertTrue(group['device']['receiver'])
        self.assertEqual(group['backend'],'mchose')

    def test_mchose_status_roundtrip_and_malformed_are_refused(self):
        self.assertEqual(parse_status(response()),(67,0,0x4150,9))
        self.assertEqual(parse_status(response(percent=100,charging=1))[:2],(100,1))
        self.assertEqual(parse_status(response(charging=2))[:2],(67,None))
        for data in (bytes(21),make_request(6,0x11,20),response(percent=101),response(charging=255),response(vid=0x9999)):
            self.assertIsNone(parse_status(data))

    def test_mchose_only_sends_status_query_to_configuration_collection(self):
        infos=[dict(vendor_id=0x3837,product_id=0x1001,product_string='K7',usage_page=page,usage=usage,path=bytes([n]))
               for n,(page,usage) in enumerate(((0xff0b,0x104),(0xff01,1),(0xff02,1)))]
        with patch('battery_backends.mchose.hidlist.enumerate',side_effect=lambda vid:[i for i in infos if i['vendor_id']==vid]),\
             patch.object(MchoseProvider,'_read_collection',return_value=(67,0,0x4150,9)) as read:
            result=MchoseProvider().poll()
        read.assert_called_once_with(bytes([1]));self.assertEqual(result[0].level,67)

    def test_worker_scopes_probe_and_exposes_safe_diagnostics(self):
        info=dict(vendor_id=0x3837,product_id=0x1001,usage_page=0xff01,usage=1,path=b'example')
        base=Device('a','MCHOSE','K7').to_dict()
        provider=Mock();provider.poll.return_value=[DeviceStatus('m','K7',67,False,True,kind='mouse')]
        provider.diagnostics.return_value=['matched status on report 0x11']
        module=Mock();module.MchoseProvider.return_value=provider
        diagnostics=[]
        with patch('worker.importlib.import_module',return_value=module):
            readings=probe({'device':base,'infos':[encode_info(info)],'backend':'mchose'},diagnostics)
        self.assertEqual(readings[0]['percent'],67);self.assertEqual(diagnostics,['matched status on report 0x11'])

    def test_diagnostics_omit_paths_serial_numbers_and_other_devices(self):
        group={'backend':'mchose','device':{'name':'K7','brand':'MCHOSE','vid':0x3837,'pid':0x1001},
               'infos':[{'vendor_id':0x3837,'product_id':0x1001,'path':'SECRET_PATH','serial_number':'SECRET_SERIAL',
                         'interface_number':2,'usage_page':0xff01,'usage':1,'bus_type':1}]}
        inventory={'ok':True,'groups':[group,{'backend':'razer','device':{},'infos':[]}]}
        probed={'ok':True,'readings':[{'name':'K7','percent':67,'connected':True,'serial_hash':'SECRET_HASH'}],
                'diagnostics':['only status']}
        with patch('providers.bounded_operation',side_effect=[inventory,probed]) as operation:
            result=diagnose_mchose()
        serialized=json.dumps(result);self.assertNotIn('SECRET',serialized)
        self.assertEqual(len(result['devices']),1);self.assertEqual(result['devices'][0]['readings'][0]['percent'],67)
        self.assertEqual(operation.call_count,2)


if __name__=='__main__':unittest.main()
