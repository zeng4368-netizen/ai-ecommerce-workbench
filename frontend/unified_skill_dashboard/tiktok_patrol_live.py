"""Store-scoped page reads and serialized patrol batches; no business mutations."""
import copy
import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from tiktok_patrol import pack, today_for
from ziniao_bridge import Bridge, load_stores
from tiktok_patrol_history import daily_history, history_csv


LEASE_SCHEMA = '''CREATE TABLE IF NOT EXISTS ziniao_browser_lease(
 id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT NOT NULL,expires REAL NOT NULL)'''


class LiveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    store_id: str
    confirmed: bool = False


def number(text, prefix='', suffix=''):
    raw = re.sub(r'\s+', '', text)
    if prefix:
        if not raw.startswith(prefix):raise HTTPException(409,'货币符号变化，停止解析')
        raw=raw[len(prefix):]
    if suffix:
        if not raw.endswith(suffix):raise HTTPException(409,'货币单位变化，停止解析')
        raw=raw[:-len(suffix)]
    if not re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?',raw):
        raise HTTPException(409,'指标不是完整数字，不解析缩略值或缺失值')
    value=float(raw.replace(',',''))
    if value>1e15:raise HTTPException(409,'指标超出有效范围')
    return value


def parse_cards(payload, recipe, kind, day):
    expected=day.strftime(recipe['date_format'])
    if payload['dates'] != [expected,expected]:
        raise HTTPException(409,'页面尚未应用昨日日期，未读取为日报')
    cards=payload['cards']
    if [c['label'] for c in cards]!=recipe['labels']:
        raise HTTPException(409,'页面指标集合或顺序变化，需要重新核验')
    if kind=='ads' and (not payload['account_ok'] or not payload['timezone_ok']):
        raise HTTPException(409,'广告账号或时区与已核验配置不一致')
    result=[]
    for c in cards:
        money=(kind=='sales' and c['label']=='GMV') or (kind=='ads' and c['label'] in ('成本','总收入','平均下单成本'))
        value=number(c['value'],recipe.get('money_prefix','') if money else '',recipe.get('money_suffix','') if money else '')
        change=None
        if c['change']:
            if re.fullmatch(r'-?\d+(?:\.\d+)?%',c['change']) and (c['up'] != c['down']):
                change=abs(float(c['change'][:-1]))*(1 if c['up'] else -1)
        result.append({'label':c['label'],'value':value,'currency':recipe['currency'] if money else '',
                       'change_pct':change,'change_note':'平台比较窗口展示；不反推原始基数'})
    return result


def parse_home(payload, recipe):
    cards=payload['cards']
    if len(cards)!=len(recipe['labels']):raise HTTPException(409,'首页待办卡片数量变化')
    output=[]
    for raw,label in zip(cards,recipe['labels']):
        lines=[x.strip() for x in raw.splitlines() if x.strip()]
        if len(lines)<2 or lines[0]!=label:raise HTTPException(409,'首页待办结构变化')
        count=number(lines[1])
        if not count.is_integer():raise HTTPException(409,'待办数量必须为整数')
        output.append({'label':label,'value':count,'detail':'；'.join(lines[2:]),'raw':raw})
    if not payload['health'] or len(payload['health'])!=1:
        raise HTTPException(409,'店铺健康状态未唯一定位')
    return {'cards':output,'health':payload['health'][0],
            'scope':'当前首页待办快照；紧急不等于超时，差评不是昨日新增，库存为平台提醒数量而非 SKU 可售件数。'}


