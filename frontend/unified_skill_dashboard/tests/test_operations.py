"""Every fixture uses an isolated DB; no production actions or model charges."""
import json
from test_data_hub import client,upload,activate
from data_hub import REQUIRED


def partition(client,job,version,period='2026-09-01/2026-09-02',preview=False):
    return client.post('/api/hub/imports/'+job['id']+('/impact' if preview else '/activate'),json={
        'mode':'partition','expected_version':version,'confirmed':not preview,
        'selections':[{'id':e['id'],'period':period,'currency':''} for e in job['entries']]})


def test_partition_revisions_preserve_other_shops_and_archive_periods(client):
    version=client.get('/api/hub/workspace').json()['version']
    row=lambda shop,n:{'库存SKU':'1234567890123456789','SKU中文名':'TEST','店铺':shop,'2026-09-01':10,'2026-09-02':n}
    initial=upload(client,[row('TEST-A',5),row('TEST-B',7)])
    version=activate(client,initial,version).json()['version']
    update=upload(client,[row('TEST-A',8)])
    preview=partition(client,update,version,preview=True)
    assert preview.status_code==200,preview.text
    assert preview.json()['impact']['changes'][0]['operation']=='revision'
    assert client.get('/api/hub/workspace').json()['version']==version
    result=partition(client,update,version);assert result.status_code==200,result.text
    version=result.json()['version']
    current=client.get('/api/hub/workspace').json()
    assert {r['店铺']:r['2026-09-02'] for r in current['data']['daily']['raw']['daily']}=={'TEST-A':8,'TEST-B':7}
    assert partition(client,update,version).json()['duplicate']
    later=upload(client,[{'库存SKU':'1234567890123456789','SKU中文名':'TEST','店铺':'TEST-A','2026-09-03':8,'2026-09-04':4}])
    result=partition(client,later,version,period='2026-09-03/2026-09-04');assert result.status_code==200,result.text
    version=result.json()['version'];current=client.get('/api/hub/workspace').json()
    assert len(current['data']['daily']['raw']['daily'])==1
    assert '2026-09-01' not in current['data']['daily']['raw']['daily'][0]
    parts=client.get('/api/hub/partitions').json()['items']
    assert len(parts)==2 and next(p for p in parts if not p['active'])['rows']==2
    restored=client.post('/api/hub/partitions/select',data={'kind':'daily','period':'2026-09-01/2026-09-02','expected_version':version,'confirmed':'true'})
    assert restored.status_code==200,restored.text
    assert len(client.get('/api/hub/workspace').json()['data']['daily']['raw']['daily'])==2
    assert client.get('/api/hub/workspace',params={'version':version}).json()['data']['daily']['raw']['daily'][0]['2026-09-04']==4


def test_partition_rejects_false_period_and_unsupported_kind_without_mutating(client):
    version=client.get('/api/hub/workspace').json()['version']
    job=upload(client,[{'库存SKU':'1','SKU中文名':'TEST','店铺':'S','2026-09-01':0,'2026-09-02':0}])
    assert partition(client,job,version,period='2026-09-03/2026-09-04').status_code==422
    assert client.get('/api/hub/workspace').json()['version']==version
    job=upload(client,[{'商品名称':'TEST','超期金额':0}],kind='warn')
    assert partition(client,job,version).status_code==422
    assert client.get('/api/hub/workspace').json()['version']==version


def test_initial_historical_partition_preserves_unknown_shop_rows(client):
    initial=client.get('/api/hub/workspace').json();version=initial['version']
    job=upload(client,[{'库存SKU':'TEST','SKU中文名':'TEST','店铺':'S','2026-09-01':8,'2026-09-02':2}])
    response=partition(client,job,version,preview=True);assert response.status_code==200,response.text
    response=partition(client,job,version);assert response.status_code==200,response.text
    current=client.get('/api/hub/workspace').json()
    ledger=current['data']['partition_store']['daily']
    old=[e for e in ledger if e['period']=='2026-06-01/2026-06-08']
    assert sum(len(e['rows']) for e in old)==571
    assert sum(len(e['rows']) for e in old if e.get('unassigned'))==1
    restored=client.post('/api/hub/partitions/select',data={'kind':'daily','period':'2026-06-01/2026-06-08','expected_version':current['version'],'confirmed':'true'})
    assert restored.status_code==200,restored.text
    assert client.get('/api/hub/workspace').json()['data']['daily']['kpis']==initial['data']['daily']['kpis']


