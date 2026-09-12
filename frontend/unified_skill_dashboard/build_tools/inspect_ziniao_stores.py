"""Read-only identities in already-open stores; no customer rows or credentials."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziniao_bridge import Bridge
from ziniao_tiktok import TikTokUI

IDS=['27183507534672','27144576844226','27123379972927','27120369569623','27007200298613','26896910699218']
SCRIPT='''JSON.stringify({url:location.origin+location.pathname,
identity:[...document.querySelectorAll('span.ub-text-db8f13')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),
links:[...document.querySelectorAll('a[href*=finance]')].map(e=>e.getAttribute('href'))})'''
CONTROLS='''JSON.stringify({identity:[...document.querySelectorAll('span.ub-text-db8f13')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),buttons:[...document.querySelectorAll('button')].filter(e=>e.getClientRects().length).map(e=>({text:e.textContent.trim(),tid:e.getAttribute('data-tid'),dtid:e.getAttribute('datatid')})).filter(e=>e.tid||e.dtid),top:document.body.innerText.slice(0,800)})'''

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    bridge=Bridge(Path(__file__).resolve().parents[3]/'config/selectors.yaml')
    for ident in IDS:
        try:
            if '--calendar' in sys.argv:
                profile=bridge.profile(store_id=ident);ui=TikTokUI(bridge,profile,{'store_id':ident,'id':'preflight-'+ident})
                recipe=profile['reports']['settlement']
                ui.click(recipe['entry_selector'],expect=recipe['date_open_selector']);ui.click(recipe['date_open_selector'])
                print(ident,'CALENDAR',json.dumps(ui.read("({headers:[...document.querySelectorAll('.p-picker-header-value')].map(e=>e.textContent),buttons:[...document.querySelectorAll('.p-popover-content button')].map(e=>({text:e.textContent,cls:e.className}))})"),ensure_ascii=False),flush=True)
                ui.screenshot(Path(__file__).resolve().parents[3]/'data/screenshots/ai_workbench/ziniao','calendar')
                ui.click(recipe['cancel_selector'])
                continue
            if '--finance' in sys.argv:
                region='TH' if ident=='27120369569623' else 'MY'
                bridge.run(['page','visit','--store-id',ident,'--url',f'https://seller-{region.lower()}.tiktok.com/finance/transactions?tab=settled_tab&shop_region={region}', '--wait-until','domcontentloaded','--timeout','20000'])
            print(ident,json.dumps(bridge.run(['page','exec','--store-id',ident,'--script',CONTROLS if '--controls' in sys.argv else SCRIPT]),ensure_ascii=False),flush=True)
        except Exception as exc:print(ident,getattr(exc,'detail',type(exc).__name__),flush=True)
