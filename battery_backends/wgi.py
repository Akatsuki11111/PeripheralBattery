"""Controller battery through the supported Windows.Gaming.Input interfaces.
Try both RawGameController and Gamepad; some drivers only provide a battery
report on one of them. Identity/capacity validation is applied by gamepads.py.

The WinRT API is reached through PowerShell (like the Bluetooth provider), so
no extra Python packages are needed. In a fresh process the controller list
fills asynchronously, so the script waits briefly for it.
"""
from __future__ import annotations

import json
import math
import hashlib
from pathlib import Path
import os
import subprocess
import sys
from typing import List, Optional

PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
  $null = [Windows.Gaming.Input.RawGameController, Windows.Gaming.Input, ContentType = WindowsRuntime]
  $null = [Windows.Gaming.Input.Gamepad, Windows.Gaming.Input, ContentType = WindowsRuntime]
  for ($i = 0; $i -lt 30; $i++) {
    if ([Windows.Gaming.Input.RawGameController]::RawGameControllers.Count -gt 0 -or
        [Windows.Gaming.Input.Gamepad]::Gamepads.Count -gt 0) { break }
    Start-Sleep -Milliseconds 100
  }
  Start-Sleep -Milliseconds 300
  $script:list = New-Object 'System.Collections.Generic.List[object]'
  $script:seen = @{}
  function Add-Controller($raw,$pad,$source) {
    $id=''; $vid=0; $pid=0; $name=''; $wireless=$null
    if ($raw) {
      try {$id="$($raw.NonRoamableId)"} catch {}
      $vid=[int]$raw.HardwareVendorId; $pid=[int]$raw.HardwareProductId
      try {$name="$($raw.DisplayName)"} catch {}
      try {$wireless=[bool]$raw.IsWireless} catch {}
    }
    $token=if($id){$id}elseif($raw){'object:'+([Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($raw))}else{''}
    if($token -and $script:seen.ContainsKey($token)){return}
    if($token){$script:seen[$token]=$true}
    $battery=$null
    if($raw){try {$battery=$raw.TryGetBatteryReport()} catch {}}
    if(-not $battery -and $pad){try {$battery=$pad.TryGetBatteryReport()} catch {}}
    if($wireless -eq $null -and $pad){try {$wireless=[bool]$pad.IsWireless} catch {}}
    $script:list.Add([pscustomobject]@{
      id=$id; name=$name; vid=$vid; pid=$pid; wireless=$wireless
      is_gamepad=[bool]$pad; enumeration=$source
      status=$(if($battery){"$($battery.Status)"}else{$null})
      remain=$(if($battery){$battery.RemainingCapacityInMilliwattHours}else{$null})
      full=$(if($battery){$battery.FullChargeCapacityInMilliwattHours}else{$null})
      rate=$(if($battery){$battery.ChargeRateInMilliwatts}else{$null})
    })
  }
  foreach($raw in [Windows.Gaming.Input.RawGameController]::RawGameControllers){
    $pad=$null
    try {$pad=[Windows.Gaming.Input.Gamepad]::FromGameController($raw)} catch {}
    # IGameControllerBatteryInfo also works for raw controllers which cannot
    # be cast to Gamepad. Do not discard their valid battery reports.
    Add-Controller $raw $pad 'RawGameController'
  }
  foreach($pad in [Windows.Gaming.Input.Gamepad]::Gamepads){
    $raw=$null
    try {$raw=[Windows.Gaming.Input.RawGameController]::FromGameController($pad)} catch {}
    Add-Controller $raw $pad 'Gamepad'
  }
  ConvertTo-Json -InputObject ([pscustomobject]@{controllers=@($script:list.ToArray())}) -Compress -Depth 4
} catch {
  ConvertTo-Json -InputObject ([pscustomobject]@{error='Windows controller battery API unavailable'}) -Compress
}
"""

# generic names Windows gives most Xbox-protocol controllers; a better name is
# derived from the hardware vendor id instead
GENERIC_NAMES = {"", "xbox controller", "xbox one controller", "controller (xbox one for windows)",
                 "xbox wireless controller"}
VENDOR_NAMES = {0x3537: "GameSir controller", 0x045E: "Xbox controller"}


class WgiController:
    def __init__(self, raw: dict):
        self.raw = dict(raw)
        # Persist only a one-way application-local token, never the native ID.
        native_id=self.raw.pop("id",None)
        if isinstance(native_id,str) and native_id and len(native_id)<=2048:
            self.raw['id_hash']=hashlib.sha256(native_id.encode('utf-8')).hexdigest()[:24]
        self.raw['name']=str(self.raw.get('name') or '')[:240]
        raw=self.raw
        self.vid = raw.get("vid") or 0
        self.pid = raw.get("pid") or 0
        self.status = str(raw.get("status") or "").lower()      # notpresent / discharging / idle / charging
        self.charging = self.status == "charging"
        remain, full = raw.get("remain"), raw.get("full")
        self.level: Optional[int] = None
        if all(type(n) in (int, float) and math.isfinite(n) for n in (remain,full)) and 0 <= remain <= full and full > 0:
            self.level = max(0, min(100, round(remain * 100 / full)))
        name = (raw.get("name") or "").strip()
        # "HID-compliant game controller" and its translations: a generic HID name
        if "hid" in name.lower():
            name = VENDOR_NAMES.get(self.vid, "")        # "" -> the provider's own name
        elif name.lower() in GENERIC_NAMES:
            name = VENDOR_NAMES.get(self.vid, name or "")
        self.name = name

    def describe(self) -> str:
        return (f"'{self.raw.get('name')}' {self.vid:04x}:{self.pid:04x} status={self.raw.get('status')} "
                f"remain={self.raw.get('remain')} full={self.raw.get('full')} rate={self.raw.get('rate')}")


def parse(raw: str, diag: List[str]) -> Optional[List[WgiController]]:
    if not raw:
        diag.append("[WGI] empty PowerShell output")
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        diag.append("[WGI] could not parse the controller snapshot")
        return None
    if not isinstance(data,dict):
        diag.append("[WGI] invalid snapshot object");return None
    if data.get("error"):
        diag.append(f"[WGI] unavailable: {str(data['error'])[:200]}")
        return None
    items = data.get("controllers") or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items,list):
        diag.append("[WGI] invalid controller list");return None
    ctrls=[];seen=set()
    for item in items[:32]:
        if not isinstance(item,dict):continue
        if any(type(item.get(k,0)) is not int or not 0<=item.get(k,0)<=65535 for k in ('vid','pid')):continue
        controller=WgiController(item);token=controller.raw.get('id_hash')
        if token and token in seen:continue
        if token:seen.add(token)
        ctrls.append(controller)
    for c in ctrls:
        diag.append(f"[WGI] {c.describe()} -> "
                    f"{'%d%%' % c.level if c.level is not None else 'no level'}"
                    f"{' charging' if c.charging else ''}")
    if not ctrls:
        diag.append("[WGI] no controllers listed")
    return ctrls


def query(diag: List[str]) -> Optional[List[WgiController]]:
    """Controllers with their battery reports, or None if the API is unavailable."""
    if sys.platform != "win32":
        return None
    try:
        proc = subprocess.run(
            [str(Path(os.environ.get("SystemRoot", r"C:\Windows"))/"System32/WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", PS_SCRIPT],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=6,
            creationflags=0x08000000)                      # CREATE_NO_WINDOW
    except subprocess.TimeoutExpired:
        diag.append("[WGI] PowerShell did not answer within 6 s")
        return None
    except Exception as e:
        diag.append(f"[WGI] {e}")
        return None
    if proc.returncode!=0:
        diag.append("[WGI] query process failed");return None
    return parse(proc.stdout.decode("utf-8", errors="replace").strip().lstrip("﻿"), diag)
