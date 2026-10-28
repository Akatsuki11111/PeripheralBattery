"""Read a confirmed ROG Harpe Ace Mini through its Omni receiver.

Only the receiver's paired-list GET and the mouse's battery GET are sent.
Other paired models and multi-device payloads are intentionally not guessed.
Protocol facts: G-Helper AsusMouse and rigstats OmniMouse battery documentation.
"""
import time
import hid

VID=0x0b05
PID=0x1ace
MINI_PID=0x1b65
PACKET=64


def parse_pairing(data):
    data=list(data)
    if len(data)!=PACKET or data[:3]!=[1,0xa0,0] or data[3]!=1 or data[4]!=0:
        return False
    return data[5]|data[6]<<8==MINI_PID and data[7:9]==[3,5]


def parse_battery(data):
    data=list(data)
    if len(data)!=PACKET or data[:5]!=[3,0x12,7,0,0] or data[5:7]==[0xff,0xaa]:
        raise ValueError('ROG 电量应答格式或长度不匹配')
    level=data[5]
    if level>100:raise ValueError('ROG 电量超出范围')
    charging=data[10]>0
    if level==0 and not charging:return False,None,None,None
    voltage=data[8]|data[9]<<8
    if not 2000<=voltage<=5000:voltage=None
    return True,level,charging,voltage


def get_report(info,report_id,command):
    handle=hid.device()
    try:
        handle.open_path(info['path'])
        packet=[report_id,*command]+[0]*(PACKET-1-len(command))
        if handle.write(packet)!=PACKET:raise OSError('ROG 请求写入长度不匹配')
        deadline=time.monotonic()+1.2
        while time.monotonic()<deadline:
            response=list(handle.read(PACKET,100))
            if response[:3]==[report_id,*command]:return response
        raise TimeoutError('ROG 接收器没有返回匹配的状态应答')
    finally:handle.close()


def query(infos):
    if not infos or any(i.get('vendor_id')!=VID or i.get('product_id')!=PID for i in infos):
        raise ValueError('ROG 接收器标识不匹配')
    def select(page):
        found=[i for i in infos if i.get('interface_number')==2 and i.get('usage_page')==page and i.get('usage')==1]
        if len(found)!=1:raise ValueError('ROG 接收器状态接口缺失或不唯一')
        return found[0]
    paired=get_report(select(0xff02),1,[0xa0,0])
    if not parse_pairing(paired):return []
    online,level,charging,voltage=parse_battery(get_report(select(0xff01),3,[0x12,7]))
    return [{'name':'ROG Harpe Ace Mini','kind':'mouse','level':level,'charging':charging,
             'online':online,'voltage_mv':voltage,'firmware':''}]
