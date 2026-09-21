(function(root){
'use strict';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds={violations:'店铺违规',overdue:'超时发货',reviews:'新增评价 / 差评',returns:'退货退款与仅退款',wallet:'广告费余额'};
const clean=v=>String(v??'').replace(/\n[ \t]*\n+/g,'\n').replace(/\n:\n/g,'：');
const num=v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
async function api(path,body){const r=await fetch('/api/hub/tiktok-details'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);const d=await r.json();if(!r.ok)throw Error(d.detail||'读取失败');return d;}
function days(a,b){if(!/^\d{4}-\d{2}-\d{2}$/.test(a)||!/^\d{4}-\d{2}-\d{2}$/.test(b)||a>b)return [];let result=[],d=new Date(a+'T00:00:00Z');while(d.toISOString().slice(0,10)<=b&&result.length<366){result.push(d.toISOString().slice(0,10));d.setUTCDate(d.getUTCDate()+1);}return result;}
function selectData(runs,store,range){
 const result={};Object.keys(kinds).forEach(k=>result[k]=[]);
 const stores=[...new Set(runs.flatMap(r=>r.items.map(i=>i.store_id)))].filter(s=>store==='all'||s===store);
 for(const sid of stores){
  const items=runs.flatMap(r=>r.items.filter(i=>i.store_id===sid).map(i=>({...i,run:r}))).sort((a,b)=>b.run.created_at.localeCompare(a.run.created_at));
  for(const kind of Object.keys(kinds)){
   if(['reviews','violations'].includes(kind)){
    for(const day of days(range.start,range.end)){
     const item=items.find(i=>i.sections[kind]?.complete&&i.sections[kind].start<=day&&i.sections[kind].end>=day);
     if(item){const s=item.sections[kind];result[kind].push({shop:item.shop,store_id:sid,day,rows:s.rows.filter(r=>r.day===day),captured:s.captured_at,source:s.source_url});}
    }
   }else{
    const seen=new Set();for(const item of items){const s=item.sections[kind];if(!s?.complete)continue;const day=s.rows[0]?.day||s.day||s.captured_at.slice(0,10);if(day<range.start||day>range.end||seen.has(day))continue;seen.add(day);result[kind].push({shop:item.shop,store_id:sid,day,rows:s.rows,captured:s.captured_at,source:s.source_url});}
   }
  }
 }
 return result;
}
function mount(host,storeId,range){
 const node=document.createElement('section');node.className='panel space patrol-details';host.querySelector('.patrol-filters').after(node);
 let timer,chart,selected='violations',star='all',runs=[],data={},running=false;
 const observer=new MutationObserver(()=>{if(!node.isConnected){clearTimeout(timer);chart?.dispose();observer.disconnect();resize.disconnect();}});observer.observe(document.body,{childList:true,subtree:true});
 const resize=new ResizeObserver(()=>chart?.resize());resize.observe(node);
 function latest(kind){const seen=new Set();return [...(data[kind]||[])].sort((a,b)=>b.day.localeCompare(a.day)).filter(r=>{if(seen.has(r.store_id))return false;seen.add(r.store_id);return true;});}
 function metric(kind){let groups=['reviews','violations'].includes(kind)?data[kind]:latest(kind);if(!groups?.length)return '未读取';const rows=groups.flatMap(g=>g.rows);
  if(kind==='wallet')return groups.map(g=>g.rows.map(r=>num(r.value)+' '+r.currency).join(' / ')).join(' / ');
  if(kind==='reviews')return rows.length+' 条 / '+rows.filter(r=>r.stars<=2).length+' 条低星';
  if(kind==='returns')return rows.filter(r=>r.type==='退货退款').length+' 退货 / '+rows.filter(r=>r.type==='仅退款').length+' 仅退款';
  return rows.length?rows.length+' 条':'无';
 }
 function renderDetails(){
  const groups=(data[selected]||[]).slice().sort((a,b)=>b.day.localeCompare(a.day));
  const latestGroup=latest(selected);const shown=['reviews','violations'].includes(selected)?groups:latestGroup;
  let rows=shown.flatMap(g=>g.rows.map(r=>({...r,shop:g.shop,day:g.day,captured:g.captured})));
  if(selected==='reviews'&&star!=='all')rows=rows.filter(r=>star==='low'?r.stars<=2:r.stars===Number(star));
  node.querySelector('[data-detail-content]').innerHTML=`<div class="patrol-section-title"><h3>${kinds[selected]}明细 · ${rows.length} 条</h3>${selected==='reviews'?`<select data-stars aria-label="评价星级"><option value="all">全部星级</option><option value="low">1—2 星</option>${[1,2,3,4,5].map(n=>`<option value="${n}">${n} 星</option>`).join('')}</select>`:''}</div>${shown.length?``:'<p>所选范围没有已核验记录。</p>'}<div class="detail-records">${rows.map(r=>`<details class="detail-record"><summary><span>${esc(r.shop)} · ${esc(r.day)} ${r.stars?' · '+r.stars+' 星':''}</span><strong>${esc(r.product||r.order_id||r.violation_id||r.label||r.order||'记录')}</strong>${selected==='wallet'?`<b>${num(r.value)} ${esc(r.currency)}</b>`:''}</summary><div>${r.product_id?`<p>商品 ID：${esc(r.product_id)}</p>`:''}${r.order?`<p>${esc(r.order)}</p>`:''}${r.start?`<p>处罚期限：${esc(r.start)} — ${esc(r.end)}</p>`:''}<pre>${esc(clean(r.text||r.rating||''))}${r.products?'\n\n商品信息\n'+esc(clean(Array.isArray(r.products)?r.products.join('\n'):r.products)):''}</pre>${r.reply?`<p>商家回复：${esc(r.reply)}</p>`:''}<small>采集：${esc(new Date(r.captured).toLocaleString())}</small></div></details>`).join('')|| (shown.length?'<p class="detail-empty">无符合条件的记录</p>':'')}</div>`;
  const select=node.querySelector('[data-stars]');if(select){select.value=star;select.onchange=()=>{star=select.value;renderDetails();};}
  chart?.dispose();const canvas=node.querySelector('[data-detail-chart]');if(!root.echarts)return;
  chart=root.echarts.init(canvas);const dates=days(range.start,range.end),stores=[...new Set(groups.map(g=>g.store_id))];
  const series=stores.map(sid=>{const group=groups.filter(g=>g.store_id===sid);return {name:group[0].shop+(selected==='wallet'?' · '+(group[0].rows[0]?.currency||''):''),type:'line',connectNulls:false,symbolSize:7,data:dates.map(day=>{const g=group.find(g=>g.day===day);return !g?null:selected==='wallet'?g.rows[0]?.value:selected==='reviews'?g.rows.filter(r=>r.stars<=2).length:g.rows.length;})};});
  chart.setOption({animation:false,color:['#009995','#568ac4','#c2753b','#7963ab','#c66580','#668048'],tooltip:{trigger:'axis'},legend:{bottom:0},grid:{left:65,right:30,top:20,bottom:70},xAxis:{type:'category',data:dates.map(d=>d.slice(5))},yAxis:{type:'value',minInterval:selected==='wallet'?undefined:1},series});
  node.querySelector('[data-chart-label]').textContent=selected==='reviews'?'每日低星评价（1—2 星）':selected==='wallet'?'可用信用额度每日快照':kinds[selected]+'每日记录';
 }
 async function refresh(){
  try{const value=await api('/status?store_id='+encodeURIComponent(storeId));if(!node.isConnected)return;runs=value.runs;data=selectData(runs,storeId,range);running=runs.some(r=>r.state==='running');const recent=runs[0];
   chart?.dispose();node.innerHTML=`<div class="patrol-heading"><div><div class="eyebrow">店铺运营巡检</div><h2>每日关注的五件事</h2></div><div class="detail-buttons"><button class="button primary" data-detail-run ${running?'disabled':''}>${running?'读取中…':'巡检五项 · 昨日 / 当前'}</button><button class="button" data-detail-range ${running?'disabled':''}>补读所选日期</button><button class="button" data-detail-export>导出明细</button></div></div><p data-detail-error role="alert"></p>${recent?`<details class="detail-status" ${recent.state==='running'||recent.state==='partial'?'open':''}><summary>最近运行：${esc({running:'读取中',complete:'完成',partial:'部分完成',interrupted:'已中断'}[recent.state]||recent.state)} · ${esc(recent.step||'')}</summary>${recent.items.filter(i=>storeId==='all'||i.store_id===storeId).map(i=>`<p><b>${esc(i.shop)}</b> · ${Object.keys(i.sections).length}/5 项完成</p>${Object.entries(i.errors).map(([k,v])=>`<p class="patrol-error">${kinds[k]}：${esc(v)}</p>`).join('')}`).join('')}</details>`:''}<div class="detail-cards">${Object.keys(kinds).map(k=>`<button class="detail-card ${k===selected?'active':''}" data-detail-kind="${k}"><span>${kinds[k]}</span><strong>${esc(metric(k))}</strong><small>${k==='reviews'?'全部评价留存，1—2 星单列':k==='wallet'?'可用信用额度':k==='returns'?'等待平台 / 客户处理':k==='violations'?'所选日期新增违规':'当前备货超时订单'}</small></button>`).join('')}</div><div class="detail-trend"><h3 data-chart-label></h3><div data-detail-chart style="height:260px"></div></div><div data-detail-content></div>`;
   node.querySelectorAll('[data-detail-kind]').forEach(b=>b.onclick=()=>{selected=b.dataset.detailKind;node.querySelectorAll('[data-detail-kind]').forEach(x=>x.classList.toggle('active',x===b));renderDetails();});
   const start=async(useRange)=>{node.querySelectorAll('[data-detail-run],[data-detail-range]').forEach(b=>b.disabled=true);try{await api('/runs',{store_id:storeId,...(useRange?range:{})});await refresh();}catch(e){node.querySelector('[data-detail-error]').textContent=e.message;node.querySelectorAll('[data-detail-run],[data-detail-range]').forEach(b=>b.disabled=false);}};
   node.querySelector('[data-detail-run]').onclick=()=>start(false);node.querySelector('[data-detail-range]').onclick=()=>start(true);
   node.querySelector('[data-detail-export]').onclick=()=>{const a=document.createElement('a'),u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.href=u;a.download='tiktok-patrol-details.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
   renderDetails();clearTimeout(timer);if(running)timer=setTimeout(refresh,4000);
  }catch(err){if(node.isConnected)node.innerHTML='<h2>运营巡检</h2><p>'+esc(err.message)+'</p>';}
 }
 refresh();
}
root.TikTokPatrolDetails={mount,selectData};
})(window);
