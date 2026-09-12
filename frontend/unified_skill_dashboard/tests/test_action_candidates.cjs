const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
require('../assets/analysis.js');const C=require('../assets/action-candidates.js');
const ctx={window:{}};vm.runInNewContext(fs.readFileSync(__dirname+'/../assets/snapshot.js','utf8'),ctx);
const D=ctx.window.WORKBENCH_DATA,raw=JSON.stringify(D),tasks=C.build(D,{currency:'USD',roiTarget:8,minSpend:5});
assert.equal(JSON.stringify(D),raw);assert.equal(tasks.length,94);
assert.ok(tasks.some(t=>t.module==='finance'));assert.ok(tasks.some(t=>t.title==='库存非正但仍有历史销量'));
assert.ok(tasks.filter(t=>t.module==='ads').length<tasks.filter(t=>t.module==='ads').reduce((s,t)=>s+t.evidence.length,0));
assert.ok(tasks.every(t=>new Set(t.evidence.map(e=>e.id)).size===t.evidence.length));
console.log('Action candidates passed: 94 groups, original data unchanged, ads merged, stock and finance covered.');
