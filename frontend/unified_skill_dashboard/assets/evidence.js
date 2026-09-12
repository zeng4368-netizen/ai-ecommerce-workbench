/* Model evidence is always recomputed from data, never from generated prose. */
(function(root){
  'use strict';
  function build(data, settings, scope='all', name=v=>v){
    const A=root.WorkbenchAnalysis, ads=A.ads(data.gmv.rows).filter(r=>r.currency===settings.currency);
    const bill=A.billRows(data.bill), creators=A.creatorRows(data.creators);
    const stock=data.daily.products.filter(p=>!p.noERP&&p.available>0&&p.days>0&&p.days<=14&&p.avg7>0).sort((a,b)=>a.days-b.days||b.avg7-a.avg7);
    const selected=module=>scope==='all'||scope===module;
    const evidence={version:1,scope,sourceHashes:data.sourceHashes,limitations:[
      '全部为已有历史快照，不代表实时店铺状态。原始算法、表头保持不变。',
      '模块间缺少统一商品映射且周期币种不同，不得跨模块合计收入或推断因果。',
      '列表为明确筛选后的有限样本，不是全量；无订单明细关联时不得将记录数当作订单数。',
      '金额不包含的费用、未提供的真实净利润与业务成效不得虚构。'
    ],settings:{...settings},sources:[]};
    if(selected('ads')) evidence.sources.push({id:'ADS',source:'GMV Max 原始内嵌数据',date:data.gmv.snapshotDate,currency:settings.currency,
      metrics:A.adSummary(ads),formulas:{roi:'总收入合计 / 成本合计',ctr:'点击合计 / 曝光合计',cpo:'成本合计 / SKU订单数合计'},
      selection:'按风险优先级再按消耗降序，最多12条',rows:[...ads].sort((a,b)=>A.adRisk(a,settings.roiTarget,settings.minSpend).priority.localeCompare(A.adRisk(b,settings.roiTarget,settings.minSpend).priority)||b.spend-a.spend).slice(0,12).map((r,i)=>({evidenceId:'ADS-'+(i+1),product:name(r.product,'商品'),campaign:name(r.campaign,'计划'),spend:r.spend,revenue:r.revenue,orders:r.orders,roi:r.roi,clicks:r.clicks,impressions:r.impressions,status:r.status,risk:A.adRisk(r,settings.roiTarget,settings.minSpend)}))});
    if(selected('inventory')) evidence.sources.push({id:'STOCK',source:'原日销库存快照',date:'日销原表日期列范围；非实时库存',originalKpis:data.daily.kpis,productCount:data.daily.products.length,
      trend:A.dailyTrend(data.daily.raw.daily),riskCandidateCount:stock.length,selection:'ERP已匹配、可用库存>0、可售天数1至14、7日均销>0；按天数升序最多8款',
      rows:stock.slice(0,8).map((p,i)=>({evidenceId:'STOCK-'+(i+1),product:name(p.name,'商品'),available:p.available,days:p.days,avg7:p.avg7,avg14:p.avg14,ring:p.ring})),
      formulas:{days:'直接沿用原看板可售天数，不重新定义',kpis:'直接沿用原看板KPI；SKU数与款数不可混用'}});
    if(selected('creators')) evidence.sources.push({id:'CREATOR',source:'原达人明细',date:'2026-07',currency:'RM',originalTotal:data.creatorTotal,detailRows:creators.length,
      selection:'GMV>=100且退款金额/GMV>=10%，按退款金额降序最多8人；原始详情只含收入>0的有效186人，不代表总计3265人。金额占比100%不证明任何特定订单全额退款',
      rows:creators.filter(c=>c.gmv>=100&&c.refundRate>=.1).sort((a,b)=>b.refund-a.refund).slice(0,8).map((c,i)=>({evidenceId:'CREATOR-'+(i+1),creator:name(c.name,'达人'),gmv:c.gmv,refund:c.refund,refundRate:c.refundRate,orders:c.orders,commission:c.commission})),formulas:{refundRate:'退款金额/GMV；金额占比不是退款订单率，可能跨期超过100%'}});
    if(selected('finance')) evidence.sources.push({id:'FINANCE',source:'原结算账单',currency:'RM',recordCount:bill.length,availableOriginalHeaders:data.bill.header,trend:A.billTrend(data.bill),
      metrics:{settlement:A.sum(bill,'结算总金额'),cost:A.sum(bill,'订单成本'),revenue:A.sum(bill,'总收入'),settlementMinusCost:A.sum(bill,'结算总金额')-A.sum(bill,'订单成本')},
      formulas:{profitRate2:'(结算总金额-订单成本)/总收入；沿用原利润率②',boundary:'结算减成本仅为账单口径差额，不是包含全部费用的净利润；账单行数不是唯一订单数'}});
    return evidence;
  }
  root.WorkbenchEvidence={build};
  if(typeof module!=='undefined')module.exports=root.WorkbenchEvidence;
})(typeof window==='undefined'?globalThis:window);
