// Isolated DOM tests. All API responses synthetic, all writes intercepted.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const dom = new JSDOM('<main id="host"></main>', {url:'http://localhost/#tiktok-patrol',runScripts:'outside-only'});
const w=dom.window, host=w.document.getElementById('host'), writes=[];
const defaults={sales_change_pct:30,stock_units:10,stock_days:14,ad_roas:2,ad_min_spend:10,negative_count:1};
const stores=[{store_id:'s1',shop:'TEST MY',currency:'MYR',timezone:'Asia/Kuala_Lumpur',yesterday:'2026-09-13'},
 {store_id:'s2',shop:'TEST TH',currency:'THB',timezone:'Asia/Bangkok',yesterday:'2026-09-13'}];
const modules=[{id:'sales',name:'销售复盘'},{id:'inventory',name:'库存预警'}];
let saved=false;
const report={id:'a'.repeat(32),store_id:'s1',shop:'TEST MY',currency:'MYR',timezone:'Asia/Kuala_Lumpur',day:'2026-09-13',
 created_at:'2026-09-14T01:00:00Z',coverage:1,rule_version:'tiktok_daily_v1',sha256:'b'.repeat(64),thresholds:defaults,scope_note:'缺失模块未检查',
 modules:[{id:'sales',name:'销售复盘',rows:1,findings:1,status:'attention'},{id:'inventory',name:'库存预警',rows:0,findings:0,status:'missing'}],
 findings:[{priority:'P1',module_name:'销售复盘',entity_name:'<img src=x onerror=alert(1)>',entity_id:'sku1',reason:'销量下滑50%',action:'检查库存',source:'合成报表',source_row:2}]};
w.fetch=async (url,options={})=>{
 if(options.method==='POST')writes.push(url);
 if(url.includes('/status'))return {ok:true,json:async()=>({stores,modules,defaults,runs:saved?[report]:[],source_note:'自动读取待联调'})};
 if(url.endsWith('/sources'))return {ok:true,json:async()=>({id:'c'.repeat(32),...stores[0],day:'2026-09-13',modules:[{id:'sales',name:'销售复盘',count:1,sample:[{entity_id:'sku1',sales:1}]}]})};
 if(url.endsWith('/runs')){saved=true;return {ok:true,json:async()=>report};}
 if(url.includes('/runs/'))return {ok:true,json:async()=>report};
 throw Error('Unexpected request '+url);
};
w.eval(fs.readFileSync(path.join(__dirname,'../assets/tiktok-patrol.js'),'utf8'));
async function settle(){for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));}
(async()=>{
 await w.TikTokPatrol.mount(host,{toast:message=>{throw Error(message);},masked:false});
 assert(host.textContent.includes('TikTok 日常巡检'));
 assert.equal(host.querySelectorAll('[data-store] option').length,3);
 assert(host.querySelector('[data-run]').disabled);
 assert.equal(writes.length,0);assert(host.querySelector('[data-range-start]'));assert(host.querySelector('[data-range-end]'));assert(!host.textContent.includes('本地规则 · 不调用付费 AI'));
 const file=host.querySelector('[data-file]');
 Object.defineProperty(file,'files',{value:[new w.File(['test'],'test.xlsx')]});
 file.dispatchEvent(new w.Event('change'));await settle();
 assert(host.textContent.includes('核对导入数据'));
 assert(!host.querySelector('[data-run]').disabled);
 host.querySelector('[data-run]').click();await settle();
 assert(host.textContent.includes('缺失模块未检查'));
 assert(host.textContent.includes('销量下滑50%'));
 assert.equal(host.querySelectorAll('[data-findings] img').length,0);
 const priority=host.querySelector('[data-priority]');priority.value='P0';priority.dispatchEvent(new w.Event('change'));
 assert(host.textContent.includes('当前优先级没有事项'));
 const shop=host.querySelector('[data-store]');shop.value='s2';shop.dispatchEvent(new w.Event('change'));await settle();
 assert(!host.textContent.includes('Asia/Bangkok'),'timezone helper text was intentionally removed');
 assert.equal(host.querySelector('[data-store]').value,'s2');
 assert(host.querySelector('[data-run]').disabled);
 assert.equal(writes.length,2);
 await w.TikTokPatrol.mount(host,{toast:()=>{},masked:true});
 assert(host.textContent.includes('关闭演示脱敏'));
 console.log('PASS: mount, import preview, manual run, escaping, priority filter, shop isolation, privacy; no live writes');
 dom.window.close();
})().catch(err=>{console.error(err);process.exitCode=1;dom.window.close();});
