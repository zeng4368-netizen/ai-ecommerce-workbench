(function(root){
 'use strict';
 const labels=['成本','SKU 订单数','平均下单成本','总收入','ROI'];
 const e=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
 const shift=(value,n)=>{const d=new Date(value+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);};
 async function api(path){const r=await fetch('/api/hub/tiktok-ads'+path);const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'请检查店铺与日期范围');return data;}
 async function mount(host,{toast=()=>{}}={}){
  const node=document.createElement('section');node.className='ads-dashboard';host.replaceChildren(node);
  let stores=[],selected=new Set(['SKU 订单数']),data=null,chart=null,ticket=0;
  const alive=()=>node.isConnected;
  function dispose(){chart?.dispose();chart=null;}
  const resize=new ResizeObserver(()=>chart?.resize());resize.observe(node);
  const observer=new MutationObserver(()=>{if(!alive()){dispose();resize.disconnect();observer.disconnect();}});observer.observe(document.body,{childList:true,subtree:true});
  function plot(){
   dispose();const el=node.querySelector('[data-ad-chart]');if(!el||!data)return;
   const names=labels.filter(x=>selected.has(x));
   if(!names.length){el.innerHTML='<div class="ads-empty">勾选上方指标查看曲线</div>';return;}
   if(!data.series.length){el.innerHTML='<div class="ads-empty">所选日期尚无广告记录</div>';return;}
   if(!root.echarts){el.innerHTML='<div class="ads-empty">图表未加载，可查看下方每日数据</div>';return;}
   el.replaceChildren();chart=root.echarts.init(el,null,{renderer:'svg'});
   const unit=name=>name==='ROI'?'倍':name==='SKU 订单数'?'单':data.currency;
   const units=[...new Set(names.map(unit))];
   chart.setOption({animation:false,color:['#00a5aa','#587ed2'],aria:{enabled:true},grid:{top:65,bottom:45,left:72,right:units.length>1?72:30},legend:{top:12,left:0},tooltip:{trigger:'axis',renderMode:'richText',valueFormatter:fmt},xAxis:{type:'category',boundaryGap:false,data:data.days,axisLabel:{formatter:v=>v.slice(5)}},yAxis:units.map((u,i)=>({type:'value',name:u,position:i?'right':'left',splitLine:{show:!i,lineStyle:{color:'#edf0f2'}},axisLabel:{color:'#879099'}})),series:names.map(name=>({name,type:'line',yAxisIndex:units.indexOf(unit(name)),showSymbol:true,symbolSize:6,lineStyle:{width:2},connectNulls:false,data:data.series.find(s=>s.label===name)?.points.map(p=>p.value)||data.days.map(()=>null)}))});
  }
  function render(){
   const money=name=>['成本','平均下单成本','总收入'].includes(name)?' '+data.currency:'';
   node.querySelector('[data-ad-account]').textContent=data.meta.account||data.meta.shop;
   node.querySelector('[data-ad-zone]').textContent=data.meta.timezone_label;
   node.querySelector('[data-ad-data]').innerHTML=`<div class="ads-title"><h2>概览</h2><span>${data.complete?'所选日期完整':`已记录 ${data.recorded_days} / ${data.range_days} 天 · 下方为已记录日汇总`}</span></div><div class="ads-kpi-grid">${labels.map(name=>{const change=data.changes[name];const good=change==null?false:['成本','平均下单成本'].includes(name)?change<0:change>0;return `<label class="ads-kpi ${selected.has(name)?'selected':''}"><span>${name}<input type="checkbox" data-ad-metric="${e(name)}" ${selected.has(name)?'checked':''} aria-label="显示${name}曲线"></span><strong>${fmt(data.values[name])}<small>${money(name)}</small></strong><small class="ads-comparison ${change==null?'':good?'positive':'negative'}">${change==null?'前期数据不足，暂不比较':`${change>0?'+':''}${fmt(change)}% · 较前一等长时段`}</small></label>`;}).join('')}</div><div class="ads-chart" data-ad-chart role="img" aria-label="广告指标每日趋势"></div><div class="ads-chart-footer"><span>勾选指标切换曲线，最多同时对比 2 项</span><span>${e(data.start)} — ${e(data.end)}</span></div><details class="ads-details"><summary>每日数据</summary><div class="table-wrap"><table class="data-table"><thead><tr><th>日期</th>${labels.map(n=>'<th>'+n+'</th>').join('')}</tr></thead><tbody>${data.days.map(day=>`<tr><td>${e(day)}</td>${labels.map(name=>'<td>'+fmt(data.series.find(s=>s.label===name)?.points.find(p=>p.day===day)?.value)+money(name)+'</td>').join('')}</tr>`).join('')}</tbody></table></div></details><details class="ads-details"><summary>统计口径与来源</summary><p>来源：此店铺已保存的 GMV Max 每日概览。未记录日期显示空白，不按零计算。</p><p>多日成本、订单数、收入相加；平均下单成本＝总成本÷总订单数；ROI＝总收入÷总成本。单日保留平台原值。ROI 不代表利润率。</p><p>只有当前和前一等长时段都完整时才显示变化率；前期为零时不计算百分比。</p><p>比较时段：${e(data.previous_start)} — ${e(data.previous_end)}。账号时区：${e(data.meta.timezone)}。</p><a class="button small" href="#tiktok-patrol">前往日常巡检更新记录</a><a class="button small" href="#legacy-gmv">查看原始广告分析模块</a></details>`;
   node.querySelectorAll('[data-ad-metric]').forEach(input=>input.onchange=()=>{
    if(input.checked&&selected.size>=2){input.checked=false;toast('最多同时对比 2 项，请先取消一项');return;}
    if(input.checked)selected.add(input.dataset.adMetric);else selected.delete(input.dataset.adMetric);
    input.closest('.ads-kpi').classList.toggle('selected',input.checked);plot();
   });
   node.querySelector('[data-ad-export]').href='/api/hub/tiktok-ads/export?'+new URLSearchParams({store_id:node.querySelector('[data-ad-store]').value,start:data.start,end:data.end});
   node.querySelector('[data-ad-export]').removeAttribute('aria-disabled');plot();
  }
  async function load(){
   const turn=++ticket;const error=node.querySelector('[data-ad-error]');error.textContent='';dispose();node.querySelector('[data-ad-data]').textContent='正在读取广告记录…';node.querySelector('[data-ad-export]').removeAttribute('href');
   const sid=node.querySelector('[data-ad-store]').value,meta=stores.find(s=>s.store_id===sid);node.querySelector('[data-ad-account]').textContent=meta.account||meta.shop;node.querySelector('[data-ad-zone]').textContent=meta.timezone_label;
   try{const result=await api('/overview?'+new URLSearchParams({store_id:sid,start:node.querySelector('[data-ad-start]').value,end:node.querySelector('[data-ad-end]').value}));if(!alive()||turn!==ticket)return;data=result;render();}
   catch(err){if(alive()&&turn===ticket){error.textContent=err.message;node.querySelector('[data-ad-data]').textContent='';}}
  }
  try{
   stores=(await api('/stores')).stores;if(!alive())return;if(!stores.length)throw Error('尚未绑定店铺');const end=stores[0].yesterday;
   node.innerHTML=`<div class="page-heading"><div><div class="eyebrow">TIKTOK SHOP / GMV MAX</div><h1>广告数据面板</h1></div></div><section class="ads-surface"><form data-ad-form><div class="ads-toolbar"><label class="ads-shop">店铺<select data-ad-store aria-label="广告店铺">${stores.map(s=>`<option value="${e(s.store_id)}">${e(s.shop)}</option>`).join('')}</select></label><div class="ads-dates"><label>开始日期<input type="date" data-ad-start value="${shift(end,-6)}" required></label><span>—</span><label>结束日期<input type="date" data-ad-end value="${end}" required></label><button class="button" type="submit">应用</button><a class="button" data-ad-export aria-label="导出每日广告数据">↓ 导出</a></div></div><div class="ads-account-row"><strong data-ad-account></strong><span data-ad-zone></span></div><div class="ads-presets">${[['yesterday','昨日'],['7','近7天'],['30','近30天'],['month','本月']].map(([v,t])=>`<button type="button" data-ad-preset="${v}">${t}</button>`).join('')}<span class="ads-tab">最大成交额广告计划 · GMV Max</span></div></form><p class="ads-error" data-ad-error role="alert"></p><div data-ad-data></div></section>`;
   node.querySelector('[data-ad-form]').onsubmit=ev=>{ev.preventDefault();load();};node.querySelector('[data-ad-store]').onchange=load;
   node.querySelectorAll('[data-ad-preset]').forEach(b=>b.onclick=()=>{const store=stores.find(s=>s.store_id===node.querySelector('[data-ad-store]').value),kind=b.dataset.adPreset;let finish=store.yesterday,start=finish;if(kind==='month'){finish=shift(finish,1);start=finish.slice(0,7)+'-01';}else if(kind!=='yesterday')start=shift(finish,1-Number(kind));node.querySelector('[data-ad-start]').value=start;node.querySelector('[data-ad-end]').value=finish;load();});
   await load();
  }catch(err){if(alive())node.innerHTML='<div class="panel"><h2>广告数据面板</h2><p role="alert">'+e(err.message)+'</p></div>';}
 }
 root.TikTokAds={mount};
})(window);
