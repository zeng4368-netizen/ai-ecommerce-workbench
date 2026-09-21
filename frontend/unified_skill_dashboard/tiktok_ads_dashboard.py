"""Advertising overview from recorded daily sections; independent of old Skill math."""
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from tiktok_patrol import today_for
from tiktok_patrol_history import daily_history, history_csv
from ziniao_bridge import load_stores

METRICS = ['成本', 'SKU 订单数', '平均下单成本', '总收入', 'ROI']


def summarize(data):
    series = [s for s in data['series'] if s['kind']=='ads']
    metrics = {s['label']:s for s in series}
    currencies = {s['currency'] for s in series if s['currency']}
    zones = {s['timezone'] for s in series}
    if len(currencies)>1 or len(zones)>1:
        raise HTTPException(409, '所选期间的广告币种或时区不一致，不能合并')
    valid = set(data['days'])
    for label in METRICS:
        valid &= {p['day'] for p in metrics.get(label,{}).get('points',[]) if p['value'] is not None}
    values = {label:None for label in METRICS}
    if valid:
        for label in ['成本','SKU 订单数','总收入']:
            values[label] = sum(p['value'] for p in metrics[label]['points'] if p['day'] in valid)
        if len(valid)==1:
            for label in ['平均下单成本','ROI']:
                values[label] = next(p['value'] for p in metrics[label]['points'] if p['day'] in valid)
        else:
            values['平均下单成本'] = values['成本']/values['SKU 订单数'] if values['SKU 订单数'] else None
            values['ROI'] = values['总收入']/values['成本'] if values['成本'] else None
    return {'values':values, 'recorded_days':len(valid), 'complete':len(valid)==len(data['days']),
            'series':series, 'currency':next(iter(currencies),'USD'), 'timezone':next(iter(zones),None)}


def create_router(live):
    router=APIRouter(prefix='/api/hub/tiktok-ads')

    def account(sid):
        store=live.patrol.store(sid)
        recipe=live.store_recipe(sid)['ads']
        zone=recipe.get('timezone',store['timezone'])
        return {'store_id':sid,'shop':store['shop'],'account':recipe.get('account_text',''),
                'currency':recipe['currency'],'timezone':zone,
                'timezone_label':recipe['timezone_text'],
                'yesterday':(today_for({**store,'timezone':zone})-timedelta(days=1)).isoformat()}

    @router.get('/stores')
    def stores():return {'stores':[account(sid) for sid in load_stores(live.patrol.selectors)]}

    @router.get('/overview')
    def overview(store_id:str,start:str,end:str):
        meta=account(store_id)
        current=daily_history(live,store_id,start,end)
        span=len(current['days'])
        previous_end=date.fromisoformat(start)-timedelta(days=1)
        previous_start=previous_end-timedelta(days=span-1)
        before=daily_history(live,store_id,previous_start.isoformat(),previous_end.isoformat())
        now,prev=summarize(current),summarize(before)
        changes={label:None for label in METRICS}
        if now['complete'] and prev['complete'] and now['currency']==prev['currency'] and now['timezone']==prev['timezone']:
            for label in METRICS:
                a,b=now['values'][label],prev['values'][label]
                if a is not None and b is not None and b!=0:changes[label]=(a/b-1)*100
        return {**now,'meta':meta,'start':start,'end':end,'days':current['days'],'range_days':span,
                'changes':changes,'previous_start':previous_start.isoformat(),'previous_end':previous_end.isoformat(),
                'rows':[r for r in current['rows'] if r['kind']=='ads']}

    @router.get('/export')
    def export(store_id:str,start:str,end:str):
        account(store_id)
        data=daily_history(live,store_id,start,end)
        data['rows']=[r for r in data['rows'] if r['kind']=='ads']
        return history_csv(data)
    return router
