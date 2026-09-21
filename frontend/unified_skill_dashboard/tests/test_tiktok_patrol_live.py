"""Read-only collector contracts. Synthetic values; no live commands."""
import copy
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data_hub import Hub
from tiktok_patrol import Patrol
from tiktok_patrol_live import LivePatrol, parse_cards, parse_home, number, findings


def config():
    path=Path(__file__).resolve().parents[3]/'config/selectors.yaml'
    return yaml.safe_load(path.read_text(encoding='utf-8'))['tiktok_patrol_live']


def payload(kind):
    r=config()[kind]
    return {'dates':[date(2026,9,13).strftime(r['date_format'])]*2,'account_ok':True,'timezone_ok':True,
            'cards':[{'label':label,'value':('RM100.00' if label=='GMV' else '100.00 USD' if label in ('成本','总收入','平均下单成本') else '10'),
                      'change':'10%','up':False,'down':True} for label in r['labels']]}


def test_sales_ads_keep_currencies_and_signed_platform_changes():
    sales=parse_cards(payload('sales'),config()['sales'],'sales',date(2026,9,13))
    ads=parse_cards(payload('ads'),config()['ads'],'ads',date(2026,9,13))
    assert sales[0]['currency']=='MYR' and ads[0]['currency']=='USD'
    assert sales[0]['change_pct']==-10
    assert next(x for x in ads if x['label']=='ROI')['currency']==''


@pytest.mark.parametrize('change',['date','currency','missing','account','timezone'])
def test_reject_wrong_scope(change):
    p=payload('ads')
    if change=='date':p['dates']=['2026-09-12']*2
    elif change=='currency':p['cards'][0]['value']='100 MYR'
    elif change=='missing':p['cards'].pop()
    elif change=='account':p['account_ok']=False
    elif change=='timezone':p['timezone_ok']=False
    with pytest.raises(HTTPException):parse_cards(p,config()['ads'],'ads',date(2026,9,13))


def test_home_counts_do_not_become_overdue_or_new_reviews():
    r=config()['homepage']
    data=parse_home({'cards':['待发货\n10\n紧急：3','待退货\n2\n紧急：1','被拒商品\n1','低库存\n4\n缺货：20','差评\n30'],
                     'health':['有待改进']},r)
    assert data['cards'][0]['value']==10
    assert data['cards'][0]['detail']=='紧急：3'
    assert '差评不是昨日新增' in data['scope']
    assert 'overdue_orders' not in str(data)
    queue=findings({'homepage':{'data':data}})
    assert any(x['title']=='待发货' and '紧急：3' in x['reason'] for x in queue)
    assert all('自动退款' not in x['action'] for x in queue)


@pytest.mark.parametrize('raw',['1.3K','--','NaN','Infinity','-1','12,34','1e12'])
def test_refuse_approximate_or_malformed_values(raw):
    with pytest.raises(HTTPException):number(raw)


def test_shared_lease_and_unreviewed_store(tmp_path,monkeypatch):
    selectors=tmp_path/'selectors.yaml'
    c=config();c['reviewed_store_ids']=['s1']
    selectors.write_text(yaml.safe_dump({'tiktok_patrol_live':c,'ziniao_stores':{
        's1':{'shop':'Test','currency':'MYR','timezone':'Asia/Kuala_Lumpur'},
        's2':{'shop':'Unreviewed','currency':'THB','timezone':'Asia/Bangkok'}}}),encoding='utf-8')
    live=LivePatrol(Patrol(Hub(lambda:sqlite3.connect(tmp_path/'test.db'),tmp_path),selectors))
    monkeypatch.setattr(live.bridge,'run',lambda *a:pytest.fail('Must not call real CLI'))
    with pytest.raises(HTTPException):live.create('s2',start=False)
    first=live.create('s1',start=False)
    with pytest.raises(HTTPException):live.create('s1',start=False)
    live.renew(first['id'])
    with live.db() as con:con.execute('UPDATE ziniao_browser_lease SET expires=0')
    second=live.create('s1',start=False)
    assert live.get(first['id'])['state']=='interrupted'
    assert second['id']!=first['id']
    with pytest.raises(HTTPException):live.renew(first['id'])
    with live.db() as con:con.execute('UPDATE ziniao_browser_lease SET expires=0')
    status_endpoint=next(r.endpoint for r in live.router().routes if r.path.endswith('/status'))
    assert status_endpoint('s1')['runs'][0]['state']=='interrupted'
    third=live.create('s1',start=False)
    monkeypatch.setattr(live.bridge,'check',lambda:{'ready':False,'message':'测试授权异常'})
    live.execute(third['id'])
    assert live.get(third['id'])['state']=='paused'
    assert live.get(third['id'])['sections']=={}
    with live.db() as con:assert con.execute('SELECT count(*) FROM ziniao_browser_lease').fetchone()[0]==0
