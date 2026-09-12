"""Verified TikTok MY UI recipes (2026-09-11). All browser IO uses Ziniao CLI.

This is not a general browser or command tool. No model-provided scripts/selectors.
An uncertain submission is resumed from its receipt, never submitted twice.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs
from fastapi import HTTPException

MY = timezone(timedelta(hours=8))

def reject(text): raise HTTPException(409,text)

def order_url(recipe, job):
    start = datetime.fromisoformat(job['start']).replace(tzinfo=MY)
    end = datetime.fromisoformat(job['end']).replace(tzinfo=MY)+timedelta(days=1)
    return recipe['url']+'?'+urlencode({'selected_sort':'6','tab':'all',
        'time_order_created[]':[int(start.timestamp()*1000),int(end.timestamp()*1000)-1]},doseq=True)


class TikTokUI:
    def __init__(self, bridge, profile, job): self.bridge,self.p,self.job=bridge,profile,job

    def read(self, expression):
        v=self.bridge.run(['page','exec','--store-id',self.job['store_id'],'--script','JSON.stringify('+expression+')'])
        if not isinstance(v,dict) or v.get('exceptionDetails'): reject('页面读取失败，未继续导出')
        try: return json.loads(v['result'])
        except (ValueError,KeyError,TypeError): reject('页面读取结构变化，需要重新审核')

    def elements(self, selector):
        return self.read("[...document.querySelectorAll("+json.dumps(selector)+")].filter(e=>e.getClientRects().length).map(e=>({text:e.innerText||e.textContent||'',value:e.value||'',disabled:!!e.disabled,log:e.getAttribute('data-log_json')||''}))")

    def check(self):
        v=self.read("({url:location.href,identity:[...document.querySelectorAll("+json.dumps(self.p['identity_selector'])+")].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),challenge:[...document.querySelectorAll("+json.dumps(self.p['challenge_selector'])+")].some(e=>e.getClientRects().length>0)})")
        if v['challenge'] or any(x in urlsplit(v['url']).path.lower() for x in ('login','captcha','verify')):
            reject('出现登录、验证码或二次验证，请人工完成后恢复')
        if v['identity']!=[self.p['expected_identity']] or urlsplit(v['url']).hostname not in self.p['allowed_hosts']:
            reject('页面店铺身份或域名与绑定不符，停止操作')
        return v['url']

    def click(self, selector, expect=None):
        self.check()
        values=self.elements(selector)
        if len(values)!=1 or values[0]['disabled']: reject('控件不唯一、不可用或页面变化，需要人工检查')
        try:self.bridge.run(['page','click','--store-id',self.job['store_id'],'--selector',selector])
        except HTTPException as exc:
            if exc.status_code!=504 or not expect:raise
            self.check()
            if not self.elements(expect):raise

    def visit(self,url):
        current=urlsplit(self.check());target=urlsplit(url)
        if current.path==target.path and parse_qs(current.query)==parse_qs(target.query):return
        self.bridge.run(['page','visit','--store-id',self.job['store_id'],'--url',url,'--wait-until','domcontentloaded','--timeout','20000'])
        for _ in range(6):
            current=urlsplit(self.check())
            if current.path==target.path and parse_qs(current.query)==parse_qs(target.query):return
            time.sleep(.5)
        reject('导航后业务页面尚未应用指定日期条件，请稍后恢复')

    def dates(self, recipe):
        cal=recipe['calendar']
        if not self.elements(cal['panels']):self.click(recipe['date_open_selector'])
        for key in ('start','end'):
            date=datetime.fromisoformat(self.job[key])
            for attempt in range(2):
                panels=self.read("[...document.querySelectorAll("+json.dumps(cal['panels'])+")].map(e=>({header:e.querySelector("+json.dumps(cal['header'])+")?.textContent,cells:[...e.querySelectorAll("+json.dumps(cal['cells'])+")].map(c=>({day:c.textContent.trim(),row:[...c.parentElement.parentElement.children].indexOf(c.parentElement)+1,col:[...c.parentElement.children].indexOf(c)+1}))}))")
                expected_header=cal.get('header_format','{year}年-{month}月').format(year=date.year,month=date.month)
                matches=[(i,c) for i,p in enumerate(panels) if p['header']==expected_header for c in p['cells'] if int(c['day'])==date.day]
                if len(matches)==1: break
                if attempt or key=='end': reject('日历月份或日期单元格未唯一匹配')
                self.click(cal['previous_month'])
            i,c=matches[0]
            selector=cal['cell_template'].format(panel=i+1,row=c['row'],col=c['col'])
            self.click(selector)
        self.click(recipe['date_confirm_selector'])
        val=self.elements(recipe['range_selector'])
        expected=' - '.join(datetime.fromisoformat(self.job[k]).strftime('%d/%m/%Y') for k in ('start','end'))
        if len(val)!=1 or val[0]['text'].strip()!=expected: reject('结算导出日期未真正生效')

    def history(self,recipe):
        # Return only export filenames and structural CSS, never customer row content.
        selector=json.dumps(recipe['history_rows'])
        return self.read("[...document.querySelectorAll("+selector+")].map((r,i)=>({name:r.querySelector("+json.dumps(recipe['history_name'])+")?.textContent.trim(),ready:[...r.querySelectorAll('button')].some(b=>b.textContent.trim()==="+json.dumps(recipe.get('download_text','下载'))+"&&!b.disabled),index:i+"+str(recipe['history_index_offset'])+"})).filter(r=>/\\.(csv|xlsx)$/.test(r.name||''))")

    def prepare(self,kind,resume=False):
        recipe=self.p['reports'][kind]
        self.visit(order_url(recipe,self.job) if kind=='orders' else recipe['url'])
        if kind=='orders':
            query=parse_qs(urlsplit(self.check()).query)
            expected=parse_qs(urlsplit(order_url(recipe,self.job)).query)
            if query!=expected: reject('订单创建日期 URL 筛选不符或出现额外筛选')
            if not self.elements(recipe['export_selector']):self.click(recipe['entry_selector'],expect=recipe['export_selector'])
            submit=self.elements(recipe['export_selector'])
            if len(submit)!=1 or json.loads(submit[0]['log'] or '{}')!={'export_type':'filtered_order','file_type':'csv'}:
                reject('订单导出范围不是筛选结果 CSV，停止提交')
            selected=self.elements(recipe['scope_selector'])
            count=re.fullmatch(r'筛选出的订单\s*\(([\d,]+) 笔订单\)',selected[0]['text'].strip()) if len(selected)==1 else None
            if not count: reject('无法确认订单导出数量与范围')
            if not resume:self.job['expected_order_count']=int(count[1].replace(',',''))
        elif resume:
            self.click(recipe['history_entry_selector'],expect=recipe['history_rows'])
        else:
            if not self.elements(recipe['date_open_selector']):self.click(recipe['entry_selector'],expect=recipe['date_open_selector'])
            self.dates(recipe)
        return recipe

    def screenshot(self,directory,kind):
        directory.mkdir(parents=True,exist_ok=True)
        dest=directory/(self.job['id']+'-'+kind+'-'+str(time.time_ns())+'.png')
        value=self.bridge.run(['page','screenshot','--store-id',self.job['store_id'],'--path',str(dest)])
        if not dest.is_file() and isinstance(value,dict) and value.get('filePath'):
            source=Path(value['filePath']).resolve(strict=True)
            if source.suffix.lower()=='.png' and source.parent.name=='ziniao-zclaw-screenshots':
                with dest.open('xb') as handle:handle.write(source.read_bytes())
        if not dest.is_file():reject('关键步骤截图未保存，未提交导出')
        return str(dest)


def receipt_time(name,kind,utc_offset=8):
    pattern=r'(\d{4}-\d{2}-\d{2}-\d{2}:\d{2})\.csv$' if kind=='orders' else r'^income_(\d{14})\(UTC\+'+str(utc_offset)+r'\)\.xlsx$'
    m=re.search(pattern,name)
    if not m:return None
    fmt='%Y-%m-%d-%H:%M' if kind=='orders' else '%Y%m%d%H%M%S'
    return datetime.strptime(m[1],fmt).replace(tzinfo=timezone(timedelta(hours=utc_offset))).timestamp()


def collect(bridge,job,save,raw_dir,screenshot_dir):
    from ziniao_bridge import profile_hash
    from ziniao_reports import report_kinds
    check=bridge.check()
    if not check['ready']:reject(check['message'])
    profile=bridge.profile(report_kinds(job),job['store_id'])
    if job['profile_hash']!=profile_hash(profile):reject('采集配方变化，请重新审核任务')
    store=bridge.run(['store','resolve','--id',job['store_id'],'--expected-name',job['shop']])
    if store.get('name',store.get('storeName'))!=job['shop'] or str(store.get('storeId'))!=job['store_id']:reject('紫鸟环境身份不符')
    opened=bridge.run(['page','extract','--mode','store','--store-id',job['store_id']])
    if not opened.get('running'):opened=bridge.run(['store','open','--id',job['store_id'],'--expected-name',job['shop']])
    if not opened.get('downloadFolderPath'):reject('无法确认店铺下载目录')
    folder=Path(opened['downloadFolderPath']).resolve(strict=True)
    job['download_folder']=str(folder)
    ui=TikTokUI(bridge,profile,job)
    for kind in report_kinds(job):
        if kind in job.get('files',{}):continue
        cp=job.setdefault('exports',{}).get(kind)
        recipe=ui.prepare(kind,resume=bool(cp))
        if not cp:
            # Settlements: read history before opening the export popup on a future run.
            if kind=='settlement':
                ui.click(recipe['cancel_selector']);ui.click(recipe['history_entry_selector'])
                prior=ui.history(recipe)
                ui.visit(recipe['url']);ui.click(recipe['entry_selector']);ui.dates(recipe)
            else:prior=ui.history(recipe)
            cp={'before':{f.name:[f.stat().st_size,f.stat().st_mtime_ns] for f in folder.iterdir() if f.is_file()},
                'history_names':[r['name'] for r in prior],'submitted_at':time.time(),
                'screenshot':ui.screenshot(screenshot_dir,kind)}
            job['exports'][kind]=cp;save(job) # Crash after this checkpoint never resubmits.
            ui.click(recipe['export_selector'])
        # Bounded polling; a slow platform job stays resumable and is not exported again.
        for _ in range(12):
            ui.check()
            rows=ui.history(recipe)
            candidates=[r for r in rows if r['name'] not in cp.get('history_names',[]) and
                receipt_time(r['name'],kind,profile.get('utc_offset',8)) is not None and -60<=receipt_time(r['name'],kind,profile.get('utc_offset',8))-cp['submitted_at']<=180]
            if cp.get('platform_name'):candidates=[r for r in candidates if r['name']==cp['platform_name']]
            if len(candidates)>1:reject('多个新导出记录符合时间，无法确认归属；请人工审核')
            if len(candidates)==1:
                record=candidates[0];cp['platform_name']=record['name'];save(job)
                if record['ready']:break
            time.sleep(2)
        else:reject('平台导出尚未完成或历史记录无法唯一对应；保留任务等待恢复，不重复导出')
        name=re.sub(r'[<>:"/\\|?*]','_',record['name'])
        path=folder/name
        def fresh():
            return path.is_file() and not path.is_symlink() and path.resolve().parent==folder and path.stat().st_mtime>=cp['submitted_at'] and cp['before'].get(name)!=[path.stat().st_size,path.stat().st_mtime_ns]
        if not fresh():
            ui.click(recipe['download_selector_template'].format(index=record['index']))
            cp['download_requested_at']=time.time();save(job)
        previous=None
        for _ in range(30):
            if fresh():
                st=path.stat();sig=(st.st_size,st.st_mtime_ns)
                if sig==previous and 0<st.st_size<=20*1024*1024:
                    ui.check();raw_dir.mkdir(parents=True,exist_ok=True)
                    content=path.read_bytes();dest=raw_dir/(kind+path.suffix.lower())
                    if dest.exists():
                        if dest.read_bytes()!=content:reject('已有原文件与下载不同，禁止覆盖')
                    else:
                        with dest.open('xb') as out:out.write(content)
                    job.setdefault('files',{})[kind]={'name':path.name,'saved_name':dest.name,'sha256':hashlib.sha256(content).hexdigest(),'size':len(content)}
                    save(job);break
                previous=sig
            time.sleep(1)
        else:reject('未取得与导出记录对应的完整文件；请检查下载后恢复')
    return profile
