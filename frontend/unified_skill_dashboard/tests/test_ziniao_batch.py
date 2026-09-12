"""Six-store acceptance fixtures; no live shop or paid model calls."""
import copy
import json
from datetime import datetime
import pytest
import yaml
from fastapi import HTTPException,FastAPI
from fastapi.testclient import TestClient
from test_ziniao_collection import system,MY,STORE
from ziniao_collection import Collection,bill_period
from ziniao_reports import native_query
from ziniao_bridge import profile_hash


@pytest.fixture
def six(system):
    c,calls,profile=system
    stores={STORE:{'shop':'EXPOSE','currency':'MYR','timezone':'Asia/Kuala_Lumpur','profile':{}}}
    for i in range(5):stores[str(i)]={'shop':'Test Store '+str(i),'currency':'MYR','timezone':'Asia/Kuala_Lumpur','profile':{}}
    c.bridge.selectors.write_text(yaml.safe_dump({'ziniao_collection':profile,'ziniao_stores':stores}),encoding='utf-8')
    return c,calls


def test_six_batch_atomic_and_frozen(six):
    c,calls=six;b=c.new_batch(now=datetime(2026,9,11,9,tzinfo=MY))
    assert len(b['runs'])==6 and len({r['store_id'] for r in b['runs']})==6
    assert all((r['start'],r['end'])==('2026-09-01','2026-09-11') for r in b['runs'])
    with pytest.raises(HTTPException):c.new_batch()
    assert len(c.status()['runs'])==6
    reopened=Collection(c.hub,c.bridge.selectors,c.model)
    assert reopened.batch(b['id'])['run_ids']==b['run_ids']
    assert not calls


def test_six_imports_dont_overwrite_other_stores_and_separate_ai_quota(six):
    c,calls=six;before=copy.deepcopy(c.hub.current()['data'])
    b=c.new_batch(now=datetime(2026,9,11,9,tzinfo=MY))
    for rid in b['run_ids']:
        c.execute(rid)
        assert c.get(rid)['state']=='pending_review'
        c.activate(rid,c.hub.current()['version'])
    cur=c.hub.current();assert len(cur['data']['tiktok_native'])==6
    assert len(calls)==6
    for k,v in before.items():assert cur['data'][k]==v
    for rid in b['run_ids']:
        j=c.get(rid);report=native_query(c.hub.current(j['version']),j['store_id'])
        assert report['summary']['shop']==j['shop']
    assert len(native_query(cur)['stores'])==6  # Never silently default to EXPOSE.
    assert c.batch(b['id'])['all_validated']
    assert c.hub.current()['meta']['datasets']['tiktok_native']['row_count']==6


def test_batch_failure_does_not_stop_other_stores(six,monkeypatch):
    c,_=six;b=c.new_batch(now=datetime(2026,9,11,9,tzinfo=MY));original=c.bridge.collect
    def fail_one(job,*args):
        if job['store_id']=='0':raise HTTPException(409,'fixture login required')
        return original(job,*args)
    monkeypatch.setattr(c.bridge,'collect',fail_one)
    c.submit_batch(b['id']).join(timeout=30)
    result=c.batch(b['id'])
    assert result['counts']['paused']==1 and result['counts']['pending_review']==5
    assert result['files_ready']==5 and not result['all_validated']


def test_batch_zip_and_confirmation(six,monkeypatch):
    c,_=six;app=FastAPI();app.include_router(c.router());api=TestClient(app)
    assert api.post('/api/hub/ziniao/batches',json={}).status_code==422
    assert api.post('/api/hub/ziniao/batches',json={'confirmed':True,'store_ids':['unknown']}).status_code==422
    b=c.new_batch(now=datetime(2026,9,11,9,tzinfo=MY))
    assert api.get('/api/hub/ziniao/batches/'+b['id']+'/download').status_code==409
    for rid in b['run_ids']:c.execute(rid)
    result=api.get('/api/hub/ziniao/batches/'+b['id']+'/download')
    assert result.status_code==200
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert len(archive.namelist())==7
        manifest=json.loads(archive.read('manifest.json'))
        assert len(manifest['stores'])==6 and manifest['all_validated']


