"""Read-only browser smoke against the explicitly imported real example.

No paid APIs, no content mutation, no personal browser profile.
"""
import hashlib
import json
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT.parents[1]/'data'
SOURCE=DATA/'raw/content_studio/m98-user-example-20260908'
ident=json.loads((SOURCE/'registration.json').read_text(encoding='utf-8'))['id']
url='http://127.0.0.1:8765'
with urllib.request.urlopen(url+'/api/hub/content/projects/'+ident) as r:record=json.load(r)
assert record['example_count']==16
for i,asset in enumerate(record['assets'],1):
    with urllib.request.urlopen(url+'/api/hub/content/projects/'+ident+'/assets/'+asset['id']) as r:content=r.read()
    assert content==(SOURCE/f'{i:02}.png').read_bytes()
    assert hashlib.sha256(content).hexdigest()==asset['sha256']
shots=DATA/'screenshots/ai_workbench';shots.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1040});errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url+'/#content-studio',wait_until='networkidle')
    page.get_by_role('heading',name='内容工作室',exact=True).wait_for()
    page.get_by_role('heading',name='M98 TV Stick｜用户成品展示实例',exact=True).wait_for()
    assert page.locator('.ce-gallery img').count()==16
    assert page.locator('.ce-title').inner_text()==record['example']['title']
    page.screenshot(path=str(shots/'18-content-studio-example.png'),full_page=False)
    page.get_by_role('button',name='详情图',exact=True).click()
    assert page.locator('.ce-tile:visible').count()==7
    page.locator('.ce-gallery').screenshot(path=str(shots/'19-content-detail-gallery.png'))
    page.get_by_role('button',name='主图与副图',exact=True).click()
    assert page.locator('.ce-tile:visible').count()==9
    with page.expect_download() as info:page.get_by_role('link',name='下载整套实例 · 原文原图').click()
    assert info.value.suggested_filename.endswith('example.zip')
    page.get_by_role('button',name='＋ 新建生成任务',exact=True).click()
    assert page.locator('#csBrief [name=detail_count]').input_value()=='8'
    assert page.locator('#csBrief [name=facts]').is_visible()
    page.get_by_role('button',name='导入已有成品实例',exact=True).click()
    assert page.locator('#ceCreate').is_visible()
    page.locator('[data-cs-project="'+ident+'"]').click()
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(shots/'20-content-studio-mobile.png'),full_page=False)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.reload(wait_until='networkidle');page.locator('.ce-gallery img').first.wait_for()
    assert page.locator('.ce-gallery img').count()==16
    browser.close()
assert not errors,errors
print(json.dumps({'images_byte_identical':16,'main_secondary':9,'details':7,'reload_persisted':True,
                  'mobile_no_overflow':True,'browser_errors':errors},ensure_ascii=False))
