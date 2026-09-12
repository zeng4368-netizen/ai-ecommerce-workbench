"""Read-only DOM metadata inspection for the explicitly scoped EXPOSE.TK pilot.

No cookies, storage, customer fields, network requests or page writes.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziniao_bridge import Bridge
import json

bridge=Bridge(Path(__file__).resolve().parents[3]/'config/selectors.yaml')
script="""JSON.stringify({url:location.href,
buttons:[...document.querySelectorAll('button')].map(e=>({text:e.innerText,attributes:[...e.attributes].map(a=>[a.name,a.value])})),
inputs:[...document.querySelectorAll('input')].filter(e=>e.type!=='checkbox').map(e=>({placeholder:e.placeholder,type:e.type,cls:e.className,readOnly:e.readOnly,dateValue:['自','至'].includes(e.placeholder)?e.value:undefined})),
identity:[...document.querySelectorAll('span,div')].filter(e=>e.children.length===0&&e.textContent.trim()==='EXPOSE TK').map(e=>e.outerHTML),
tabs:[...document.querySelectorAll('[role=tab]')].map(e=>({text:e.innerText,id:e.id})),
dialogs:[...document.querySelectorAll('[role=dialog]')].map(e=>({text:e.innerText,cls:e.className})),
links:[...document.querySelectorAll('a[href]')].map(e=>({text:e.innerText,url:e.href})).filter(e=>/finance|settle|statement/.test(e.url))})"""
if '--popover' in sys.argv:
    script="""JSON.stringify([...document.querySelectorAll('.p-popover-content,.p-trigger-popup,.p-modal')].filter(e=>e.getClientRects().length).map(e=>e.outerHTML))"""
elif '--finance' in sys.argv:
    script="""JSON.stringify({url:location.href,inputs:[...document.querySelectorAll('input')].filter(e=>/日期/.test(e.placeholder)).map(e=>({value:e.value,html:e.parentElement.parentElement.outerHTML})),dialog:[...document.querySelectorAll('[role=dialog]')].map(e=>e.outerHTML),pickers:[...document.querySelectorAll('[class*=picker]')].filter(e=>/开始|结束/.test(e.textContent)&&e.textContent.length<200).map(e=>e.outerHTML).slice(0,8)})"""
elif '--download-dom' in sys.argv:
    script="""JSON.stringify([...document.querySelectorAll('[role=dialog] *')].filter(e=>e.children.length===0&&/\\.(csv|xlsx)$/.test(e.textContent.trim())).map(e=>({text:e.textContent,html:e.parentElement.parentElement.outerHTML})))"""
elif '--history' in sys.argv:
    script="""JSON.stringify({url:location.href,dialogs:[...document.querySelectorAll('[role=dialog]')].map(e=>({text:e.innerText,rows:[...e.querySelectorAll('tr')].map(r=>r.outerHTML.slice(0,4000))})),radio:[...document.querySelectorAll('[role=dialog] label')].map(e=>e.outerHTML)})"""
elif '--calendar' in sys.argv:
    script="""JSON.stringify({dateInputs:[...document.querySelectorAll('input')].filter(e=>['自','至'].includes(e.placeholder)).map(e=>({value:e.value,html:e.parentElement.outerHTML})),
    headers:[...document.querySelectorAll('[class*=picker-header]')].map(e=>({text:e.innerText,cls:e.className})),
    calendars:[...document.querySelectorAll('.p-picker-cell:not(.p-picker-cell-disabled)')].map(e=>({html:e.outerHTML,parent:e.parentElement.parentElement.outerHTML.slice(0,180)})).slice(0,50)})"""
value=bridge.run(['page','exec','--store-id','27007200298613','--script',script])
if isinstance(value,dict) and isinstance(value.get('result'),str):
    value=json.loads(value['result'])
if isinstance(value,dict) and 'buttons' in value:
    value['buttons']=[b for b in value['buttons'] if b['text'] not in ('打印单据','联系承运商','更多操作','安排发货','安排发货并打印')]
print(json.dumps(value,ensure_ascii=False,indent=2))
