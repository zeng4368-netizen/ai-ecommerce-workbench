"""Task attachments and versioned observations. Never auto-completes business actions."""
import json
import uuid
import calendar
from datetime import date
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from data_hub import engine,pack,stamp,digest


def period_window(value):
    """Only explicit calendar windows can be compared; labels are not dates."""
    try:
        if len(value)==7:
            year,month=map(int,value.split('-'))
            return date(year,month,1),date(year,month,calendar.monthrange(year,month)[1])
        if '/' in value:
            start,end=value.split('/')
            return date.fromisoformat(start),date.fromisoformat(end)
        point=date.fromisoformat(value)
        return point,point
    except (TypeError,ValueError):
        return None

def candidates(hub,version=''):
    current=hub.current(version);data=current['data']
    currencies={r.get('货币','未标注') for r in data['gmv']['rows']}
    items=[]
    for i,currency in enumerate(sorted(currencies)):
        batch=engine({'op':'candidates','data':data,'settings':{'currency':currency,'roiTarget':8,'minSpend':5}})
        items.extend(c for c in batch if i==0 or c['module']=='ads')
    for group in engine({'op':'daily_action_evidence','data':data}):
        for row in group['rows']:
            items.append({'module':'daily','entity':row['product'],
                'entity_key':json.dumps([group['shop'],row['product']],ensure_ascii=False),
                'title':'店铺日销下滑待核查','priority':'P1',
                'rule':'原下降汇总筛选：末日销量差<0，或近7日均销较基准变化率<0；不足14天用首日销量作基准，零基准变化率为空。候选不是因果结论。',
                'source':'店铺日销 · '+group['shop']+' · '+group['dates'][0]+' 至 '+group['dates'][-1],
                'evidence':[{'id':row['evidenceId'],**row,'shop':group['shop'],'dates':group['dates'],
                             'baseline_note':group['baselineNote']}],
                'suggested_action':'先核对该店铺商品末日是否完整、销售口径与平台订单是否一致；记录实时库存、流量及转化证据后再判断原因。任何优惠券、价格或投放调整均需人工到平台执行。'})
    for item in items:
        if item['module']=='creators':
            meta=current['meta']['datasets']['creator']
            item['source']='达人明细 · '+meta['period']+' · '+meta.get('currency','未标注')
        elif item['module']=='finance':
            meta=current['meta']['datasets']['bill']
            item['source']='结算账单 · '+meta['period']+' · '+meta.get('currency','未标注')
            for evidence in item['evidence']: evidence['currency']=meta.get('currency','未标注')
    return {'version':current['version'],'items':items}