def test_thai_date_receipt_and_schema_independence(six):
    from ziniao_tiktok import receipt_time
    c,_=six
    instant=datetime.fromisoformat('2026-09-30T17:01:00+00:00')
    assert bill_period(instant,'Asia/Bangkok')==('2026-10-01','2026-10-01')
    instant=datetime.fromisoformat('2026-09-30T16:01:00+00:00')
    assert bill_period(instant,'Asia/Bangkok')==('2026-09-01','2026-09-30')
    assert bill_period(instant)==('2026-10-01','2026-10-01')
    assert receipt_time('income_20260911120000(UTC+7).xlsx','settlement',7) is not None
    assert receipt_time('income_20260911120000(UTC+7).xlsx','settlement',8) is None
    basehash=profile_hash(c.recipe(STORE))
    document=yaml.safe_load(c.bridge.selectors.read_text(encoding='utf-8'))
    document['ziniao_stores']['0']['profile']={'expected_identity':'Different','platform_timezone':'Asia/Bangkok'}
    c.bridge.selectors.write_text(yaml.safe_dump(document),encoding='utf-8')
    assert profile_hash(c.recipe(STORE))==basehash
    assert c.recipe('0')['expected_identity']=='Different'


def test_global_browser_guard(six):
    c,_=six;b=c.new_batch(now=datetime(2026,9,11,9,tzinfo=MY))
    first=c.get(b['run_ids'][0]);first['state']='running';c.save(first)
    with pytest.raises(HTTPException):c.submit(b['run_ids'][1])
    assert c.get(b['run_ids'][1])['state']=='queued'


@pytest.mark.parametrize('sid,currency,zone',[('27183507534672','MYR','UTC+8'),('27120369569623','THB','UTC+7')])
def test_reviewed_english_and_thai_control_schemas(sid,currency,zone):
    from pathlib import Path
    from openpyxl import Workbook
    from ziniao_bridge import load_profile
    from ziniao_reports import parse_report
    import io
    schema=load_profile(Path(__file__).resolve().parents[3]/'config/selectors.yaml',sid)['reports']['settlement']['schema']
    wb=Workbook();ws=wb.active;ws.title=schema['sheet'];ws.append(schema['headers'])
    values={h:'' for h in schema['headers']}
    for h in schema['fee_fields']:values[h]='0'
    for k,h in schema['fields'].items():values[h]='0'
    values.update({'Order/Adjustment ID':'1234567890123456789','Transaction type':'Order','Order settled time':'2026/09/11','Currency':currency,'Total settlement amount':'10','Total Revenue':'12','Total Fees':'-2','Refund subtotal after seller discounts':'0','Adjustment amount':'0'})
    ws.append([values[h] for h in schema['headers']]);control=wb.create_sheet(schema['control_sheet'])
    control.append(['Time period','2026/09/01-2026/09/11']);control.append(['Time zone',zone]);control.append(['Currency',currency])
    for k,h in schema['control_totals'].items():control.append([h,values[schema['fields'][k]]])
    out=io.BytesIO();wb.save(out)
    parsed=parse_report(out.getvalue(),'native.xlsx','settlement',schema,'2026-09-01','2026-09-11',currency)
    assert parsed['rows'][0]['transaction_id']=='1234567890123456789' and parsed['header']==schema['headers']
    control['B2']='UTC+0';out=io.BytesIO();wb.save(out)
    with pytest.raises(HTTPException):parse_report(out.getvalue(),'native.xlsx','settlement',schema,'2026-09-01','2026-09-11',currency)


def test_scheduler_keeps_legacy_single_store_until_explicit_expansion(six,monkeypatch):
    c,_=six;now=datetime(2026,9,11,9,tzinfo=MY);seen=[]
    c.setting(enabled=True,next_due=now.isoformat(),approved_profile_hash=profile_hash(c.recipe(STORE)))
    monkeypatch.setattr(c,'submit',lambda rid:seen.append(c.get(rid)['store_id']))
    c.tick(now)
    assert seen==[STORE]


def test_schedule_six_requires_all_store_approvals(six,monkeypatch):
    c,_=six;app=FastAPI();app.include_router(c.router());api=TestClient(app)
    monkeypatch.setattr(c,'check',lambda:{'ready':True})
    monkeypatch.setattr(c.bridge,'profile',lambda store_id:c.recipe(store_id))
    response=api.post('/api/hub/ziniao/plan',json={'confirmed':True,'enabled':True,'store_ids':list(c.bindings())})
    assert response.status_code==409 and not c.settings()['enabled']
    c.setting(approved_profiles={sid:profile_hash(c.recipe(sid)) for sid in c.bindings()})
    response=api.post('/api/hub/ziniao/plan',json={'confirmed':True,'enabled':True,'store_ids':list(c.bindings())})
    assert response.status_code==200 and len(response.json()['store_ids'])==6
