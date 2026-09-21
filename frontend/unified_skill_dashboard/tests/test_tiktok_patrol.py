"""Synthetic fixtures only; no browser, credentials, original DB or model calls."""
import io
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data_hub import Hub
from tiktok_patrol import COMMON, MODULES, Patrol, RunRequest, Thresholds, analyze, parse_book

STORE = {'shop':'Test MY','currency':'MYR','timezone':'Asia/Kuala_Lumpur'}


def row(**values):
    return {'store_id':'s1','day':'2026-09-13','currency':'MYR','timezone':'Asia/Kuala_Lumpur',
            'entity_id':'sku1','entity_name':'测试商品','source':'本地合成数据','source_row':2,**values}


def workbook(rows):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as writer:
        for key,records in rows.items():
            title,fields=MODULES[key]
            names={**COMMON,**fields}
            pd.DataFrame([{v:r[k] for k,v in names.items()} for r in records],columns=list(names.values())).to_excel(writer,index=False,sheet_name=title)
    return out.getvalue()


def test_rules_all_modules_and_no_mixed_metric():
    data={'sales':[row(sales=5,previous_sales=10,revenue=40)],
          'inventory':[row(available=0,sales_7d=0)],
          'ads':[row(spend=100,attributed_revenue=90)],
          'orders':[row(pending_orders=10,overdue_orders=2)],
          'reviews':[row(review_count=2,negative_count=1)],
          'health':[row(violations=1)],'inbox':[row(unread=5,urgent=1)]}
    parsed=parse_book(workbook(data),'s1',STORE,'2026-09-13')
    report=analyze(parsed,Thresholds())
    assert report['coverage']==7 and report['status']=='complete'
    assert len(report['findings'])==7
    assert report['findings'][0]['priority']=='P0'
    assert '不可计算' in next(f['reason'] for f in report['findings'] if f['module']=='inventory')
    assert 'ROAS 0.90' in next(f['reason'] for f in report['findings'] if f['module']=='ads')


def test_missing_is_not_healthy_and_zero_denominator():
    report=analyze({'sales':[row(sales=3,previous_sales=0,revenue=10)],
                    'ads':[row(spend=0,attributed_revenue=0)]},Thresholds())
    assert report['coverage']==2 and report['status']=='partial'
    assert report['modules'][1]['status']=='missing'
    assert len(report['findings'])==1
    assert '无法计算' in report['findings'][0]['reason']


@pytest.mark.parametrize('change',[{'currency':'THB'},{'store_id':'s2'},{'day':'2026-09-12'},
                                  {'timezone':'Asia/Bangkok'},{'available':''},{'available':'NaN'},
                                  {'available':-1},{'available':0.5},{'source':''}])
def test_reject_bad_evidence(change):
    with pytest.raises(HTTPException) as err:
        parse_book(workbook({'inventory':[row(available=5,sales_7d=7,**{} )|change]}),'s1',STORE,'2026-09-13')
    assert err.value.status_code==422


def test_duplicates_and_impossible_counts():
    for data in [{'inventory':[row(available=5,sales_7d=7)]*2},
                 {'orders':[row(pending_orders=1,overdue_orders=2)]},
                 {'reviews':[row(review_count=1,negative_count=2)]}]:
        with pytest.raises(HTTPException):parse_book(workbook(data),'s1',STORE,'2026-09-13')


def test_thresholds_reject_nonfinite_and_unknown():
    for kwargs in [{'ad_roas':float('nan')},{'stock_days':float('inf')},{'unknown':2},{'negative_count':1.5}]:
        with pytest.raises(ValidationError):Thresholds(**kwargs)


def test_persistence_is_append_only_and_store_scoped(tmp_path):
    selectors=tmp_path/'selectors.yaml'
    selectors.write_text('ziniao_stores:\n  s1:\n    shop: Test MY\n    currency: MYR\n    timezone: Asia/Kuala_Lumpur\n',encoding='utf-8')
    hub=Hub(lambda:sqlite3.connect(tmp_path/'test.db'),tmp_path)
    p=Patrol(hub,selectors)
    data=workbook({'inventory':[row(available=5,sales_7d=7)]})
    source=p.ingest(data,'s1','2026-09-13')
    first=p.run(RunRequest(source_id=source['id']))
    second=p.run(RunRequest(source_id=source['id'],thresholds=Thresholds(stock_units=0,stock_days=1)))
    assert first['id']!=second['id']
    assert p.get(first['id'])['findings']
    assert not p.get(second['id'])['findings']
    assert (tmp_path/'raw/ai_workbench/tiktok_patrol'/source['id']/'source.xlsx').read_bytes()==data
    assert len(list((tmp_path/'output/ai_workbench/tiktok_patrol').glob('*/run.log')))==2
    assert p.get(first['id'])['source_id']==p.get(second['id'])['source_id']
    with pytest.raises(HTTPException):p.ingest(data,'s2','2026-09-13')


def test_http_workflow_with_temporary_database(tmp_path):
    import asyncio
    import httpx
    from fastapi import FastAPI
    selectors=tmp_path/'selectors.yaml'
    selectors.write_text('ziniao_stores:\n  s1:\n    shop: Test MY\n    currency: MYR\n    timezone: Asia/Kuala_Lumpur\n',encoding='utf-8')
    patrol=Patrol(Hub(lambda:sqlite3.connect(tmp_path/'api.db'),tmp_path),selectors)
    app=FastAPI();app.include_router(patrol.router())
    async def workflow():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            prefix='/api/hub/tiktok-patrol'
            status=(await client.get(prefix+'/status')).json()
            assert len(status['stores'])==1 and not status['scheduled'] and not status['paid_ai']
            template=await client.get(prefix+'/template',params={'store_id':'s1','day':'2026-09-13'})
            assert template.status_code==200
            data=workbook({'sales':[row(sales=5,previous_sales=10,revenue=20)]})
            preview=await client.post(prefix+'/sources',data={'store_id':'s1','day':'2026-09-13'},files={'file':('test.xlsx',data)})
            assert preview.status_code==200
            original=await client.get(prefix+'/sources/'+preview.json()['id']+'/file')
            assert original.status_code==200 and original.content==data
            report=await client.post(prefix+'/runs',json={'source_id':preview.json()['id']})
            assert report.status_code==200 and report.json()['coverage']==1
            ident=report.json()['id']
            assert (await client.get(prefix+'/runs/'+ident)).json()['findings'][0]['priority']=='P1'
            downloaded=await client.get(prefix+'/runs/'+ident+'/report')
            assert downloaded.status_code==200 and '来源 SHA256' in downloaded.text
            assert len((await client.get(prefix+'/status?store_id=s1')).json()['runs'])==1
            assert (await client.get(prefix+'/status?store_id=other')).status_code==422
            assert (await client.get(prefix+'/runs/missing')).status_code==404
            assert (await client.post(prefix+'/runs',json={'source_id':'bad'})).status_code==422
    asyncio.run(workflow())