def create_router(hub):
    router=APIRouter(prefix='/api/hub/actions')
    def task(con,ident):
        row=con.execute('SELECT value FROM actions WHERE id=?',(ident,)).fetchone()
        if not row: raise HTTPException(404,'行动不存在')
        return json.loads(row[0])

    @router.get('/{ident}/attachments')
    def listing(ident:str):
        with hub.db() as con:
            task(con,ident)
            return {'items':[json.loads(r[0]) for r in con.execute('SELECT value FROM hub_attachments WHERE task_id=?',(ident,))]}

    @router.post('/{ident}/attachments')
    async def upload(ident:str,file:UploadFile=File(...),version:int=Form(...)):
        name=Path((file.filename or '').replace('\\','/')).name
        suffix=Path(name).suffix.lower()
        if suffix not in ('.png','.jpg','.jpeg','.pdf','.xlsx','.csv','.txt','.md'): raise HTTPException(422,'支持图片、PDF、表格和文本证据，不接收可执行文件')
        content=await file.read(10*1024*1024+1)
        if not content or len(content)>10*1024*1024: raise HTTPException(413,'证据文件须为1字节至10MB')
        attachment=uuid.uuid4().hex
        item={'id':attachment,'task_id':ident,'name':name,'size':len(content),'sha256':digest(content),'created_at':stamp(),'suffix':suffix}
        with hub.db() as con:
            con.execute('BEGIN IMMEDIATE');record=task(con,ident)
            if record['version']!=version: raise HTTPException(409,'任务已变化，请重新打开后上传')
            if record['state'] in ('done','dismissed'): raise HTTPException(409,'已归档任务不可追加证据，请先明确重新打开')
            folder=hub.data/'raw/ai_workbench/attachments';folder.mkdir(parents=True,exist_ok=True)
            (folder/(attachment+suffix)).write_bytes(content)
            con.execute('INSERT INTO hub_attachments VALUES(?,?,?)',(attachment,ident,pack(item)))
            record['version']+=1;record['updated_at']=stamp()
            record.setdefault('attachments',[]).append(item)
            con.execute('UPDATE actions SET value=? WHERE id=?',(pack(record),ident))
            con.execute('INSERT INTO action_events(task_id,value) VALUES(?,?)',(ident,pack({'time':stamp(),'op':'attachment','state':record['state'],'version':record['version'],'detail':item})))
        return item

    @router.get('/{ident}/attachments/{attachment}')
    def download(ident:str,attachment:str):
        with hub.db() as con:
            row=con.execute('SELECT value FROM hub_attachments WHERE id=? AND task_id=?',(attachment,ident)).fetchone()
        if not row: raise HTTPException(404)
        meta=json.loads(row[0]);path=hub.data/'raw/ai_workbench/attachments'/(meta['id']+meta['suffix'])
        if not path.is_file(): raise HTTPException(404,'证据文件不可用')
        return FileResponse(path,filename=meta['name'],media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})

    @router.get('/{ident}/comparison')
    def compare(ident:str):
        with hub.db() as con: record=task(con,ident)
        if record.get('origin',{}).get('kind')=='chat' or record['module']=='general':
            return {'status':'pending','reason':'聊天建议尚未绑定可自动复算的风险规则；请按任务验收指标记录实际观察，不自动认定效果。'}
        current=hub.current();base=record.get('data_version')
        if not base or base==current['version']:
            return {'status':'pending','reason':'缺少执行前数据版本，或尚未导入新数据；不能判定效果。','before_version':base,'after_version':current['version']}
        before=hub.current(base);kind={'ads':'gmv','inventory':'erp','creators':'creator','finance':'bill','daily':'daily','after':'after'}[record['module']]
        b=before['meta']['datasets'].get(kind,{});a=current['meta']['datasets'].get(kind,{})
        if not b.get('period') or b.get('period')==a.get('period') or b.get('currency')!=a.get('currency'):
            return {'status':'pending','reason':'同周期修订或周期/币种不可比，不作为执行效果。','before':b,'after':a}
        bw=period_window(b.get('period',''));aw=period_window(a.get('period',''))
        if not bw or not aw or (bw[1]-bw[0])!=(aw[1]-aw[0]) or aw[0]<=bw[1]:
            return {'status':'pending','reason':'观察窗口不明确、长度不同或前后重叠，无法按同一窗口比较；请补充可比数据。','before':b,'after':a}
        matches=[c for c in candidates(hub,current['version'])['items'] if c['module']==record['module'] and c['entity_key']==record['entity_key'] and c['rule']==record['rule']]
        if not matches:
            return {'status':'pending','reason':'该对象当前未命中相同风险规则；可能因数据缺失或范围改变，不能自动认定风险已解决。','before':b,'after':a}
        previous=record['evidence'];latest=matches[0]['evidence'];changes=[]
        if len(previous)==len(latest)==1:
            for key,value in previous[0].items():
                new=latest[0].get(key)
                if isinstance(value,(int,float)) and isinstance(new,(int,float)):
                    changes.append({'metric':key,'before':value,'after':new,'delta':new-value})
        return {'status':'observation','before_version':base,'after_version':current['version'],'before':b,'after':a,
                'changes':changes,'before_evidence':previous,'after_evidence':latest,
                'reason':'同规则原值观察；尚需人工确认窗口长度、样本与执行时点可比，不证明因果，不自动完成任务。'}
    return router