def test_health_finds_missing_dates_values_and_duplicate_skus_without_repair(client):
    version=client.get('/api/hub/workspace').json()['version']
    rows=[{'库存SKU':'TEST-1','SKU中文名':'TEST','店铺':'S','2026-09-01':10,'2026-09-03':''},
          {'库存SKU':'TEST-1','SKU中文名':'TEST','店铺':'S','2026-09-01':0,'2026-09-03':0}]
    job=upload(client,rows)
    result=activate(client,job,version,period='2026-09-01/2026-09-03');assert result.status_code==200,result.text
    health=client.get('/api/hub/operations/health').json()
    row=health['daily_shops'][0]
    assert row['missing_dates']==['2026-09-02'] and row['missing_cells']==1 and row['duplicate_sku_rows']==1
    assert client.get('/api/hub/workspace').json()['data']['daily']['raw']['daily'][0]['2026-09-03']==''


def test_product_triage_feedback_and_timeline_are_exact_and_local(client):
    version=client.get('/api/hub/workspace').json()['version']
    triage=client.get('/api/hub/operations/triage',params={'shop':'EXPOSE TK','limit':100}).json()
    assert triage['total']==71 and len(triage['rows'])==71
    first=triage['rows'][0];assert first['dayDiff']==-5
    product=client.get('/api/hub/operations/product',params={'shop':'EXPOSE TK','product':first['product']}).json()
    assert product['daily_metrics']['rows'][0]['latest']==6
    assert next(s for s in product['sections'] if s['kind']=='gmv')['status']=='mapping_required'
    assert product['comparison']['same_period'] is False
    assert client.get('/api/hub/operations/product',params={'shop':'EXPOSE TK','product':first['product']+'假名'}).status_code==404
    feedback={'version':version,'shop':'EXPOSE.TK','product':first['product'],'verdict':'data_issue','reason':'TEST ONLY: incomplete export needs checking'}
    assert client.post('/api/hub/operations/feedback',json=feedback).status_code==200
    again=client.get('/api/hub/operations/triage',params={'shop':'EXPOSE TK','q':first['product']}).json()
    assert again['total']==1 and again['rows'][0]['feedback']['verdict']=='data_issue'
    annotation={'version':version,'shop':'EXPOSE.TK','product':first['product'],'category':'check','occurred_on':'2026-06-08','note':'TEST ONLY: no real operation'}
    assert client.post('/api/hub/operations/annotations',json=annotation).status_code==422
    assert client.post('/api/hub/operations/annotations',json={**annotation,'confirmed':True}).status_code==200
    detail=client.get('/api/hub/operations/product',params={'shop':'EXPOSE.TK','product':first['product']}).json()
    assert detail['timeline'][0]['note']==annotation['note']
    assert client.get('/api/hub/workspace').json()['version']==version
    assert client.get('/api/hub/operations/triage',params={'shop':'EXPOSE TK'}).json()['total']==71
    export=client.get('/api/hub/operations/product/export',params={'shop':'EXPOSE.TK','product':first['product'],'version':version})
    assert export.status_code==200 and 'attachment' in export.headers['content-disposition']
    assert all(s['total']==len(s['rows']) for s in export.json()['sections'])


def test_ai_product_tool_is_read_only_versioned_and_minimal(client,monkeypatch):
    from test_server import server
    version=client.get('/api/hub/workspace').json()['version'];calls=[]
    product=client.get('/api/hub/operations/products',params={'shop':'EXPOSE.TK','limit':1}).json()['rows'][0]['product']
    def model(prompt,**kwargs):
        calls.append(kwargs)
        if len(calls)==1:return {'message':{'content':None,'tool_calls':[{'id':'profile','type':'function','function':{'name':'product_profile','arguments':json.dumps({'shop':'EXPOSE.TK','product':product})}}]},'model':'mock','usage':{}}
        return {'message':{'content':'已查询商品档案；不同周期不能归因。[E1]'},'model':'mock','usage':{}}
    monkeypatch.setattr(server,'local_model',model)
    result=client.post('/api/hub/assistant',json={'question':'查这个商品档案','version':version})
    assert result.status_code==200,result.text
    evidence=result.json()['evidence'][0]
    assert evidence['result']['version']==version and evidence['tool']=='product_profile'
    assert all(len(s['rows'])<=3 for s in evidence['result']['sections'])
    assert client.get('/api/hub/workspace').json()['version']==version


