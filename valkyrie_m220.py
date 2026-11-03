"""VK M3 series M220 identity page read used by the official Windows driver.

The 2.4G receiver answers command 0x10 by itself, so a reply alone never proves
that the mouse is awake; payload byte 14 is the only observed link indicator.
Byte 13 is the battery percentage, byte 12 a raw status flag whose charging
meaning is not established, so charging stays unknown here.
Only the read command 0x10 is sent, never a configuration write.
Evidence: identity replies captured on this machine against the locally
installed official VK M3 Series 1.0.0.5 driver, cross-checked with three
independent fixtures published by OpenMouse-Project/mouse-protocol
(docs/valkyrie-m3-series.md) at 78%, 90% and 100%. Call only in a worker.
"""
from dataclasses import dataclass

RECEIVER_IDS = {(0x249a, 0x5c2f)}
# E023 (VK M3) shares these USB IDs but was never observed on hardware.
MODEL_CODES = {b'M220': ('VALKYRIE', 'VK M3 Lite')}
CONFIG_COLLECTION = (2, 0x0001, 0x0000)


@dataclass(frozen=True)
class Identity:
    linked: bool
    percent: int | None
    status_raw: int
    link_raw: int
    model_code: bytes
    firmware: str
    payload: bytes


def payload(frame):
    data = bytes(frame)
    if len(data) == 33:
        if data[0] != 0:
            raise ValueError('M220 report ID does not match')
        data = data[1:]
    if len(data) != 32:
        raise ValueError('M220 reply must contain 32 payload bytes')
    return data


def identity_packet():
    return bytes([0, 0x10]) + bytes(31)


def parse_identity(frame):
    data = payload(frame)
    if data[0] != 0x10:
        raise ValueError('M220 identity response does not match')
    if data[1] != 0:
        raise ValueError('M220 receiver rejected the identity query')
    if data[2] != 1 or data[3] != 0x0b or not all(0x20 <= c <= 0x7e for c in data[4:8]):
        raise ValueError('M220 identity header is invalid')
    if sum(data[4:31]) & 0xff != data[31]:
        raise ValueError('M220 identity checksum failed')
    level = data[13]
    if not 0 <= level <= 100:
        raise ValueError('M220 battery percentage is invalid')
    return Identity(data[14] == 1, level, data[12], data[14], data[4:8],
                    f'{data[8] | data[9] << 8:04X}', data)


def validate_interface(info):
    if (info.get('vendor_id'), info.get('product_id')) not in RECEIVER_IDS:
        raise ValueError('M220 receiver ID is not allowed')
    interface, page, usage = CONFIG_COLLECTION
    if not (info.get('interface_number') == interface and info.get('usage_page') == page
            and info.get('usage') == usage):
        raise ValueError('M220 configuration collection does not match')


def query_receiver(info):
    """Return the receiver's identity page plus the model gate, never a guess.

    A model code outside MODEL_CODES keeps the battery unread even though the
    reply carries a plausible percentage.
    """
    validate_interface(info)
    from protocols import query
    identity = parse_identity(query(info, identity_packet(), 0x10))
    return {'identity': identity, 'model': MODEL_CODES.get(identity.model_code)}
