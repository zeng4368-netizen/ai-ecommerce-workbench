const fs=require('fs'),vm=require('vm'),assert=require('assert');const window={};vm.runInNewContext(fs.readFileSync(require('path').join(__dirname,'../assets/tiktok-patrol-details.js'),'utf8'),{window});
const select=window.TikTokPatrolDetails.selectData;
const make=(at,rows,start='2026-09-01',end='2026-09-02')=>({created_at:at,items:[{store_id:'a',shop:'A',sections:{reviews:{complete:true,start,end,rows,captured_at:at}}}]});
const r=select([make('2026-09-03',[{day:'2026-09-01',stars:1}]),make('2026-09-04',[],'2026-09-01','2026-09-01')],'a',{start:'2026-09-01',end:'2026-09-03'});
assert.equal(r.reviews.length,2);assert.equal(r.reviews.find(g=>g.day==='2026-09-01').rows.length,0);assert(!r.reviews.some(g=>g.day==='2026-09-03'));
assert.equal(select([make('2026-09-03',[])],'b',{start:'2026-09-01',end:'2026-09-03'}).reviews.length,0);
console.log('Daily deduplication, verified zero, missing day, store isolation passed');

