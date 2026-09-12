"""Create a local audit checkpoint for the explicitly approved real export pilot.

Does not click, download, activate data or call an LLM. Repeated invocations reuse
the active pilot. The verified download folder comes from store open/extract.
"""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import collection
from ziniao_collection import STORE

kind=sys.argv[1]
if kind not in ('orders','settlement'):raise SystemExit('orders or settlement required')
with collection.db() as con:
    row=con.execute("SELECT value FROM ziniao_runs WHERE store_id=? AND state IN ('queued','paused')",(STORE,)).fetchone()
job=json.loads(row[0]) if row else collection.new_run('pilot')
folder=Path('C:/Users/PC/AppData/Roaming/ziniaobrowserdatas/ziniao browser/MS0237-EXPOSE．TK')
job.setdefault('exports',{}).setdefault(kind,{'before':{f.name:[f.stat().st_size,f.stat().st_mtime_ns] for f in folder.iterdir() if f.is_file()},'submitted_at':time.time(),'history_before':'All order-2026-09-10-02:47.xlsx' if kind=='orders' else ''})
job.update(state='paused',error='真实单店导出联调中；尚未激活数据或启用定时',download_folder=str(folder))
collection.save(job)
print(json.dumps(collection.public(job),ensure_ascii=False))
