"""Operational views above unchanged Skill metrics: health, products, triage, human notes."""
from collections import Counter, defaultdict
from datetime import date, timedelta
import json
import logging
import math
import re
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal
from data_hub import engine, objects, pack, stamp


def normalized(value):
    return re.sub(r'[^\w]','',str(value or '')).casefold()


def number(value):
    try:
        result=float(str(value).replace(',',''))
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


def daily_dates(rows):
    return sorted({k for r in rows for k in r if re.fullmatch(r'20\d{2}-\d{2}-\d{2}',k)})


def data_health(current):
    data=current['data'];raw=data['daily']['raw']['daily'];issues=[];shops=[]
    grouped=defaultdict(list)
    for row in raw:grouped[str(row.get('店铺') or '未标注店铺')].append(row)
    for shop,rows in grouped.items():
        if shop=='未标注店铺':issues.append({'kind':'daily','code':'missing_shop','severity':'warning','count':len(rows),'message':'原表存在店铺为空的行；保留原值，不用于店铺商品关联'})
        days=daily_dates(rows)
        missing=sum(r.get(d) in (None,'') for r in rows for d in days)
        invalid=sum(r.get(d) not in (None,'') and number(r.get(d)) is None for r in rows for d in days)
        duplicates=sum(n-1 for n in Counter(str(r.get('库存SKU','')) for r in rows).values() if n>1)
        gaps=[]
        if days:
            try:
                start,end=date.fromisoformat(days[0]),date.fromisoformat(days[-1])
                if (end-start).days<=3660:gaps=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1) if (start+timedelta(days=i)).isoformat() not in days]
            except ValueError:issues.append({'kind':'daily','shop':shop,'code':'invalid_date','severity':'error','message':'日期列包含无效日历日期'})
        details={'shop':shop,'rows':len(rows),'days':len(days),'start':days[0] if days else None,'end':days[-1] if days else None,
                 'missing_cells':missing,'invalid_cells':invalid,'duplicate_sku_rows':duplicates,'missing_dates':gaps}
        shops.append(details)
        for code,count,text in [('missing_cells',missing,'销量缺失单元格；不能把缺失直接解释为零销量'),('invalid_cells',invalid,'销量非数字单元格'),('duplicate_sku_rows',duplicates,'同店铺同SKU重复行；可能合法拆行，需人工核查')]:
            if count:issues.append({'kind':'daily','shop':shop,'code':code,'count':count,'severity':'error' if code=='invalid_cells' else 'warning','message':text})
        if gaps:issues.append({'kind':'daily','shop':shop,'code':'missing_dates','severity':'warning','dates':gaps,'message':'观察窗口存在缺少的日历日期'})
        if len(days)<14:issues.append({'kind':'daily','shop':shop,'code':'short_history','severity':'info','message':f'仅{len(days)}天；原下降汇总的7日比较按不足14天降级口径，不是完整周环比'})
    unmatched=[p['name'] for p in data['daily']['products'] if p.get('noERP')]
    if unmatched:issues.append({'kind':'erp','code':'unmatched_cost_or_stock','severity':'warning','count':len(unmatched),'examples':unmatched[:10],'message':'商品没有匹配ERP；不能把缺少记录当作库存为零'})
    datasets=[]
    for kind,meta in current['meta']['datasets'].items():
        datasets.append({'kind':kind,**meta})
        if meta.get('completeness'):issues.append({'kind':kind,'code':'coverage','severity':'info','message':meta['completeness']})
        if not re.match(r'^20\d{2}-\d{2}',meta.get('period','')):
            issues.append({'kind':kind,'code':'unknown_period','severity':'warning','message':'未明确业务周期，不能用于执行效果验证'})
    return {'version':current['version'],'datasets':datasets,'daily_shops':shops,'store_count':sum(x['shop']!='未标注店铺' for x in shops),'issues':issues,
            'counts':dict(Counter(x['severity'] for x in issues)),
            'note':'健康检查是新增的数据质量提示，不修改原算法；报表末日是否完整仍需人工核实。历史批次不是实时数据。'}


