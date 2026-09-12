"""Versioned local data hub. Immutable inputs; atomic activation; no platform writes."""
from __future__ import annotations
import hashlib
import io
import json
import logging
import re
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
LABELS = {'gmv':'广告经营明细','daily':'店铺日销','erp':'ERP 库存详细','warn':'超期库存预警',
          'bill':'已处理账单','after':'售后退包原表','creator':'达人明细','mapping':'店铺人员名单',
          'links':'链接汇总','ad_summary':'广告汇总（规范待补）','cleaned':'GMV 清洗结果',
          'orders':'马帮订单原表','settlement':'TikTok 结算原表','product_pack':'产品包'}
REQUIRED = {
 'gmv':['商品 ID','成本','总收入','SKU 订单数','创意作品类型','货币'],
 'daily':['库存SKU','SKU中文名','店铺'],
 'erp':['库存SKU编号','中文名称','仓位库存','可用库存量','当前可售天数','销量(7/28/42)'],
 'warn':['商品名称','超期金额'], 'bill':['订单结算时间','月份','状态','一级类目','二级类目','三级类目','款名','中文名','店编','产品标签','是否样品','订单成本','结算总金额','总收入','退款类型','订单类型','相关订单 ID','商家运费','交易手续费','TikTok Shop 佣金费','平台支持费','奖金返现服务费','商家共同赞助优惠券折扣','联盟佣金','联盟服务商佣金','联盟店铺广告佣金','所属地区'],
 'after':['登记月份','订单商品数量','退包类型','收货状态','店铺','登记时间','一级类目','二级类目','三级类目','款名','商品成本价','sku处理结果','最后验货入库时间'],
 'creator':['达人名称','达人归因GMV','达人直播归因GMV','联盟视频归因GMV','退款金额','归因订单数','平均订单金额','联盟商品卡归因GMV','视频数','视频播放量','预计佣金'], 'mapping':['店名','店编','国家','初级','中级','CEO'],
 'links':['店编','商品 ID','商品名称','类目','SKU数','链接款名','链接标签','链接平均客单','链接平均成本','链接目标CPA','是否新品'],
 'ad_summary':['年','月','周','店编','实际CPA(USD)','ROI','建议方案'],
 'cleaned':['店名','店编','L7D新建素材数','L7D新建素材消耗额','总素材数','总消耗','总CTR','总CVR'],
 'orders':['订单编号','状态','交易编号','付款时间','店铺财务编码','店铺名','店长','所属地区','所属城市','SKU','商品数量','商品中文名称','是否测评','订单核算金额（原始货币）','tiktok样品订单','货运单号','交运时间','最后发货期限','发货时间'],
 'settlement':['Order created time','Order settled time','Transaction type','Customer refund','Related order ID','Order/Adjustment ID','Total settlement amount','Total Revenue'],
 'product_pack':['SKU','销售成本国家币'],
}

def stamp(): return datetime.now(timezone.utc).isoformat()
def pack(value): return json.dumps(value, ensure_ascii=False, separators=(',',':'), allow_nan=False)
def digest(value): return hashlib.sha256(value).hexdigest()

