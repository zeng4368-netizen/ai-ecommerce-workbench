"""Persistent independent chats, with reversible trash and legacy-analysis import."""
import json
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from data_hub import pack, stamp


class ChatCreate(BaseModel):
    title: str = Field(default='新对话',min_length=1,max_length=120)
    workspace_enabled: bool = True


class ChatEdit(BaseModel):
    expected_revision: int
    title: str | None = Field(default=None,min_length=1,max_length=120)
    workspace_enabled: bool | None = None
    deleted: bool | None = None


class ChatStore:
    def __init__(self,hub): self.hub=hub

    def normalize(self,ident,p):
        p.setdefault('id',ident);p.setdefault('revision',0)
        p.setdefault('created_at',p.get('turns',[{}])[0].get('created_at',stamp()) if p.get('turns') else stamp())
        p.setdefault('updated_at',p['created_at']);p.setdefault('deleted',False);p.setdefault('workspace_enabled',True)
        p.setdefault('turns',[])
        p.setdefault('title',p['turns'][0]['question'][:48] if p['turns'] else '新对话')
        for i,t in enumerate(p['turns']):
            t.setdefault('id',t.get('analysis_id') or f'legacy-{i}')
            t.setdefault('status','complete');t.setdefault('created_at',p['created_at'])
        return p

    def get(self,con,ident):
        row=con.execute('SELECT value FROM hub_conversations WHERE id=?',(ident,)).fetchone()
        if not row: raise HTTPException(404,'聊天不存在')
        return self.normalize(ident,json.loads(row[0]))

    def save(self,con,p):
        p['revision']+=1;p['updated_at']=stamp()
        con.execute('INSERT OR REPLACE INTO hub_conversations VALUES (?,?)',(p['id'],pack(p)))
        return p

    def new(self,ident='',title='新对话',workspace=True):
        return self.normalize(ident or uuid.uuid4().hex,{'title':title,'turns':[],'workspace_enabled':workspace})

    def legacy(self):
        """Non-destructive, idempotent migration. Original analyses remain untouched."""
        with self.hub.db() as con:
            con.execute('BEGIN IMMEDIATE')
            rows=con.execute('SELECT id,value FROM hub_conversations').fetchall()
            chats=[self.normalize(r[0],json.loads(r[1])) for r in rows]
            represented={t.get('analysis_id') for p in chats for t in p['turns']}
            for ident,value in con.execute('SELECT id,value FROM analyses').fetchall():
                if ident in represented:continue
                r=json.loads(value)
                # Do not duplicate an analysis whose original conversation still exists.
                if r.get('conversation_id') in {c['id'] for c in chats}:continue
                cid='analysis-'+ident
                if con.execute('SELECT 1 FROM hub_conversations WHERE id=?',(cid,)).fetchone():continue
                question='历史分析 · '+str(r.get('scope','综合'))
                try:
                    messages=json.loads(r.get('prompt',''))
                    if isinstance(messages,list):question=next((m['content'] for m in reversed(messages) if m.get('role')=='user' and isinstance(m.get('content'),str)),question)
                except (ValueError,TypeError):pass
                created=r.get('created_at',stamp())
                p=self.new(cid,question[:48]);p.update(created_at=created,updated_at=created,legacy=True)
                p['turns']=[{'id':ident,'analysis_id':ident,'question':question,'content':r.get('content',''),
                    'status':'complete','created_at':created,'version':r.get('version',''),'evidence':r.get('evidence',[]),
                    'model':r.get('model',''),'usage':r.get('usage',{})}]
                con.execute('INSERT INTO hub_conversations VALUES (?,?)',(cid,pack(p)))

    def router(self,busy):
        router=APIRouter(prefix='/conversations',tags=['chat'])

        @router.get('')
        def listing(q: str='',deleted: bool=False):
            self.legacy()
            with self.hub.db() as con:
                rows=[self.normalize(r[0],json.loads(r[1])) for r in con.execute('SELECT id,value FROM hub_conversations')]
            rows=[p for p in rows if p['deleted']==deleted and (not q or q.casefold() in (p['title']+' '+ ' '.join(t['question']+' '+t.get('content','') for t in p['turns'])).casefold())]
            return {'items':[{'id':p['id'],'title':p['title'],'updated_at':p['updated_at'],'revision':p['revision'],
                'deleted':p['deleted'],'turn_count':len(p['turns']),'busy':p['id'] in busy,
                'preview':p['turns'][-1]['question'][:90] if p['turns'] else ''} for p in sorted(rows,key=lambda p:p['updated_at'],reverse=True)]}

        @router.post('')
        def create(body: ChatCreate):
            p=self.new(title=body.title,workspace=body.workspace_enabled)
            with self.hub.db() as con:return self.save(con,p)

        @router.get('/{ident}')
        def get(ident: str):
            with self.hub.db() as con:
                p=self.get(con,ident)
                # A server restart interrupts unfinished model requests, not user history.
                if ident not in busy and any(t['status']=='pending' for t in p['turns']):
                    for t in p['turns']:
                        if t['status']=='pending':t.update(status='error',error='上次请求中断；消息已保留，可重试。')
                    self.save(con,p)
            return {**p,'busy':ident in busy}

        @router.patch('/{ident}')
        def edit(ident: str,body:ChatEdit):
            if ident in busy:raise HTTPException(409,'该聊天正在回复，请完成后再修改或移入回收站。')
            with self.hub.db() as con:
                con.execute('BEGIN IMMEDIATE');p=self.get(con,ident)
                if p['revision']!=body.expected_revision:raise HTTPException(409,'聊天已更新，请刷新重试。')
                for key in ('title','workspace_enabled','deleted'):
                    value=getattr(body,key)
                    if value is not None:p[key]=value.strip() if key=='title' else value
                if not p['title']:raise HTTPException(422,'聊天标题不能为空')
                return self.save(con,p)

        @router.get('/{ident}/export')
        def export(ident: str):
            with self.hub.db() as con:p=self.get(con,ident)
            text='# '+p['title']+'\n\n'
            for t in p['turns']:
                text+='## 你\n\n'+t['question']+'\n\n## 助手\n\n'+(t.get('content') or t.get('error','待回复'))+'\n\n'
                if t.get('version'):text+='数据版本：'+t['version']+'\n\n'
                if t.get('evidence'):text+='查询依据：\n```json\n'+json.dumps(t['evidence'],ensure_ascii=False,indent=2)+'\n```\n\n'
            return Response(text,media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="chat-'+ident+'.md"'})
        return router
