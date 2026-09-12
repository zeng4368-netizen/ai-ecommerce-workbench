"""One explicitly enabled live DeepSeek query; persists a real analysis record."""
import argparse
import json
from pathlib import Path
import urllib.request

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:raise SystemExit('Add --live only when a paid model validation is intended.')
    base='http://127.0.0.1:8765'
    with urllib.request.urlopen(base+'/api/hub/workspace',timeout=30) as r:current=json.load(r)
    payload={'version':current['version'],'scope':'daily','question':'EXPOSE TK 日销哪些产品下滑？只列末日减少最多的前5款，给出前日、末日和变化量，不给建议。'}
    request=urllib.request.Request(base+'/api/hub/assistant',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=300) as response:result=json.load(response)
    evidence=result.get('evidence',[])
    assert evidence and all(e['version']==current['version'] for e in evidence)
    assert '让我确认' not in result['content'] and '用户要求' not in result['content'], 'Model included self-review instead of a direct answer'
    output={'analysis_id':result['id'],'model':result['model'],'version':result['version'],'usage':result['usage'],
            'tools':[{'tool':e['tool'],'arguments':e['arguments'],'total':e['result'].get('total'),'returned':len(e['result'].get('rows',[]))} for e in evidence],
            'content':result['content']}
    target=Path(__file__).resolve().parents[3]/'data/output/ai_workbench'
    target.mkdir(parents=True,exist_ok=True)
    (target/('tool_query_validation_'+result['id']+'.json')).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
