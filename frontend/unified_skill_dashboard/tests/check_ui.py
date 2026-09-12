"""Headless local UI checks in a fresh browser context, never using user profiles."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
SHOTS = PROJECT / 'data/screenshots/ai_workbench'
SHOTS.mkdir(parents=True, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1080}, device_scale_factor=1)
        page = context.new_page()
        test_tasks = {}
        def task_api(route):
            if route.request.method == 'PUT':
                test_tasks.clear()
                test_tasks.update(route.request.post_data_json['tasks'])
                route.fulfill(json={'saved': True})
            else:
                route.fulfill(json={'tasks': test_tasks})
        page.route('**/api/tasks', task_api)
        # This general regression must never spend API credits.
        page.route('**/api/health', lambda r: r.fulfill(json={'status': 'ok', 'llm': 'not_configured'}))
        page.route('**/api/analyses', lambda r: r.fulfill(json={'analyses': []}))
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto('http://127.0.0.1:8765/', wait_until='networkidle')
        page.get_by_role('heading', name='经营总览', exact=True).wait_for()
        assert page.locator('.chart svg').count() == 2
        page.screenshot(path=str(SHOTS / '01-overview.png'), full_page=True)
        page.locator('#navigation [data-route="ads"]').click()
        page.locator('#roiTarget').fill('12')
        page.locator('#roiTarget').dispatch_event('change')
        assert page.locator('#roiTarget').input_value() == '12'
        page.locator('[data-ad]').first.click()
        assert page.locator('dialog').is_visible()
        page.locator('.dialog-close').click()
        page.locator('#adSearch').fill('does-not-exist')
        page.get_by_text('当前筛选没有匹配数据。').wait_for()
        page.locator('#adSearch').fill('')
        page.locator('[data-ad]').first.wait_for()
        for route, title in [('inventory','日销与库存'),('creators','达人分析'),('finance','售后与利润'),('tasks','行动中心'),('assistant','AI 分析助理'),('data','数据与 Skill'),('portfolio','项目与面试演示')]:
            page.locator(f'#navigation [data-route="{route}"]').click()
            page.get_by_role('heading',name=title,exact=True).wait_for()
        page.locator('#presentButton').click()
        assert page.locator('#privacyButton').get_attribute('aria-pressed') == 'true'
        assert page.locator('#demoBar').is_visible()
        for i in range(5):
            page.locator('#demoNext').click()
        page.locator('#demoNext').click()
        assert not page.locator('#demoBar').is_visible()
        page.screenshot(path=str(SHOTS / '02-portfolio.png'), full_page=True)
        page.locator('#navigation [data-route="tasks"]').click()
        page.locator('[data-ac="legacy"]').click()
        task_key = page.locator('[data-task-state]').first.get_attribute('data-task-state')
        page.locator('[data-task-state]').first.select_option('doing')
        page.wait_for_function("document.querySelectorAll('.task-column')[1].querySelectorAll('.task-card').length === 1")
        page.reload(wait_until='networkidle')
        page.locator('[data-ac="legacy"]').click()
        assert page.locator('.task-column').nth(1).locator('.task-card').count() == 1
        page.locator('#navigation [data-route="assistant"]').click()
        page.locator('[data-action="run-model"]').click()
        page.get_by_text('尚未配置模型：', exact=False).wait_for()
        with page.expect_download() as dl:
            page.locator('[data-action="export-current"]').click()
        assert dl.value.suggested_filename.endswith('.md')
        page.locator('#navigation [data-route="data"]').click()
        page.locator('#importFile').set_input_files({'name':'invalid.csv','mimeType':'text/csv','buffer':b'wrong,header\n1,2'})
        page.get_by_text('预检未通过',exact=True).wait_for()
        assert not page.locator('#applyImport').is_visible()
        page.locator('#importFile').set_input_files(str(PROJECT / 'data/output/skill_embedded_tables_2026-09-02_2/01_GMV_Max/GMV_Max_逐行内嵌数据.xlsx'))
        page.get_by_text('表头预检通过', exact=True).wait_for()
        assert page.locator('#applyImport').is_visible()
        page.locator('#applyImport').click()
        page.get_by_role('heading', name='广告诊断',exact=True).wait_for()
        assert page.locator('.chart svg').count() == 2
        page.screenshot(path=str(SHOTS / '03-ad-diagnostics.png'), full_page=True)
        # Shared legacy file keeps one iframe for aftersales and profit.
        page.locator('#privacyButton').click()
        page.goto('http://127.0.0.1:8765/#legacy-after', wait_until='networkidle')
        page.frame_locator('iframe').locator('#afterSalesView').wait_for(state='visible')
        page.locator('[data-legacy="profit"]').click()
        page.frame_locator('iframe').locator('#profitView').wait_for(state='visible')
        assert page.locator('iframe').count() == 1
        page.locator('[data-route="overview"]').last.click()
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('heading', name='经营总览', exact=True).wait_for()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
        page.screenshot(path=str(SHOTS / '04-mobile.png'), full_page=True)
        page.locator('#menuButton').click()
        page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().left > -2")
        # Static offline entry also renders without API or CDN.
        offline = context.new_page()
        offline.goto((ROOT / 'index.html').as_uri(), wait_until='load')
        offline.get_by_role('heading',name='经营总览',exact=True).wait_for()
        assert offline.locator('.chart svg').count() == 2
        browser.close()
        assert not errors, errors
        print(json.dumps({'ui':'passed','screenshots':str(SHOTS),'page_errors':errors}))


if __name__ == '__main__':
    main()
