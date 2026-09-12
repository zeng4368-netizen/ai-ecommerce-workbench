"""Serve original calculation/view engines with a single immutable workspace version.

Only bootstrap, persistence and upload routing are adapted; the source files stay intact.
"""
from pathlib import Path
import json
import re
import sys
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'build_tools'))
from export_embedded_skill_tables import extract_js_assignment

FILES={'gmv':'TikTok_GMVMax广告经营管理看板v45_简约版_离线.html','daily':'日销异常1.html',
       'after':'售后数据.html','profit':'售后数据.html','creator':'售后数据.html','marketing':'广告数据.html'}

def safe_json(data): return json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')

def render_module(kind,current,history=False):
    if kind not in FILES: raise HTTPException(404)
    html=(ROOT/'modules'/FILES[kind]).read_text(encoding='utf-8')
    data=current['data']
    after_table=data.get('tables',{}).get('after')
    months=[]
    if after_table and '登记月份' in after_table['header']:
        col=after_table['header'].index('登记月份')
        months=list(dict.fromkeys(str(r[col])[:7] for r in after_table['rows'] if r[col]))
    def assignment(name,value):
        nonlocal html
        literal=extract_js_assignment(html,name)
        if literal is None: raise HTTPException(500,'原模块数据接口发生变化：'+name)
        html=html.replace(literal,safe_json(value),1)
    if kind=='gmv':
        payload=data['gmv']
        if history and data.get('gmv_history'):
            currency=current['meta']['datasets']['gmv'].get('currency','USD')
            batches=[b for b in data['gmv_history'] if b['currency']==currency]
            payload={**payload,'rows':[{**r,'__snapshotDate':r.get('__snapshotDate',b['payload']['snapshotDate'])} for b in batches for r in b['payload']['rows']]}
        assignment('EMBEDDED_PAYLOAD',payload)
    elif kind=='daily':
        html=re.sub(r'(<script type="application/json" id="dashboardData">).*?(</script>)',
                    lambda m:m[1]+safe_json(data['daily'])+m[2],html,flags=re.S)
        # Never let an older browser-local snapshot supersede the selected SQLite version.
        html=html.replace('const restored = await restoreSavedDashboardData();','const restored = false;')
    else:
        assignment('BILL_DATA',data['bill'])
        if 'MK_CREATOR_DETAIL' in html: assignment('MK_CREATOR_DETAIL',data['creators'])
        if 'MK_CREATOR_TOTAL' in html: assignment('MK_CREATOR_TOTAL',data['creatorTotal'])
        if 'MK_CREATOR_ROWS' in html: assignment('MK_CREATOR_ROWS',[[r[0],r[1],r[4],r[10],r[9],r[8]] for r in data['creators']])
        creator_period=current['meta']['datasets']['creator']['period']
        html=html.replace("m: '2026-07'",'m: '+safe_json(creator_period))
        html=html.replace('数据周期：2026-07','数据周期：'+creator_period).replace('仅 2026-07 一期数据','仅 '+creator_period+' 一期数据').replace('数据周期 2026-07','数据周期 '+creator_period)
        view_currency=current['meta']['datasets']['creator' if kind in ('creator','marketing') else 'bill'].get('currency','MYR')
        if view_currency!='MYR':
            html=html.replace("'RM'",safe_json(view_currency)).replace('(RM)','('+view_currency+')').replace('/RM','/'+view_currency)
        if months:
            # Data-dependent period axes. Same accumulation/formulas; no invented fifth slot or stale May-Aug labels.
            html=html.replace("['2026-05', '2026-06', '2026-07', '2026-08']",'window.HUB_MONTHS')
            html=html.replace("['5月', '6月', '7月', '8月']",'window.HUB_MONTHS.map(function(m){return parseInt(m.slice(5),10)+"月";})')
            marker=html.index('/* 店铺数据处理技能引擎')
            before,after=html[:marker],html[marker:]
            before=before.replace('i < 4;', 'i < window.HUB_MONTHS.length;')
            before=before.replace('[0,0,0,0]','Array(window.HUB_MONTHS.length).fill(0)').replace('[0, 0, 0, 0]','Array(window.HUB_MONTHS.length).fill(0)')
            before=before.replace("function sum8(a) { return a[0] + a[1] + a[2] + a[3]; }",'function sum8(a) { return a.reduce(function(s,v){return s+(Number(v)||0);},0); }')
            before=before.replace("'维度,类目,2026-05,2026-06,2026-07,2026-08,合计'","'维度,类目,'+window.HUB_MONTHS.join(',')+',合计'")
            # Preserve each slot's chronological meaning when the report starts outside the embedded May-Aug period.
            before=before.replace('var months = [];','var months = window.HUB_MONTHS.slice();')
            for field in ('post','buyer'):
                before=before.replace('['+', '.join(f'round2(o.{field}[{i}])' for i in range(4))+']',f'o.{field}.map(round2)')
            for field in ('postQ','buyerQ'):
                before=before.replace('['+', '.join(f'o.{field}[{i}]' for i in range(4))+']',f'o.{field}.slice()')
            before=before.replace("'¥'",safe_json(current['meta']['datasets']['after']['currency']+' '))
            html=before+after
    html=re.sub(r'<script src="https://[^\"]*xlsx[^\"]*"[^>]*></script>',
                '<script src="/assets/vendor/xlsx.full.min.js"></script>',html)
    style='''<style>
      html,body{background:#f5f7f3!important}body{margin:0!important}
      .sidebar,.nav-sidebar,aside.sidebar{display:none!important}
      .main,.main-content{margin-left:0!important}.app{grid-template-columns:1fr!important}
      .save-data-btn,#clearDataBtn{display:none!important}
      #hubModuleNote{position:sticky;top:0;z-index:900;background:#e8efe5;color:#345542;padding:9px 16px;font:12px/1.6 'Microsoft YaHei',sans-serif;border-bottom:1px solid #ccd9c6}
      #hubModuleNote button{float:right;border:0;background:none;color:#24593b;cursor:pointer}
    </style>'''
    config={'kind':kind,'version':current['version'],'meta':current['meta']['datasets'],
            'after':after_table,'months':months}
    boot='<script>window.HUB_MODULE='+safe_json(config)+';window.HUB_MONTHS=window.HUB_MODULE.months;</script><script src="/assets/module-bridge.js"></script>'
    html=html.replace('</head>',style+boot+'</head>',1)
    return html

def create_router(hub):
    router=APIRouter()
    @router.get('/api/hub/modules/{kind}',response_class=HTMLResponse)
    def module(kind:str,version:str='',history:bool=False):
        return HTMLResponse(render_module(kind,hub.current(version),history),headers={'Cache-Control':'no-store'})
    return router
