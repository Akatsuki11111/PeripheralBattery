"""Read Windows' cached Bluetooth battery properties for one enumerated pad.

No discovery, GATT writes, pairing changes, or input state is requested. A
cached percentage is used as live only after a current connection is confirmed.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import subprocess
from identity import cfgmgr,instance_from_path,property_key

BATTERY_KEYS=(property_key('104ea319-6ee2-4701-bd47-8ddbf425bbe5',2),
              property_key('49cd1f76-5626-4b17-a4e8-18b4aa1a2213',10))
XBOX_BT_PIDS={0x02e0,0x02fd,0x0b05,0x0b0c,0x0b13,0x0b20,0x0b21,0x0b22}
XBOX_BLE_PIDS={0x0b13,0x0b20,0x0b21,0x0b22}


def is_bluetooth(infos,vid=0,pid=0):
    if vid==0x045e and pid in XBOX_BT_PIDS:return True
    for info in infos:
        path=info.get('path',b'')
        text=(path.decode(errors='ignore') if isinstance(path,bytes) else str(path)).casefold()
        if info.get('bus_type')==2 or '00001124-' in text or '00001812-' in text or 'bthle' in text:return True
    return False


def bluetooth_properties(infos):
    """Return properties bound to the HID node/its Bluetooth ancestors only."""
    values=set();addresses=set();le=False
    try:
        api=cfgmgr()
        visited=set()
        for info in infos[:8]:
            node=W.DWORD()
            if api.CM_Locate_DevNodeW(C.byref(node),instance_from_path(info.get('path',b'')),0)!=0:continue
            for _ in range(12):
                if node.value in visited:break
                visited.add(node.value)
                text=C.create_unicode_buffer(2048)
                if api.CM_Get_Device_IDW(node,text,len(text),0)!=0:break
                instance=text.value.upper()
                if instance.startswith('USB\\'):break  # Never read the host radio/PC battery.
                if instance.startswith(('BTHLE\\','BTHLEDEVICE\\')):le=True
                match=re.search(r'DEV_([0-9A-F]{12})(?![0-9A-F])',instance)
                if not match and instance.startswith(('BTHENUM\\','BTHLE\\','BTHLEDEVICE\\')):
                    match=re.search(r'_([0-9A-F]{12})(?:_|\\|$)',instance)
                if match:addresses.add(match[1])
                for key in BATTERY_KEYS:
                    kind=W.ULONG();size=W.ULONG(8);buffer=(C.c_ubyte*8)()
                    if api.CM_Get_DevNode_PropertyW(node,C.byref(key),C.byref(kind),buffer,C.byref(size),0)!=0:continue
                    if kind.value==3 and size.value==1:value=buffer[0]  # DEVPROP_TYPE_BYTE
                    elif kind.value==7 and size.value==4:value=int.from_bytes(bytes(buffer[:4]),'little')
                    else:continue
                    if 0<=value<=100:values.add(value)  # 101 is Windows' unknown sentinel.
                parent=W.DWORD()
                if api.CM_Get_Parent(C.byref(parent),node,0)!=0:break
                node=parent
    except (OSError,AttributeError,ValueError):pass
    return {'percent':next(iter(values)) if len(values)==1 else None,
            'address':next(iter(addresses)) if len(addresses)==1 else None,
            'le':le,'conflict':len(values)>1}


CONNECTION_SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
try {
 Add-Type -AssemblyName System.Runtime.WindowsRuntime
 $asTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
   $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
 $address=[Convert]::ToUInt64($env:PB_PAD_BT_ADDRESS,16)
 if($env:PB_PAD_BT_LE -eq '1') {
   $type=[Windows.Devices.Bluetooth.BluetoothLEDevice,Windows.Devices.Bluetooth,ContentType=WindowsRuntime]
   $operation=[Windows.Devices.Bluetooth.BluetoothLEDevice]::FromBluetoothAddressAsync($address)
 } else {
   $type=[Windows.Devices.Bluetooth.BluetoothDevice,Windows.Devices.Bluetooth,ContentType=WindowsRuntime]
   $operation=[Windows.Devices.Bluetooth.BluetoothDevice]::FromBluetoothAddressAsync($address)
 }
 $task=$asTask.MakeGenericMethod($type).Invoke($null,@($operation))
 $connected=$null;$percent=$null
 if($task.Wait(1500)) {
   $device=$task.Result
   if($device) {
     try {
       $connected=("$($device.ConnectionStatus)" -eq 'Connected')
       if($connected) {
         $null=[Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration,ContentType=WindowsRuntime]
         $kind=[Windows.Devices.Enumeration.DeviceInformationKind]::AssociationEndpoint
         $infoType=[Windows.Devices.Enumeration.DeviceInformation]
         $infoOp=$infoType::CreateFromIdAsync($device.DeviceInformation.Id,[string[]]@('System.Devices.BatteryLife'),$kind)
         $infoTask=$asTask.MakeGenericMethod($infoType).Invoke($null,@($infoOp))
         if($infoTask.Wait(1000) -and $infoTask.Result) {
           $value=$infoTask.Result.Properties['System.Devices.BatteryLife']
           if($null -ne $value -and $value -isnot [bool] -and $value -ge 0 -and $value -le 100){$percent=[int]$value}
         }
       }
     } catch {} finally {$device.Dispose()}
   }
 }
 [pscustomobject]@{connected=$connected;percent=$percent} | ConvertTo-Json -Compress
} catch { [pscustomobject]@{connected=$null} | ConvertTo-Json -Compress }
'''


def bluetooth_state(address,le):
    unknown={'connected':None,'percent':None}
    if not isinstance(address,str) or not re.fullmatch('[0-9A-Fa-f]{12}',address):return unknown
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        process=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-Command',CONNECTION_SCRIPT],
            env={**os.environ,'PB_PAD_BT_ADDRESS':address,'PB_PAD_BT_LE':'1' if le else '0'},
            stdin=subprocess.DEVNULL,capture_output=True,timeout=4,creationflags=0x08000000)
        if process.returncode!=0:return unknown
        value=json.loads(process.stdout.decode('utf-8-sig'))
        connected=value.get('connected') if isinstance(value,dict) else None
        percent=value.get('percent') if isinstance(value,dict) else None
        return {'connected':connected if type(connected) is bool else None,
                'percent':percent if connected is True and type(percent) is int and 0<=percent<=100 else None}
    except (OSError,ValueError,subprocess.TimeoutExpired):return unknown


def bluetooth_connected(address,le):
    return bluetooth_state(address,le)['connected']
