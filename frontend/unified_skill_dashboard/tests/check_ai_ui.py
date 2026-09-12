"""Fresh-browser AI integration check. --live makes one explicitly requested billable call."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1080})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        if not args.live:
            page.route('**/api/health', lambda r: r.fulfill(json={'status': 'ok', 'llm': 'configured', 'model': 'mock-model', 'provider': 'mock'}))
            page.route('**/api/analyses', lambda r: r.fulfill(json={'analyses': []}))
            def analyze(route):
                payload = route.request.post_data_json
                assert 'ADS-1' in payload['prompt'] and 'FINANCE' in payload['prompt']
                route.fulfill(json={'content': '事实：ADS 总成本 1027.883 USD。建议人工核实。', 'model': 'mock-model', 'provider': 'mock', 'id': 'mock-test', 'created_at': '2026-09-07T00:00:00Z', 'usage': {'total_tokens': 99}, 'evidence_sha256': 'test-hash', 'finish_reason': 'stop'})
            page.route('**/api/analyze', analyze)
        page.goto('http://127.0.0.1:8765/#assistant', wait_until='networkidle')
        page.get_by_role('heading', name='AI 分析助理', exact=True).wait_for()
        page.locator('#aiQuestion').fill('请根据全部四个模块的历史数据，整理给运营负责人看的经营诊断。每个模块至少一项发现；列出有证据编号、商品或达人、风险和优先级的具体行动，给出三天验证计划。不同币种和周期不能相加，不能声称已经带来收益。')
        with page.expect_response('**/api/analyze', timeout=150000) as response_info:
            page.locator('[data-action="run-model"]').click()
        response = response_info.value
        result = response.json()
        if not response.ok:
            print(json.dumps({'status': response.status, 'detail': result.get('detail')}, ensure_ascii=False))
            browser.close()
            raise SystemExit(1)
        page.wait_for_function("document.querySelector('#briefText').textContent.includes('真实模型生成')")
        assert not errors, errors
        page.locator('[data-action="view-evidence"]').click()
        assert 'ADS-1' in page.locator('#detailDialog').inner_text()
        page.keyboard.press('Escape')
        if args.live:
            folder = ROOT.parents[1] / 'data/output/ai_workbench'
            folder.mkdir(parents=True, exist_ok=True)
            report = folder / ('DeepSeek_经营分析_' + result['id'] + '.md')
            report.write_text('真实模型生成 · 待人工复核\n\n模型：' + result['model'] + '\n运行编号：' + result['id'] + '\n输入 SHA256：' + result['evidence_sha256'] + '\n\n' + result['content'], encoding='utf-8')
            page.screenshot(path=str(ROOT.parents[1] / 'data/screenshots/ai_workbench/05-deepseek-analysis.png'), full_page=True)
            print(json.dumps({'live': True, 'model': result['model'], 'id': result['id'], 'usage': result['usage'], 'finish_reason': result['finish_reason'], 'report': str(report)}, ensure_ascii=False))
        else:
            page.locator('#navigation [data-route="overview"]').click()
            page.locator('#navigation [data-route="assistant"]').click()
            assert 'mock-model' in page.locator('#briefText').inner_text()
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            print('AI UI passed: evidence, real-call path mocked, report preserved, mobile layout, no JS errors.')
        browser.close()


if __name__ == '__main__':
    main()
