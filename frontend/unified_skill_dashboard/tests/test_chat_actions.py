import json
import pytest
from test_data_hub import client
from test_server import server
from test_chat import fake_model


def source(client,monkeypatch):
    monkeypatch.setattr(server,'local_model',fake_model)
    r=client.post('/api/hub/assistant',json={'question':'请建议如何准备面试','workspace_enabled':False}).json()
    return dict(analysis_id=r['id'],conversation_id=r['conversation_id'],module='general',entity='面试准备',
                title='完善一个项目案例',action='整理项目问题、实现和验证结果；输出一页介绍。',confirmed=True)


def test_explicit_transfer_idempotent_origin_and_backlink(client,monkeypatch):
    body=source(client,monkeypatch)
    assert client.post('/api/actions/from-analysis',json={**body,'confirmed':False}).status_code==422
    r=client.post('/api/actions/from-analysis',json=body)
    assert r.status_code==200,r.text
    task=r.json()['item'];assert task['state']=='candidate'
    assert task['origin']['analysis_id']==body['analysis_id']
    assert task['evidence'][0]['kind']=='ai_suggestion'
    assert task['data_version']==''
    chat=client.get('/api/hub/conversations/'+body['conversation_id']).json()
    assert chat['turns'][0]['linked_actions'][0]['id']==task['id']
    again=client.post('/api/actions/from-analysis',json={**body,'action':'不同编辑不覆盖'})
    assert again.json()['created'] is False and again.json()['item']['action']==body['action']
    different=client.post('/api/actions/from-analysis',json={**body,'title':'第二项行动'})
    assert different.json()['created'] is True
    assert client.get('/api/hub/actions/'+task['id']+'/comparison').json()['status']=='pending'
    detail=client.get('/api/actions/'+task['id']).json()
    assert detail['events'][0]['detail']['human_confirmed'] is True


def test_transfer_rejects_forgery_deleted_and_pending_chat(client,monkeypatch):
    body=source(client,monkeypatch)
    assert client.post('/api/actions/from-analysis',json={**body,'evidence':[{'fake':1}]}).status_code==422
    assert client.post('/api/actions/from-analysis',json={**body,'due_date':'2000-01-01'}).status_code==422
    assert client.post('/api/actions/from-analysis',json={**body,'conversation_id':'unknown'}).status_code==404
    other=client.post('/api/hub/conversations',json={}).json()
    assert client.post('/api/actions/from-analysis',json={**body,'conversation_id':other['id']}).status_code==422
    with server.hub.db() as con:
        chat=json.loads(con.execute('SELECT value FROM hub_conversations WHERE id=?',(body['conversation_id'],)).fetchone()[0])
        chat['turns'].append({'status':'pending','question':'another'})
        con.execute('UPDATE hub_conversations SET value=? WHERE id=?',(json.dumps(chat),body['conversation_id']))
    assert client.post('/api/actions/from-analysis',json=body).status_code==409


def test_action_first_prompt_keeps_original_facts(client,monkeypatch):
    from test_action_center import seed
    t=seed(client);captured=[]
    plan=dict(steps=['导出该对象的退款订单，形成原因明细表。','抽查退款原因并保存记录。'],acceptance='提交原因分类表和抽查记录',
        hypothesis='退款占比偏高，原因仍待核查。',metric='退款金额 / GMV',guardrail='不自动退款',missing_data=['退款原因'],evidence_ids=['ADS-1'])
    def model(prompt,structured=False):
        captured.append(prompt)
        return dict(content=json.dumps(plan),model='mock',provider='mock',usage={},finish_reason='stop')
    monkeypatch.setattr(server,'local_model',model)
    r=client.post('/api/actions/'+t['id']+'/ai');assert r.status_code==200,r.text
    assert '先写 steps' in captured[0] and 'current_plan' in captured[0]
    assert r.json()['item']['evidence']==t['evidence']
    assert r.json()['item']['action']==t['action']


def test_stale_ai_plan_never_overwrites_saved_action(client,monkeypatch):
    from test_action_center import seed
    t=seed(client)
    def model(prompt,structured=False):
        with server.hub.db() as con:
            current=json.loads(con.execute('SELECT value FROM actions WHERE id=?',(t['id'],)).fetchone()[0])
            current['version']+=1;current['action']='用户刚保存的新方案'
            con.execute('UPDATE actions SET value=? WHERE id=?',(json.dumps(current),t['id']))
        plan=dict(steps=['旧方案'],hypothesis='待核查',acceptance='有记录',metric='资格',guardrail='人审',missing_data=[],evidence_ids=['ADS-1'])
        return dict(content=json.dumps(plan),model='mock',provider='mock',usage={},finish_reason='stop')
    monkeypatch.setattr(server,'local_model',model)
    r=client.post('/api/actions/'+t['id']+'/ai');assert r.status_code==409,r.text
    saved=client.get('/api/actions/'+t['id']).json()
    assert saved['item']['action']=='用户刚保存的新方案' and saved['item']['ai_draft'] is None
    assert saved['ai_runs'][0]['applied'] is False
