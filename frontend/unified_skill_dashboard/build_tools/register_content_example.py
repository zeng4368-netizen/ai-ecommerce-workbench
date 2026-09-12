"""Explicitly import the user's 16-file M98 example into the local content studio."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
import urllib.request
import uuid

parser=argparse.ArgumentParser()
parser.add_argument('--folder',type=Path,required=True)
parser.add_argument('--url',default='http://127.0.0.1:8765')
args=parser.parse_args()
if urlsplit(args.url).hostname not in ('localhost','127.0.0.1'):raise SystemExit('Local server only')
record=args.folder/'registration.json'
issues=[
 '第13张（详情图4）写4GB RAM、1080P、2.4GHz，并展示盒式设备；标题与主图为M98电视棒、8GB+64GB、4K、双频WiFi。不能作为同一规格的真实性证明。',
 '第15张（详情图6）展示TX98盒式产品，与M98电视棒的型号、机身和接口不一致。',
 '第12张（详情图3）展示不同遥控器并声明蓝牙/语音控制；第16张也声明蓝牙控制。需核对实际发货遥控器，不能从展示图自动迁入产品事实。',
 '第10、11张声明HDR10+，第14张声明H313处理器。当前标题与详情未给出对应核实依据。',
 '第5张底部内容不完整并有白色空白。按用户要求原样保留，不自动裁切、补画或修复。',
 '免费内容、三年保修、COD和24小时发货均来自用户提供文案。实例归档不代表授权、履约条件或平台审核已被系统验证。',
 '部分图含页码、多个卖点和对比示意，与默认V2.0新生成规则存在差异；本实例按用户明确要求原样归档，不冒称符合全部生图规则。'
]
def call(path,payload=None,file=None):
    content=None;headers={}
    if file is not None:
        boundary=uuid.uuid4().hex;parts=[]
        for key,value in payload.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\nContent-Type: image/png\r\n\r\n'.encode()+file.read_bytes()+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode());content=b''.join(parts)
        headers['Content-Type']='multipart/form-data; boundary='+boundary
    elif payload is not None:
        content=json.dumps(payload,ensure_ascii=False).encode('utf-8');headers['Content-Type']='application/json'
    request=urllib.request.Request(args.url+'/api/hub/content'+path,data=content,headers=headers)
    with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)

def main():
    if record.exists():
        ident=json.loads(record.read_text(encoding='utf-8'))['id']
        p=call('/projects/'+ident)
    else:
        p=call('/examples',{
          'brief':{'name':'M98 TV Stick｜用户成品展示实例','detail_count':7,
                   'unknowns':'图片与文案规格不一致，保留原样供展示；核对提示见实例。'},
          'title':(args.folder/'title.txt').read_text(encoding='utf-8'),
          'description':(args.folder/'description.md').read_text(encoding='utf-8'),'issues':issues})
        with record.open('x',encoding='utf-8') as stream:json.dump({'id':p['id'],'url':args.url+'/#content-studio'},stream,ensure_ascii=False,indent=2)
    for i in range(1,17):
        path=args.folder/f'{i:02}.png';slot='square-'+str(i) if i<=9 else 'detail-'+str(i-9)
        p=call('/projects/'+p['id']+'/assets',{'expected_revision':p['revision'],'role':'result','slot':slot},path)
    print(json.dumps({'id':p['id'],'state':p['state'],'images':p['example_count'],'total':len(p['slots']),
                     'api_generation_calls':0,'title_preserved':p['example']['title']==(args.folder/'title.txt').read_text(encoding='utf-8')},ensure_ascii=False))

main()
