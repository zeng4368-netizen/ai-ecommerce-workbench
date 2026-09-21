const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const dom=new JSDOM('<main><div class="patrol-heading"></div></main>',{url:'http://localhost',runScripts:'outside-only'}),w=dom.window;
w.ResizeObserver=class{observe(){}disconnect(){}};
const options=[],posts=[];w.echarts={init:()=>({setOption:o=>options.push(o),dispose(){},resize(){}})};
const data={days:['2026-09-11','2026-09-12','2026-09-13'],recorded_days:2,range_days:3,rows:[],series:[
 {kind:'sales',label:'GMV',currency:'MYR',shop:'MY',points:[{value:10},{value:null},{value:20}]},
 {kind:'sales',label:'GMV',currency:'THB',shop:'TH',points:[{value:100},{value:200},{value:300}]}]};
w.fetch=async(url,opts={})=>{if(opts.method==='POST')posts.push(opts.body);return {ok:true,json:async()=>url.includes('/history?')?data:{ready:true,runs:[],batches:[]}};};
w.eval(fs.readFileSync(path.join(__dirname,'../assets/tiktok-patrol-live.js'),'utf8'));
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
(async()=>{w.TikTokPatrolLive.mount(w.document.querySelector('main'),'all',{start:'2026-09-11',end:'2026-09-13'});await settle();
 assert.equal(posts.length,0);assert.equal(options[0].series.length,1);assert.equal(options[0].series[0].connectNulls,false);assert.deepEqual(Array.from(options[0].series[0].data),[10,null,20]);
 const select=w.document.querySelector('[data-chart-metric="sales"]');select.value='GMV|THB';select.dispatchEvent(new w.Event('change'));assert.equal(options.at(-1).series[0].name,'TH');
 w.document.querySelector('[data-live-start]').click();await settle();assert.equal(JSON.parse(posts[0]).store_id,'all');
 assert(w.document.querySelector('a[href*="history.csv"]'));console.log('PASS: gaps, currency-isolated charts, metric switching, all-store manual batch, CSV link');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exit(1);});