def engine(payload):
    try:
        p = subprocess.run(['node',str(ROOT/'skill_engine.cjs')], input=pack(payload),
            capture_output=True,text=True,encoding='utf-8',timeout=40,cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(503,'原 Skill 计算服务不可用，请检查 Node.js；当前数据未被覆盖。') from None
    if p.returncode:
        logging.error('Skill engine failed: %s',p.stderr[-2000:])
        raise HTTPException(422,'原 Skill 处理失败：'+p.stderr.split('\n')[0][:400])
    return json.loads(p.stdout)

def objects(table): return [dict(zip(table['header'],r)) for r in table['rows']]
def table_of(rows):
    header=list(dict.fromkeys(k for r in rows for k in r))
    return {'header':header,'rows':[[r.get(k) for k in header] for r in rows]}

class Activation(BaseModel):
    expected_version: str
    selections: list[dict] = Field(min_length=1,max_length=100)
    confirmed: bool = False
    mode: Literal['replace','partition'] = 'replace'

class Mapping(BaseModel):
    shop: str = Field(min_length=1,max_length=200)
    product_id: str = Field(default='',max_length=100)
    sku: str = Field(default='',max_length=100)
    name: str = Field(min_length=1,max_length=300)
    confirmed: bool = False

class Query(BaseModel):
    version: str = ''
    kind: str
    shop: str = ''
    product: str = ''
    start: str = ''
    end: str = ''
    offset: int = Field(default=0,ge=0)
    limit: int = Field(default=100,ge=1,le=500)
    question: str = Field(default='',max_length=2000)

class Hub:
    def __init__(self,connect,data):
        self.connect,self.data=connect,Path(data)

    @contextmanager
    def db(self):
        con=self.connect()
        try:
            con.executescript('''CREATE TABLE IF NOT EXISTS hub_versions(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,parent TEXT,payload TEXT NOT NULL,meta TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS hub_head(id INTEGER PRIMARY KEY CHECK(id=1),version TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS hub_jobs(id TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS hub_mappings(id TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS hub_events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT,value TEXT);
              CREATE TABLE IF NOT EXISTS hub_attachments(id TEXT PRIMARY KEY,task_id TEXT,value TEXT);
              CREATE TABLE IF NOT EXISTS hub_feedback(id TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE IF NOT EXISTS hub_annotations(id TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE IF NOT EXISTS hub_conversations(id TEXT PRIMARY KEY,value TEXT);''')
            with con: yield con
        finally: con.close()

    def seed(self):
        with self.db() as con:
            if con.execute('SELECT 1 FROM hub_head').fetchone(): return
            script=(ROOT/'assets/snapshot.js').read_text(encoding='utf-8')
            data=json.loads(script.split('=',1)[1].strip().removesuffix(';'))
            embedded=data['daily']
            computed=engine({'op':'daily','raw':embedded['raw']})
            computed_by_name={p['name']:p for p in computed['products']}
            differences=[{'product':p['name'],'field':k,'embedded':v,'runtime':computed_by_name[p['name']].get(k)}
                         for p in embedded['products'] for k,v in p.items() if computed_by_name[p['name']].get(k)!=v]
            data['embedded_daily_baseline']=embedded
            data['daily']=computed
            meta={'origin':'原始内嵌历史数据','datasets':{
              'gmv':{'period':'2026-08-17','currency':'USD'},'daily':{'period':'2026-06-01/2026-06-08'},
              'erp':{'period':'原快照未标注库存时点'},'warn':{'period':'原快照未标注预警时点'},
              'bill':{'period':'2026-08-01/2026-08-09','currency':'MYR'},
              'creator':{'period':'2026-07','currency':'MYR','completeness':'仅186位有收入达人明细；总览3265位'},
              'after':{'period':'原内嵌汇总','completeness':'缺少逐行原表，不能还原订单明细'}},'files':[],
              'baseline_differences':differences,'calculation_note':'日销使用原 HTML 运行算法；内嵌冻结值另存 embedded_daily_baseline，舍入/列表顺序差异明确保留。'}
            con.execute('BEGIN IMMEDIATE')
            if not con.execute('SELECT 1 FROM hub_head').fetchone(): self.save(con,data,meta,None)

    def save(self,con,data,meta,parent):
        ident=uuid.uuid4().hex
        con.execute('INSERT INTO hub_versions VALUES(?,?,?,?,?)',(ident,stamp(),parent,pack(data),pack(meta)))
        con.execute('INSERT OR REPLACE INTO hub_head VALUES(1,?)',(ident,))
        con.execute('INSERT INTO hub_events(created_at,value) VALUES(?,?)',(stamp(),pack({'op':'activate','version':ident,'parent':parent})))
        logging.info('hub activated version=%s parent=%s',ident,parent)
        return ident

    def current(self,version=''):
        self.seed()
        with self.db() as con:
            ident=version or con.execute('SELECT version FROM hub_head').fetchone()[0]
            row=con.execute('SELECT payload,meta,created_at FROM hub_versions WHERE id=?',(ident,)).fetchone()
        if not row: raise HTTPException(404,'数据版本不存在')
        return {'version':ident,'data':json.loads(row[0]),'meta':json.loads(row[1]),'created_at':row[2]}

    def preview(self,filename,content):
        suffix=Path(filename).suffix.lower()
        if suffix not in ('.xlsx','.xls','.csv'): raise HTTPException(422,'仅支持 XLSX、XLS、CSV')
        if filename.startswith('~$'): raise HTTPException(422,'请不要上传 Excel 临时锁文件')
        if suffix=='.csv':
            frames=None
            for encoding in ('utf-8-sig','gb18030'):
                try:
                    frames={'CSV':pd.read_csv(io.BytesIO(content),header=None,dtype=object,keep_default_na=False,encoding=encoding)}
                    break
                except UnicodeDecodeError: pass
            if frames is None: raise HTTPException(422,'无法识别 CSV 编码')
        else:
            frames=pd.read_excel(io.BytesIO(content),sheet_name=None,header=None,dtype=object,
                                 keep_default_na=False,engine='xlrd' if suffix=='.xls' else 'openpyxl')
        result=[]
        for sheet,df in frames.items():
            if df.empty: continue
            def val(x):
                if isinstance(x,(datetime,date,pd.Timestamp)): return x.isoformat()
                if hasattr(x,'item'): x=x.item()
                return x
            matrix=[[val(x) for x in row] for row in df.values.tolist()]
            matches=[]
            for i,row in enumerate(matrix[:20]):
                fields={str(x).strip() for x in row if str(x).strip()}
                for kind,need in REQUIRED.items():
                    score=sum(h in fields for h in need)/len(need)
                    if score>=.6: matches.append((score,len(need),-i,kind))
            match=max(matches) if matches else (0,0,0,'unknown')
            kind,header_row=match[3],-match[2]
            header=[str(x).strip() for x in matrix[header_row]]
            if '订单成本' in header and '状态' in header and ('Related order ID' in header or '相关订单 ID' in header):kind='bill'
            rows=[r for r in matrix[header_row+1:] if any(x not in ('',None) for x in r)]
            issues=[]
            if not rows: issues.append('工作表没有数据行')
            if kind=='unknown': issues.append('无法识别表格类型，请选择正确工作表和类型后重试。')
            elif kind=='bill':
                try:engine({'op':'bill_normalize','table':{'header':header,'rows':[]}})
                except HTTPException as exc:issues.append(exc.detail)
            else:
                missing=[h for h in REQUIRED[kind] if h not in header]
                if missing: issues.append('缺少字段：'+'、'.join(missing))
            if len(set(header))!=len(header) or '' in header: issues.append('存在空白或重复表头，请修正后重新上传。')
            for col,h in enumerate(header):
                if re.search(r'(?i)\bid\b|编号|SKU|商品 ID|视频 ID|计划 ID',h):
                    for row in rows:
                        x=row[col]
                        if isinstance(x,(int,float)) and abs(x)>9007199254740991:
                            issues.append(f'{h} 含不安全长数字，原导出可能已丢失精度，请重新导出文本 ID。');break
                        if x not in ('',None): row[col]=str(int(x)) if isinstance(x,float) and x.is_integer() else str(x)
            if kind=='daily' and not any(re.match(r'^20\d{2}[-/]\d{1,2}[-/]\d{1,2}',h) for h in header): issues.append('没有日销日期列')
            if kind=='after' and '登记月份' in header:
                months={str(r[header.index('登记月份')]) for r in rows}
                if len(months)>4: issues.append('原售后引擎仅支持单批最多4个月；请缩小周期，不能静默丢失第5个月数据。')
            numeric={'gmv':['成本','总收入','SKU 订单数'],'bill':['订单成本','结算总金额','总收入'],'creator':REQUIRED['creator'][1:]}.get(kind,[])
            for column in numeric:
                if column in header:
                    for row in rows:
                        value=row[header.index(column)]
                        if value not in ('',None):
                            try:
                                number=float(str(value).replace(',',''))
                                if not __import__('math').isfinite(number): raise ValueError()
                            except ValueError:
                                issues.append(column+' 包含非有限数值，请修正后导入');break
            dates=sorted({h[:10] for h in header if re.match(r'^20\d{2}-\d{2}-\d{2}',h)})
            result.append({'id':uuid.uuid4().hex,'name':filename,'sheet':sheet,'kind':kind,'header_row':header_row+1,
                           'header':header,'rows':rows,'row_count':len(rows),'issues':list(dict.fromkeys(issues)),
                           'suggested_period':('/'.join([dates[0],dates[-1]]) if dates else ''),'sha256':digest(content)})
        return result

    def activate(self,job_id,payload,dry_run=False):
        if not payload.confirmed and not dry_run: raise HTTPException(422,'请先核对导入影响并确认更新方式；原文件和旧版本保留。')
        before=self.current()
        if before['version']!=payload.expected_version: raise HTTPException(409,'数据已更新，请重新预览')
        with self.db() as con:
            row=con.execute('SELECT value FROM hub_jobs WHERE id=?',(job_id,)).fetchone()
        if not row: raise HTTPException(404,'导入任务不存在')
        job=json.loads(row[0]);lookup={e['id']:e for e in job['entries']};groups={};used=[]
        for selection in payload.selections:
            entry=lookup.get(selection.get('id'))
            if not entry or entry['issues']: raise HTTPException(422,'选中的文件未通过预检')
            period=str(selection.get('period','')).strip();currency=str(selection.get('currency','')).strip().upper()
            if not period: raise HTTPException(422,'请填写实际报表周期；不能以导入时间代替业务时间')
            try:
                parts=period.split('/')
                if len(parts)>2: raise ValueError()
                parsed=[date.fromisoformat(p+'-01' if re.fullmatch(r'\d{4}-\d{2}',p) else p) for p in parts]
                if len(parsed)==2 and parsed[0]>parsed[1]: raise ValueError()
            except ValueError: raise HTTPException(422,'周期格式为 YYYY-MM、YYYY-MM-DD 或 YYYY-MM-DD/YYYY-MM-DD，起点不能晚于终点')
            if entry['kind'] in ('gmv','bill','creator','after','settlement','cleaned','ad_summary','links','product_pack') and not currency:
                raise HTTPException(422,'金额表必须标注原始币种')
            shop=str(selection.get('shop','')).strip()
            if not shop:
                code=re.search(r'(?i)MS\d+',entry['name'])
                shop=code[0].upper() if code else ''
            item={**entry,'period':period,'currency':currency,'shop':shop}
            groups.setdefault(entry['kind'],[]).append(item);used.append(item)
        data=before['data'];meta=before['meta']
        fingerprints=sorted((e['sha256'],e['sheet'],e['kind'],e['period'],e['currency'],e['shop']) for e in used)
        current_fingerprints=sorted(tuple(x) for x in meta.get('last_import',[]))
        duplicate=fingerprints==current_fingerprints and meta.get('last_import_mode','replace')==payload.mode
        for kind,entries in groups.items():
            if len({(e['period'],e['currency']) for e in entries})>1: raise HTTPException(422,'同类型一次导入须为同周期、同币种；不同周期请分批保存')
            if kind=='daily':
                for entry in entries:
                    days=sorted(h for h in entry['header'] if re.fullmatch(r'20\d{2}-\d{2}-\d{2}',h))
                    if days and entry['period'] not in (days[0] if len(days)==1 else '',days[0]+'/'+days[-1]):
                        raise HTTPException(422,'日销所填周期必须与日期列起止一致；不能给旧数据贴新日期。')
        changes=[]
        if payload.mode=='partition':
            from hub_partitions import prepare
            if 'bill' in groups:
                groups['bill']=[{**e,**engine({'op':'bill_normalize','table':{'header':e['header'],'rows':e['rows']}})} for e in groups['bill']]
            groups,ledger,changes=prepare(before,groups)
            data['partition_store']=ledger
            if changes and all(c['operation']=='unchanged' for c in changes) and all(
                meta['datasets'].get(k,{}).get('period')==es[0]['period'] and meta['datasets'].get(k,{}).get('currency','')==es[0]['currency'] for k,es in groups.items()):duplicate=True
        else:
            for kind,entries in groups.items():
                data.get('partition_store',{}).pop(kind,None)
                changes.append({'kind':kind,'operation':'replace_type','after_rows':sum(len(e['rows']) for e in entries)})
        self.apply_groups(data,meta,groups)
        from hub_partitions import index
        impact={'mode':payload.mode,'changes':changes,'active_scopes':{k:meta['datasets'][k] for k in groups},
                'partitions':index(before),'affected':['业务模块','原指标查询','AI查数','行动候选（需点击同步）'],
                'note':'同周期店铺分区合并；其他周期保存在分区目录，不进入当前周期总计。' if payload.mode=='partition' else '选中数据类型整体替换；未选中类型不变，旧版本保留。'}
        if dry_run:return {'version':before['version'],'duplicate':duplicate,'impact':impact}
        if duplicate:return {'version':before['version'],'duplicate':True,'impact':impact}
        meta['last_import']=fingerprints
        meta['last_import_mode']=payload.mode
        meta['last_impact']=impact
        meta['files']=meta.get('files',[])+[{k:e[k] for k in ('name','sheet','kind','sha256','period','currency')} for e in used]
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT version FROM hub_head').fetchone()[0]!=payload.expected_version: raise HTTPException(409,'数据已更新，请重试')
            ident=self.save(con,data,meta,before['version'])
        return {'version':ident,'duplicate':False,'changed':list(groups),'impact':impact}

    def apply_groups(self,data,meta,groups):
        for kind,entries in groups.items():
            first=entries[0]
            if any(e['header']!=first['header'] for e in entries): raise HTTPException(422,'同类型多文件表头必须一致，避免静默丢列')
            if len({(e['period'],e['currency']) for e in entries})>1: raise HTTPException(422,'同类型一次导入须为同周期、同币种；不同周期请分批保存')
            table={'header':first['header'],'rows':[r for e in entries for r in e['rows']]}
            if kind=='gmv':
                currencies={str(r[table['header'].index('货币')]).strip().upper() for r in table['rows']}
                if currencies!={first['currency']}: raise HTTPException(422,'广告原表币种与所填币种不一致，或同表存在多币种；请分币种导入。')
            data.setdefault('source_tables',{})[kind]=[{k:e[k] for k in ('name','sheet','shop','header','rows','period','currency')} for e in entries]
            meta['datasets'][kind]={'period':first['period'],'currency':first['currency'],'files':[e['name'] for e in entries],
                                    'row_count':len(table['rows']),'updated_at':stamp()}
            if kind=='gmv':
                history=data.setdefault('gmv_history',[{'period':data['gmv']['snapshotDate'],
                                                       'currency':(data['gmv']['rows'][0].get('货币','USD') if data['gmv']['rows'] else 'USD'),'payload':data['gmv']}])
                data['gmv']={**data['gmv'],'rows':objects(table),'headers':table['header'],'snapshotDate':first['period'].split('/')[-1],
                             'sourceFile':' / '.join(e['name'] for e in entries),'importedAt':stamp()}
                data['gmv_history']=[h for h in history if h['period']!=first['period'] or h['currency']!=first['currency']]+[{'period':first['period'],'currency':first['currency'],'payload':data['gmv']}]
            elif kind in ('daily','erp','warn'): data['daily']['raw'][kind]=objects(table)
            elif kind=='bill':
                data['bill']=engine({'op':'bill_normalize','table':table})
                # Imported/reselected bills must not export an earlier pipeline's cached profit.
                # Immutable older workspace versions retain those original pipeline artifacts.
                data.pop('pipeline_results',None)
            else: data.setdefault('tables',{})[kind]=table
        if any(k in groups for k in ('daily','erp','warn')): data['daily']=engine({'op':'daily','raw':data['daily']['raw']})
        if 'creator' in groups:
            table=data['tables']['creator'];index=[table['header'].index(h) for h in REQUIRED['creator']]
            all_rows=[[r[index[0]],*[float(str(r[i] or 0).replace(',','')) for i in index[1:]]] for r in table['rows']]
            data['creators']=[r for r in all_rows if r[1]>0]
            totals=lambda i:sum(r[i] for r in all_rows)
            data['creatorTotal']={'count':len(all_rows),'valid':len(data['creators']),'invalid':len(all_rows)-len(data['creators']),
              'gmv':totals(1),'live':totals(2),'video':totals(3),'refund':totals(4),'customers':totals(5),
              'goods':totals(7),'videoN':totals(8),'videoViews':totals(9),'comm':totals(10)}
            meta['datasets']['creator']['completeness']='仅本次导入明细的汇总；有收入明细筛选 GMV>0，不冒充平台全量。'

    def query(self,p):
        current=self.current(p.version);data=current['data'];kind=p.kind
        if kind=='daily_anomalies':
            question=(p.shop+' '+p.product+' '+p.start+' '+p.end+' '+(p.question or '日销异常')).strip()
            result=engine({'op':'daily_query','data':data,'question':question})
            rows=result.pop('rows',[])
            return {**result,'version':current['version'],'total':len(rows),'rows':rows[p.offset:p.offset+p.limit],'offset':p.offset}
        if kind=='inventory': rows=data['daily']['products'];table=table_of(rows)
        elif kind=='gmv': table=table_of(data['gmv']['rows'])
        elif kind in ('daily','erp','warn'): table=table_of(data['daily']['raw'][kind])
        elif kind=='bill': table=data['bill']
        elif kind=='creator': table={'header':REQUIRED['creator'],'rows':data['creators']}
        elif kind in data.get('tables',{}): table=data['tables'][kind]
        else: raise HTTPException(422,'该数据没有可查询的逐行明细')
        rows=objects(table)
        def norm(x): return re.sub(r'[^\w]','',str(x)).casefold()
        def match(r):
            shops=[r.get(k,'') for k in ('店铺','店编','店名','店铺名称')]
            products=[r.get(k,'') for k in ('商品 ID','库存SKU','库存SKU编号','SKU中文名','中文名称','商品名称','款名','name','SKU','达人名称')]+r.get('skuList',[])
            return (not p.shop or norm(p.shop) in map(norm,shops)) and (not p.product or any(norm(p.product) in norm(x) for x in products))
        selected=[{'source_row':i+2,**r} for i,r in enumerate(rows) if match(r)]
        if p.start or p.end:
            if kind=='daily':
                dates=[h for h in table['header'] if re.match(r'^20\d{2}-\d{2}-\d{2}',h)]
                keep=[h for h in dates if (not p.start or h>=p.start) and (not p.end or h<=p.end)]
                selected=[{k:v for k,v in r.items() if k not in dates or k in keep} for r in selected]
            elif kind=='bill':
                def key(r):
                    m=re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',str(r['订单结算时间']))
                    return f'{m[1]}-{m[2].zfill(2)}-{m[3].zfill(2)}' if m else ''
                selected=[r for r in selected if key(r) and (not p.start or key(r)>=p.start) and (not p.end or key(r)<=p.end)]
            else: raise HTTPException(422,'该表不支持逐行日期筛选，请选择对应批次')
        metrics=None
        if kind=='gmv': metrics=engine({'op':'ad_metrics','rows':selected})
        return {'version':current['version'],'kind':kind,'total':len(selected),'rows':selected[p.offset:p.offset+p.limit],'metrics_by_currency':metrics,
                'offset':p.offset,'header':table['header'],'source':current['meta']['datasets'].get(kind,{}),'filters':p.model_dump()}


def create_router(hub):
    router=APIRouter(prefix='/api/hub')

    @router.get('/workspace')
    def workspace(version: str=''): return hub.current(version)

    @router.get('/versions')
    def versions():
        hub.seed()
        with hub.db() as con:
            rows=con.execute('SELECT id,created_at,parent,meta FROM hub_versions ORDER BY rowid DESC').fetchall()
        return {'versions':[{'id':r[0],'created_at':r[1],'parent':r[2],'meta':json.loads(r[3])} for r in rows]}

    @router.post('/versions/{version}/restore')
    def restore(version: str,expected_version: str=Form(...)):
        target=hub.current(version)
        with hub.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT version FROM hub_head').fetchone()[0]!=expected_version: raise HTTPException(409,'数据版本已变化')
            ident=hub.save(con,target['data'],{**target['meta'],'restored_from':version},expected_version)
        return {'version':ident}

    @router.get('/requirements')
    def requirements():
        return {'types':[{'kind':k,'name':v,'required':REQUIRED[k]} for k,v in LABELS.items()],
          'workflows':[
            {'name':'日销库存联动','inputs':['daily','erp','warn'],'status':'原计算引擎'},
            {'name':'广告经营','inputs':['gmv'],'status':'原 v45 全功能'},
            {'name':'GMV 清洗','inputs':['mapping','广告素材原表 + 明确 L7D 起点'],'status':'原脚本'},
            {'name':'账单利润','inputs':['bill'],'status':'原三阶段引擎'},
            {'name':'马帮→账单→利润','inputs':['orders','product_pack','settlement'],'status':'原三阶段引擎'},
            {'name':'售后退包','inputs':['after'],'status':'原页面处理逻辑'},
            {'name':'链接→广告汇总','inputs':['店编-商品链接.xlsx','月份-产品包.xlsx','年/月/周-店编.xlsx'],'status':'缺少四脚本和49列表头规范，未接通'}]}

    @router.post('/imports/preview')
    async def preview(files:list[UploadFile]=File(...)):
        if not 1<=len(files)<=40: raise HTTPException(422,'一次上传 1–40 个文件')
        ident=uuid.uuid4().hex;folder=hub.data/'raw/ai_workbench/imports'/ident;folder.mkdir(parents=True)
        entries=[];errors=[];seen=set();originals=[]
        for i,file in enumerate(files):
            content=await file.read(20*1024*1024+1)
            if len(content)>20*1024*1024: raise HTTPException(413,'单个文件不得超过20MB')
            name=Path((file.filename or 'file').replace('\\','/')).name
            if digest(content) in seen: continue
            seen.add(digest(content))
            file_id=uuid.uuid4().hex
            saved_name=f'{i:02d}_{file_id}{Path(name).suffix}'
            (folder/saved_name).write_bytes(content)
            originals.append({'id':file_id,'name':name,'saved_name':saved_name,'sha256':digest(content),'size':len(content)})
            try: entries.extend(hub.preview(name,content))
            except Exception as exc: errors.append({'name':name,'error':getattr(exc,'detail',str(exc))[:500]})
        job={'id':ident,'created_at':stamp(),'entries':entries,'errors':errors,'originals':originals}
        with hub.db() as con: con.execute('INSERT INTO hub_jobs VALUES(?,?)',(ident,pack(job)))
        logging.info('hub import preview=%s files=%s errors=%s',ident,len(files),len(errors))
        return {**job,'entries':[{**e,'rows':e['rows'][:3]} for e in entries]}

    @router.get('/imports')
    def imports():
        with hub.db() as con: rows=con.execute('SELECT value FROM hub_jobs ORDER BY rowid DESC LIMIT 100').fetchall()
        return {'jobs':[{k:v for k,v in json.loads(r[0]).items() if k!='entries'} for r in rows]}

    @router.get('/imports/{job_id}/original/{file_id}')
    def original(job_id:str,file_id:str):
        with hub.db() as con: row=con.execute('SELECT value FROM hub_jobs WHERE id=?',(job_id,)).fetchone()
        if not row:raise HTTPException(404)
        record=next((x for x in json.loads(row[0]).get('originals',[]) if x['id']==file_id),None)
        if not record:raise HTTPException(404)
        path=hub.data/'raw/ai_workbench/imports'/job_id/record['saved_name']
        if not path.is_file():raise HTTPException(404,'原始文件不可用')
        return FileResponse(path,filename=record['name'],media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})

    @router.post('/imports/{job_id}/activate')
    def activate(job_id:str,payload:Activation): return hub.activate(job_id,payload)

    @router.post('/imports/{job_id}/impact')
    def impact(job_id:str,payload:Activation): return hub.activate(job_id,payload,dry_run=True)

    @router.get('/partitions')
    def partitions(version:str=''):
        from hub_partitions import index
        return {'items':index(hub.current(version))}

    @router.post('/partitions/select')
    def select_partition(kind:str=Form(...),period:str=Form(...),currency:str=Form(''),expected_version:str=Form(...),confirmed:bool=Form(False)):
        if not confirmed:raise HTTPException(422,'请确认切换该类型的分析周期；其他周期不会删除。')
        current=hub.current()
        if current['version']!=expected_version:raise HTTPException(409,'版本已变化，请刷新')
        entries=[e for e in current['data'].get('partition_store',{}).get(kind,[]) if e['period']==period and e.get('currency','')==currency]
        if not entries:raise HTTPException(404,'未找到该周期分区')
        hub.apply_groups(current['data'],current['meta'],{kind:entries})
        current['meta']['last_import']=[]
        current['meta']['view_selection']={'kind':kind,'period':period,'currency':currency}
        with hub.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT version FROM hub_head').fetchone()[0]!=expected_version:raise HTTPException(409,'版本已变化，请刷新')
            ident=hub.save(con,current['data'],current['meta'],expected_version)
        return {'version':ident}

    @router.post('/query')
    def query(payload:Query): return hub.query(payload)

    @router.get('/linked-product')
    def linkage(shop:str,product_id:str,version:str=''):
        from hub_linkage import linked_product
        return linked_product(hub,hub.current(version),shop,product_id)

    @router.get('/coverage')
    def coverage():
        path=ROOT/'assets/skill-coverage.json'
        if not path.is_file():raise HTTPException(503,'功能覆盖清单尚未生成')
        return json.loads(path.read_text(encoding='utf-8'))

    @router.get('/export/{kind}')
    def export(kind:str,version:str=''):
        current=hub.current(version);data=current['data']
        if kind=='bill': table=data['bill']
        elif kind in ('daily','erp','warn'): table=table_of(data['daily']['raw'][kind])
        elif kind=='gmv': table=table_of(data['gmv']['rows'])
        elif kind in data.get('tables',{}): table=data['tables'][kind]
        else: raise HTTPException(404,'没有可导出的逐行数据')
        buffer=io.BytesIO()
        with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
            pd.DataFrame(table['rows'],columns=table['header']).to_excel(writer,index=False,sheet_name='数据')
            ws=writer.book['数据'];ws.freeze_panes='A2'
            # Strings that look like formulae stay literal; source values never execute on export.
            for row in ws:
                for cell in row:
                    if cell.data_type=='f': cell.data_type='s'
        return Response(buffer.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':f'attachment; filename="{kind}_{current["version"][:8]}.xlsx"'})

    @router.get('/mappings')
    def mappings():
        with hub.db() as con: rows=con.execute('SELECT id,value FROM hub_mappings').fetchall()
        return {'items':[{'id':r[0],**json.loads(r[1])} for r in rows]}

    @router.post('/mappings')
    def mapping(payload:Mapping):
        if not payload.confirmed or not (payload.sku or payload.product_id): raise HTTPException(422,'需填写 SKU 或商品 ID 并人工确认')
        item=payload.model_dump();ident=digest(pack([item['shop'],item['product_id'],item['sku']]).encode())[:32]
        with hub.db() as con:
            previous=con.execute('SELECT value FROM hub_mappings WHERE id=?',(ident,)).fetchone()
            con.execute('INSERT OR REPLACE INTO hub_mappings VALUES(?,?)',(ident,pack(item)))
            con.execute('INSERT INTO hub_events(created_at,value) VALUES(?,?)',(stamp(),pack({'op':'mapping','id':ident,'before':json.loads(previous[0]) if previous else None,'after':item})))
        return {'id':ident,**item}

    @router.get('/connectors')
    def connectors():
        return {'items':[{'id':k,'name':n,'status':'not_configured','read_only':True,
                          'message':'官方 API 权限尚未配置；当前使用批量上传，无后台登录自动化。'} for k,n in [('tiktok','TikTok'),('mabang','马帮')]]}

    @router.post('/connectors/{connector}/pull')
    @router.post('/connectors/{connector}/check')
    def connector_stub(connector:str):
        if connector not in ('tiktok','mabang'): raise HTTPException(404)
        raise HTTPException(503,'官方 API 接口已预留，尚未授权和配置；未发起远程请求。')

    return router
