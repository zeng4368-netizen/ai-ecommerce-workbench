// Synthetic DOM verification, no real shop/API writes.
const {JSDOM}=require('jsdom');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const dom=new JSDOM('<main><div class="patrol-heading">巡检</div></main>',{url:'http://localhost',runScripts:'outside-only'});
const w=dom.window;w.ResizeObserver=class{observe(){}disconnect(){}};const host=w.document.querySelector('main');let posts=0,ready=true;
const section={period:'2026-09-13',captured_at:'2026-09-14T01:00:00Z',source_url:'https://seller-my.tiktok.com/homepage',sha256:'abc',
 data:[{label:'GMV',value:100,currency:'MYR',change_pct:10}]};
const r={id:'a'.repeat(32),created_at:'2026-09-14T01:00:00Z',day:'2026-09-13',shop:'测试店',timezone:'Asia/Kuala_Lumpur',state:'complete',step:'完成',scope:'仅概览',
 sections:{sales:section,ads:{...section,currency:'USD',data:[{label:'成本',value:10,currency:'USD'}]},homepage:{...section,data:{cards:[{label:'待发货',value:5,detail:'紧急：2'}],health:'<img src=x onerror=alert(1)>',scope:'紧急不等于超时'}}}};
w.fetch=async(url,opts={})=>{if(opts.method==='POST'){posts++;return {ok:true,json:async()=>r};}return {ok:true,json:async()=>({ready,runs:[r],scope:'只读概览'})};};
w.eval(fs.readFileSync(path.join(__dirname,'../assets/tiktok-patrol-live.js'),'utf8'));
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 w.TikTokPatrolLive.mount(host,'s1');await settle();
 assert.equal(posts,0);assert(host.textContent.includes('销售概览'));assert(host.textContent.includes('USD'));
 assert.equal(host.querySelectorAll('img').length,0);assert.equal(host.querySelectorAll('.patrol-attention,[data-chart="homepage"]').length,0);
 host.querySelector('[data-live-start]').click();await settle();assert.equal(posts,1);
 host.querySelector('.patrol-live').remove();ready=false;
 w.TikTokPatrolLive.mount(host,'s2');await settle();assert(host.querySelector('[data-live-start]').disabled);
 console.log('PASS: real-time panel, explicit manual trigger, currency isolation, scope labels, escaping, unreviewed-store guard');
 dom.window.close();
})().catch(err=>{console.error(err);process.exitCode=1;dom.window.close();});
