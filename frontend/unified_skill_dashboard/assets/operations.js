(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
 const json=v=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});
 const labels={daily:'店铺日销',erp:'SKU仓库库存',gmv:'广告经营',bill:'结算账单',after:'售后退包'};
 let serial=0,chart=null,resize=null,pending=null,mode='triage',shop='',search='';
 function cancel(){serial++;if(chart)chart.dispose();chart=null;if(resize)root.removeEventListener('resize',resize);resize=null;}
 function ask(question){root.dispatchEvent(new CustomEvent('workspace:ask',{detail:{question}}));}
 async function mount(node,{toast,masked}){
   cancel();const ticket=serial;const valid=()=>ticket===serial&&node.isConnected;
   if(masked){node.innerHTML='<div class="empty">商品档案包含原始业务值。请关闭演示脱敏后使用；不要将此页面作为脱敏材料外发。</div>';return;}
   if(!DataHub.current){node.innerHTML='<div class="empty">请先启动本地工作台服务。</div>';return;}
   const version=DataHub.current.version;
   node.innerHTML='<div class="empty">正在按同一数据版本整理商品与异常…</div>';
   try{
     const health=await DataHub.api('/operations/health?version='+version);if(!valid())return;
     node.innerHTML=`<div class="page-heading"><div><div class="eyebrow">PRODUCT OPERATIONS / 从问题到证据</div><h1>商品与异常</h1><p>版本 ${version.slice(0,8)} · 当前日销周期 ${esc(DataHub.current.meta.datasets.daily.period)} · 新增分诊不改变原下降名单</p></div><button class="button" data-route="data">更新数据与切换周期</button></div>
       <div class="ops-stats"><article><small>当前覆盖店铺</small><strong>${health.store_count}</strong></article><article><small>数据警示</small><strong>${(health.counts.error||0)+(health.counts.warning||0)}</strong></article><article><small>口径与完整度提示</small><strong>${health.counts.info||0}</strong></article></div>
       <details class="panel ops-health"><summary>先检查数据是否足够可信</summary><p>${esc(health.note)}</p>${health.issues.map(x=>`<p class="ops-check ${x.severity}"><b>${esc(x.shop||labels[x.kind]||x.kind)}</b> · ${esc(x.message)}${x.count?' · '+x.count+'项':''}</p>`).join('')||'<p>未发现所列规则覆盖的问题；不代表平台数据已完整。</p>'}</details>
       <section class="panel space"><div class="ops-toolbar"><button class="button ${mode==='triage'?'primary':''}" id="opsTriage">异常分诊</button><button class="button ${mode==='catalog'?'primary':''}" id="opsCatalog">全部商品档案</button><label>店铺<select id="opsShop"><option value="">全部店铺</option>${health.daily_shops.map(s=>`<option ${shop===s.shop?'selected':''}>${esc(s.shop)}</option>`).join('')}</select></label><label>商品 / SKU<input id="opsSearch" value="${esc(search)}" placeholder="输入名称或SKU"></label><button class="button" id="opsFilter">查询</button></div><div id="opsList"></div></section><div id="opsProfile"></div>`;
     let offset=0,rows=[],listTicket=0,profileTicket=0;
     const query=async()=>{
       const request=++listTicket;
       const params=new URLSearchParams({version,shop,offset:String(offset),limit:'30',q:search});
       const r=await DataHub.api('/operations/'+(mode==='triage'?'triage':'products')+'?'+params);if(!valid()||request!==listTicket)return;
       rows=r.rows;
       node.querySelector('#opsList').innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>商品 / 店铺</th>${mode==='triage'?'<th>前日 → 末日</th><th>连续下降</th><th>数据与人工判断</th>':'<th>SKU</th>'}<th>操作</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td><b>${esc(r.product)}</b><br><small>${esc(r.shop)}</small></td>${mode==='triage'?`<td>${fmt(r.previous)} → ${fmt(r.latest)}<br><span class="${r.dayDiff<0?'ops-down':''}">${r.dayDiff>0?'+':''}${fmt(r.dayDiff)} 件</span></td><td>${r.consecutive_decline_days} 天<br><small>7日均销 ${fmt(r.avg7)}</small></td><td>${r.quality_notes.map(esc).join('<br>')||'未命中所列质量提示'}${r.feedback?'<br><span class="tag">人工：'+esc({needs_review:'待核查',normal_fluctuation:'正常波动',data_issue:'数据问题'}[r.feedback.verdict])+'</span>':''}</td>`:`<td>${r.skus.map(esc).join('<br>')}</td>`}<td><button class="button small" data-ops-open="${i}">商品全景 →</button></td></tr>`).join('')||'<tr><td colspan="5">当前周期没有匹配商品，请检查店铺或切换数据周期。</td></tr>'}</tbody></table></div><div class="form-actions"><button class="button" id="opsPrev" ${offset===0?'disabled':''}>上一页</button><button class="button" id="opsNext" ${offset+rows.length>=r.total?'disabled':''}>下一页</button></div>`;
       node.querySelectorAll('#opsList tbody tr').forEach((tr,i)=>{const title=tr.querySelector('td b');if(!title||!rows[i])return;const link=document.createElement('button');link.className='ops-product-link';link.dataset.opsOpen=i;link.textContent=title.textContent;title.replaceWith(link);});
       node.querySelectorAll('[data-ops-open]').forEach(b=>b.onclick=()=>profile(rows[Number(b.dataset.opsOpen)]));
       node.querySelector('#opsPrev').onclick=()=>{offset=Math.max(0,offset-30);query().catch(e=>toast(e.message));};
       node.querySelector('#opsNext').onclick=()=>{offset+=30;query().catch(e=>toast(e.message));};
     };
     const profile=async object=>{
       const request=++profileTicket;
       const target=node.querySelector('#opsProfile');target.innerHTML='<div class="panel space">正在读取商品证据…</div>';
       try{
         const d=await DataHub.api('/operations/product?'+new URLSearchParams({version,shop:object.shop,product:object.product}));if(!valid()||request!==profileTicket)return;
         const metric=d.daily_metrics.rows[0]||{},dates=d.daily_metrics.dates;
         target.innerHTML=`<section class="panel space ops-profile"><div class="page-heading"><div><div class="eyebrow">PRODUCT DOSSIER / 商品全景档案</div><h2>${esc(d.product)}</h2><p>${esc(d.shop)} · ${d.skus.map(esc).join(' / ')} · ${version.slice(0,8)}</p></div><button class="button primary" id="opsAsk">带这个商品询问 AI</button></div><div class="ops-stats"><article><small>末日日销 · ${esc(dates.at(-1))}</small><strong>${fmt(metric.latest)}</strong></article><article><small>较前日变化</small><strong>${fmt(metric.dayDiff)}</strong></article><article><small>原导出口径近7日均销</small><strong>${fmt(metric.avg7)}</strong></article></div><p class="notice">${esc(d.comparison.note)} ${esc(d.daily_metrics.baselineNote)}</p><div id="opsTrend" class="ops-chart" aria-label="商品日销趋势"></div><div class="ops-sections">${d.sections.map(s=>`<article><h3>${labels[s.kind]}</h3><p>${esc(s.source.period||'周期未知')} · ${esc(s.source.currency||'无金额币种')}</p><span class="tag">${s.total?s.total+'条精确关联':s.status==='mapping_required'?'需要人工映射':'暂无对应明细'}</span><p>${esc(s.note)}</p><details><summary>查看该块原始依据</summary><pre class="hub-query">${esc(JSON.stringify(s,null,2))}</pre></details></article>`).join('')}</div>
           <h3>人工核查反馈</h3><p>反馈只记录在当前版本，不改变原始异常规则，不自动屏蔽下一批异常。</p><form id="opsFeedback" class="form-grid"><label>核查结果<select name="verdict"><option value="needs_review">仍需核查</option><option value="normal_fluctuation">正常波动</option><option value="data_issue">数据问题</option></select></label><label>事实依据<input name="reason" required maxlength="2000" placeholder="例如：导出截止时间不足全天"></label><button class="button">保存人工判断</button></form>
           <h3>已有行动</h3>${d.actions.map(t=>`<p><button class="button small" data-ops-task="${t.id}">${esc(t.title)}</button> · ${esc(t.state)} · 截止 ${esc(t.due_date||'未填写')}</p>`).join('')||'<p>还没有与该商品关联的行动。</p>'}<button class="button" id="opsSync">同步当前完整数据候选</button>
           <h3>观察时间线</h3><p>按实际发生日期记录干扰因素和核查事项；保存记录不会调价、投放或联系客户。</p><form id="opsAnnotation" class="form-grid"><label>发生日期<input name="occurred_on" type="date" required></label><label>事项<select name="category"><option value="check">人工核查</option><option value="promotion">促销活动</option><option value="price">人工调价记录</option><option value="stock">库存变更记录</option><option value="other">其他</option></select></label><label>实际情况<input name="note" required maxlength="2000"></label><label><input type="checkbox" name="confirmed" required> 确认是实际发生的事项</label><button class="button">保存事项记录</button></form><div class="ops-timeline">${d.timeline.map(t=>`<article><small>${esc(t.date)}</small><b>${esc(t.type==='action'?t.title:t.category)}</b><p>${esc(t.note||t.event)}</p></article>`).join('')||'<p>暂无记录，不生成示例业务成果。</p>'}</div><details><summary>历史人工反馈 ${d.feedback.length} 条</summary><pre class="hub-query">${esc(JSON.stringify(d.feedback,null,2))}</pre></details></section>`;
         if(chart)chart.dispose();if(resize)root.removeEventListener('resize',resize);
         const listSection=node.querySelector('#opsList').closest('section');listSection.hidden=true;
         const back=document.createElement('button');back.className='button small';back.textContent='← 返回商品列表';back.onclick=()=>{profileTicket++;listSection.hidden=false;target.replaceChildren();if(chart)chart.dispose();chart=null;if(resize)root.removeEventListener('resize',resize);resize=null;listSection.scrollIntoView({behavior:'smooth',block:'start'});};target.querySelector('.page-heading').prepend(back);
         const download=document.createElement('a');download.className='button small';download.textContent='下载该商品完整匹配证据 JSON';download.href='/api/hub/operations/product/export?'+new URLSearchParams({version,shop:d.shop,product:d.product});target.querySelector('#opsAsk').after(download);
         const states={candidate:'待复核候选',ready:'已确认待办',doing:'进行中',review:'待验收',done:'已复盘',dismissed:'已搁置'};
         target.querySelectorAll('[data-ops-task]').forEach((button,i)=>{for(const text of button.parentNode.childNodes)if(text.nodeType===3)text.textContent=text.textContent.replace(' · '+d.actions[i].state+' · ',' · '+(states[d.actions[i].state]||d.actions[i].state)+' · ');});
         const categories={check:'人工核查',promotion:'促销活动',price:'人工调价记录',stock:'库存变更记录',other:'其他事项'};
         const events={created:'生成候选',approve:'人工确认入列',start:'开始处理',submit:'提交复核',complete:'人工验收',attachment:'保存证据',data_refresh:'更新关联数据',save:'保存记录',dismiss:'忽略或搁置',reopen:'重新打开'};
         target.querySelectorAll('.ops-timeline article').forEach((article,i)=>{const entry=d.timeline[i];if(entry.type==='annotation')article.querySelector('b').textContent=categories[entry.category]||entry.category;else article.querySelector('p').textContent=events[entry.event]||entry.event;if(entry.date.includes('T'))article.querySelector('small').textContent=new Date(entry.date).toLocaleString('zh-CN')+'（本机时间）';});
         chart=echarts.init(target.querySelector('#opsTrend'));
         chart.setOption({tooltip:{trigger:'axis'},grid:{left:45,right:20,top:25,bottom:40},xAxis:{type:'category',data:dates},yAxis:{type:'value',minInterval:1},series:[{type:'line',name:'原日销量',data:metric.values||[],symbolSize:7,lineStyle:{color:'#246b59',width:3},itemStyle:{color:'#246b59'},areaStyle:{color:'#e2eee6'},markLine:{symbol:'none',data:d.timeline.filter(t=>t.type==='annotation'&&dates.includes(t.occurred_on)).map(t=>({xAxis:t.occurred_on,name:t.category}))}}]});
         resize=()=>chart?.resize();root.addEventListener('resize',resize);
         target.querySelector('#opsAsk').onclick=()=>ask(`${d.shop} 的「${d.product}」在 ${dates[0]} 至 ${dates.at(-1)} 的日销变化是什么？请查该商品原始证据，区分事实与待核查原因。`);
         target.querySelector('#opsFeedback').onsubmit=async ev=>{ev.preventDefault();try{await DataHub.api('/operations/feedback',json({version,shop:d.shop,product:d.product,...Object.fromEntries(new FormData(ev.target))}));toast('人工判断已留档，原规则未更改');await query();await profile(object);}catch(e){toast(e.message);}};
         target.querySelector('#opsAnnotation').onsubmit=async ev=>{ev.preventDefault();const value=Object.fromEntries(new FormData(ev.target));try{await DataHub.api('/operations/annotations',json({version,shop:d.shop,product:d.product,...value,confirmed:value.confirmed==='on'}));toast('事项已记录，没有执行平台操作');await profile(object);}catch(e){toast(e.message);}};
         target.querySelectorAll('[data-ops-task]').forEach(b=>b.onclick=()=>root.dispatchEvent(new CustomEvent('workspace:action',{detail:{id:b.dataset.opsTask}})));
         target.querySelector('#opsSync').onclick=async ev=>{if(!confirm('同步完整数据的本地候选行动？只更新证据，不批准或执行任何业务操作。'))return;ev.target.disabled=true;try{const r=await fetch('/api/actions/sync',json({candidates:[],use_workspace:true}));const value=await r.json();if(!r.ok)throw Error(value.detail);toast('候选已同步；新增 '+value.added+' 项');await profile(object);}catch(e){toast(e.message);ev.target.disabled=false;}};
         target.scrollIntoView({behavior:'smooth',block:'start'});
       }catch(e){if(valid()&&request===profileTicket)target.innerHTML='<div class="notice">'+esc(e.message)+'</div>';}
     };
     node.querySelector('#opsTriage').onclick=()=>{mode='triage';mount(node,{toast,masked});};
     node.querySelector('#opsCatalog').onclick=()=>{mode='catalog';mount(node,{toast,masked});};
     node.querySelector('#opsFilter').onclick=()=>{shop=node.querySelector('#opsShop').value;search=node.querySelector('#opsSearch').value;offset=0;query().catch(e=>toast(e.message));};
     await query();if(pending&&valid()){const selected=pending;pending=null;await profile(selected);}
   }catch(e){if(valid())node.innerHTML='<div class="empty">'+esc(e.message)+'</div>';}
 }
 function enhanceAnswer(result,node){
   if(!node||!result.evidence)return;
   const products=new Map();
   for(const evidence of result.evidence){
     const output=evidence.result||{};
     if(output.product&&output.shop)products.set(output.shop+'|'+output.product,{shop:output.shop,product:output.product});
     for(const row of output.rows||[]){const shop=row.shops?.length===1?row.shops[0]:row['店铺'];const product=row.product||row['SKU中文名'];if(shop&&product)products.set(shop+'|'+product,{shop,product});}
   }
   if(!products.size)return;
   const section=document.createElement('section');section.className='panel space';
   const title=document.createElement('h3');title.textContent='本次证据中的商品';section.append(title);
   if(result.version!==DataHub.current?.version){const note=document.createElement('p');note.textContent='这是历史版本回答。请在数据中心恢复相应版本后查阅商品，避免把当前数据当作当时证据。';section.append(note);}
   else for(const object of [...products.values()].slice(0,20)){const button=document.createElement('button');button.className='button small';button.textContent=object.shop+' · '+object.product;button.onclick=()=>root.dispatchEvent(new CustomEvent('workspace:product',{detail:object}));section.append(button);}
   if(products.size>20){const note=document.createElement('p');note.textContent='快捷入口显示前20个商品；完整名单见查询证据。';section.append(note);}
   node.append(section);
 }
 root.Operations={mount,cancel,enhanceAnswer,select:value=>{pending=value;}};
})(window);
