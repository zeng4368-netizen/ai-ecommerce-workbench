"""Independent, evidence-based TikTok daily checks. Never calls an LLM or a shop."""
import hashlib
import io
import json
import math
import uuid
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ziniao_bridge import load_stores

MODULES = {
    'sales': ('销售复盘', {'sales':'昨日销量', 'previous_sales':'前日销量', 'revenue':'昨日商品销售额'}),
    'inventory': ('库存预警', {'available':'可售库存', 'sales_7d':'近7日销量'}),
    'ads': ('广告异常', {'spend':'广告花费', 'attributed_revenue':'广告归因收入'}),
    'orders': ('履约风险', {'pending_orders':'待发货订单数', 'overdue_orders':'超时待发货订单数'}),
    'reviews': ('新增差评', {'review_count':'新增商品评价数', 'negative_count':'新增低星商品评价数'}),
    'health': ('店铺健康', {'violations':'未处理违规数'}),
    'inbox': ('通知待办', {'unread':'未读通知数', 'urgent':'紧急通知数'}),
}
COMMON = {'store_id':'店铺ID', 'day':'业务日期', 'currency':'币种', 'timezone':'时区',
          'entity_id':'对象ID', 'entity_name':'对象名称', 'source':'来源说明'}
MAX_BYTES = 5 * 1024 * 1024
RULE_VERSION = 'tiktok_daily_v1'


