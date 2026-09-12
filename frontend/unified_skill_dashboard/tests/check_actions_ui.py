"""Real UI: --live only syncs candidates and generates ONE AI draft; never approves business work."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1080})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8765/#tasks',wait_until='networkidle')
        page.locator('[data-ac="sync"]').wait_for()
        if args.live:
            with page.expect_response('**/api/actions/sync') as info:
                page.locator('[data-ac="sync"]').click()
            assert info.value.ok
            page.locator('[data-open-action]').first.wait_for()
        count=page.locator('[data-open-action]').count()
        assert count>0
        page.screenshot(path=str(ROOT.parents[1]/'data/screenshots/ai_workbench/06-action-center.png'),full_page=True)
        page.locator('[data-open-action]').first.click()
        page.locator('#actionForm').wait_for()
        if args.live:
            with page.expect_response('**/api/actions/*/ai',timeout=150000) as info:
                page.locator('[data-op="ai"]').click()
            response=info.value
            if not response.ok:
                print(json.dumps(response.json(),ensure_ascii=False));raise SystemExit(1)
            result=response.json()
            assert result['item']['state']=='candidate'
            page.locator('.action-ai').wait_for()
            print(json.dumps({'live_ai':True,'model':result['run']['model'],'usage':result['run']['usage'],'task':result['item']['id'],'state':result['item']['state'],'evidence_ids':result['run']['plan']['evidence_ids']},ensure_ascii=False))
        # Read-only draft/evidence inspection. All transition tests use isolated SQLite in pytest.
        page.screenshot(path=str(ROOT.parents[1]/'data/screenshots/ai_workbench/07-action-detail.png'),full_page=True)
        page.keyboard.press('Escape')
        page.reload(wait_until='networkidle')
        page.locator('[data-open-action]').first.wait_for()
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        page.screenshot(path=str(ROOT.parents[1]/'data/screenshots/ai_workbench/08-actions-mobile.png'),full_page=True)
        browser.close()
        print('Action UI passed: persistence, modal, responsive layout, no JavaScript errors.')


if __name__=='__main__':main()