def findings(sections):
    """Attention queue from explicit platform reminders, not invented SLA/thresholds."""
    items=[]
    home=sections.get('homepage',{}).get('data',{})
    for card in home.get('cards',[]):
        label=card['label']
        if card['value'] or re.search(r'：\s*[1-9]',card['detail']):
            action={'待发货':'查看平台紧急订单及实际发货截止时间，安排仓库跟进。',
                    '待退货':'核对紧急售后和截止时间，准备人工处理队列。',
                    '被拒商品':'核对商品被拒原因及资料，准备修正建议。',
                    '低库存':'检查平台缺货和低库存商品清单，核对在途与可售库存。',
                    '差评':'查看评价原文及时间范围，区分商品问题，先拟处理建议。'}[label]
            items.append({'priority':'P1' if label in ('待发货','待退货','低库存') else 'P2',
                          'title':label,'reason':f"首页显示 {card['value']:g}；{card['detail']}", 'action':action,'source':'homepage'})
    if home.get('health') and '有待改进' in home['health']:
        items.insert(0,{'priority':'P1','title':'店铺健康需跟进','reason':home['health'],
                        'action':'进入账号健康核对三项未达标指标与具体要求；此处不自动申诉或修改设置。','source':'homepage'})
    return items


class LivePatrol:
    def __init__(self, patrol):
        self.patrol=patrol
        self.bridge=Bridge(patrol.selectors)

    def recipe(self):
        return (yaml.safe_load(self.patrol.selectors.read_text(encoding='utf-8')) or {}).get('tiktok_patrol_live',{})

    def store_recipe(self, store_id):
        recipe=copy.deepcopy(self.recipe())
        override=recipe.get('store_profiles',{}).get(store_id)
        if override:
            for key,value in override.items():
                if isinstance(value,dict):recipe[key].update(value)
                else:recipe[key]=value
        elif store_id not in recipe.get('reviewed_store_ids',[]):
            raise HTTPException(409,'此店铺尚未配置巡检页面')
        return recipe

    def db(self):
        return self.patrol.db()

    @staticmethod
    def schema(con):
        con.execute(LEASE_SCHEMA)
        con.execute('CREATE TABLE IF NOT EXISTS tiktok_patrol_live_runs(id TEXT PRIMARY KEY,store_id TEXT NOT NULL,state TEXT NOT NULL,value TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS tiktok_patrol_live_batches(id TEXT PRIMARY KEY,value TEXT NOT NULL)')

    def get(self, ident):
        with self.db() as con:
            self.schema(con)
            row=con.execute('SELECT value FROM tiktok_patrol_live_runs WHERE id=?',(ident,)).fetchone()
        if not row:raise HTTPException(404,'实时巡检不存在')
        return json.loads(row[0])

    def save(self, value):
        with self.db() as con:
            con.execute('UPDATE tiktok_patrol_live_runs SET state=?,value=? WHERE id=?',(value['state'],pack(value),value['id']))

    def renew(self, ident):
        with self.db() as con:
            cur=con.execute('UPDATE ziniao_browser_lease SET expires=? WHERE id=1 AND owner=? AND expires>?',(time.time()+180,ident,time.time()))
            if cur.rowcount!=1:raise HTTPException(409,'浏览器运行租约已失效，停止本次巡检')

    def create(self, store_id, start=True, batch_id=None):
        store=self.patrol.store(store_id)
        recipe=self.store_recipe(store_id)
        ident=uuid.uuid4().hex
        value={'id':ident,'store_id':store_id,'shop':store['shop'],'currency':store['currency'],'timezone':store['timezone'],
               'day':(today_for(store)-timedelta(days=1)).isoformat(),'created_at':datetime.now(timezone.utc).isoformat(),
               'state':'running','step':'检查紫鸟连接','sections':{},'error':'','events':[],'recipe_version':recipe['version'],
               'recipe_sha256':hashlib.sha256(pack(recipe).encode()).hexdigest(),
               'scope':'昨日销售概览、昨日广告概览，以及当前首页待办/库存/健康快照。未读取 SKU 全量明细、昨日新增差评或站内信。'}
        value['section_days']={kind:(today_for({**store,'timezone':recipe[kind].get('timezone',store['timezone'])})-timedelta(days=1)).isoformat()
                               for kind in ('sales','ads')}
        if batch_id:value['batch_id']=batch_id
        with self.db() as con:
            self.schema(con)
            con.commit()
            con.execute('BEGIN IMMEDIATE')
            lease=con.execute('SELECT owner FROM ziniao_browser_lease WHERE id=1 AND expires>?',(time.time(),)).fetchone()
            exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ziniao_runs'").fetchone()
            exporting=exists and con.execute("SELECT 1 FROM ziniao_runs WHERE state='running'").fetchone()
            if (lease and lease[0]!=batch_id) or exporting:raise HTTPException(409,'紫鸟正在执行其他采集，请等待完成后再试')
            # Interrupted reads never resume automatically. Preserve partial sections.
            for row in con.execute("SELECT value FROM tiktok_patrol_live_runs WHERE state='running'").fetchall():
                old=json.loads(row[0]);old.update(state='interrupted',step='已中断',error='上次进程或运行租约已结束；可手动新建巡检。')
                con.execute('UPDATE tiktok_patrol_live_runs SET state=?,value=? WHERE id=?',('interrupted',pack(old),old['id']))
            con.execute('INSERT OR REPLACE INTO ziniao_browser_lease VALUES(1,?,?)',(ident,time.time()+180))
            con.execute('INSERT INTO tiktok_patrol_live_runs VALUES(?,?,?,?)',(ident,store_id,'running',pack(value)))
        if start:threading.Thread(target=self.execute,args=(ident,),daemon=True,name='tiktok-readonly-patrol').start()
        return value

    def execute(self, ident):
        job=self.get(ident);recipe=self.store_recipe(job['store_id']);target=None
        folder=self.patrol.hub.data/'raw/ai_workbench/tiktok_patrol_live'/ident
        shots=self.patrol.hub.data/'screenshots/ai_workbench/tiktok_patrol_live'/ident
        def event(text):
            job['step']=text;job['events'].append({'at':datetime.now(timezone.utc).isoformat(),'step':text});self.save(job)
        def command(args):
            self.renew(ident)
            if args[0]=='page':
                args=args+['--store-id',job['store_id']]+(['--target-id',target] if target else [])
            return self.bridge.run(args)
        def read(expression):
            nonlocal target
            value=command(['page','exec','--script','JSON.stringify('+expression+')'])
            if value.get('exceptionDetails'):raise HTTPException(409,'页面读取失败')
            if not target:target=value.get('targetId')
            try:return json.loads(value['result'])
            except (KeyError,TypeError,ValueError):raise HTTPException(409,'页面返回结构变化') from None
        def texts(selector):
            return read('[...document.querySelectorAll('+json.dumps(selector)+')].filter(e=>e.getClientRects().length).map(e=>(e.innerText||e.textContent||"" ).trim())')
        def identity():
            for attempt in range(15):
                value=read('({url:location.href,identity:[...document.querySelectorAll('+json.dumps(recipe['identity_selector'])+')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),challenge:[...document.querySelectorAll('+json.dumps(recipe['challenge_selector'])+')].some(e=>e.getClientRects().length>0)})')
                if value['challenge'] or any(x in urlsplit(value['url']).path.lower() for x in ('login','captcha','verify')):
                    raise HTTPException(401,'出现登录、验证码或二次验证，请在紫鸟内处理后重新巡检')
                if value['identity'] or urlsplit(value['url']).hostname!=recipe['allowed_host']:break
                time.sleep(1)
            if urlsplit(value['url']).hostname!=recipe['allowed_host'] or value['identity']!=[recipe['expected_identity']]:
                raise HTTPException(401,'页面店铺身份或域名不符，已停止巡检')
            return value['url']
        def click(selector, expected=None):
            identity();values=texts(selector)
            if len(values)!=1 or (expected is not None and values[0]!=expected):
                raise HTTPException(409,'日期控件不唯一或文案变化，不点击其他按钮')
            command(['page','click','--selector',selector])
        def capture(kind):
            p=recipe[kind]
            identity()
            command(['page','visit','--url',p['url'],'--wait-until','domcontentloaded','--timeout','20000'])
            # Wait for actual identity and required elements, never assume navigation equals ready.
            for attempt in range(12):
                current=identity()
                if urlsplit(current).path==urlsplit(p['url']).path and texts(p['cards']):break
                time.sleep(1)
            else:raise HTTPException(409,'业务页面或指标尚未加载，请稍后再试')
            if kind!='homepage':
                click(p['date_open']);click(p['yesterday'],p['yesterday_text'])
            previous=None;stable=0
            for attempt in range(15):
                identity()
                if kind=='homepage':
                    payload={'cards':texts(p['cards']),'health':texts(p['health'])}
                    normalized=parse_home(payload,p)
                else:
                    q=json.dumps(p)
                    payload=read('(()=>{const p='+q+';return {dates:[p.start,p.end].map(s=>document.querySelector(s)?.value),account_ok:!p.account_text||document.body.innerText.includes(p.account_text),timezone_ok:!p.timezone_text||document.body.innerText.includes(p.timezone_text),cards:[...document.querySelectorAll(p.cards)].map(e=>({label:e.querySelector(p.label)?.innerText?.trim(),value:e.querySelector(p.value)?.textContent?.trim(),change:e.querySelector(p.change)?.innerText?.trim()||"",up:!!e.querySelector(p.up),down:!!e.querySelector(p.down)}))}})()')
                    try:normalized=parse_cards(payload,p,kind,datetime.fromisoformat(job.get('section_days',{}).get(kind,job['day'])).date())
                    except HTTPException:
                        if attempt==14:raise
                        time.sleep(1);continue
                signature=pack(payload)
                stable=stable+1 if signature==previous else 0
                previous=signature
                if stable>=2:break
                time.sleep(2)
            else:raise HTTPException(409,'指标未稳定，未保存为成功结果')
            evidence={'url':identity(),'captured_at':datetime.now(timezone.utc).isoformat(),'payload':payload}
            raw=pack(evidence).encode();(folder/(kind+'.json')).write_bytes(raw)
            screenshot_status='unavailable'
            try:
                destination=shots/(kind+'.png')
                receipt=command(['page','screenshot','--path',str(destination)])
                if not destination.is_file() and receipt.get('filePath'):
                    origin=Path(receipt['filePath']).resolve()
                    allowed=(Path(tempfile.gettempdir())/'ziniao-zclaw-screenshots').resolve()
                    if origin.is_relative_to(allowed) and origin.suffix.lower()=='.png' and origin.is_file() and origin.stat().st_size<10*1024*1024:
                        if origin.read_bytes()[:8]==b'\x89PNG\r\n\x1a\n':shutil.copyfile(origin,destination)
                if destination.is_file():screenshot_status='saved'
            except (HTTPException,OSError):pass
            result={'data':normalized,'source_url':evidence['url'],'captured_at':evidence['captured_at'],
                    'sha256':hashlib.sha256(raw).hexdigest(),'screenshot':screenshot_status,
                    'period':'采集时的当前快照' if kind=='homepage' else job.get('section_days',{}).get(kind,job['day']),
                    'timezone':p.get('timezone',job['timezone']),
                    'currency':p.get('currency',job['currency'])}
            if kind!='homepage':result['note']='店铺级概览；不等同于 SKU 或广告计划逐条诊断。平台显示的变化率保留原口径。'
            return result
        try:
            folder.mkdir(parents=True,exist_ok=False);shots.mkdir(parents=True,exist_ok=False)
            if hashlib.sha256(pack(recipe).encode()).hexdigest()!=job['recipe_sha256']:
                raise HTTPException(409,'配方发生变化，需重新新建巡检')
            check=self.bridge.check()
            if not check['ready']:raise HTTPException(401,check['message'])
            event('核验 '+job['shop']+' 身份')
            resolved=command(['store','resolve','--id',job['store_id'],'--expected-name',job['shop']])
            if resolved.get('matched') is not True or resolved.get('storeId')!=job['store_id']:
                raise HTTPException(401,'店铺匹配结果不符')
            command(['store','open','--id',job['store_id'],'--expected-name',job['shop'],'--url',recipe['homepage']['url']])
            for kind,label in [('homepage','读取当前待办、库存和健康'),('sales','读取昨日销售概览'),('ads','读取昨日广告概览（USD）')]:
                if kind=='ads' and not recipe['ads'].get('account_text'):
                    job.setdefault('section_errors',{})['ads']='广告账号尚未核验，未读取广告数据'
                    continue
                event(label)
                job['sections'][kind]=capture(kind);self.save(job)
            job.update(state='partial' if job.get('section_errors') else 'complete',step='部分完成' if job.get('section_errors') else '只读巡检完成')
        except HTTPException as exc:
            job.update(state='paused',step='已暂停',error=str(exc.detail))
        except Exception:
            job.update(state='paused',step='已暂停',error='本地读取失败，已保存完成部分；未自动重试业务操作。')
        finally:
            job['findings']=findings(job['sections'])
            job['finished_at']=datetime.now(timezone.utc).isoformat()
            job['events'].append({'at':job['finished_at'],'step':job['step'],'error':job['error']})
            self.save(job)
            output=self.patrol.hub.data/'output/ai_workbench/tiktok_patrol_live'/ident
            output.mkdir(parents=True,exist_ok=True)
            (output/'report.json').write_text(pack(job),encoding='utf-8')
            (output/'run.log').write_text(pack(job['events']),encoding='utf-8')
            with self.db() as con:
                if job.get('batch_id'):
                    con.execute('UPDATE ziniao_browser_lease SET owner=?,expires=? WHERE owner=?',(job['batch_id'],time.time()+180,ident))
                else:con.execute('DELETE FROM ziniao_browser_lease WHERE owner=?',(ident,))

    def create_batch(self, store_id, start=True):
        ids=list(load_stores(self.patrol.selectors)) if store_id=='all' else [store_id]
        for sid in ids:self.patrol.store(sid)
        ident=uuid.uuid4().hex
        batch={'id':ident,'state':'running','created_at':datetime.now(timezone.utc).isoformat(),
               'items':[{'store_id':sid,'shop':self.patrol.store(sid)['shop'],'state':'queued'} for sid in ids]}
        with self.db() as con:
            self.schema(con);con.commit();con.execute('BEGIN IMMEDIATE')
            lease=con.execute('SELECT owner FROM ziniao_browser_lease WHERE expires>?',(time.time(),)).fetchone()
            exporting=con.execute("SELECT 1 FROM sqlite_master WHERE name='ziniao_runs'").fetchone()
            if lease or (exporting and con.execute("SELECT 1 FROM ziniao_runs WHERE state='running'").fetchone()):
                raise HTTPException(409,'紫鸟正在执行其他采集，请等待完成后再试')
            con.execute('INSERT OR REPLACE INTO ziniao_browser_lease VALUES(1,?,?)',(ident,time.time()+180))
            con.execute('INSERT INTO tiktok_patrol_live_batches VALUES(?,?)',(ident,pack(batch)))
        if start:threading.Thread(target=self.execute_batch,args=(ident,),daemon=True).start()
        return batch

    def get_batch(self, ident):
        with self.db() as con:
            self.schema(con)
            row=con.execute('SELECT value FROM tiktok_patrol_live_batches WHERE id=?',(ident,)).fetchone()
            if not row:raise HTTPException(404,'批次不存在')
            batch=json.loads(row[0])
            owners=[ident]+[i['run_id'] for i in batch['items'] if i.get('run_id')]
            lease=con.execute('SELECT owner,expires FROM ziniao_browser_lease WHERE id=1').fetchone()
            if lease and lease[0] not in owners:
                child=con.execute('SELECT value FROM tiktok_patrol_live_runs WHERE id=?',(lease[0],)).fetchone()
                if child and json.loads(child[0]).get('batch_id')==ident:owners.append(lease[0])
            if batch['state']=='running' and (not lease or lease[0] not in owners or lease[1]<=time.time()):
                batch['state']='interrupted'
                for item in batch['items']:
                    if item['state'] in ('queued','running'):item.update(state='interrupted',error='进程或租约已结束，请手动重新巡检')
                con.execute('UPDATE tiktok_patrol_live_batches SET value=? WHERE id=?',(pack(batch),ident))
        return batch

    def execute_batch(self, ident):
        batch=self.get_batch(ident)
        def save():
            with self.db() as con:con.execute('UPDATE tiktok_patrol_live_batches SET value=? WHERE id=?',(pack(batch),ident))
        try:
            for item in batch['items']:
                try:
                    self.renew(ident)
                    run=self.create(item['store_id'],start=False,batch_id=ident)
                    item.update(state='running',run_id=run['id']);save()
                    self.execute(run['id'])
                    result=self.get(run['id'])
                    item.update(state=result['state'],error=result.get('error') or '；'.join(result.get('section_errors',{}).values()))
                except HTTPException as exc:item.update(state='paused',error=str(exc.detail))
                except Exception:item.update(state='paused',error='本地巡检失败，已保留记录')
                save()
            batch['state']='complete' if all(i['state']=='complete' for i in batch['items']) else 'partial'
        finally:
            batch['finished_at']=datetime.now(timezone.utc).isoformat();save()
            with self.db() as con:con.execute('DELETE FROM ziniao_browser_lease WHERE owner=?',(ident,))

    def router(self):
        router=APIRouter(prefix='/api/hub/tiktok-patrol/live')
        @router.get('/history')
        def history(store_id:str,start:str,end:str):return daily_history(self,store_id,start,end)
        @router.get('/history.csv')
        def export_history(store_id:str,start:str,end:str):return history_csv(daily_history(self,store_id,start,end))
        @router.post('/batches')
        def batch(body:LiveRequest):
            if not body.confirmed:raise HTTPException(422,'请确认本次巡检')
            return self.create_batch(body.store_id)
        @router.get('/batches/{ident}')
        def batch_detail(ident:str):return self.get_batch(ident)
        @router.get('/status')
        def status(store_id:str):
            if store_id!='all':self.patrol.store(store_id)
            with self.db() as con:
                self.schema(con)
                rows=con.execute('SELECT value FROM tiktok_patrol_live_runs'+(' WHERE store_id=?' if store_id!='all' else '')+' ORDER BY rowid DESC LIMIT 100',(store_id,) if store_id!='all' else ()).fetchall()
                batch_rows=con.execute('SELECT id FROM tiktok_patrol_live_batches ORDER BY rowid DESC LIMIT 5').fetchall()
                lease=con.execute('SELECT owner,expires FROM ziniao_browser_lease WHERE id=1').fetchone()
                runs=[]
                for row in rows:
                    value=json.loads(row[0])
                    if value['state']=='running' and (not lease or lease[0]!=value['id'] or lease[1]<=time.time()):
                        value.update(state='interrupted',step='已中断',error='运行租约已结束，已保留读取结果；可手动重新巡检。')
                        con.execute('UPDATE tiktok_patrol_live_runs SET state=?,value=? WHERE id=?',('interrupted',pack(value),value['id']))
                    runs.append(value)
            return {'ready':store_id=='all' or store_id in self.recipe().get('reviewed_store_ids',[]) or store_id in self.recipe().get('store_profiles',{}),'runs':runs,
                    'batches':[self.get_batch(r[0]) for r in batch_rows],
                    'scope':'读取各店昨日销售、昨日广告和当前首页提醒；按绑定身份、币种和账号时区校验。'}
        @router.post('/runs')
        def create(body:LiveRequest):
            if not body.confirmed:raise HTTPException(422,'请确认本次只读采集')
            return self.create(body.store_id)
        @router.get('/runs/{ident}')
        def detail(ident:str):return self.get(ident)
        @router.get('/runs/{ident}/report')
        def report(ident:str):
            return Response(pack(self.get(ident)),media_type='application/json',headers={'Content-Disposition':'attachment; filename="tiktok-live-patrol.json"'})
        return router
