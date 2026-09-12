"""Non-destructive, timestamped backup before data-hub migration."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import shutil
import sqlite3

root=Path(__file__).resolve().parents[1]
project=root.parents[1]
target=project/'data/output/ai_workbench_backups'/datetime.now().strftime('%Y%m%d_%H%M%S')
target.mkdir(parents=True,exist_ok=False)
for name in ('modules','skills'):
    shutil.copytree(root/name,target/name,ignore=shutil.ignore_patterns('__pycache__'))
db=project/'data/processed/ai_workbench/workbench.sqlite3'
if db.exists():
    with sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True) as source, sqlite3.connect(target/'workbench.sqlite3') as dest:
        source.backup(dest)
hashes={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
(target/'manifest.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
print(target)