def catalog(current,query='',shop=''):
    grouped={}
    for row in current['data']['daily']['raw']['daily']:
        name=str(row.get('SKU中文名') or '');store=str(row.get('店铺') or '')
        if not name or not store:continue
        if shop and normalized(store)!=normalized(shop):continue
        key=(store,name)
        grouped.setdefault(key,{'shop':store,'product':name,'skus':[]})['skus'].append(str(row.get('库存SKU','')))
    result=[]
    for item in grouped.values():
        item['skus']=sorted(set(item['skus']))
        if not query or normalized(query) in normalized(item['product']) or any(normalized(query) in normalized(s) for s in item['skus']):result.append(item)
    return sorted(result,key=lambda x:(x['shop'],x['product']))


def feedback_rows(hub,current):
    with hub.db() as con:
        return [json.loads(r[0]) for r in con.execute('SELECT value FROM hub_feedback') if json.loads(r[0]).get('version')==current['version']]


def triage(hub,current,shop=''):
    health=data_health(current);quality={normalized(x['shop']):x for x in health['daily_shops']}
    notes={(normalized(r['shop']),r['product']):r for r in feedback_rows(hub,current)}
    results=[]
    for group in engine({'op':'daily_action_evidence','data':current['data']}):
        if shop and normalized(shop)!=normalized(group['shop']):continue
        info=quality.get(normalized(group['shop']),{})
        for row in group['rows']:
            streak=0
            for i in range(len(row['values'])-1,0,-1):
                if row['values'][i]<row['values'][i-1]:streak+=1
                else:break
            loss=max(0,-(row['dayDiff'] or 0))
            checks=[]
            if info.get('missing_cells') or info.get('missing_dates') or info.get('invalid_cells'):checks.append('该店报表有数据缺口，先核查数据')
            if len(group['dates'])<14:checks.append('不足14天，7日比较使用原降级口径')
            if row['previous'] is not None and row['previous']<5:checks.append('前日销量少于5，百分比易受小样本影响')
            results.append({'shop':group['shop'],**row,'dates':group['dates'],'daily_unit_loss':loss,'consecutive_decline_days':streak,
                            'quality_notes':checks,'feedback':notes.get((normalized(group['shop']),row['product']))})
    results.sort(key=lambda r:(-r['daily_unit_loss'],-r['consecutive_decline_days'],-r['avg7'],r['shop'],r['product']))
    return {'version':current['version'],'rows':results,'total':len(results),
            'rule':'保留原下降汇总完整集合；新增处理顺序依次按末日减少件数、连续下降天数、近7日日均销量降序。不是AI评分，不是损失金额。',
            'counts':{'daily_drop':sum(r['daily_unit_loss']>0 for r in results),'baseline_only':sum(r['daily_unit_loss']==0 for r in results),'quality_attention':sum(bool(r['quality_notes']) for r in results)}}


