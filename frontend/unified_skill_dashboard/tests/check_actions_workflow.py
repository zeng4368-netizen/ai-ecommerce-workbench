"""Browser actions are intercepted by TestClient + temporary SQLite; zero real business state changes."""
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from test_server import server


def main():
    with tempfile.TemporaryDirectory(prefix='workbench-actions-test-') as folder:
        server.DB=Path(folder)/'test.sqlite3'
        def model(prompt,structured=False):
            data=json.loads(prompt[prompt.index('{"entity"'):])
            plan=dict(hypothesis='测试核查假设',steps=['核查当前状态','记录核查时点','请负责人复核'],acceptance='取得可回查证据',metric='当前状态',guardrail='不自动变更业务',missing_data=['实时记录'],evidence_ids=[data['evidence'][0]['id']])
            return dict(content=json.dumps(plan),model='TEST-MODEL',usage={'total_tokens':10},finish_reason='stop',provider='test')
        server.local_model=model
        client=TestClient(server.app)
        with sync_playwright() as p:
            b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
            page=b.new_page(viewport={'width':1440,'height':1080});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def intercept(route):
                request=route.request
                response=client.request(request.method,urlsplit(request.url).path,content=request.post_data or None,headers={'Content-Type':'application/json'})
                route.fulfill(status=response.status_code,content_type='application/json',body=response.text)
            page.route('**/api/actions**',intercept)
            page.goto('http://127.0.0.1:8765/#tasks',wait_until='networkidle')
            page.locator('[data-ac="sync"]').click();page.locator('[data-open-action]').first.click()
            page.locator('[data-op="ai"]').click();page.locator('.action-ai').wait_for()
            def operation(op):
                with page.expect_response('**/api/actions/*/update') as info:page.locator('[data-op="'+op+'"]').click()
                response=info.value;assert response.ok,response.text()
                item=response.json()['item'];page.wait_for_function('(v)=>document.querySelector(".action-form-head").textContent.includes("v"+v)',arg=item['version'])
                return item
            operation('adopt')
            page.locator('[name="owner"]').fill('TEST-OPERATOR');page.locator('[name="due_date"]').fill('2099-01-01')
            page.locator('[name="confirmed"]').check();assert operation('approve')['state']=='ready'
            assert operation('start')['state']=='doing'
            page.locator('[data-op="submit"]').click()
            page.locator('#actionError').get_by_text('提交验收需要',exact=False).wait_for()
            page.locator('[name="execution_note"]').fill('仅测试：已核查')
            page.locator('[name="result_evidence"]').fill('TEST-REPORT-001')
            page.locator('[name="observed_result"]').fill('仅测试：样本不足')
            assert operation('submit')['state']=='review'
            page.locator('[name="reviewer"]').fill('TEST-REVIEWER')
            page.locator('[name="conclusion"]').select_option('inconclusive')
            page.locator('[name="review_note"]').fill('仅验证流程，不声称实际改善')
            page.locator('[name="confirmed"]').check();task=operation('complete');assert task['state']=='done'
            page.keyboard.press('Escape');page.reload(wait_until='networkidle')
            page.locator('#acState').select_option('done');page.locator('[data-open-action]').first.click()
            assert page.locator('[name="conclusion"]').input_value()=='inconclusive'
            page.keyboard.press('Escape')
            with page.expect_download() as info:page.locator('[data-ac="export"]').click()
            assert info.value.suggested_filename.endswith('.xlsx')
            assert not errors,errors
            b.close()
    print('Full workflow UI passed: AI draft, adopt, approval, owner/date, execution evidence, review, persistence, export. Isolated DB only.')


if __name__=='__main__':main()
