"""Validate and archive the two explicitly identified real pilot files.

No export submission, workspace activation, paid AI call or schedule enablement.
"""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import collection
from ziniao_bridge import load_profile,profile_hash
from ziniao_reports import parse_report,metrics,content_fingerprint
from ziniao_tiktok import TikTokUI
parser=argparse.ArgumentParser();parser.add_argument('--prepare',choices=['orders','settlement']);parser.add_argument('--resume-receipts',action='store_true');parser.add_argument('--screenshot',action='store_true');args=parser.parse_args()
job=collection.get('0b4d85354f5e4dc2842d0fd652ffac50')
profile=load_profile(collection.bridge.selectors)
if args.screenshot:
    ui=TikTokUI(collection.bridge,profile,job);ui.check()
    job.setdefault('validation_screenshots',{})['export_history']=ui.screenshot(collection.hub.data/'screenshots/ai_workbench/ziniao','export-history')
    collection.save(job);print('Saved real export history screenshot');raise SystemExit()
if args.prepare:
    ui=TikTokUI(collection.bridge,profile,job)
    ui.prepare(args.prepare)
    job.setdefault('validation_screenshots',{})[args.prepare]=ui.screenshot(collection.hub.data/'screenshots/ai_workbench/ziniao',args.prepare)
    print(json.dumps({'kind':args.prepare,'expected_order_count':job.get('expected_order_count'),'history':ui.history(profile['reports'][args.prepare])},ensure_ascii=False))
    collection.save(job)
    raise SystemExit()
if args.resume_receipts:
    # Test recovery from actual prior platform jobs, with no second export submission.
    job['profile_hash']=profile_hash(profile);job['files']={}
    collection.bridge.collect(job,collection.save,collection.hub.data/'raw/ai_workbench/imports'/job['id'],collection.hub.data/'screenshots/ai_workbench/ziniao')
    collection.save(job)
    print(json.dumps({'verified_receipts':list(job['files'])},ensure_ascii=False))
    raise SystemExit()
files={'orders':'全部 笔订单-2026-09-11-12_12.csv','settlement':'income_20260911122255(UTC+8).xlsx'}
reports={};folder=collection.hub.data/'raw/ai_workbench/imports'/job['id'];folder.mkdir(parents=True,exist_ok=True)
for kind,name in files.items():
    source=Path(job['download_folder'])/name
    cp=job['exports'][kind]
    if source.stat().st_mtime < cp['submitted_at']:raise SystemExit('File predates submission')
    content=source.read_bytes();dest=folder/(kind+source.suffix)
    if dest.exists():
        if dest.read_bytes()!=content:raise SystemExit('Immutable original differs')
    else:
        with dest.open('xb') as out:out.write(content)
    job['files'][kind]={'name':name,'saved_name':dest.name,'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    cp['platform_name']=name.replace('12_12','12:12')
    reports[kind]=parse_report(content,name,kind,profile['reports'][kind]['schema'],job['start'],job['end'],'MYR')
if len({r['order_id'] for r in reports['orders']['rows']})!=1040:raise SystemExit('Count differs from platform')
job['expected_order_count']=1040
job['profile_hash']=profile_hash(profile)
job['snapshot']={'store_id':job['store_id'],'shop':job['shop'],'currency':'MYR','start':job['start'],'end':job['end'],'platform_timezone':profile['platform_timezone'],'reports':reports,'job_id':job['id'],'fingerprint':content_fingerprint(reports)}
job.update(summary=metrics(job['snapshot']),state='pending_review',error='真实文件已对账，等待人工确认首批导入；定时和 AI 均未启用')
collection.save(job)
from data_hub import pack
with collection.hub.db() as con:
    con.execute('INSERT OR REPLACE INTO hub_jobs VALUES(?,?)',(job['id'],pack({'id':job['id'],'created_at':job['created_at'],'entries':[],'errors':[],'originals':[{'id':k,**v} for k,v in job['files'].items()],'origin':'ziniao','note':'TikTok 原生首批；需从紫鸟采集面板成对审核，不进入马帮流水线'})))
print(json.dumps(collection.public(job),ensure_ascii=False,indent=2))
