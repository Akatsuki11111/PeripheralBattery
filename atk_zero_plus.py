"""Read-only BitMouse status for ATK ZERO+ (hardware verified on both transports)."""
from dataclasses import dataclass
import time

import hid

VID = 0x373B
USB_PID = 0x129E
RECEIVER_PID = 0x124F
NAME = 'ATK ZERO+'
RECEIVER_NAME = 'ATK 8K 接收器 (L0)'
OTHER_MODEL = 1

# Requests and IDs checked against atkctl's protocol notes and local captures.
# 0x81: radio link, 0x4A: mouse identity, 0x07: battery, 0x0F: charging.
_READ_COMMANDS = {0x81: (3, 1), 0x4A: (8, 6), 0x07: (2, 1), 0x0F: (2, 1)}


@dataclass(frozen=True)
class Status:
    online: bool
    model: int | None = None
    percent: int | None = None
    charging: bool | None = None
    packet: bytes = b''


def request_frame(command, receiver):
    params, length = _READ_COMMANDS[command]
    target = int(receiver and command != 0x81)
    packet = bytearray(64)
    packet[:8] = bytes((8, 0, 0x72, params, 0, target, command, length))
    packet[1] = sum(packet[2:]) & 0xff
    return bytes(packet)


def read_reply(handle, command, receiver):
    frame = request_frame(command, receiver)
    if handle.write(frame) != len(frame):
        raise OSError('ATK 状态请求未完整发送。')
    deadline = time.monotonic() + 0.95
    while (remaining := deadline - time.monotonic()) > 0:
        packet = bytes(handle.read(64, max(1, int(remaining * 1000))))
        if (len(packet) == 64 and packet[:3] == b'\x08\x72\x00'
                and packet[5] == command and packet[6] == _READ_COMMANDS[command][1]):
            return packet
    raise TimeoutError('未收到 ATK 对应的有效状态应答；请唤醒鼠标并确认当前连接。')


def read_status(infos, pid):
    matches = [info for info in infos if (info.get('vendor_id'), info.get('product_id'),
               info.get('interface_number'), info.get('usage_page'), info.get('usage'))
               == (VID, pid, 3, 0xff05, 1)]
    if len(matches) != 1 or pid not in (USB_PID, RECEIVER_PID):
        raise ValueError('ATK BitMouse 状态接口缺失或不唯一。')
    receiver = pid == RECEIVER_PID
    handle = hid.device()
    handle.open_path(matches[0]['path'])
    try:
        if receiver:
            linked = read_reply(handle, 0x81, True)[7]
            if linked not in (0, 1):
                raise ValueError('ATK 8K 接收器链路字段无效。')
            if not linked:
                return Status(online=False)
        identity = read_reply(handle, 0x4A, receiver)
        if identity[8:13] != b'\x08\x01\x00\x00\x00':
            return Status(online=True, model=OTHER_MODEL)
        packet = read_reply(handle, 0x07, receiver)
        percent = packet[7]
        if not 0 <= percent <= 100:
            raise ValueError('ATK 电量字段超出百分比范围。')
        try:
            flag = read_reply(handle, 0x0F, receiver)[7]
        except TimeoutError:
            flag = None
        charging = bool(flag) if flag in (0, 1) else None
        return Status(True, USB_PID, percent, charging, packet)
    finally:
        handle.close()
