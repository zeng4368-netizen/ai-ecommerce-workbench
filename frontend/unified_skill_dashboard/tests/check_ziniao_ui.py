"""Read-only live pilot and mocked bill UI check; never clicks paid/run controls."""
import json
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    for _ in range(40):
        try:
            urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=1).close();break
        except OSError:time.sleep(.25)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8765/#data',wait_until='networkidle')
        page.get_by_role('heading',name='紫鸟自动采集',exact=True).wait_for()
        page.get_by_text('当月 1 日至当天（含当天）；当天截至导出时',exact=True).wait_for()
        page.locator('[data-z-job]').first.click()
        page.locator('.ziniao-detail h3').filter(has_text='任务详情').wait_for()
        page.get_by_text('70663.93',exact=True).wait_for()
        assert page.get_by_text('未启用 / 已暂停',exact=True).count()==1
        shots=Path(__file__).resolve().parents[3]/'data/screenshots/ai_workbench/ziniao';shots.mkdir(parents=True,exist_ok=True)
        page.locator('.ziniao-panel').screenshot(path=str(shots/'pilot-review-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.locator('.ziniao-panel').screenshot(path=str(shots/'pilot-review-mobile.png'))
        # Isolated browser fixture: validate bill-only UI without changing real data.
        bill={'version':'ui-test-only','summary':{'orders_available':False,'period':'2026-09-01 / 2026-09-11',
            'platform_timezone':'Asia/Kuala_Lumpur','currency':'MYR','rules':[],
            'completeness_note':'包含当天数据；当天仅截至导出时，不是完整自然日。',
            'settlement':{'transaction_count':1,'settlement':'10.10','revenue':None,'fees':None,'refund':'-1.20','adjustment':None}}}
        page.route('**/api/hub/ziniao/data?*',lambda route:route.fulfill(json=bill))
        page.locator('[data-z=data]').click()
        page.get_by_role('heading',name='TikTok 账单分析 · 独立口径',exact=True).wait_for()
        assert page.locator('[data-kind=settlement]').count()==1
        assert page.locator('[data-kind=orders]').count()==0
        assert page.get_by_text('10.10',exact=True).count()==1
        assert page.get_by_text('创建窗口每日订单数',exact=True).count()==0
        assert not errors,errors
        print(json.dumps({'page_errors':errors,'review_ready':True,'schedule_enabled':False,'screenshots':str(shots)}))
        browser.close()

if __name__=='__main__':main()
