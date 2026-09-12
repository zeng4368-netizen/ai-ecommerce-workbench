import json
import threading
import pytest
from fastapi import HTTPException
from test_data_hub import client
from test_server import server
from model_stream import read_stream


def fake_model(prompt='', **kwargs):
    messages=kwargs['messages']
    content='测试回复：'+messages[-1]['content']
    if kwargs.get('on_event'):
        kwargs['on_event']({'type':'delta','text':content[:4]})
        kwargs['on_event']({'type':'delta','text':content[4:]})
    return {'message':{'role':'assistant','content':content},'model':'TEST ONLY','provider':'mock','usage':{'total_tokens':10},'finish_reason':'stop'}


def test_general_context_isolation_and_idempotency(client,monkeypatch):
    captured=[]
    def model(*args,**kwargs):
        captured.append(kwargs['messages'].copy())
        return fake_model(*args,**kwargs)
    monkeypatch.setattr(server,'local_model',model)
    chat=client.post('/api/hub/conversations',json={'workspace_enabled':False}).json()
    for i in range(7):
        r=client.post('/api/hub/assistant',json={'question':f'普通问题{i}','conversation_id':chat['id'],'request_id':f'turn{i}'})
        assert r.status_code==200,r.text
        assert r.json()['evidence']==[] and r.json()['mode']=='chat'
    assert len(captured[-1])==14
    assert captured[-1][1]['content']=='普通问题0'
    count=len(captured)
    same=client.post('/api/hub/assistant',json={'question':'普通问题6','conversation_id':chat['id'],'request_id':'turn6'})
    assert same.status_code==200 and len(captured)==count
    assert client.post('/api/hub/assistant',json={'question':'换个问题','conversation_id':chat['id'],'request_id':'turn6'}).status_code==409
    other=client.post('/api/hub/assistant',json={'question':'另一聊天','workspace_enabled':False})
    assert other.status_code==200 and len(captured[-1])==2
    assert '普通问题0' not in json.dumps(captured[-1],ensure_ascii=False)


def test_chat_crud_search_export_and_legacy(client,monkeypatch):
    monkeypatch.setattr(server,'local_model',fake_model)
    result=client.post('/api/hub/assistant',json={'question':'我的昵称是小鹿','workspace_enabled':False}).json()
    ident=result['conversation_id'];url='/api/hub/conversations/'+ident
    p=client.get(url).json()
    renamed=client.patch(url,json={'title':'面试准备','expected_revision':p['revision']}).json()
    assert renamed['title']=='面试准备'
    assert client.patch(url,json={'title':'冲突','expected_revision':p['revision']}).status_code==409
    assert client.get('/api/hub/conversations?q=小鹿').json()['items'][0]['id']==ident
    assert '我的昵称是小鹿' in client.get(url+'/export').text
    archived=client.patch(url,json={'deleted':True,'expected_revision':renamed['revision']}).json()
    assert not client.get('/api/hub/conversations').json()['items']
    assert len(client.get('/api/hub/conversations?deleted=true').json()['items'])==1
    assert client.post('/api/hub/assistant',json={'question':'hello','conversation_id':ident}).status_code==409
    assert client.patch(url,json={'deleted':False,'expected_revision':archived['revision']}).status_code==200
    with server.hub.db() as con:
        value={'id':'old','scope':'all','created_at':'2026-01-01T00:00:00Z','content':'旧报告'}
        con.execute('INSERT INTO analyses VALUES(?,?,?)',('old',value['created_at'],json.dumps(value)))
    for _ in range(2):assert len(client.get('/api/hub/conversations').json()['items'])==2
    assert client.get('/api/hub/conversations/analysis-old').json()['turns'][0]['content']=='旧报告'


def test_stream_and_failed_retry(client,monkeypatch):
    def failure(*args,**kwargs):raise HTTPException(504,'模拟超时')
    monkeypatch.setattr(server,'local_model',failure)
    p=client.post('/api/hub/conversations',json={'workspace_enabled':False}).json()
    payload={'question':'你好','conversation_id':p['id'],'request_id':'retry-1'}
    r=client.post('/api/hub/assistant/stream',json=payload)
    assert '模拟超时' in r.text
    saved=client.get('/api/hub/conversations/'+p['id']).json()
    assert saved['turns'][0]['status']=='error' and not saved['busy']
    monkeypatch.setattr(server,'local_model',fake_model)
    r=client.post('/api/hub/assistant/stream',json=payload)
    events=[json.loads(s[6:]) for s in r.text.splitlines() if s.startswith('data: ')]
    assert [e['type'] for e in events].count('delta')==2
    assert events[-1]['type']=='done'
    saved=client.get('/api/hub/conversations/'+p['id']).json()
    assert len(saved['turns'])==1 and saved['turns'][0]['status']=='complete'
    assert len(saved['turns'][0]['attempts'])==1


def test_disabled_tools_and_context_limit(client,monkeypatch):
    def bad_model(*args,**kwargs):
        assert kwargs['tool_specs']==[]
        if kwargs['messages'][-1]['role']=='tool':return fake_model(*args,**kwargs)
        return {'message':{'tool_calls':[{'id':'tool1','function':{'name':'query_data','arguments':'{"kind":"daily"}'}}]}}
    monkeypatch.setattr(server,'local_model',bad_model)
    def forbidden(*args,**kwargs):raise AssertionError('Disabled tools must not read hub data')
    monkeypatch.setattr(server.hub,'query',forbidden)
    r=client.post('/api/hub/assistant',json={'question':'你好','workspace_enabled':False})
    assert r.status_code==200,r.text
    assert '已关闭' in r.json()['evidence'][0]['result']['error']
    ident=r.json()['conversation_id']
    with server.hub.db() as con:
        p=json.loads(con.execute('SELECT value FROM hub_conversations WHERE id=?',(ident,)).fetchone()[0])
        p['turns'][0]['content']='x'*120000
        con.execute('UPDATE hub_conversations SET value=? WHERE id=?',(json.dumps(p),ident))
    r=client.post('/api/hub/assistant',json={'question':'继续','conversation_id':ident})
    assert r.status_code==422 and '没有悄悄删除' in r.text


def test_provider_sse_parser():
    chunks=[{'choices':[{'delta':{'reasoning_content':'private reasoning','content':'你好'}}]},
        {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'t1','function':{'name':'query_data','arguments':'{"kind":'}}]}}]},
        {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"daily"}'}}]},'finish_reason':'tool_calls'}]},
        {'choices':[],'usage':{'total_tokens':20},'model':'test'}]
    lines=[('data: '+json.dumps(c)+'\n\n').encode() for c in chunks]+[b'data: [DONE]\n']
    events=[];r=read_stream(lines,events.append)
    assert events==[{'type':'delta','text':'你好'}]
    assert json.loads(r['choices'][0]['message']['tool_calls'][0]['function']['arguments'])=={'kind':'daily'}
    assert r['usage']['total_tokens']==20
    with pytest.raises(HTTPException):read_stream(lines[:-1],lambda e:None)
    stop=threading.Event();stop.set()
    with pytest.raises(HTTPException) as e:read_stream(lines,lambda e:None,stop)
    assert e.value.status_code==499