def product_profile(hub,current,shop,product,include_all=False):
    data=current['data'];meta=current['meta']['datasets']
    rows=[(i,r) for i,r in enumerate(data['daily']['raw']['daily']) if normalized(r.get('店铺'))==normalized(shop) and str(r.get('SKU中文名',''))==product]
    if not rows:raise HTTPException(404,'当前周期未匹配该店铺商品；请从商品列表选择精确对象，或切换数据周期。')
    shop=str(rows[0][1]['店铺']);skus={str(r.get('库存SKU','')) for _,r in rows}
    daily=engine({'op':'daily_query','data':{'daily':{'raw':{'daily':[r for _,r in rows]}}},'question':'日销明细'})
    def section(kind,matched,status='matched',note=''):
        return {'kind':kind,'status':status if matched else ('mapping_required' if status=='mapping_required' else 'missing'),
                'source':meta.get(kind,{}),'total':len(matched),'rows':[{'source_row':i+2,**r} for i,r in (matched if include_all else matched[:100])],
                'display_limit':None if include_all else 100,'note':note}
    sections=[section('daily',rows,note='同店铺同款的原日销；来源行是已保存标准表的行号。')]
    erp=[(i,r) for i,r in enumerate(data['daily']['raw']['erp']) if str(r.get('库存SKU编号','')) in skus]
    sections.append(section('erp',erp,note='仅按精确SKU关联；这里是SKU仓库库存，不是该店铺独占库存。'))
    with hub.db() as con:
        mappings=[json.loads(r[0]) for r in con.execute('SELECT value FROM hub_mappings')]
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tasks=[json.loads(r[0]) for r in con.execute('SELECT value FROM actions')] if 'actions' in tables else []
        feedback=[json.loads(r[0]) for r in con.execute('SELECT value FROM hub_feedback')]
        annotations=[json.loads(r[0]) for r in con.execute('SELECT value FROM hub_annotations')]
    confirmed=[m for m in mappings if m.get('confirmed') and normalized(m['shop'])==normalized(shop) and m.get('sku') in skus]
    ids={m['product_id'] for m in confirmed if m.get('product_id')}
    conflicts=any(len({m['product_id'] for m in confirmed if m['sku']==sku and m.get('product_id')})>1 for sku in skus)
    ads=[] if conflicts else [(i,r) for i,r in enumerate(data['gmv']['rows']) if str(r.get('商品 ID','')) in ids and any(normalized(r.get(h))==normalized(shop) for h in ('店铺','店编','店名','店铺名称'))]
    sections.append(section('gmv',ads,'matched' if ids and not conflicts else 'mapping_required',
                            '需要已人工确认且无冲突的店铺/SKU/商品ID映射；无法关联时不按相似名称猜测。'))
    bills=[(i,r) for i,r in enumerate(objects(data['bill'])) if str(r.get('款名',''))==product and normalized(r.get('店编'))==normalized(shop)]
    sections.append(section('bill',bills,note='仅精确同店编同款；店名与财务店编未对应时不猜测，不把结算减成本称为净利润。'))
    after=[(i,r) for i,r in enumerate(objects(data.get('tables',{}).get('after',{'header':[],'rows':[]}))) if str(r.get('款名',''))==product and normalized(r.get('店铺'))==normalized(shop)]
    sections.append(section('after',after,note='只有导入逐行退包原表后才能下钻；历史汇总不能还原订单。'))
    matched_periods={s['kind']:s['source'].get('period') for s in sections if s['total']}
    def related(t):
        if t.get('entity')!=product:return False
        if t['module']=='inventory':return True
        return any(normalized(e.get('shop'))==normalized(shop) for e in t.get('evidence',[])) or str(t.get('entity_key','')).split('|')[0]==shop
    relevant=[t for t in tasks if related(t)]
    timeline=[]
    with hub.db() as con:
        if 'action_events' in tables:
            for task in relevant:
                for record in con.execute('SELECT value FROM action_events WHERE task_id=?',(task['id'],)):
                    event=json.loads(record[0]);timeline.append({'date':event['time'],'type':'action','task_id':task['id'],'title':task['title'],'event':event['op'],'state':event['state']})
    timeline.extend({'date':n['occurred_on'],'type':'annotation',**n} for n in annotations if normalized(n['shop'])==normalized(shop) and n['product']==product)
    timeline.sort(key=lambda x:x['date'],reverse=True)
    return {'version':current['version'],'shop':shop,'product':product,'skus':sorted(skus),'daily_metrics':daily,
            'sections':sections,'confirmed_mappings':confirmed,'mapping_conflict':conflicts,
            'comparison':{'periods':matched_periods,'same_period':bool(matched_periods) and len(set(matched_periods.values()))==1,
                          'note':'各块独立展示原周期。相同周期也不证明因果；跨周期只作档案查阅，不做联合收益或原因推断。'},
            'actions':[{'id':t['id'],'title':t['title'],'state':t['state'],'due_date':t.get('due_date'),'module':t['module'],'data_version':t.get('data_version')} for t in relevant],
            'feedback':[n for n in feedback if normalized(n['shop'])==normalized(shop) and n['product']==product],
            'timeline':timeline[:100],'timeline_total':len(timeline)}


