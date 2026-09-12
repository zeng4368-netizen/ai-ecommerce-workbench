"""Integration smoke: isolated database, fresh browser, no real API calls or user profile."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=Path(tempfile.mkdtemp(prefix='commerce-hub-test-'))
    env={**os.environ,'WORKBENCH_DATA_DIR':str(folder),'WORKBENCH_LLM_MODEL':'','PYTHONIOENCODING':'utf-8'}
    log=(folder/'server.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--port','8767'],env=env,stdout=log,stderr=log)
    report={'test_data':str(folder),'pages':[]}
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen('http://127.0.0.1:8767/api/health',timeout=1);break
            except Exception:time.sleep(.25)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1080})
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8767/',wait_until='networkidle')
            page.get_by_role('heading',name='经营总览',exact=True).wait_for()
            for route,kind in [('ads','gmv'),('inventory','daily'),('finance','profit'),('after','after'),('creators','creator'),('marketing','marketing')]:
                page.locator(f'#navigation [data-route="{route}"]').click()
                frame=page.frame_locator('.hub-module')
                frame.locator('#hubModuleNote').wait_for(timeout=30000)
                report['pages'].append({'route':route,'note':frame.locator('#hubModuleNote').inner_text()})
                if route=='inventory':
                    child=page.locator('.hub-module').element_handle().content_frame()
                    actual=child.evaluate('({products:PRODUCTS,kpis:KPIS})')
                    workspace=page.evaluate('DataHub.current.data.daily')
                    assert actual['products']==workspace['products']
                    assert actual['kpis']==workspace['kpis']
                    for tab in ['shop','overdue','daily']:
                        frame.locator(f'.tab[data-template="{tab}"]').click()
                    shots=ROOT.parents[1]/'data/screenshots/ai_workbench';shots.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(shots/'10-integrated-daily.png'),full_page=True)
            page.locator('#navigation [data-route="tasks"]').click()
            page.locator('[data-ac="sync"]').click()
            page.wait_for_function("document.querySelectorAll('.action-card').length>0")
            page.locator('#acModule').select_option('daily')
            page.locator('#acSearch').fill('EXPOSE.TK');page.locator('#acSearch').press('Tab')
            page.get_by_text('71 项符合筛选',exact=True).wait_for()
            page.locator('[data-open-action]').first.click()
            page.get_by_role('button',name='查看业务明细',exact=True).click()
            page.locator('#actionSourceResults').get_by_text('任务来源明细',exact=False).wait_for()
            page.screenshot(path=str(shots/'14-integrated-daily-action.png'),full_page=True)
            page.evaluate("document.getElementById('detailDialog').close()")
            page.locator('#navigation [data-route="operations"]').click()
            page.locator('#opsShop').select_option('EXPOSE.TK')
            page.locator('#opsFilter').click()
            page.locator('#opsList').get_by_text('71',exact=True).wait_for()
            page.screenshot(path=str(shots/'15-operations-triage.png'),full_page=True)
            page.locator('[data-ops-open]').first.click()
            page.locator('#opsTrend canvas').wait_for()
            page.locator('#opsFeedback [name="verdict"]').select_option('data_issue')
            page.locator('#opsFeedback [name="reason"]').fill('TEST ONLY: check export completeness')
            page.locator('#opsFeedback button').click()
            page.get_by_text('历史人工反馈 1 条',exact=True).wait_for()
            page.locator('#opsAnnotation [name="occurred_on"]').fill('2026-06-08')
            page.locator('#opsAnnotation [name="note"]').fill('TEST ONLY: no platform changes')
            page.locator('#opsAnnotation [name="confirmed"]').check()
            page.locator('#opsAnnotation button').click()
            page.locator('.ops-timeline').get_by_text('TEST ONLY: no platform changes',exact=True).wait_for()
            page.screenshot(path=str(shots/'16-product-dossier.png'),full_page=True)
            page.locator('#opsProfile').screenshot(path=str(shots/'16-product-dossier-detail.png'))
            page.locator('#opsAsk').click()
            page.locator('#chatInput').wait_for()
            page.wait_for_function("document.querySelector('#chatInput').value.includes('EXPOSE.TK')")
            page.locator('#chatNew').click()
            assert page.locator('#chatInput').input_value()==''
            page.locator('#navigation [data-route="data"]').click()
            page.get_by_role('heading',name='一次导入，贯通业务').wait_for()
            content='库存SKU,SKU中文名,店铺,2026-09-01,2026-09-02\n1234567890123456789,TEST-PRODUCT,EXPOSE.TK,8,2\n'
            page.locator('#hubFiles').set_input_files({'name':'daily.csv','mimeType':'text/csv','buffer':content.encode()})
            page.locator('#hubPreview').click();page.locator('#hubActivate').wait_for()
            page.locator('#hubConfirm').check();page.locator('#hubImpact').click();page.locator('#hubActivate').click()
            page.wait_for_function("DataHub.current.data.daily.raw.daily.length===1")
            page.reload(wait_until='networkidle')
            page.get_by_role('heading',name='一次导入，贯通业务').wait_for()
            assert page.evaluate('DataHub.current.data.daily.raw.daily[0].库存SKU')=='1234567890123456789'
            page.locator('#hubShop').fill('EXPOSE.TK');page.locator('#hubQuery').click()
            page.get_by_text('匹配 1 条',exact=False).wait_for()
            page.screenshot(path=str(shots/'11-integrated-data-center.png'),full_page=True)
            page.locator('#navigation [data-route="inventory"]').click()
            frame=page.frame_locator('.hub-module');frame.locator('#hubModuleNote').wait_for()
            child=page.locator('.hub-module').element_handle().content_frame()
            assert child.evaluate('RAW.daily.length')==1
            # New-month aftersales upload must not leave the embedded May-Aug labels/data behind.
            import csv
            import io
            headers=['登记月份','订单商品数量','退包类型','收货状态','店铺','登记时间','一级类目','二级类目','三级类目','款名','商品成本价','sku处理结果','最后验货入库时间']
            output=io.StringIO();writer=csv.writer(output);writer.writerow(headers)
            writer.writerow(['2026-09',2,'买家退包','收货完成','TEST-S','2026-09-01','一级','二级','三级','TEST-P',5,'验货入库','2026-09-02'])
            writer.writerow(['2026-10',2,'邮局退包','待收货','TEST-S','2026-10-01','一级','二级','三级','TEST-Q',10,'待验货',''])
            job=context.request.post('http://127.0.0.1:8767/api/hub/imports/preview',multipart={'files':{'name':'after.csv','mimeType':'text/csv','buffer':output.getvalue().encode()}}).json()
            assert not job['entries'][0]['issues'],job
            version=page.evaluate('DataHub.current.version')
            response=context.request.post('http://127.0.0.1:8767/api/hub/imports/'+job['id']+'/activate',data={'expected_version':version,'confirmed':True,'selections':[{'id':job['entries'][0]['id'],'period':'2026-09-01/2026-10-31','currency':'CNY'}]})
            assert response.ok,response.text()
            page.evaluate('DataHub.reload()')
            page.locator('#navigation [data-route="after"]').click()
            frame=page.frame_locator('.hub-module');frame.locator('#hubModuleNote').wait_for()
            child=page.locator('.hub-module').element_handle().content_frame()
            assert child.evaluate('Object.keys(DAILY_KPI).includes("2026-09-01")')
            assert child.evaluate('STORE_DETAIL["TEST-S"][0][5].length')==2
            assert '9月' in frame.locator('#storeTable thead').inner_text()
            assert '10月' in frame.locator('#storeTable thead').inner_text()
            assert '30' in frame.locator('.kpi-cost .kpi-value').inner_text()
            assert '初始化失败' not in frame.locator('#hubModuleNote').inner_text()
            page.screenshot(path=str(shots/'12-integrated-after-import.png'),full_page=True)
            # Content forms and batch upload run only in this isolated TEST database.
            page.locator('#navigation [data-route="content-studio"]').click()
            page.locator('#csBrief [name="name"]').fill('TEST ONLY generated workflow')
            page.locator('#csBrief [name="facts"]').fill('TEST ONLY fact')
            page.locator('#csBrief [name="invariants"]').fill('TEST ONLY shape')
            page.locator('#csBrief [name="detail_count"]').select_option('7')
            page.get_by_role('button',name='创建任务并上传图片',exact=True).click()
            page.get_by_role('heading',name='TEST ONLY generated workflow',exact=True).wait_for()
            assert page.locator('.cs-shot').count()==16
            page.get_by_role('button',name='导入已有成品实例',exact=True).click()
            page.locator('#ceCreate [name="name"]').fill('TEST ONLY finished example')
            page.locator('#ceCreate [name="title"]').fill('TEST <script>window.BAD=true</script>')
            page.locator('#ceCreate [name="description"]').fill('### TEST ONLY\n\n- ORIGINAL\n<script>window.BAD=true</script>')
            page.locator('#ceCreate [name="detail_count"]').select_option('7')
            page.get_by_role('button',name='创建实例并上传成品图',exact=True).click()
            page.get_by_role('heading',name='TEST ONLY finished example',exact=True).wait_for()
            page.get_by_text('补充图片 / 上传新版本',exact=True).click()
            from PIL import Image
            pic=io.BytesIO();Image.new('RGB',(8,8),'white').save(pic,'PNG')
            page.locator('#ceFiles').set_input_files([{'name':'01.png','mimeType':'image/png','buffer':pic.getvalue()},
                                                   {'name':'02.png','mimeType':'image/png','buffer':pic.getvalue()}])
            page.get_by_role('button',name='确认图序并原样归档',exact=True).click()
            page.get_by_text('已归档 2/16 张',exact=True).wait_for()
            assert page.locator('.ce-gallery img').count()==2
            assert page.evaluate('window.BAD') is None
            report['content_workflow']={'task_slots':16,'example_originals':2,'escaped_untrusted_copy':True,'paid_api_calls':0}
            page.set_viewport_size({'width':390,'height':844})
            page.evaluate("location.hash='data'")
            page.get_by_role('heading',name='一次导入，贯通业务').wait_for()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            page.screenshot(path=str(shots/'13-integrated-mobile.png'))
            page.evaluate("location.hash='operations'")
            page.locator('#opsList table').wait_for()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            page.screenshot(path=str(shots/'17-operations-mobile.png'))
            report['errors']=errors
            context.close();browser.close()
            print(json.dumps(report,ensure_ascii=False,indent=2))
            assert not errors,errors
    finally:
        process.terminate();process.wait(timeout=15);log.close()
if __name__=='__main__':main()
