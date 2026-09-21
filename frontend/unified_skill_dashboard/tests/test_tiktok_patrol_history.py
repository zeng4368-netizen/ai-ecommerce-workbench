"""Daily history and serialized batches, using synthetic records only."""
import json
import sqlite3
import sys
from pathlib import Path
from datetime import date

import pytest
import yaml
from fastapi import HTTPException

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data_hub import Hub
from tiktok_patrol import Patrol, pack
from tiktok_patrol_live import LivePatrol
from tiktok_patrol_history import daily_history

@pytest.fixture
def live(tmp_path):
    cfg=yaml.safe_load((Path(__file__).resolve().parents[3]/'config/selectors.yaml').read_text(encoding='utf8'))['tiktok_patrol_live']
    cfg['reviewed_store_ids']=['s1','s2'];cfg['store_profiles']={}
    path=tmp_path/'selectors.yaml'
    path.write_text(yaml.safe_dump({'tiktok_patrol_live':cfg,'ziniao_stores':{
        's1':{'shop':'MY test','currency':'MYR','timezone':'Asia/Kuala_Lumpur'},
        's2':{'shop':'TH test','currency':'THB','timezone':'Asia/Bangkok'}}}),encoding='utf8')
    value=LivePatrol(Patrol(Hub(lambda:sqlite3.connect(tmp_path/'db.sqlite'),tmp_path),path))
    with value.db() as con:value.schema(con)
    return value

def add(live,ident,day,value,sid='s1',captured='2026-09-14T01:00:00+00:00',home=False):
    section={'period':day,'captured_at':captured,'sha256':ident,'data':[{'label':'GMV','value':value,'currency':'MYR' if sid=='s1' else 'THB'}]}
    sections={'sales':section}
    if home:sections['homepage']={**section,'period':'current','data':{'cards':[{'label':'待发货','value':7,'detail':''}],'health':'test'}}
    r={'id':ident,'store_id':sid,'day':day,'timezone':'Asia/Kuala_Lumpur' if sid=='s1' else 'Asia/Bangkok','sections':sections,'state':'complete'}
    with live.db() as con:con.execute('INSERT INTO tiktok_patrol_live_runs VALUES(?,?,?,?)',(ident,sid,'complete',pack(r)))

def test_latest_version_gaps_daily_change_and_currencies(live):
    add(live,'a','2026-09-12',100)
    add(live,'b','2026-09-13',130)
    add(live,'c','2026-09-13',140,captured='2026-09-14T02:00:00+00:00',home=True)
    add(live,'d','2026-09-13',900,sid='s2')
    data=daily_history(live,'all','2026-09-11','2026-09-14')
    sales=next(s for s in data['series'] if s['store_id']=='s1' and s['kind']=='sales')
    assert [p['value'] for p in sales['points']]==[None,100,140,None]
    assert sales['points'][2]['versions']==2
    assert sales['points'][2]['delta']==40
    assert sales['points'][2]['daily_change_pct']==pytest.approx(40)
    home=next(s for s in data['series'] if s['kind']=='homepage')
    assert home['points'][2]['value'] is None and home['points'][3]['value']==7
    assert {s['currency'] for s in data['series']}=={'','MYR','THB'}
    with live.db() as con:assert con.execute('SELECT count(*) FROM tiktok_patrol_live_runs').fetchone()[0]==4

def test_missing_previous_not_compared_and_invalid_range(live):
    add(live,'a','2026-09-10',5);add(live,'b','2026-09-12',10)
    d=daily_history(live,'s1','2026-09-10','2026-09-12')
    assert d['series'][0]['points'][-1]['daily_change_pct'] is None
    for start,end in [('bad','2026-09-12'),('2026-09-14','2026-09-12'),('2020-01-01','2026-01-01')]:
        with pytest.raises(HTTPException):daily_history(live,'all',start,end)

def test_batch_runs_each_store_serially_and_preserves_pause(live,monkeypatch):
    calls=[]
    def fake_execute(ident):
        job=live.get(ident);calls.append(job['store_id'])
        live.renew(ident)
        job.update(state='complete' if job['store_id']=='s1' else 'paused',error='' if job['store_id']=='s1' else 'login needed')
        live.save(job)
        with live.db() as con:con.execute('UPDATE ziniao_browser_lease SET owner=? WHERE owner=?',(job['batch_id'],ident))
    monkeypatch.setattr(live,'execute',fake_execute)
    batch=live.create_batch('all',start=False)
    with pytest.raises(HTTPException):live.create('s1',start=False)
    with pytest.raises(HTTPException):live.create_batch('all',start=False)
    live.execute_batch(batch['id'])
    result=live.get_batch(batch['id'])
    assert calls==['s1','s2'] and result['state']=='partial'
    assert result['items'][1]['error']=='login needed'
    with live.db() as con:assert con.execute('SELECT count(*) FROM ziniao_browser_lease').fetchone()[0]==0

def test_expired_batch_does_not_resume(live):
    batch=live.create_batch('all',start=False)
    with live.db() as con:con.execute('UPDATE ziniao_browser_lease SET expires=0')
    assert live.get_batch(batch['id'])['state']=='interrupted'

def test_section_days_follow_each_account_timezone(live,monkeypatch):
    import tiktok_patrol_live
    cfg=live.recipe();cfg['ads']['timezone']='Asia/Shanghai'
    monkeypatch.setattr(live,'recipe',lambda:cfg)
    monkeypatch.setattr(tiktok_patrol_live,'today_for',lambda store:date(2026,9,15) if store['timezone']=='Asia/Shanghai' else date(2026,9,14))
    job=live.create('s2',start=False)
    assert job['day']=='2026-09-13'
    assert job['section_days']=={'sales':'2026-09-13','ads':'2026-09-14'}
