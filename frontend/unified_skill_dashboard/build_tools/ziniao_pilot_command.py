"""CLI argument transport for the scoped, human-supervised report pilot."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziniao_bridge import Bridge
bridge=Bridge(Path(__file__).resolve().parents[3]/'config/selectors.yaml')
if len(sys.argv)!=3 or sys.argv[1] not in ('click','visit'): raise SystemExit('click selector | visit URL')
print(json.dumps(bridge.run(['page',sys.argv[1],'--store-id','27007200298613','--'+('selector' if sys.argv[1]=='click' else 'url'),sys.argv[2]],raw=True),ensure_ascii=False))
