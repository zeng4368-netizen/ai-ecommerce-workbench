"""Refresh workbench snapshots from unchanged module HTML; never recalculate Skill metrics."""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / 'scripts'))
sys.path.insert(0, str(ROOT / 'build_tools'))
from export_embedded_skill_tables import extract_js_assignment, parse_js_literal


def build():
    files = list((ROOT / 'modules').glob('*.html')) + list((ROOT / 'skills').rglob('*'))
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if p.is_file() and '__pycache__' not in str(p)}
    gmv_path = next((ROOT / 'modules').glob('TikTok*.html'))
    gmv_text = gmv_path.read_text(encoding='utf-8')
    daily_text = (ROOT / 'modules/日销异常1.html').read_text(encoding='utf-8')
    after_text = (ROOT / 'modules/售后数据.html').read_text(encoding='utf-8')
    gmv = parse_js_literal(extract_js_assignment(gmv_text, 'EMBEDDED_PAYLOAD'))
    daily = json.loads(re.search(r'<script type="application/json" id="dashboardData">(.*?)</script>', daily_text, re.S)[1])
    bundle = {'version': 2, 'gmv': gmv, 'daily': daily,
              'bill': parse_js_literal(extract_js_assignment(after_text, 'BILL_DATA')),
              'creators': parse_js_literal(extract_js_assignment(after_text, 'MK_CREATOR_DETAIL')),
              'creatorTotal': parse_js_literal(extract_js_assignment(after_text, 'MK_CREATOR_TOTAL')),
              'sourceHashes': hashes}
    out = ROOT / 'assets/snapshot.js'
    out.parent.mkdir(exist_ok=True)
    out.write_text('window.WORKBENCH_DATA = ' + json.dumps(bundle, ensure_ascii=False).replace('</', '<\\/') + ';\n', encoding='utf-8')
    (ROOT / 'assets/source-integrity.json').write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Snapshot ready: {len(gmv["rows"])} ads, {len(daily["products"])} products, {len(bundle["bill"]["rows"])} bill rows.')


if __name__ == '__main__':
    build()