def pack(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Thresholds(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    sales_change_pct: float = Field(30, ge=1, le=1000)
    stock_units: float = Field(10, ge=0, le=1000000)
    stock_days: float = Field(14, ge=1, le=365)
    ad_roas: float = Field(2, gt=0, le=100)
    ad_min_spend: float = Field(10, ge=0, le=1000000)
    negative_count: int = Field(1, ge=1, le=1000000)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    thresholds: Thresholds = Field(default_factory=Thresholds)


def today_for(store):
    # Existing bindings are MY / TH; fixed UTC offsets have no DST ambiguity.
    offsets = {'Asia/Kuala_Lumpur':8, 'Asia/Bangkok':7, 'Asia/Shanghai':8}
    if store['timezone'] not in offsets:
        raise HTTPException(422, '当前巡检尚未配置此店铺时区')
    return datetime.now(timezone(timedelta(hours=offsets[store['timezone']]))).date()


def parse_book(content, store_id, store, day):
    if len(content) > MAX_BYTES:
        raise HTTPException(413, '报表最大 5 MB')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 25 * 1024 * 1024:
                raise ValueError('工作簿解压后过大')
        book = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=str, keep_default_na=False, engine='openpyxl')
    except Exception as exc:
        raise HTTPException(422, '无法读取 XLSX，请使用巡检模板；不支持损坏、加密或过大的工作簿') from exc
    result = {}
    for key, (title, fields) in MODULES.items():
        frame = book.get(title)
        if frame is None or frame.empty:
            continue
        if len(frame) > 10000:
            raise HTTPException(422, f'{title}最多 10000 行')
        expected = {**COMMON, **fields}
        if list(frame.columns) != list(expected.values()):
            raise HTTPException(422, f'{title}表头不匹配，请重新下载模板，不自动猜测字段')
        records, seen = [], set()
        for n, raw in enumerate(frame.to_dict('records'), 2):
            row = {k:str(raw[v]).strip() for k,v in expected.items()}
            if not any(row.values()):
                continue
            for field, value in [('store_id',store_id),('day',day),('currency',store['currency']),('timezone',store['timezone'])]:
                if row[field] != value:
                    raise HTTPException(422, f'{title}第 {n} 行的{COMMON[field]}与所选店铺/日期不一致')
            if not row['entity_id'] or not row['entity_name'] or not row['source']:
                raise HTTPException(422, f'{title}第 {n} 行缺少对象 ID、名称或来源说明')
            if row['entity_id'] in seen:
                raise HTTPException(422, f'{title}第 {n} 行对象 ID 重复，请先核对统计粒度')
            seen.add(row['entity_id'])
            for metric in fields:
                try:
                    number = float(row[metric])
                    if not math.isfinite(number) or number < 0 or number > 1e15:
                        raise ValueError()
                    if metric not in ('revenue','spend','attributed_revenue') and not number.is_integer():
                        raise ValueError()
                except ValueError:
                    raise HTTPException(422, f'{title}第 {n} 行的{fields[metric]}必须填写有效非负数（数量为整数），缺失不能填 0 代替') from None
                row[metric] = number
            if key == 'orders' and row['overdue_orders'] > row['pending_orders']:
                raise HTTPException(422, '超时待发货数不能超过待发货总数')
            if key == 'reviews' and row['negative_count'] > row['review_count']:
                raise HTTPException(422, '低星评价数不能超过评价总数')
            if key == 'inbox' and row['urgent'] > row['unread']:
                raise HTTPException(422, '紧急未读通知数不能超过未读总数')
            row['source_row'] = n
            records.append(row)
        if records:
            result[key] = records
    if not result:
        raise HTTPException(422, '没有可巡检的数据；请至少填写一个模块，空表不会记作正常')
    return result


def analyze(rows, thresholds):
    t = thresholds.model_dump()
    modules, findings = [], []
    for key, (title, _) in MODULES.items():
        records = rows.get(key, [])
        count = 0
        for r in records:
            issues = []
            if key == 'sales':
                previous = r['previous_sales']
                if previous == 0:
                    if r['sales'] > 0:
                        issues.append(('P2','前日销量为 0，无法计算环比', '核对是否新品或恢复销售；不要套用百分比增长。'))
                else:
                    change = (r['sales'] / previous - 1) * 100
                    if abs(change) >= t['sales_change_pct']:
                        issues.append(('P1' if change < 0 else 'P2', f'销量 {r["sales"]:g}，前日 {previous:g}，环比 {change:+.1f}%', '下滑时检查流量、转化与缺货；上涨时核对直播活动及备货。'))
            elif key == 'inventory':
                days = r['available'] / (r['sales_7d'] / 7) if r['sales_7d'] else None
                if r['available'] <= t['stock_units'] or (days is not None and days <= t['stock_days']):
                    issues.append(('P0' if r['available']==0 else 'P1', f'可售库存 {r["available"]:g}；可售天数 '+(f'{days:.1f}' if days is not None else '不可计算（近7日无销量）'), '核对在途、预留和补货周期，准备补货建议；不自动采购。'))
            elif key == 'ads':
                spend = r['spend']
                if spend > 0 and spend >= t['ad_min_spend']:
                    roas = r['attributed_revenue'] / spend
                    if roas < t['ad_roas']:
                        issues.append(('P1', f'花费 {spend:g}，归因收入 {r["attributed_revenue"]:g}，ROAS {roas:.2f}', '核对归因窗口和样本量，检查素材与转化；只生成优化建议。'))
            elif key == 'orders' and r['overdue_orders'] > 0:
                issues.append(('P0', f'待发货 {r["pending_orders"]:g} 笔，其中超时 {r["overdue_orders"]:g} 笔', '按平台截止时间核对订单，安排仓库人工跟进。'))
            elif key == 'reviews' and r['negative_count'] >= t['negative_count']:
                issues.append(('P1', f'新增评价 {r["review_count"]:g} 条，其中低星 {r["negative_count"]:g} 条', '核对商品评价原文，归类质量、物流或描述问题后拟回复草稿。'))
            elif key == 'health' and r['violations'] > 0:
                issues.append(('P0', f'未处理违规 {r["violations"]:g} 项', '核对违规原文、申诉期限与凭证，由运营决定处理方式。'))
            elif key == 'inbox' and r['unread'] > 0:
                issues.append(('P1' if r['urgent'] else 'P2', f'未读 {r["unread"]:g} 条，其中紧急 {r["urgent"]:g} 条', '先查看紧急通知，分类记录；不自动标已读或发送消息。'))
            for priority, reason, action in issues:
                count += 1
                findings.append({'module':key,'module_name':title,'entity_id':r['entity_id'], 'entity_name':r['entity_name'], 'priority':priority, 'reason':reason, 'action':action, 'source':r['source'], 'source_row':r['source_row']})
        note = ('低于最低花费或零花费的广告不做 ROAS 预警；零花费不能计算 ROAS。' if key=='ads'
                else '近7日无销量时不能计算可售天数，仍检查库存件数。' if key=='inventory' else '')
        modules.append({'id':key,'name':title,'rows':len(records),'findings':count,'note':note,
                        'status':'missing' if not records else ('attention' if count else 'checked')})
    findings.sort(key=lambda f:f['priority'])
    return {'modules':modules,'findings':findings,'coverage':sum(bool(rows.get(k)) for k in MODULES),
            'status':'partial' if any(not rows.get(k) for k in MODULES) else 'complete'}


class Patrol:
    def __init__(self, hub, selectors):
        self.hub, self.selectors = hub, selectors

    @contextmanager
    def db(self):
        with self.hub.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS tiktok_patrol_sources(id TEXT PRIMARY KEY,value TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS tiktok_patrol_runs(id TEXT PRIMARY KEY,store_id TEXT NOT NULL,day TEXT NOT NULL,value TEXT NOT NULL)')
            yield con

    def store(self, store_id):
        value = load_stores(self.selectors).get(store_id)
        if not value:
            raise HTTPException(422, '请选择已绑定的 TikTok 店铺')
        return value

    def get(self, ident, source=False):
        with self.db() as con:
            table = 'tiktok_patrol_sources' if source else 'tiktok_patrol_runs'
            row = con.execute(f'SELECT value FROM {table} WHERE id=?',(ident,)).fetchone()
        if not row:
            raise HTTPException(404, '巡检记录不存在')
        return json.loads(row[0])

    def ingest(self, content, store_id, day):
        store = self.store(store_id)
        try:
            parsed_day = date.fromisoformat(day)
            if day != parsed_day.isoformat() or parsed_day > today_for(store):
                raise ValueError()
        except ValueError:
            raise HTTPException(422, '业务日期无效或晚于店铺当地今天') from None
        rows = parse_book(content, store_id, store, day)
        ident = uuid.uuid4().hex
        folder = self.hub.data / 'raw/ai_workbench/tiktok_patrol' / ident
        folder.mkdir(parents=True, exist_ok=False)
        (folder/'source.xlsx').write_bytes(content)
        value = {'id':ident,'store_id':store_id,'shop':store['shop'],'currency':store['currency'],
                 'timezone':store['timezone'],'day':day,'created_at':datetime.now(timezone.utc).isoformat(),
                 'sha256':hashlib.sha256(content).hexdigest(),'rows':rows,'source_type':'manual_workbook',
                 'current_day_partial':parsed_day==today_for(store)}
        with self.db() as con:
            con.execute('INSERT INTO tiktok_patrol_sources VALUES(?,?)',(ident,pack(value)))
        return self.preview(value)

    def preview(self, value):
        return {k:v for k,v in value.items() if k!='rows'} | {'modules':[
            {'id':k,'name':MODULES[k][0],'count':len(v),'sample':v[:3]} for k,v in value['rows'].items()]}

    def run(self, request):
        source = self.get(request.source_id, source=True)
        result = analyze(source['rows'], request.thresholds)
        ident = uuid.uuid4().hex
        value = {k:v for k,v in source.items() if k not in ('rows','id','created_at')}
        value.update(result, id=ident, source_id=source['id'], created_at=datetime.now(timezone.utc).isoformat(),
                     thresholds=request.thresholds.model_dump(),rule_version=RULE_VERSION,
                     scope_note='仅检查导入报表覆盖的对象，不代表全店完整采集。缺失模块未检查。'+
                     ('所选业务日尚未结束，本报告为当日部分数据。' if source['current_day_partial'] else ''))
        folder = self.hub.data / 'output/ai_workbench/tiktok_patrol' / ident
        folder.mkdir(parents=True, exist_ok=False)
        (folder/'report.json').write_text(pack(value), encoding='utf-8')
        (folder/'report.md').write_text(self.markdown(value), encoding='utf-8')
        (folder/'run.log').write_text(pack({'event':'local_rules_completed','run_id':ident,'source_sha256':source['sha256'],
                                           'rule_version':RULE_VERSION,'paid_ai':False,'browser_operations':0}),encoding='utf-8')
        with self.db() as con:
            con.execute('INSERT INTO tiktok_patrol_runs VALUES(?,?,?,?)',(ident,value['store_id'],value['day'],pack(value)))
        return value

    @staticmethod
    def markdown(value):
        # Plain lines rather than tables avoid untrusted data changing table structure.
        lines = ['# TikTok 日常巡检', f"店铺：{value['shop']} · {value['currency']}",
                 f"业务日期：{value['day']} · {value['timezone']}",f"覆盖模块：{value['coverage']}/7",value['scope_note'],
                 f"来源 SHA256：{value['sha256']}",f"规则：{value['rule_version']}", '']
        for f in value['findings']:
            lines.extend([f"## {f['priority']} · {f['module_name']} · {f['entity_name']}",
                          f"对象：{f['entity_id']}",f"依据：{f['reason']}",f"建议：{f['action']}",
                          f"来源：{f['source']}，工作表第 {f['source_row']} 行",''])
        if not value['findings']:
            lines.append('已导入数据未触发当前阈值；不代表缺失模块正常。')
        lines.append('阈值：'+pack(value['thresholds']))
        return '\n\n'.join(lines)

    def router(self):
        router = APIRouter(prefix='/api/hub/tiktok-patrol')

        @router.get('/status')
        def status(store_id:str=''):
            live_ids=(yaml.safe_load(self.selectors.read_text(encoding='utf-8')) or {}).get('tiktok_patrol_live',{}).get('reviewed_store_ids',[])
            stores = [{'store_id':k, **{x:v[x] for x in ('shop','currency','timezone')},
                       'yesterday':(today_for(v)-timedelta(days=1)).isoformat()} for k,v in load_stores(self.selectors).items()]
            if store_id:
                self.store(store_id)
            with self.db() as con:
                sql = 'SELECT value FROM tiktok_patrol_runs'
                args = ()
                if store_id:
                    sql += ' WHERE store_id=?'
                    args = (store_id,)
                saved = con.execute(sql+' ORDER BY rowid DESC LIMIT 30',args).fetchall()
            runs = [{k:v for k,v in json.loads(r[0]).items() if k not in ('findings','modules')} for r in saved]
            return {'stores':stores,'modules':[{'id':k,'name':v[0]} for k,v in MODULES.items()], 'runs':runs,
                    'defaults':runs[0]['thresholds'] if store_id and runs else Thresholds().model_dump(),
                    'browser_ready':store_id in live_ids,'live_ready_stores':live_ids,'scheduled':False,'paid_ai':False,
                    'source_note':'下方为报表导入巡检，支持 SKU 级规则检查；上方实时读取单独展示已核验店铺的销售、广告概览及当前待办，不混用两种数据口径。'}

        @router.get('/template')
        def template(store_id:str, day:str):
            store = self.store(store_id)
            try:
                date.fromisoformat(day)
            except ValueError:
                raise HTTPException(422,'日期格式错误') from None
            output = io.BytesIO()
            with pd.ExcelWriter(output,engine='openpyxl') as writer:
                instructions = [
                    ['填写要求','每个模块单独工作表；不需要的模块保持空表。模板不含业务数据。'],
                    ['店铺ID',store_id],['业务日期',day],['币种',store['currency']],['时区',store['timezone']],
                    ['对象粒度','销售/库存/评价按 SKU 或商品；广告按计划；健康/通知可按店铺。每表对象ID唯一，不混合汇总与明细。'],
                    ['日期口径','销量/广告/新增评价为选定业务日；库存/订单/健康/通知为该日结束时快照。近7日销量包含该日。'],
                    ['来源说明','写明后台报表名称、导出时间和统计窗口；空值不是零，未知模块留空表。'],
                    ['广告口径','广告归因收入/花费称 ROAS；并非净利润 ROI。各行使用同一归因窗口。'],
                    ['低星定义','仅商品评价1至3星，不混入店铺绩效评分。紧急通知数仅统计未读部分。'],
                    ['使用步骤','复制上述店铺ID/日期/币种/时区到数据行，填写真实数据 → 导入预览 → 确认并巡检。']]
                pd.DataFrame(instructions,columns=['项目','说明']).to_excel(writer,index=False,sheet_name='填写说明')
                for title, fields in MODULES.values():
                    pd.DataFrame(columns=list(COMMON.values())+list(fields.values())).to_excel(writer,index=False,sheet_name=title)
                for sheet in writer.book:
                    sheet.freeze_panes='A2'
                    for col in sheet.columns:
                        sheet.column_dimensions[col[0].column_letter].width=24
            return Response(output.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers={'Content-Disposition':'attachment; filename="tiktok-patrol-template.xlsx"'})

        @router.post('/sources')
        async def source(file:UploadFile=File(...),store_id:str=Form(...),day:str=Form(...)):
            content = await file.read(MAX_BYTES+1)
            return self.ingest(content,store_id,day)

        @router.post('/runs')
        def run(body:RunRequest):
            return self.run(body)

        @router.get('/sources/{ident}/file')
        def original(ident:str):
            value = self.get(ident,source=True)
            path = self.hub.data / 'raw/ai_workbench/tiktok_patrol' / value['id'] / 'source.xlsx'
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=value['sha256']:
                raise HTTPException(409,'原始报表缺失或校验失败，请检查本地归档')
            return FileResponse(path,filename='tiktok-patrol-source.xlsx')

        @router.get('/runs/{ident}')
        def detail(ident:str):
            return self.get(ident)

        @router.get('/runs/{ident}/report')
        def report(ident:str):
            value = self.get(ident)
            return Response(self.markdown(value),media_type='text/markdown; charset=utf-8',
                            headers={'Content-Disposition':'attachment; filename="tiktok-patrol-report.md"'})

        return router
