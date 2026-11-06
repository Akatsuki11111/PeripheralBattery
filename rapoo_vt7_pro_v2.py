"""VT7 PRO V2 vendor status reports, verified on USB and 2.4 GHz.

The official A HUB VT_nrf54L manifest assigns 24AE:46A7 to the mouse
and 24AE:14A7 to its receiver. This collection sends report 0x07 about
every three seconds while active. No configuration command is required.
"""
from dataclasses import dataclass
import math
import time

import hid

VID = 0x24AE
USB_PID = 0x46A7
RECEIVER_PID = 0x14A7
REPORT_SIZE = 19


@dataclass(frozen=True)
class Status:
    packet: bytes
    online: bool
    percent: int | None
    charging: bool | None


def parse_status(packet, pid):
    if (pid not in (USB_PID, RECEIVER_PID) or len(packet) != REPORT_SIZE
            or packet[0] != 0x07 or int.from_bytes(packet[13:15], 'little') != USB_PID):
        return None
    if pid == RECEIVER_PID and not packet[18] & 0x80:
        return Status(packet, False, None, None)
    battery_state, percent = packet[7:9]
    if battery_state not in (1, 2, 3) or percent > 100:
        return None
    return Status(packet, True, percent, battery_state == 2)


def read_status(infos, pid, timeout=6.5):
    matches = [i for i in infos if (i.get('vendor_id'), i.get('product_id'), i.get('interface_number'),
                                    i.get('usage_page'), i.get('usage')) == (VID, pid, 1, 0xFF00, 2)]
    if len(matches) != 1 or pid not in (USB_PID, RECEIVER_PID):
        raise ValueError('雷柏 VT7 PRO V2 的专用状态接口缺失或不唯一。')
    device = hid.device()
    device.open_path(matches[0]['path'])
    try:
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            packet = bytes(device.read(REPORT_SIZE, math.ceil(remaining * 1000)))
            if not packet:
                break
            status = parse_status(packet, pid)
            if status is not None:
                return status
        return None
    finally:
        device.close()
