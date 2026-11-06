"""Identity/descriptor diagnostics, available in both release channels."""
import re,json
from pathlib import Path
from inventory import enumerate_groups,decode_info


def inspect_device(identity):
    if not re.fullmatch('[a-f0-9]{24}',str(identity)):raise ValueError('设备标识无效')
    groups=[g for g in enumerate_groups() if g['device'].get('identity')==identity]
    if len(groups)!=1:raise ValueError('设备已断开或身份改变，请重新选择')
    group=groups[0];device=group['device'];infos=[decode_info(i) for i in group['infos']]
    from feature_reports import inspect_features
    candidates=[]
    try:
        rows=json.loads((Path(__file__).with_name('assets')/'valkyrie-devices.json').read_text(encoding='utf-8'))['rows']
        candidates=[r for r in rows if int(r['vid'],16)==device['vid'] and int(r['pid'],16)==device['pid']]
    except (OSError,ValueError,KeyError,TypeError):pass
    diagnostics=inspect_features(infos)
    feature_declared=any(row.get('report_ids') for row in diagnostics)
    vendor_io=any(row.get('usage_page',0)>=0xff00 and row.get('input_length',0)
                  and row.get('output_length',0) for row in diagnostics)
    channel_summary={'known_backend':bool(group['backend']),'feature_declared':feature_declared,
                     'vendor_input_output':vendor_io}
    return {'device':{k:device.get(k) for k in ('name','brand','vid','pid','kind','receiver')},
            'backend':group['backend'],
            'interfaces':[{k:i.get(k) for k in ('interface_number','usage_page','usage','bus_type','product_string','manufacturer_string')} for i in infos[:32]],
            'feature_diagnostics':diagnostics,'channel_summary':channel_summary,'valkyrie_candidates':candidates,
            'scope':'仅读取设备身份及报告描述；不读取键鼠输入，不查询电量，不修改设备'}

