"""Fresh headless UI with current read-only local API, no writes or paid calls.

Allows testing new code while a user-owned older workbench service is running.
"""
import json,sys,hashlib,io,zipfile
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import server

BATCH='4f568ffe190b4564a3679beac172dd19'

def main():
    sys.stdout.reconfigure(encoding='utf-8');api=TestClient(server.app)
    b=api.get('/api/hub/ziniao/batches/'+BATCH).json()
    assert b['files_ready']==6 and b['all_validated']
    r=api.get('/api/hub/ziniao/batches/'+BATCH+'/download');assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        manifest=json.loads(archive.read('manifest.json'));assert len(manifest['stores'])==6
        assert len(archive.namelist())==7
        for entry in manifest['stores']:
            name=next(n for n in archive.namelist() if entry['store_id'] in n)
            assert hashlib.sha256(archive.read(name)).hexdigest()==entry['sha256']
    out=server.PROJECT/'data/output/ai_workbench';out.mkdir(parents=True,exist_ok=True)
    bundle=out/('six_store_bills_20260901_20260911_'+BATCH[:8]+'.zip')
    if not bundle.exists():bundle.write_bytes(r.content)
    errors=[];posts=[];queries=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
        def intercept(route):
            req=route.request;u=urlsplit(req.url)
            if req.method=='POST':
                posts.append({'path':u.path,'body':req.post_data_json})
                return route.fulfill(json={'id':'ui-no-external-write'})
            if u.path.endswith('/data'):
                queries.append(parse_qs(u.query).get('store_id',[''])[0])
            result=api.get(u.path+('?' + u.query if u.query else ''))
            route.fulfill(status=result.status_code,body=result.content,content_type=result.headers.get('content-type','application/json'))
        page.route('**/api/hub/ziniao/**',intercept)
        page.goto('http://127.0.0.1:8765/#data',wait_until='networkidle')
        page.get_by_role('heading',name='紫鸟自动采集',exact=True).wait_for()
        assert page.locator('[data-store-run]').count()==6
        assert page.locator('[data-z=run]').is_enabled()
        assert page.get_by_role('link',name='下载全部原始账单 ZIP',exact=True).count()==1
        page.on('dialog',lambda d:d.accept())
        page.locator('[data-z=run]').click();page.wait_for_timeout(1500)
        assert len(posts)==1 and posts[0]['path'].endswith('/batches') and len(posts[0]['body']['store_ids'])==6
        rid=next(j['id'] for j in b['runs'] if j['currency']=='THB')
        page.locator('[data-z-job="'+rid+'"]').click()
        page.get_by_text('148709.34',exact=True).wait_for()
        assert page.locator('[data-j=activate]').count()==1
        page.locator('[data-z=data]').click()
        page.locator('[data-store-select]').select_option('27120369569623')
        page.wait_for_timeout(500)
        assert queries[-1]=='27120369569623'
        shots=server.PROJECT/'data/screenshots/ai_workbench/ziniao'
        page.locator('.ziniao-panel').screenshot(path=str(shots/'six-store-panel-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.locator('.ziniao-panel').screenshot(path=str(shots/'six-store-panel-mobile.png'))
        assert not errors,errors
        # An old backend cannot accidentally submit old single-store handlers.
        page.unroute('**/api/hub/ziniao/**');page.reload(wait_until='networkidle')
        if 'batch_supported' not in __import__('urllib.request',fromlist=['urlopen']).urlopen('http://127.0.0.1:8765/api/hub/ziniao/status').read().decode():
            assert page.locator('[data-z=run]').is_disabled()
        browser.close()
    print(json.dumps({'files':6,'bundle':str(bundle),'page_errors':errors,'post_requests_mocked':posts},ensure_ascii=False))

if __name__=='__main__':main()
