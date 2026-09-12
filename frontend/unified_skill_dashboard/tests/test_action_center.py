import json
import pytest
from fastapi.testclient import TestClient
from test_server import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DB', tmp_path / 'actions.sqlite3')
    return TestClient(server.app)


def candidate():
    return dict(module='ads', entity='TEST-PRODUCT', entity_key='shop|product|USD', title='资格核查', priority='P0',
                rule='有消耗且资格异常', source='历史快照 · USD', evidence=[{'id': 'ADS-1', 'spend': 20, 'roi': 8}], suggested_action='核查实时状态')


def seed(client):
    assert client.post('/api/actions/sync', json={'candidates': [candidate()]}).json()['added'] == 1
    return client.get('/api/actions').json()['items'][0]


def change(client, task, op, **kwargs):
    return client.post('/api/actions/'+task['id']+'/update', json={'version': task['version'], 'op': op, **kwargs})


def test_sync_idempotency_and_snapshot_identity(client):
    task = seed(client)
    assert client.post('/api/actions/sync', json={'candidates': [candidate()]}).json()['added'] == 0
    changed = candidate(); changed['evidence'][0]['spend'] = 30
    assert client.post('/api/actions/sync', json={'candidates': [changed]}).json()['added'] == 1
    assert len(client.get('/api/actions').json()['items']) == 2
    bad = candidate();bad['evidence'] = [{'spend': 50}]
    assert client.post('/api/actions/sync', json={'candidates': [bad]}).status_code == 422
    assert client.get('/api/actions/'+task['id']).json()['events'][0]['op'] == 'created'


def test_complete_workflow_and_confirmation_gates(client):
    t = seed(client)
    assert change(client,t,'complete',confirmed=True).status_code == 422
    assert change(client,t,'approve',confirmed=True).status_code == 422
    values = dict(owner='运营测试', due_date='2099-01-01', action='核查当前投放资格', acceptance='取得平台状态截图并记录核查时间',
                  metric='当前投放资格状态', baseline='历史状态异常，实时状态待核查', guardrail='不自动调整预算')
    assert change(client,t,'approve',**values).status_code == 422
    r=change(client,t,'approve',confirmed=True,**values); assert r.status_code == 200
    assert change(client,t,'save',owner='stale').status_code == 409
    t=r.json()['item']; assert t['state']=='ready'
    assert change(client,t,'start',action='擅自替换行动').status_code==422
    t=change(client,t,'start').json()['item'];assert t['state']=='doing'
    assert change(client,t,'submit').status_code==422
    t=change(client,t,'submit',execution_note='测试核查记录',result_evidence='fixture/screenshot.png',observed_result='测试结果：当前证据不足').json()['item']
    assert t['state']=='review'
    assert change(client,t,'complete',confirmed=True).status_code==422
    t=change(client,t,'complete',confirmed=True,reviewer='测试复核人',conclusion='inconclusive',review_note='仅测试流转，不代表真实业务结果').json()['item']
    assert t['state']=='done'
    assert change(client,t,'save',owner='edit').status_code==409
    t=change(client,t,'reopen',reason='重新验证').json()['item']
    assert t['state']=='candidate' and not t['observed_result']
    assert len(client.get('/api/actions/'+t['id']).json()['events'])==6


def test_ai_draft_cannot_approve_or_mutate_facts(client,monkeypatch):
    t=seed(client)
    plan=dict(hypothesis='历史资格需复核',steps=['导出当前状态','记录状态与时点','提交人审'],acceptance='有可回查截图',metric='当前资格',guardrail='不自动调预算',missing_data=['实时状态'],evidence_ids=['ADS-1'])
    calls=[]
    def model(prompt,structured=False):
        calls.append(prompt)
        assert structured
        return dict(content=json.dumps(plan),model='mock',provider='mock',usage={'total_tokens':12},finish_reason='stop')
    monkeypatch.setattr(server,'local_model',model)
    r=client.post('/api/actions/'+t['id']+'/ai');assert r.status_code==200
    t=r.json()['item'];assert t['state']=='candidate' and t['action']=='核查实时状态'
    assert t['evidence']==candidate()['evidence']
    t=change(client,t,'adopt').json()['item'];assert t['state']=='candidate' and '导出当前状态' in t['action']
    plan['evidence_ids']=['FAKE-1']
    assert client.post('/api/actions/'+t['id']+'/ai').status_code==422
    history=client.get('/api/actions/'+t['id']).json()
    assert history['ai_runs'][0]['valid'] is False
    assert history['item']['ai_draft']['plan']['evidence_ids']==['ADS-1']
