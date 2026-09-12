"""Explicit human-confirmed transfer of a saved answer into the existing state machine."""
import hashlib
import json
from datetime import date
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from action_center import FIELDS, encoded, now


class FromAnalysis(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    analysis_id: str = Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    conversation_id: str = Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    module: Literal['ads','inventory','creators','finance','daily','after','general']
    entity: str = Field(min_length=1,max_length=500)
    title: str = Field(min_length=1,max_length=200)
    action: str = Field(min_length=1,max_length=6000)
    priority: Literal['P0','P1','P2']='P1'
    owner: str = Field(default='',max_length=100)
    due_date: str = Field(default='',max_length=10)
    acceptance: str = Field(default='',max_length=2000)
    confirmed: bool=False


def register(router,db,put):
    @router.post('/from-analysis')
    def transfer(body:FromAnalysis):
        if not body.confirmed:raise HTTPException(422,'请确认要将这条建议保存为待复核候选。')
        if body.due_date:
            try:
                if date.fromisoformat(body.due_date)<date.today():raise ValueError()
            except ValueError:raise HTTPException(422,'截止日期无效或早于今天。')
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT value FROM analyses WHERE id=?',(body.analysis_id,)).fetchone()
            if not row:raise HTTPException(404,'分析记录不存在。')
            analysis=json.loads(row[0])
            row=con.execute('SELECT value FROM hub_conversations WHERE id=?',(body.conversation_id,)).fetchone()
            if not row:raise HTTPException(404,'来源聊天不存在。')
            chat=json.loads(row[0])
            if chat.get('deleted'):raise HTTPException(409,'请先恢复来源聊天。')
            if any(t.get('status')=='pending' for t in chat.get('turns',[])):
                raise HTTPException(409,'该聊天仍在回复，请回复完成后再加入行动。')
            turn=next((t for t in chat.get('turns',[]) if t.get('analysis_id')==body.analysis_id),None)
            if not turn or turn.get('status','complete')!='complete':raise HTTPException(422,'只能使用此聊天中已完成的分析回复。')
            identity=encoded([body.analysis_id,body.module,body.entity.casefold(),body.title.casefold()])
            task_id=hashlib.sha256(identity.encode()).hexdigest()[:32]
            row=con.execute('SELECT value FROM actions WHERE id=?',(task_id,)).fetchone()
            if row:return {'item':json.loads(row[0]),'created':False,'note':'这条建议已加入行动中心；未覆盖现有进度。'}
            evidence=analysis.get('evidence') or []
            # The answer is a suggestion, never label it as measured business evidence.
            frozen=[{'id':'CHAT-'+body.analysis_id,'kind':'ai_suggestion','question':turn['question'],
                'answer':analysis.get('content',''),'note':'AI 分析建议，需人工复核；不是原始业务事实。'}]
            frozen.extend({**e,'id':'QUERY-'+str(i+1)} for i,e in enumerate(evidence))
            origin={'kind':'chat','analysis_id':body.analysis_id,'conversation_id':body.conversation_id,
                'turn_id':turn.get('id',body.analysis_id),'question':turn['question'],'model':analysis.get('model',''),
                'original_answer':analysis.get('content',''),'query_evidence':evidence}
            item={**{k:'' for k in FIELDS},'id':task_id,'version':1,'state':'candidate','created_at':now(),
                'module':body.module,'entity':body.entity,'entity_key':'chat|'+body.entity.casefold(),
                'title':body.title,'priority':body.priority,'rule':'用户从 AI 回复选取并确认的建议；尚未证明原因或效果。',
                'source':'AI 聊天 · '+chat.get('title',turn['question'])[:80],'evidence':frozen,
                'suggested_action':body.action,'action':body.action,'owner':body.owner,'due_date':body.due_date,
                'acceptance':body.acceptance,'baseline':'待补充执行前实测基线；聊天建议不等同实时数据。',
                'guardrail':'先人工复核；退款、调价、投放和联系客户等操作由人到平台执行。',
                'ai_draft':None,'plan_origin':'chat:'+body.analysis_id,'origin':origin,
                'data_version':analysis.get('version',''),'latest_data_version':analysis.get('version','')}
            put(con,item,'created',{'source':'chat','analysis_id':body.analysis_id,'human_confirmed':True})
            turn.setdefault('linked_actions',[]).append({'id':task_id,'title':body.title})
            chat['revision']=chat.get('revision',0)+1;chat['updated_at']=now()
            con.execute('UPDATE hub_conversations SET value=? WHERE id=?',(encoded(chat),body.conversation_id))
        return {'item':item,'created':True,'note':'已保存为待复核候选；不会自动开始或执行。'}
