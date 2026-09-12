"""Question-focused regression. --live sends this single user-requested question to DeepSeek."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
QUESTION='expose tk的日销哪个产品是异常的'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    with sync_playwright() as p:
        b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=b.new_page(viewport={'width':1440,'height':1080});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        if not args.live:
            page.route('**/api/health',lambda r:r.fulfill(json={'status':'ok','llm':'configured','model':'mock','provider':'mock'}))
            page.route('**/api/analyses',lambda r:r.fulfill(json={'analyses':[]}))
            def mock(route):
                payload=route.request.post_data_json
                assert payload['scope']=='daily'
                e=json.loads(payload['prompt'].split('输入证据 JSON：\n')[1]);assert len(e['sources'])==1
                assert e['sources'][0]['shops']==['EXPOSE.TK']
                route.fulfill(json={'content':'EXPOSE.TK 日销：3C-手卷电子7垫鼓从11件降至6件，减少5件。','id':'question-mock','model':'mock','provider':'mock','created_at':'2026-09-07T00:00:00Z','evidence_sha256':'mock','usage':{},'finish_reason':'stop'})
            page.route('**/api/analyze',mock)
        page.goto('http://127.0.0.1:8765/#assistant',wait_until='networkidle')
        page.locator('#aiAnswerMode').wait_for();assert page.locator('#aiAnswerMode').input_value()=='auto'
        # Question takes precedence over a previously selected unrelated tab.
        page.locator('[data-brief-scope="ads"]').click()
        page.locator('#aiQuestion').fill(QUESTION)
        page.locator('[data-action="view-evidence"]').click()
        page.wait_for_function("document.querySelector('#detailDialog').textContent.includes('DAILY')")
        evidence=page.locator('#detailDialog').inner_text();assert 'EXPOSE.TK' in evidence and 'CREATOR' not in evidence
        page.keyboard.press('Escape')
        with page.expect_response('**/api/analyze',timeout=150000) as info:page.locator('[data-action="run-model"]').click()
        response=info.value;assert response.ok,response.text();result=response.json()
        page.wait_for_function("document.querySelector('#briefText').textContent.includes('真实模型生成')")
        if args.live:
            assert not any(s in result['content'] for s in ['三日验证计划','优先行动表','三天验证计划','达人合作复盘'])
            folder=ROOT.parents[1]/'data/output/ai_workbench';folder.mkdir(parents=True,exist_ok=True)
            path=folder/('DeepSeek_定向日销问答_'+result['id']+'.md')
            path.write_text('# '+QUESTION+'\n\n'+result['content'],encoding='utf-8')
            page.screenshot(path=str(ROOT.parents[1]/'data/screenshots/ai_workbench/09-question-focused.png'),full_page=True)
            print(json.dumps({'live':True,'id':result['id'],'scope':'daily','model':result['model'],'usage':result['usage'],'report':str(path)},ensure_ascii=False))
        page.locator('#navigation [data-route="overview"]').click();page.locator('#navigation [data-route="assistant"]').click()
        assert page.locator('#aiQuestion').input_value()==QUESTION
        assert not errors,errors
        b.close()
    print('Question UI passed: shop evidence only, overrides old tab, no forced report, question preserved.')


if __name__=='__main__':main()