class Feedback(BaseModel):
    version:str
    shop:str=Field(min_length=1,max_length=200)
    product:str=Field(min_length=1,max_length=500)
    verdict:Literal['needs_review','normal_fluctuation','data_issue']
    reason:str=Field(min_length=1,max_length=2000)


class Annotation(BaseModel):
    version:str
    shop:str=Field(min_length=1,max_length=200)
    product:str=Field(min_length=1,max_length=500)
    occurred_on:date
    category:Literal['promotion','price','stock','check','other']
    note:str=Field(min_length=1,max_length=2000)
    confirmed:bool=False


def create_router(hub):
    router=APIRouter(prefix='/api/hub/operations')
    @router.get('/health')
    def health(version:str=''):return data_health(hub.current(version))
    @router.get('/products')
    def products(version:str='',q:str='',shop:str='',offset:int=0,limit:int=50):
        if offset<0 or not 1<=limit<=100:raise HTTPException(422,'分页参数无效')
        current=hub.current(version);rows=catalog(current,q,shop)
        return {'version':current['version'],'rows':rows[offset:offset+limit],'total':len(rows),'offset':offset}
    @router.get('/triage')
    def anomalies(version:str='',shop:str='',q:str='',offset:int=0,limit:int=50):
        if offset<0 or not 1<=limit<=100:raise HTTPException(422,'分页参数无效')
        result=triage(hub,hub.current(version),shop)
        if q:result['rows']=[r for r in result['rows'] if normalized(q) in normalized(r['product']) or any(normalized(q) in normalized(s) for s in r['skus'])]
        result['total']=len(result['rows']);result['rows']=result['rows'][offset:offset+limit];result['offset']=offset
        return result
    @router.get('/product')
    def profile(shop:str,product:str,version:str=''):return product_profile(hub,hub.current(version),shop,product)
    @router.get('/product/export')
    def export_profile(shop:str,product:str,version:str=''):
        current=hub.current(version);result=product_profile(hub,current,shop,product,include_all=True)
        return Response(pack(result),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="product_evidence_{current["version"][:8]}.json"'})
    @router.post('/feedback')
    def record_feedback(payload:Feedback):
        current=hub.current()
        if current['version']!=payload.version:raise HTTPException(409,'数据版本已变化，请重新核查后提交')
        if not any(r['product']==payload.product for r in catalog(current,shop=payload.shop)):raise HTTPException(404,'未匹配商品')
        ident=uuid.uuid4().hex;item={'id':ident,**payload.model_dump(),'created_at':stamp()}
        with hub.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT version FROM hub_head').fetchone()[0]!=payload.version:raise HTTPException(409,'数据版本已变化，请重新核查')
            con.execute('INSERT INTO hub_feedback VALUES(?,?)',(ident,pack(item)))
        logging.info('operational feedback id=%s version=%s verdict=%s',ident,payload.version,payload.verdict)
        return item
    @router.post('/annotations')
    def record_annotation(payload:Annotation):
        if not payload.confirmed:raise HTTPException(422,'请确认这是实际发生事项的记录；系统不会执行平台操作。')
        if payload.occurred_on>date.today():raise HTTPException(422,'实际发生日期不能在未来；尚未执行的计划请记录为待办行动。')
        current=hub.current()
        if current['version']!=payload.version:raise HTTPException(409,'数据已更新，请刷新')
        if not any(r['product']==payload.product for r in catalog(current,shop=payload.shop)):raise HTTPException(404,'未匹配商品')
        ident=uuid.uuid4().hex;item={'id':ident,**payload.model_dump(mode='json'),'created_at':stamp()}
        with hub.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT version FROM hub_head').fetchone()[0]!=payload.version:raise HTTPException(409,'数据版本已变化，请刷新')
            con.execute('INSERT INTO hub_annotations VALUES(?,?)',(ident,pack(item)))
        logging.info('operational annotation id=%s version=%s category=%s',ident,payload.version,payload.category)
        return item
    return router
