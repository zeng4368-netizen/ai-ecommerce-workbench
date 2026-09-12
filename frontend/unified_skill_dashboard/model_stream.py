"""Parse actual provider SSE deltas; never simulate typing of a completed answer."""
import json
from fastapi import HTTPException


def read_stream(response,emit,cancel=None):
    content=[];calls={};usage={};model='';finish=None;size=0;done=False
    for raw in response:
        if cancel and cancel.is_set():raise HTTPException(499,'已停止生成。')
        size+=len(raw)
        if size>4*1024*1024:raise HTTPException(502,'模型流式响应超过安全大小限制。')
        line=raw.decode('utf-8').strip()
        if not line.startswith('data:'):continue
        value=line[5:].strip()
        if value=='[DONE]':done=True;break
        chunk=json.loads(value)
        if chunk.get('error'):raise HTTPException(502,'模型返回流式错误，请重试。')
        model=chunk.get('model',model)
        if chunk.get('usage'):usage=chunk['usage']
        for choice in chunk.get('choices',[]):
            if choice.get('index',0)!=0:continue
            delta=choice.get('delta') or {}
            if delta.get('content'):
                content.append(delta['content']);emit({'type':'delta','text':delta['content']})
            for t in delta.get('tool_calls') or []:
                index=t.get('index',0)
                c=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                if t.get('id'):c['id']=t['id']
                for key in ('name','arguments'):
                    if t.get('function',{}).get(key):c['function'][key]+=t['function'][key]
            if choice.get('finish_reason'):finish=choice['finish_reason']
    if not done or not finish:raise HTTPException(502,'模型连接中断，回答可能不完整；可以重试。')
    message={'role':'assistant','content':''.join(content)}
    if calls:message['tool_calls']=[calls[i] for i in sorted(calls)]
    return {'choices':[{'message':message,'finish_reason':finish}],'model':model,'usage':usage}
