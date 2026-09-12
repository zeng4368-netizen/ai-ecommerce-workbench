/* New workflow rules sit above original Skill calculations; original files remain untouched. */
(function(root){
  function build(D,settings){
    const A=root.WorkbenchAnalysis,out=[];
    const add=(module,entity,key,title,priority,rule,source,evidence,action)=>out.push({module,entity:String(entity),entity_key:String(key),title,priority,rule,source,evidence,suggested_action:action});
    const ads=A.ads(D.gmv.rows).filter(r=>r.currency===settings.currency&&A.adRisk(r,settings.roiTarget,settings.minSpend).priority!=='P2');
    for(const rows of A.group(ads,r=>[r.shop,r.product==='未提供'?r.id:r.product,r.currency,A.adRisk(r,settings.roiTarget,settings.minSpend).title].join('|')).values()){
      const first=rows[0],risk=A.adRisk(first,settings.roiTarget,settings.minSpend);
      add('ads',first.product,[first.shop,first.product,first.currency,risk.title].join('|'),risk.title,risk.priority,
        `原诊断规则：有消耗的资格异常优先；消耗≥${settings.minSpend}再判断无订单/ROI<${settings.roiTarget}。同店铺、商品、币种和问题合并，保留逐条原值。`,
        'GMV Max · '+(D.gmv.snapshotDate||'日期未标注')+' · '+first.currency,
        rows.map((r,i)=>({id:'ADS-'+(i+1),record:r.id,campaign:r.campaign,currency:r.currency,spend:r.spend,revenue:r.revenue,orders:r.orders,roi:r.roi,status:r.status,clicks:r.clicks,impressions:r.impressions})),
        '先核实平台当前状态、归因窗口和素材授权；保留核查截图，再由负责人判断后续措施。');
    }
    const dates=A.dailyTrend(D.daily.raw.daily).map(x=>x.date);
    for(const p of D.daily.products){
      if(p.noERP||!(p.avg7>0))continue;
      const zero=p.available<=0,low=p.available>0&&p.days>0&&p.days<=14;
      if(!zero&&!low)continue;
      add('inventory',p.name,p.name,zero?'库存非正但仍有历史销量':'可售天数偏低',zero||p.days<=7?'P0':'P1',
        zero?'新增补充规则：已匹配ERP、可用库存≤0、7日均销>0；零库存不等同已损失订单。':'沿用原筛选：ERP已匹配、库存>0、可售天数1–14、7日均销>0；天数字段照录。',
        '日销库存历史快照 · 日销日期列 '+dates[0]+' 至 '+dates.at(-1),
        [{id:'STOCK-1',product:p.name,available:p.available,days:p.days,avg7:p.avg7,avg14:p.avg14}],
        '核对实时可用库存、待发货占用和采购在途；记录补货交期与缺口，采购及推广调整交由负责人确认。');
    }
    for(const c of A.creatorRows(D.creators).filter(c=>c.gmv>=100&&c.refundRate>=.1))
      add('creators',c.name,c.name,'达人退款金额占比偏高','P1','沿用原筛选：GMV≥100 RM且退款金额/GMV≥10%；不是退款订单率，小样本不直接停止合作。','达人明细 · 2026-07 · RM',
        [{id:'CREATOR-1',creator:c.name,gmv:c.gmv,refund:c.refund,refundAmountRatio:c.refundRate,orders:c.orders,commission:c.commission}],
        '调取关联订单退款原因与时间分布，核对是否跨期；补充样本后判断商品承接或内容承诺是否需要调整。');
    const bills=A.billRows(D.bill);
    for(const [key,rows] of A.group(bills.filter(r=>r['款名']),r=>[r['店编'],r['款名']].join('|'))){
      const settle=A.sum(rows,'结算总金额'),cost=A.sum(rows,'订单成本'),diff=settle-cost;
      if(!(cost>0&&diff<0))continue;
      const times=rows.map(r=>A.dateKey(r['订单结算时间'])).filter(Boolean).sort();
      add('finance',rows[0]['款名'],key,'账单结算减成本为负','P1','新增核查规则：同店编同款账单结算合计−成本合计<0且成本>0；差额非完整净利润，行数非订单数。',
        '原结算账单 · '+times[0]+' 至 '+times.at(-1)+' · RM',
        [{id:'FINANCE-1',shop:rows[0]['店编'],product:rows[0]['款名'],currency:'RM',records:rows.length,settlement:settle,cost,revenue:A.sum(rows,'总收入'),settlementMinusCost:diff}],
        '核对账单退款类型、成本入账时点及费用明细，区分跨期结算与持续性问题，输出可回查的差额原因。');
    }
    return out.sort((a,b)=>a.priority.localeCompare(b.priority)||a.module.localeCompare(b.module)||a.entity.localeCompare(b.entity));
  }
  root.ActionCandidates={build};if(typeof module!=='undefined')module.exports=root.ActionCandidates;
})(typeof window==='undefined'?globalThis:window);
