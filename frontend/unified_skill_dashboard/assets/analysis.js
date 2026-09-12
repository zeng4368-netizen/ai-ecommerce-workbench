/* Additional analysis layer. Original Skill modules are not modified. */
(function(root){
  'use strict';
  const num=v=>{if(v==null||v==='')return 0; const n=Number(String(v).replace(/,/g,''));return Number.isFinite(n)?n:0;};
  const sum=(rows,key)=>rows.reduce((a,r)=>a+num(typeof key==='function'?key(r):r[key]),0);
  const ratio=(a,b)=>b?a/b:null;
  function group(rows,key){const map=new Map();for(const r of rows){const k=key(r);if(!map.has(k))map.set(k,[]);map.get(k).push(r);}return map;}
  function ads(rows){return rows.map((r,i)=>({raw:r,id:[r['店铺']||r['店编']||'未标注店铺',r['广告计划 ID'],r['商品 ID'],r['视频 ID'],r['创意作品类型'],i].join('|'),
    shop:String(r['店铺']||r['店编']||'未标注店铺'),campaign:String(r['广告计划名称']||'未提供'),product:String(r['商品 ID']||'未提供'),
    account:String(r['TikTok 账号']||'未提供'),type:String(r['创意作品类型']||'未提供'),status:String(r['状态']||'未提供'),
    currency:String(r['货币']||'未标注'),spend:num(r['成本']),revenue:num(r['总收入']),orders:num(r['SKU 订单数']),
    impressions:num(r['商品广告曝光数']),clicks:num(r['商品广告点击数']),roi:ratio(num(r['总收入']),num(r['成本']))}));}
  function adSummary(rows){const spend=sum(rows,'spend'),revenue=sum(rows,'revenue'),orders=sum(rows,'orders'),clicks=sum(rows,'clicks'),impressions=sum(rows,'impressions');return{spend,revenue,orders,clicks,impressions,roi:ratio(revenue,spend),ctr:ratio(clicks,impressions),cpo:ratio(spend,orders),count:rows.length};}
  function campaigns(rows){return [...group(rows,r=>r.shop+'|'+r.campaign).values()].map(rs=>({name:rs[0].campaign,shop:rs[0].shop,...adSummary(rs)})).sort((a,b)=>b.revenue-a.revenue);}
  function adRisk(row,roiTarget=8,minSpend=5){if(row.spend<=0)return{priority:'P2',title:'无消耗',kind:'neutral'};
    if(/ineligible/i.test(row.status))return{priority:'P0',title:'投放资格待核实',kind:'danger'};
    if(row.spend<minSpend)return{priority:'P2',title:'小样本观察',kind:'neutral'};
    if(row.orders===0)return{priority:'P0',title:'有消耗无订单',kind:'danger'};
    if(row.roi<roiTarget)return{priority:'P1',title:'低于实验目标',kind:'warn'};
    return{priority:'P2',title:'效率达标候选',kind:'green'};}
  function billRows(bill){return bill.rows.map(row=>Object.fromEntries(bill.header.map((h,i)=>[h,row[i]])));}
  function dateKey(value){const m=String(value||'').match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);return m?`${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`:'';}
  function billTrend(bill){return [...group(billRows(bill).filter(r=>dateKey(r['订单结算时间'])),r=>dateKey(r['订单结算时间'])).entries()].sort(([a],[b])=>a.localeCompare(b)).map(([date,rs])=>({date,revenue:sum(rs,'总收入'),settle:sum(rs,'结算总金额'),cost:sum(rs,'订单成本'),profit:sum(rs,'结算总金额')-sum(rs,'订单成本'),rows:rs.length}));}
  function dailyTrend(raw,allowedNames=null){const rows=allowedNames?raw.filter(r=>allowedNames.has(r['SKU中文名'])):raw; const dates=[...new Set(raw.flatMap(r=>Object.keys(r).filter(k=>/^\d{4}[-/]\d{2}[-/]\d{2}$/.test(k))))].sort();return dates.map(date=>({date,sales:sum(rows,r=>r[date])}));}
  function creatorRows(rows){return rows.map((r,i)=>({id:'creator-'+i,name:r[0],gmv:num(r[1]),live:num(r[2]),video:num(r[3]),refund:num(r[4]),orders:num(r[5]),aov:num(r[6]),goods:num(r[7]),videoN:num(r[8]),views:num(r[9]),commission:num(r[10]),refundRate:ratio(num(r[4]),num(r[1])),rpm:ratio(num(r[1])*1000,num(r[9]))}));}
  function tasks(data,settings){const rows=ads(data.gmv.rows).filter(r=>r.currency===settings.currency);const result=[];
    for(const r of [...rows].sort((a,b)=>adRisk(a,settings.roiTarget,settings.minSpend).priority.localeCompare(adRisk(b,settings.roiTarget,settings.minSpend).priority)||b.spend-a.spend)){const risk=adRisk(r,settings.roiTarget,settings.minSpend);if(risk.priority==='P2')continue;result.push({id:'ad:'+(data.gmv.snapshotDate||'undated')+'|'+r.id,module:'ads',priority:risk.priority,name:r.product,title:risk.title,reason:`成本 ${r.spend.toFixed(2)} ${r.currency}；SKU 订单数 ${r.orders}；ROI ${r.roi==null?'无分母':r.roi.toFixed(2)}；状态 ${r.status}`,action:risk.priority==='P0'?'核对平台当前状态与归因窗口；检查素材授权、商品承接和转化数据，再决定预算调整。':'检查主图、价格和落地页转化，补充同类素材对照实验；确认毛利与库存后再决定投放。',source:`GMV Max · ${data.gmv.snapshotDate||'日期未标注'}`,rule:`新增诊断：资格异常优先；消耗 ≥ ${settings.minSpend} 才评估零订单与 ROI < ${settings.roiTarget}。`,risk:risk.priority==='P0'?'高':'中'});if(result.length>=8)break;}
    const stock=data.daily.products.filter(p=>!p.noERP&&p.available>0&&p.days>0&&p.days<=14&&p.avg7>0).sort((a,b)=>a.days-b.days||b.avg7-a.avg7).slice(0,5);
    stock.forEach(p=>result.push({id:'stock:'+p.name,module:'inventory',priority:p.days<=7?'P0':'P1',name:p.name,title:'可售天数偏低',reason:`原看板可售天数 ${p.days} 天；可用库存 ${p.available}；7日均销 ${p.avg7}`,action:'核对在途批次、补货交期与仓库库存；确认到货前控制推广节奏。',source:'日销库存 · 内嵌快照',rule:'新增筛选：已匹配 ERP、可用库存 > 0、可售天数 1–14、7日均销 > 0。',risk:p.days<=7?'高':'中'}));
    creatorRows(data.creators).filter(c=>c.gmv>=100&&c.refundRate>=.1).sort((a,b)=>b.refund-a.refund).slice(0,4).forEach(c=>result.push({id:c.id,module:'creators',priority:'P1',name:c.name,title:'达人退款占比偏高',reason:`归因 GMV ${c.gmv.toFixed(2)} RM；退款金额 ${c.refund.toFixed(2)} RM；退款金额占比 ${(c.refundRate*100).toFixed(1)}%`,action:'复核该达人关联商品、退款原因及内容承诺，检查集中退款是否来自同一批次。',source:'达人明细 · 2026-07',rule:'新增筛选：GMV ≥ 100 RM 且退款金额 / GMV ≥ 10%，不据此断言内容导致退款。',risk:'中'}));
    return result.sort((a,b)=>a.priority.localeCompare(b.priority));
  }
  const api={num,sum,ratio,group,ads,adSummary,campaigns,adRisk,billRows,billTrend,dailyTrend,creatorRows,tasks,dateKey};
  root.WorkbenchAnalysis=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window==='undefined'?globalThis:window);