def test_ad_partitions_keep_currency_separate(client):
    version=client.get('/api/hub/workspace').json()['version']
    row=lambda shop,cost,currency:{'商品 ID':'1234567890123456789','成本':cost,'总收入':50,'SKU 订单数':10,'创意作品类型':'Video','货币':currency,'店铺':shop}
    job=upload(client,[row('S1',5,'USD'),row('S2',6,'USD')],kind='gmv')
    version=activate(client,job,version,period='2026-09-01',currency='USD').json()['version']
    def apply(job,version,currency):
        return client.post('/api/hub/imports/'+job['id']+'/activate',json={'mode':'partition','confirmed':True,'expected_version':version,
            'selections':[{'id':job['entries'][0]['id'],'period':'2026-09-01','currency':currency}]})
    job=upload(client,[row('S1',7,'USD')],kind='gmv');result=apply(job,version,'USD')
    assert result.status_code==200,result.text
    version=result.json()['version']
    assert {r['店铺']:r['成本'] for r in client.get('/api/hub/workspace').json()['data']['gmv']['rows']}=={'S1':7,'S2':6}
    job=upload(client,[row('S1',30,'MYR')],kind='gmv');result=apply(job,version,'MYR')
    assert result.status_code==200,result.text
    current=client.get('/api/hub/workspace').json()
    assert len(current['data']['gmv']['rows'])==1 and current['data']['gmv']['rows'][0]['货币']=='MYR'
    parts=client.get('/api/hub/partitions').json()['items']
    assert len(parts)==2 and next(p for p in parts if p['currency']=='USD')['rows']==2


def test_bill_partition_uses_original_alias_normalization(client):
    version=client.get('/api/hub/workspace').json()['version']
    def row(shop,cost):
        r={h:'' for h in REQUIRED['bill']};r.update({'店编':shop,'款名':'TEST','订单结算时间':'2026-09-01','订单成本':cost,'总收入':100,'结算总金额':90,'相关订单 ID':'1234567890123456789','状态':'已发货'})
        return r
    job=upload(client,[row('MS0001',20),row('MS0002',30)],kind='bill')
    version=activate(client,job,version,period='2026-09-01',currency='MYR').json()['version']
    corrected={('Related order ID' if k=='相关订单 ID' else k):v for k,v in row('MS0001',25).items()}
    job=upload(client,[corrected],kind='bill')
    response=client.post('/api/hub/imports/'+job['id']+'/activate',json={'mode':'partition','confirmed':True,'expected_version':version,
        'selections':[{'id':job['entries'][0]['id'],'period':'2026-09-01','currency':'MYR'}]})
    assert response.status_code==200,response.text
    table=client.get('/api/hub/workspace').json()['data']['bill']
    assert table['header']==REQUIRED['bill']
    rows=[dict(zip(table['header'],r)) for r in table['rows']]
    assert {r['店编']:r['订单成本'] for r in rows}=={'MS0001':25,'MS0002':30}
    assert all(r['相关订单 ID']=='1234567890123456789' for r in rows)


def test_new_bill_invalidates_stale_pipeline_export_but_preserves_history(client):
    from test_server import server
    before=client.get('/api/hub/workspace').json()
    before['data']['pipeline_results']=[{'shop':'OLD-SENTINEL','out3':{'summary':[['TEST']]}}]
    with server.hub.db() as con:
        version=server.hub.save(con,before['data'],before['meta'],before['version'])
    r={h:'' for h in REQUIRED['bill']};r.update({'店编':'MS0001','款名':'TEST','订单结算时间':'2026-09-01','订单成本':20,'总收入':100,'结算总金额':90,'状态':'已发货'})
    job=upload(client,[r],kind='bill')
    response=activate(client,job,version,period='2026-09-01',currency='MYR')
    assert response.status_code==200,response.text
    assert not client.get('/api/hub/workspace').json()['data'].get('pipeline_results')
    assert client.get('/api/hub/workspace',params={'version':version}).json()['data']['pipeline_results'][0]['shop']=='OLD-SENTINEL'
    assert client.get('/api/hub/pipeline/export/profit').status_code==200
