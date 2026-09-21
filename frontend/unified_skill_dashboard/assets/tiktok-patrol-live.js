(function(root){
 'use strict';
 const e=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
 const labels={running:'读取中',queued:'等待巡检',complete:'巡检完成',partial:'部分完成',paused:'需要处理',interrupted:'已中断'};
 async function api(path,options){const r=await fetch('/api/hub/tiktok-patrol/live'+path,options);const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求未完成');return d;}
 function mount(host,storeId,range={}){
  const node=document.createElement('section');node.className='panel space patrol-live';(host.querySelector('.patrol-filters')||host.querySelector('.patrol-heading')).after(node);
  let timer,busy=false,selected='',generation=0,charts=[],metricChoice={},batchId='';
  const alive=()=>node.isConnected;
  function dispose(){charts.forEach(c=>c.dispose());charts=[];}
  const observer=new MutationObserver(()=>{if(!alive()){clearTimeout(timer);dispose();resize.disconnect();observer.disconnect();}});observer.observe(document.body,{subtree:true,childList:true});
  function cards(values){return '<div class="patrol-metric-grid">'+values.map(v=>`<article class="patrol-metric"><span>${e(v.label)}</span><strong>${fmt(v.value)} <small>${e(v.currency||'')}</small></strong>${v.change_pct!=null?`<small class="patrol-change">平台变化 ${v.change_pct>0?'+':''}${fmt(v.change_pct)}%</small>`:''}${v.detail?`<p>${e(v.detail)}</p>`:''}</article>`).join('')+'</div>';}
  function report(r){
   const home=r.sections.homepage,sales=r.sections.sales,ads=r.sections.ads;
   return `<div class="patrol-report-head"><div><h3>${e(r.shop)}</h3><p>${e(r.day)} · ${e(labels[r.state]||r.state)}</p></div><a class="button small" href="/api/hub/tiktok-patrol/live/runs/${e(r.id)}/report">下载本次记录</a></div>${r.error?`<p class="patrol-error" role="alert">${e(r.error)}</p>`:''}

    ${sales?`<div class="patrol-section-title"><h3>销售概览 · ${e(sales.currency)}</h3><small>${e(sales.period)} · ${e(sales.timezone||r.timezone)}</small></div>${cards(sales.data)}`:'<p>销售概览：尚未取得已核验数据</p>'}
    ${ads?`<div class="patrol-section-title"><h3>GMV Max 广告 · ${e(ads.currency)} <a class="button small" href="#ads">打开广告数据面板 →</a></h3><small>${e(ads.period)} · ${e(ads.timezone||r.timezone)}</small></div>${cards(ads.data)}`:`<p>广告概览：${e(r.section_errors?.ads||'尚未取得已核验数据')}</p>`}

    <details><summary>采集证据与统计口径</summary><p>${e(r.scope)}</p><p>销售与广告币种分别统计；平台 ROI 不代表利润率。</p>${Object.entries(r.sections).map(([k,v])=>`<p>${e({homepage:'首页',sales:'销售',ads:'广告'}[k])} · ${e(new Date(v.captured_at).toLocaleString())}<br><a href="${e(v.source_url)}" target="_blank" rel="noopener">平台原页面</a><br><span class="patrol-hash">SHA256 ${e(v.sha256)}</span></p>`).join('')}</details>`;
  }
  function trendHTML(data){
   if(!data)return '';
   return `<section class="patrol-trends"><div class="patrol-section-title"><div><h2>每日趋势</h2><p>${e(range.start)} — ${e(range.end)} · 已记录 ${data.recorded_days} / ${data.range_days} 天</p></div><a class="button small" href="/api/hub/tiktok-patrol/live/history.csv?${e(new URLSearchParams({store_id:storeId,start:range.start,end:range.end}))}">导出每日数据</a></div><div class="patrol-chart-grid">${[['sales','销售变化'],['ads','广告表现']].map(([kind,title])=>{const choices=[...new Map(data.series.filter(s=>s.kind===kind).map(s=>[s.label+'|'+s.currency,s])).values()];if(!choices.some(s=>s.label+'|'+s.currency===metricChoice[kind]))metricChoice[kind]=choices[0]?choices[0].label+'|'+choices[0].currency:'';return `<article class="patrol-chart-card"><div><h3>${title}</h3><select data-chart-metric="${kind}" aria-label="${title}指标">${choices.map(s=>`<option value="${e(s.label+'|'+s.currency)}" ${metricChoice[kind]===s.label+'|'+s.currency?'selected':''}>${e(s.label)}${s.currency?' · '+e(s.currency):''}</option>`).join('')}</select></div><div class="patrol-chart" data-chart="${kind}" role="img" aria-label="${title}每日折线图"></div></article>`;}).join('')}</div><details><summary>每日数据明细与日环比</summary><div class="table-wrap"><table class="data-table"><thead><tr>${['日期','店铺','模块 / 指标','数值','时区','较前日','日环比','当日版本'].map(t=>'<th>'+t+'</th>').join('')}</tr></thead><tbody>${data.rows.filter(r=>r.kind!=='homepage').map(r=>`<tr><td>${e(r.day)}</td><td>${e(r.shop)}</td><td>${e({sales:'销售',ads:'广告',homepage:'待办'}[r.kind])} / ${e(r.label)}</td><td>${fmt(r.value)} ${e(r.currency)}</td><td>${e(r.timezone)}</td><td>${fmt(r.delta)}</td><td>${r.daily_change_pct==null?'—':fmt(r.daily_change_pct)+'%'}</td><td>${r.versions}</td></tr>`).join('')}</tbody></table></div></details></section>`;
  }
  function renderCharts(data){
   if(!data)return;dispose();
   node.querySelectorAll('[data-chart]').forEach(el=>{
    const kind=el.dataset.chart,series=data.series.filter(s=>s.kind===kind&&s.label+'|'+s.currency===metricChoice[kind]);
    if(!series.length){el.innerHTML='<div class="patrol-chart-empty">所选范围尚无记录</div>';return;}
    if(!root.echarts){el.innerHTML='<div class="patrol-chart-empty">图表资源未加载，可展开每日数据明细查看</div>';return;}
    const c=root.echarts.init(el,null,{renderer:'svg'});charts.push(c);
    c.setOption({animation:false,color:['#286f5c','#c38b32','#5c7fc0','#9465ad','#ba6862','#54949b'],aria:{enabled:true},grid:{left:65,right:25,top:45,bottom:80},tooltip:{trigger:'axis',renderMode:'richText',valueFormatter:v=>fmt(v)},legend:{bottom:0,type:'scroll',textStyle:{fontSize:11}},xAxis:{type:'category',data:data.days,axisLabel:{formatter:v=>v.slice(5)}},yAxis:{type:'value',scale:true,splitLine:{lineStyle:{color:'#e8eeeb'}}},series:series.map(s=>({name:s.shop,type:'line',data:s.points.map(p=>p.value),connectNulls:false,smooth:false,showSymbol:true,symbolSize:8,lineStyle:{width:3}}))});
   });
   node.querySelectorAll('[data-chart-metric]').forEach(el=>el.onchange=()=>{metricChoice[el.dataset.chartMetric]=el.value;renderCharts(data);});
  }
  const resize=new ResizeObserver(()=>charts.forEach(c=>c.resize()));resize.observe(node);
  async function refresh(){
   if(!alive()){resize.disconnect();return;}const ticket=++generation;
   try{
    const [s,data]=await Promise.all([api('/status?store_id='+encodeURIComponent(storeId)),range.start&&range.end?api('/history?'+new URLSearchParams({store_id:storeId,start:range.start,end:range.end})):null]);
    if(!alive()||ticket!==generation)return;
    const batch=(s.batches||[]).find(b=>b.id===batchId)||(s.batches||[]).find(b=>b.state==='running')||(s.batches||[])[0];
    const active=s.runs.find(r=>r.state==='running')||batch?.state==='running';
    const runs=s.runs.filter(r=>!range.start||r.day>=range.start&&r.day<=range.end);
    if(!runs.some(r=>r.id===selected))selected=runs[0]?.id||'';
    dispose();
    node.innerHTML=`<div class="patrol-heading"><div><div class="eyebrow">紫鸟 / 每日巡检</div><h2>从 TikTok 后台读取</h2></div><div><button class="button primary" data-live-start ${!s.ready||busy||active?'disabled':''}>${active?'正在巡检…':storeId==='all'?'巡检全部店铺':'开始一次只读巡检'}</button><p class="patrol-hint">采集昨日销售、广告与当前待办</p></div></div><p data-live-error role="alert"></p>${batch?`<details class="patrol-batch" ${batch.state==='running'||batch.state==='partial'?'open':''}><summary>最近批次 · ${e(labels[batch.state]||batch.state)} · ${batch.items.filter(i=>i.state==='complete').length}/${batch.items.length} 店完整完成</summary><div class="patrol-batch-grid">${batch.items.map(i=>`<div><b>${e(i.shop)}</b><span class="patrol-state ${i.state==='complete'?'checked':'attention'}">${e(labels[i.state]||i.state)}</span>${i.error?`<p>${e(i.error)}</p>`:''}</div>`).join('')}</div></details>`:''}${trendHTML(data)}<section class="patrol-latest"><div class="patrol-section-title"><h2>巡检详情</h2><select data-live-select aria-label="选择巡检记录">${runs.map(r=>`<option value="${e(r.id)}" ${selected===r.id?'selected':''}>${e(r.day)} · ${e(r.shop)} · ${e(new Date(r.created_at).toLocaleString())}</option>`).join('')}</select></div><div data-live-report>${selected?report(runs.find(r=>r.id===selected)):'<p>所选范围尚无巡检记录。</p>'}</div></section>`;
    renderCharts(data);
    node.querySelector('[data-live-start]').onclick=async()=>{
     if(busy)return;busy=true;node.querySelector('[data-live-start]').disabled=true;
     try{const r=await api('/batches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({store_id:storeId,confirmed:true})});batchId=r.id;}
     catch(err){if(alive()){node.querySelector('[data-live-error]').textContent=err.message;node.querySelector('[data-live-start]').disabled=false;}busy=false;return;}
     busy=false;await refresh();
    };
    node.querySelector('[data-live-select]').onchange=ev=>{selected=ev.target.value;node.querySelector('[data-live-report]').innerHTML=report(runs.find(r=>r.id===selected));};
    clearTimeout(timer);if(active)timer=setTimeout(refresh,4000);
   }catch(err){if(alive()){node.innerHTML='<h2>每日巡检</h2><p role="alert">'+e(err.message)+'</p><button class="button" data-live-retry>重试连接</button>';node.querySelector('[data-live-retry]').onclick=refresh;}}
  }
  refresh();
 }
 root.TikTokPatrolLive={mount};
})(window);
