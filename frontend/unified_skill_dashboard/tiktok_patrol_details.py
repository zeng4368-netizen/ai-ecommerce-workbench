"""Five evidence-backed TikTok checks. CLI DOM reads only; no business actions."""
import json, re, time, uuid, threading, hashlib, shutil, tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from tiktok_patrol import today_for, pack
from tiktok_patrol_live import LEASE_SCHEMA

KINDS={'violations':'店铺违规','overdue':'超时发货','reviews':'商品评价','returns':'退货退款与仅退款','wallet':'广告可用信用额度'}

def review_day(text):
    months={'janeiro':1,'fevereiro':2,'março':3,'abril':4,'maio':5,'junho':6,'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12}
    m=re.search(r'(\d{1,2}) de (\w+) de (\d{4})',text)
    if m and m[2] in months:return date(int(m[3]),months[m[2]],int(m[1])).isoformat()
    for fmt in ('%B %d, %Y','%b %d, %Y','%m/%d/%Y','%d/%m/%Y','%Y-%m-%d'):
        try:return datetime.strptime(text.splitlines()[0],fmt).date().isoformat()
        except ValueError:pass
    raise ValueError('评价日期格式变化，未归入日报')

def split_orders(text):
    parts=re.split(r'订单 ID\s*:\s*(\d{10,})',text)
    return [{'order_id':parts[i],'text':parts[i+1].strip()} for i in range(1,len(parts),2)]

def parse_violation(text, vid):
    detail=text.split('违规详情ID:')[-1]
    if vid not in detail:raise ValueError('违规详情与列表 ID 不符')
    reason=detail.split('违规原因\n')[-1].split('\n违规详情')[0]
    prod=re.search(r'\n商品\n\n(.*?)\n\n商品 ID:\s*(\d+)',detail,re.S)
    period=re.search(r'开始日期：(\d{2}/\d{2}/\d{4}), 结束日期：(\d{2}/\d{2}/\d{4})',detail)
    # Keep complete raw detail even for other punishment structures.
    return {'violation_id':vid,'reason':reason if '违规原因\n' in detail else '',
            'product':prod[1] if prod else '', 'product_id':prod[2] if prod else '',
            'start':datetime.strptime(period[1],'%m/%d/%Y').date().isoformat() if period else '',
            'end':datetime.strptime(period[2],'%m/%d/%Y').date().isoformat() if period else '',
            'text':detail.split('你可采取的行动')[0].strip()}

class DetailRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    store_id:str
    start:date|None=None
    end:date|None=None

class DetailPatrol:
    def __init__(self,live):self.live=live;self.patrol=live.patrol
    def config(self):return yaml.safe_load(self.patrol.selectors.read_text(encoding='utf8'))['tiktok_patrol_details']
    def schema(self,con):
        con.execute(LEASE_SCHEMA)
        con.execute('CREATE TABLE IF NOT EXISTS tiktok_detail_runs(id TEXT PRIMARY KEY,value TEXT NOT NULL)')
    def save(self,job):
        with self.live.db() as con:
            self.schema(con);con.execute('INSERT OR REPLACE INTO tiktok_detail_runs VALUES(?,?)',(job['id'],pack(job)))
    def runs(self):
        with self.live.db() as con:
            self.schema(con);return [json.loads(r[0]) for r in con.execute('SELECT value FROM tiktok_detail_runs ORDER BY rowid DESC')]
    def create(self,request,start_thread=True):
        stores=list(self.live.recipe()['reviewed_store_ids']) if request.store_id=='all' else [request.store_id]
        for sid in stores:self.patrol.store(sid)
        if (request.start is None)!=(request.end is None):raise HTTPException(422,'开始和结束日期必须一起选择')
        if request.start and (request.start>request.end or (request.end-request.start).days>365):raise HTTPException(422,'日期范围需为 1—366 天')
        for sid in stores:
            if request.end and request.end>today_for(self.patrol.store(sid)):raise HTTPException(422,'不能读取未来日期')
        ident=uuid.uuid4().hex
        job={'id':ident,'state':'running','created_at':datetime.now(timezone.utc).isoformat(),'items':[], 'step':'准备五项巡检','events':[],
             'recipe_version':self.config()['version']}
        for sid in stores:
            store=self.patrol.store(sid);yesterday=today_for(store)-timedelta(days=1)
            job['items'].append({'store_id':sid,'shop':store['shop'],'start':str(request.start or yesterday),'end':str(request.end or yesterday),'sections':{},'errors':{}})
        with self.live.db() as con:
            self.schema(con);con.commit();con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM ziniao_browser_lease WHERE expires>?',(time.time(),)).fetchone():raise HTTPException(409,'紫鸟正在执行其他采集，请稍后重试')
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='ziniao_runs'").fetchone() and con.execute("SELECT 1 FROM ziniao_runs WHERE state='running'").fetchone():raise HTTPException(409,'报表采集正在运行')
            for row in con.execute('SELECT value FROM tiktok_detail_runs').fetchall():
                old=json.loads(row[0])
                if old['state']=='running':old['state']='interrupted';con.execute('UPDATE tiktok_detail_runs SET value=? WHERE id=?',(pack(old),old['id']))
            con.execute('INSERT OR REPLACE INTO ziniao_browser_lease VALUES(1,?,?)',(ident,time.time()+180))
            con.execute('INSERT INTO tiktok_detail_runs VALUES(?,?)',(ident,pack(job)))
        if start_thread:threading.Thread(target=self.execute,args=(job,),daemon=True).start()
        return job
    def execute(self,job):
        try:
            if not self.live.bridge.check()['ready']:raise ValueError('紫鸟连接或授权检查未通过')
            for item in job['items']:
                self.live.bridge.run(['store','open','--id',item['store_id'],'--expected-name',item['shop']])
                reader=DetailReader(self,job,item)
                for kind in KINDS:
                    job['step']=item['shop']+' · '+KINDS[kind];self.save(job)
                    try:
                        for attempt in range(2):
                            try:
                                payload=reader.capture(kind);break
                            except HTTPException as error:
                                if error.status_code==401 or attempt:raise
                            except Exception:
                                if attempt:raise
                            job['events'].append(item['shop']+' · '+KINDS[kind]+'：页面未稳定，重新读取一次')
                        payload.update(captured_at=datetime.now(timezone.utc).isoformat(),complete=True,store_id=item['store_id'],day=today_for(self.patrol.store(item['store_id'])).isoformat())
                        folder=self.patrol.hub.data/'raw/ai_workbench/tiktok_details'/job['id'];folder.mkdir(parents=True,exist_ok=True)
                        path=folder/(item['store_id']+'-'+kind+'.json');raw=pack(payload).encode();path.write_bytes(raw)
                        payload['sha256']=hashlib.sha256(raw).hexdigest();item['sections'][kind]=payload
                    except Exception as err:
                        item['errors'][kind]=getattr(err,'detail',str(err))[:350]
                        try:
                            evidence=reader.read('({url:location.href,text:document.body.innerText})')
                            folder=self.patrol.hub.data/'raw/ai_workbench/tiktok_details'/job['id'];folder.mkdir(parents=True,exist_ok=True)
                            (folder/(item['store_id']+'-'+kind+'-error.json')).write_text(pack(evidence),encoding='utf8')
                        except Exception:pass
                        if isinstance(err,HTTPException) and err.status_code==401:
                            for remaining in KINDS:
                                if remaining not in item['sections'] and remaining not in item['errors']:item['errors'][remaining]='店铺登录或身份核验中断，未继续读取'
                            break
                    self.save(job)
            job['state']='complete' if all(len(x['sections'])==5 for x in job['items']) else 'partial'
            job['step']='五项巡检结束'
        except Exception as err:job['state']='partial';job['step']=getattr(err,'detail',str(err))[:350]
        finally:
            self.save(job)
            with self.live.db() as con:con.execute('DELETE FROM ziniao_browser_lease WHERE owner=?',(job['id'],))
    def router(self):
        router=APIRouter(prefix='/api/hub/tiktok-details')
        @router.get('/status')
        def status(store_id:str='all'):
            runs=self.runs()
            with self.live.db() as con:
                lease=con.execute('SELECT owner FROM ziniao_browser_lease WHERE expires>?',(time.time(),)).fetchone()
            for run in runs:
                if run['state']=='running' and (not lease or lease[0]!=run['id']):run['state']='interrupted'
            return {'runs':[r for r in runs if store_id=='all' or any(i['store_id']==store_id for i in r['items'])], 'labels':KINDS}
        @router.post('/runs')
        def create(request:DetailRequest):return self.create(request)
        return router

class DetailReader:
    def __init__(self,service,job,item):
        self.service=service;self.live=service.live;self.job=job;self.item=item;self.sid=item['store_id'];self.target=None
        self.config=service.config();self.s=self.config['selectors'];self.recipe=self.live.store_recipe(self.sid)
    def cmd(self,mode,*args):
        self.live.renew(self.job['id'])
        return self.live.bridge.run(['page',mode,'--store-id',self.sid]+(['--target-id',self.target] if self.target else [])+list(args))
    def read(self,expression):
        r=self.cmd('exec','--script','JSON.stringify('+expression+')')
        if r.get('exceptionDetails'):raise ValueError('页面读取失败')
        self.target=r.get('targetId',self.target)
        value=r.get('result')
        if isinstance(value,str):return json.loads(value)
        if isinstance(value,dict) and value.get('type')=='undefined':return None
        return value
    def click(self,selector):
        # A command can time out after the actual click. Every caller checks the result state.
        try:self.cmd('click','--selector',selector)
        except HTTPException as err:
            if err.status_code==401:raise
            self.job['events'].append('点击返回未确认，核验页面状态：'+selector)
        time.sleep(.5)
    def pick(self,selector,text=None,index=0,contains=False):
        expression='(()=>{const a=[...document.querySelectorAll('+json.dumps(selector)+')].filter(e=>e.getClientRects().length'+('&&(e.innerText||e.textContent||"").trim()'+('.includes('+json.dumps(text)+')' if contains else '==='+json.dumps(text)) if text is not None else '')+');const e=a['+str(index)+'];if(!e)return null;let parts=[];for(let p=e;p&&p.tagName!=="HTML";p=p.parentElement){parts.unshift(p.tagName.toLowerCase()+":nth-child("+([...p.parentElement.children].indexOf(p)+1)+")")}return parts.join(" > ")})()'
        path=self.wait(expression)
        if not path:raise ValueError('未找到预期控件：'+str(text or selector))
        self.click(path)
    def wait(self,expression,predicate=lambda x:bool(x)):
        for _ in range(15):
            v=self.read(expression)
            if predicate(v):return v
            time.sleep(1)
        raise ValueError('页面状态未通过核验，请稍后重试')
    def identity(self):
        q=json.dumps(self.recipe['identity_selector']);challenge=json.dumps(self.recipe['challenge_selector'])
        v=self.wait('({url:location.href,identity:[...document.querySelectorAll('+q+')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),challenge:[...document.querySelectorAll('+challenge+')].some(e=>e.getClientRects().length)})',lambda v:bool(v['identity']) or v['challenge'] or 'login' in v['url'])
        if v['challenge'] or urlsplit(v['url']).hostname!=self.recipe['allowed_host'] or v['identity']!=[self.recipe['expected_identity']]:raise HTTPException(401,'店铺身份不符或需要登录/验证码，已停止此项')
    def visit(self,url,wallet=False):
        # Bind the current tab before navigating; CLI defaults can otherwise pick a different open tab.
        if not self.target:self.read('location.href')
        try:self.cmd('visit','--url',url,'--wait-until','domcontentloaded','--timeout','20000')
        except HTTPException as err:
            if err.status_code==401:raise
        self.wait('location.href',lambda v:urlsplit(v).hostname==urlsplit(url).hostname and urlsplit(v).path==urlsplit(url).path)
        if not wallet:self.identity()
    def dates(self,opener,kind):
        self.pick(opener,'日期',contains=True) if kind=='violations' else self.pick(opener)
        for day in (date.fromisoformat(self.item['start']),date.fromisoformat(self.item['end'])):
            expected=f'{day.year}年-{day.month}月'
            for _ in range(24):
                headers=self.read('[...document.querySelectorAll('+json.dumps(self.s['calendar_header'])+')].filter(e=>e.getClientRects().length).map(e=>e.innerText)')
                if expected in headers:break
                match=re.search(r'(\d+)年-(\d+)月',headers[0] if headers else '')
                if not match:raise ValueError('日期控件月份无法识别')
                before=(int(match[1]),int(match[2]))>(day.year,day.month)
                self.pick(self.s['calendar_previous' if before else 'calendar_next'])
            else:raise ValueError('日期范围超过日历导航限制')
            p=self.s['calendar_panel'];c=self.s['calendar_cell'];h=self.s['calendar_header']
            expression='(()=>{const panels=[...document.querySelectorAll('+json.dumps(p)+')].filter(e=>e.getClientRects().length);const panel=panels.find(e=>e.querySelector('+json.dumps(h)+')?.innerText==='+json.dumps(expected)+');const e=[...panel.querySelectorAll('+json.dumps(c)+')].find(e=>Number(e.innerText)==='+str(day.day)+');if(!e)return null;let a=[];for(let p=e;p&&p.tagName!=="HTML";p=p.parentElement)a.unshift(p.tagName.toLowerCase()+":nth-child("+([...p.parentElement.children].indexOf(p)+1)+")");return a.join(" > ")})()'
            path=self.wait(expression)
            if not path:raise ValueError('日期不可选')
            self.click(path)
        expected=[date.fromisoformat(self.item[k]).strftime('%m/%d/%Y') for k in ('start','end')]
        if kind=='reviews':self.wait('[...document.querySelectorAll('+json.dumps(self.s['date_values'])+')].map(e=>e.value)',lambda v:v==expected)
        else:self.wait('document.body.innerText',lambda t:'日期: '+'-'.join(expected) in t)
    def screenshot(self,kind,page):
        folder=self.service.patrol.hub.data/'screenshots/ai_workbench/tiktok_details'/self.job['id'];folder.mkdir(parents=True,exist_ok=True)
        dest=folder/f'{self.sid}-{kind}-{page}.png'
        try:
            r=self.cmd('screenshot','--path',str(dest));src=Path(r.get('filePath',dest)).resolve()
            allowed=(Path(tempfile.gettempdir())/'ziniao-zclaw-screenshots').resolve()
            if not dest.exists() and src.is_relative_to(allowed) and src.read_bytes().startswith(b'\x89PNG'):shutil.copy2(src,dest)
            return str(dest) if dest.exists() else ''
        except Exception:return ''
    def capture(self,kind):
        self.kind=kind
        if kind=='wallet':return self.wallet()
        self.visit('https://'+self.recipe['allowed_host']+self.config['paths'][kind])
        if kind in ('violations','reviews'):
            if kind=='violations':self.pick(self.s['violation_tab'],'违规记录')
            self.dates(self.s['violation_date' if kind=='violations' else 'review_date'],kind)
        if kind=='overdue':
            self.pick(self.s['overdue'],'备货超时',contains=True)
            self.wait('location.href',lambda v:'urgency[]=103' in v)
        if kind=='returns':
            self.pick(self.s['return_tab'],'等待 TikTok Shop/客户处理',contains=True)
            self.wait('[...document.querySelectorAll('+json.dumps(self.s['return_selected'])+')].map(e=>e.innerText).join("")',lambda v:'等待 TikTok Shop/客户处理' in v)
        rows=[];screens=[];seen=set();total=None
        for page in range(1,101):
            self.identity()
            if kind=='reviews':
                q=json.dumps(self.s)
                r=self.wait('(()=>{const s='+q+';return {total:document.body.innerText.match(/(\\d+) 个评分/)?.[1],rows:[...document.querySelectorAll(s.review_cards)].map(e=>{const t=k=>e.querySelector(s[k])?.innerText||"";return {stars:e.querySelectorAll(s.review_stars).length,rating:t("review_rating"),reply:t("review_reply"),order:t("review_order"),product_id:t("review_product_id"),product:t("review_product"),sku:t("review_sku"),user:t("review_user"),text:e.innerText}})}})()',lambda r:r['total'] is not None and (bool(r['rows']) or r['total']=='0'))
                total=int(r['total']);current=r['rows']
                for row in current:
                    row['day']=review_day(row['rating'])
                    if not self.item['start']<=row['day']<=self.item['end'] or not 1<=row['stars']<=5:raise ValueError('评价日期/星级不符')
            elif kind=='violations':
                current=self.read('[...document.querySelectorAll('+json.dumps(self.s['violation_rows'])+')].filter(e=>/ID:\\s*\\d+/.test(e.innerText)).map(e=>({text:e.innerText}))')
                if not current:
                    self.wait('document.body.innerText',lambda t:any(x in t for x in ['暂无搜索结果','暂无数据','暂无违规','没有违规','无数据']))
                    total=0;screens.append(self.screenshot(kind,page))
                for row in current:
                    vid=re.search(r'ID:\s*(\d+)',row['text'])[1];d=re.search(r'\d{2}/\d{2}/\d{4}',row['text'])
                    if not d:raise ValueError('违规日期缺失')
                    row['day']=datetime.strptime(d[0],'%m/%d/%Y').date().isoformat()
                    if not self.item['start']<=row['day']<=self.item['end']:raise ValueError('违规日期筛选不符')
                    # Select only the row containing this ID, then its detail button.
                    selector=self.read('(()=>{const e=[...document.querySelectorAll("tbody tr")].find(e=>e.innerText.includes('+json.dumps(vid)+'));return "tbody tr:nth-child("+([...e.parentElement.children].indexOf(e)+1)+") button"})()')
                    self.click(selector)
                    detail=self.wait('document.body.innerText',lambda t:'违规详情ID:' in t and vid in t.split('违规详情ID:')[-1] and '违规原因' in t.split('违规详情ID:')[-1])
                    row.update(parse_violation(detail,vid));screens.append(self.screenshot(kind,vid))
                    self.pick(self.s['detail_close']);self.wait('!!document.querySelector('+json.dumps(self.s['detail_close'])+')',lambda v:not v)
            else:
                if kind=='overdue':
                    for _ in range(100):
                        count=self.read('[...document.querySelectorAll('+json.dumps(self.s['order_expand'])+')].filter(e=>e.innerText.includes("再显示")).length')
                        if not count:break
                        self.pick(self.s['order_expand'],'再显示',contains=True)
                    text=self.read('document.querySelector("table")?.innerText||""')
                    totaltext=self.read('document.body.innerText');m=re.search(r'找到\s*(\d+)\s*个订单',totaltext)
                    if not m:raise ValueError('订单结果总数缺失')
                    total=int(m[1]);current=split_orders(text)
                else:
                    loaded=self.wait('({text:document.querySelector("table")?.innerText||"",empty:document.body.innerText.includes("暂无工单")})',lambda v:bool(v['text']) or v['empty'])
                    current=split_orders(loaded['text'])
                    selected=self.read('document.querySelector('+json.dumps(self.s['return_selected'])+').innerText')
                    count_match=re.search(r'\d+',selected)
                    if not count_match and not loaded['empty']:raise ValueError('售后总数未核验')
                    total=int(count_match[0]) if count_match else 0
                    if not current and total:
                        current=split_orders(self.wait('document.querySelector("table")?.innerText||""',lambda text:bool(split_orders(text))))
                    for index,row in enumerate(current):
                        self.pick(self.s['return_products'],index=index)
                        row['products']=self.wait('[...document.querySelectorAll('+json.dumps(self.s['popover'])+')].filter(e=>e.getClientRects().length && /^\\d+\\s*件商品/.test(e.innerText.trim())).map(e=>e.innerText)',lambda v:len(v)==1)[0]
                        self.pick(self.s['return_products'],index=index)
                        row['type']='仅退款' if row['text'].split('\n\n')[-1].startswith('仅退款') else ('仅退款' if '\n仅退款\n' in '\n'+row['text']+'\n' else '退货退款')
                for row in current:row['day']=today_for(self.service.patrol.store(self.sid)).isoformat()
            signature=hashlib.sha256(pack(current).encode()).hexdigest()
            if current and signature in seen:raise ValueError('分页重复，未标记完整')
            seen.add(signature);rows+=current
            if kind!='violations':screens.append(self.screenshot(kind,page))
            nxt=self.s['order_next' if kind=='overdue' else 'next'];pg=self.s['order_page' if kind=='overdue' else 'page']
            state=self.read('({page:document.querySelector('+json.dumps(pg)+')?.innerText,next:document.querySelector('+json.dumps(nxt)+')?.className})')
            if not state.get('next'):
                if total==0:break
                raise ValueError('分页完整性未核验')
            if 'disabled' in state['next']:break
            old=state['page'];self.pick(nxt);self.wait('document.querySelector('+json.dumps(pg)+')?.innerText',lambda v:v and v!=old)
        else:raise ValueError('超过分页限制；保留失败状态')
        if total is not None and len(rows)!=total:raise ValueError(f'条数不一致：读取 {len(rows)} / 页面 {total}')
        self.identity()
        return {'rows':rows,'count':len(rows),'start':self.item['start'],'end':self.item['end'],'scope':'按日期新增记录' if kind in ('reviews','violations') else ('等待 TikTok Shop/客户处理' if kind=='returns' else '当前备货超时订单'),'source_url':self.read('location.href'),'screenshots':screens}
    def wallet(self):
        account=self.config['wallet_accounts'].get(self.sid)
        if not account:raise ValueError('此店铺尚未绑定广告付款账号，未套用其他店铺余额')
        self.visit(account['url'],wallet=True)
        self.wait('document.body.innerText',lambda t:account['account'] in t and '可用信用额度' in t)
        if self.read('location.href')!=account['url']:raise ValueError('广告付款账号 URL 不符')
        q=json.dumps(self.s)
        values=self.read('(()=>{const s='+q+';return [...document.querySelectorAll(s.wallet_blocks)].filter(e=>e.querySelector(s.wallet_label)?.innerText==="可用信用额度").map(e=>({label:"可用信用额度",value:e.querySelector(s.wallet_amount)?.innerText,currency:e.querySelector(s.wallet_currency)?.innerText}))})()')
        if len(values)!=1 or not re.fullmatch(r'[\d,]+\.\d{2}',values[0]['value']):raise ValueError('广告信用额度格式变化')
        values[0]['value']=float(values[0]['value'].replace(',',''));values[0]['day']=today_for(self.service.patrol.store(self.sid)).isoformat()
        return {'rows':values,'count':1,'source_url':account['url'],'account':account['account'],'scope':'当前可用信用额度','screenshots':[self.screenshot('wallet',1)]}
