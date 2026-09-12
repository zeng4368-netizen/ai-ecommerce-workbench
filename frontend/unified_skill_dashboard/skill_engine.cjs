/* Execute trusted, unchanged Skill code. User input is JSON data, never source code. */
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm');
const ROOT=__dirname;
require('./assets/analysis.js');
require('./assets/evidence.js');
require('./assets/question-context.js');
require('./assets/action-candidates.js');
function daily(raw){
  const html=fs.readFileSync(path.join(ROOT,'modules/日销异常1.html'),'utf8');
  const start=html.indexOf('function cleanStr('),end=html.indexOf('function renderKpis()',start);
  if(start<0||end<start)throw Error('Original daily engine boundary changed');
  const context=vm.createContext({input:raw});
  vm.runInContext(`let RAW=input,PRODUCTS=[],DETAIL={},KPIS={};
    const EXCLUDED_SKUS=new Set(["MYQTD001","MYQTD7777","MYQTD9999","MYQTD8888","TKZP001"]);
    const STATUS_ORDER=["正常销售","等待开发","商品清仓","停止销售"];
    const ACTIVITY_ORDER=["其他","爆款","旺款","滞销款","平款"];
    ${html.slice(start,end)}
    buildDashboardData();result={raw:RAW,products:PRODUCTS,detailData:DETAIL,kpis:KPIS};`,context,{timeout:15000});
  return context.result;
}
function pipeline(operation,args){
  const html=fs.readFileSync(path.join(ROOT,'modules/售后数据.html'),'utf8');
  const script=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('window.SKILL_PIPE ='));
  if(!script)throw Error('Original profit engine not found');
  const context=vm.createContext({window:{},args});
  vm.runInContext(script,context,{timeout:15000});
  if(!['stage1','stage2','stage3'].includes(operation))throw Error('Unsupported operation');
  vm.runInContext(`result=window.SKILL_PIPE.${operation}(...args)`,context,{timeout:15000});
  return context.result;
}
function execute(p){
  if(p.op==='bill_normalize'){
    const html=fs.readFileSync(path.join(ROOT,'modules/售后数据.html'),'utf8');
    const section=html.slice(html.indexOf('var FILTER_IDS ='));
    const need=section.match(/var NEED = ([\s\S]*?);/)[1],alias=section.match(/var ALIAS = ([\s\S]*?\n  });/)[1];
    const ctx=vm.createContext({input:p.table});
    vm.runInContext(`const NEED=${need},ALIAS=${alias};const columns=NEED.map(k=>(ALIAS[k]||[k]).map(h=>input.header.indexOf(h)).find(i=>i>=0));if(columns.some(i=>i===undefined))throw Error('账单缺少字段：'+NEED.filter((k,i)=>columns[i]===undefined).join('、'));result={header:NEED,rows:input.rows.map(r=>columns.map(i=>r[i]??null))};`,ctx,{timeout:10000});
    return ctx.result;
  }
  if(p.op==='daily')return daily(p.raw);
  if(p.op==='pipeline')return pipeline(p.stage,p.args);
  if(p.op==='candidates')return globalThis.ActionCandidates.build(p.data,p.settings||{roiTarget:8,minSpend:5,currency:'USD'});
  if(p.op==='question')return globalThis.QuestionContext.prepare(p.data,p.settings||{roiTarget:8,minSpend:5,currency:'USD'},p.question,p.scope||'all');
  if(p.op==='daily_query')return globalThis.QuestionContext.daily(p.data,p.question,v=>v,Number.MAX_SAFE_INTEGER);
  if(p.op==='daily_action_evidence'){
    const raw=p.data.daily.raw.daily,shops=[...new Set(raw.map(r=>String(r['店铺']||'').trim()).filter(Boolean))];
    return shops.map(shop=>{
      // Exact shop scoping before retrieval avoids substring collisions between shop names.
      const scoped={daily:{raw:{daily:raw.filter(r=>String(r['店铺']||'').trim()===shop)}}};
      return {shop,...globalThis.QuestionContext.daily(scoped,'全部日销下降',v=>v,Number.MAX_SAFE_INTEGER)};
    });
  }
  if(p.op==='ads')return globalThis.WorkbenchAnalysis.ads(p.rows);
  if(p.op==='ad_metrics'){const A=globalThis.WorkbenchAnalysis;return [...A.group(A.ads(p.rows),r=>r.currency)].map(([currency,rows])=>({currency,...A.adSummary(rows)}));}
  throw Error('Unsupported engine operation');
}
if(require.main===module){let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);process.stdin.on('end',()=>{try{process.stdout.write(JSON.stringify(execute(JSON.parse(input))));}catch(e){process.stderr.write(e.stack);process.exitCode=1;}});}
module.exports={execute,daily,pipeline};
