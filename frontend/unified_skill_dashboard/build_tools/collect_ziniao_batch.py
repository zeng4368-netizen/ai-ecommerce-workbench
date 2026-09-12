"""Explicit local onboarding runner; uses the same persistent batch queue as the UI.

No model call or data activation. Run only with user-authorized store scope.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--resume');args=parser.parse_args()
    if not args.run and not args.resume:parser.error('Use --run or --resume BATCH_ID explicitly')
    import server
    c=server.collection
    if c.settings()['enabled']:raise SystemExit('Pause automatic plan before manual onboarding; no paid analysis is allowed here.')
    check=c.check()
    if not check['ready']:raise SystemExit(check['message'])
    backup=server.PROJECT/'data/processed/ai_workbench'/('workbench_before_six_stores_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3')
    src=sqlite3.connect('file:'+str(server.DB)+'?mode=ro',uri=True);dest=sqlite3.connect(backup)
    src.backup(dest);dest.close();src.close()
    b=c.batch(args.resume) if args.resume else c.new_batch(origin='manual')
    print(json.dumps({'batch_id':b['id'],'backup':str(backup)},ensure_ascii=False),flush=True)
    worker=c.submit_batch(b['id'])
    while worker.is_alive():
        worker.join(10)
        b=c.batch(b['id'])
        print(json.dumps({'batch_id':b['id'],'counts':b['counts'],'files_ready':b['files_ready'],
            'runs':[{'id':j['id'],'shop':j['shop'],'state':j['state'],'error':j.get('error','')} for j in b['runs']]},ensure_ascii=False),flush=True)
