(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const state={queued:'等待执行',running:'正在采集',paused:'已暂停 · 需要处理',pending_review:'待审核导入',complete:'数据已保存',cancelled:'已取消'};
 const ai={not_requested:'尚未调用',running:'正在分析',complete:'报告已保存',failed:'失败 · 不自动重试',daily_limit:'今日自动额度已使用',skipped_unchanged:'数据未变 · 跳过调用',input_limit:'输入过长 · 未调用'};
 const post=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 async function api(path,options){const r=await fetch('/api/hub/ziniao'+path,options);const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求未完成');return d;}
 function chat(id){root.dispatchEvent(new CustomEvent('workspace:chat',{detail:{id}}));}
 const labels={order_id:'订单号',line_id:'SKU ID',sku_id:'SKU ID',sku:'商家 SKU',product:'商品',status:'状态',created_at:'创建时间',quantity:'商品数量',returned_quantity:'退回商品数量',return_type:'取消 / 退货类型',source_row:'来源行',transaction_id:'订单 / 调整单 ID',transaction_type:'交易类型',settled_at:'结算日期',currency:'币种',settlement:'结算金额',revenue:'总收入',refund:'折扣后退款小计',fees:'总费用',adjustment:'调整金额',related_order_id:'相关订单',commission:'平台佣金',transaction_fee:'交易手续费',shipping_fee:'商家运费',affiliate_fee:'联盟佣金',line_count:'商品行数',cancelled_lines:'取消商品行',cancelled_line_share:'取消行占比',source_rows:'来源行',rule:'筛查口径',risk:'符合筛查'};
 function table(rows){if(!rows?.length)return '<p>当前范围没有明细。</p>';const keys=Object.keys(rows[0]);return '<div class="table-wrap"><table class="data-table"><thead><tr>'+keys.map(k=>'<th>'+esc(labels[k]||k)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>'<td>'+esc(r[k]===null?'不可计算':Array.isArray(r[k])?r[k].join(', '):r[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
 function fees(s){const rows=Object.entries(s?.settlement?.fee_breakdown||{});return rows.length?'<details><summary>查看平台费用拆解 · '+rows.length+' 列</summary><p>按原字段及符号展示；父子层级项目不可再次相加。</p>'+table(rows.map(([name,value])=>({'平台原字段':name,'金额':value})))+'</details>':'';}
 function summary(s){
  if(!s)return '<p>尚无已验证数据。</p>';
  const hasOrders=s.orders_available!==false, cards=[
   ['账单交易',s.settlement.transaction_count+' 条'],['结算金额 · '+s.currency,s.settlement.settlement],
   ['总收入',s.settlement.revenue],['总费用（原符号）',s.settlement.fees],
   ['折扣后退款小计',s.settlement.refund],['调整金额',s.settlement.adjustment]];
  if(hasOrders)cards.push(['历史创建窗口订单',s.orders.order_count+' 笔'],['商品行 / 数量',s.orders.line_count+' / '+(s.orders.quantity??'不可计算')],['窗口内未匹配交易',s.settlement.unmatched_transaction_count+' 条']);
  const days=s.daily||[],max=Math.max(1,...days.map(d=>d.order_count));
  const orderDetail=hasOrders?'<h4>创建窗口每日订单数</h4><div class="ziniao-bars">'+days.map(d=>'<div><span>'+esc(d.date)+'</span><meter min="0" max="'+max+'" value="'+d.order_count+'"></meter><strong>'+d.order_count+'</strong></div>').join('')+'</div><h4>订单商品行状态分布</h4>'+table(Object.entries(s.orders.line_status_counts).map(([status,count])=>({status,line_count:count})))+'<p>新增取消商品行风险筛查：'+esc(s.product_risk_count??0)+' 个 SKU。数量包含已取消商品行，不等于成交销量。</p>':'<p>本批次仅包含账单，不含订单列表；不计算日销、总订单量或取消率。</p>';
  return '<div class="ziniao-grid">'+cards.map(([k,v])=>'<div><small>'+esc(k)+'</small><p class="ziniao-number">'+esc(v??'不可计算')+'</p></div>').join('')+'</div><p class="notice">'+esc(s.period)+' · '+esc(s.platform_timezone)+'。结算金额不是银行到账或利润。'+esc(s.completeness_note||'历史批次按原日期范围，订单与账单不是同一订单群。')+'</p>'+orderDetail+'<details><summary>计算与对账口径</summary><ul>'+s.rules.map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul></details>';
 }
 async function mount(host,{toast}){
  const node=document.createElement('section');node.className='panel space ziniao-panel';host.prepend(node);
  let busy=false,detailId='',timer,selectedStore='',stores=[],backendReady=false;
  async function refresh(){
   if(!node.isConnected){clearTimeout(timer);return;}
   try{
    const s=await api('/status');if(!node.isConnected)return;const p=s.plan;backendReady=!!s.batch_supported;stores=s.stores||[];if(!selectedStore&&stores.length)selectedStore=stores[0].store_id;
    if(s.current_version&&DataHub.current?.version&&s.current_version!==DataHub.current.version&&s.runs.some(j=>j.version===s.current_version)){await DataHub.reload();toast('采集数据已更新，工作台已切换到同一版本');if(!node.isConnected)return;}
    node.innerHTML=`<div class="ziniao-heading"><div><div class="eyebrow">ZINIAO / 自动报表</div><h2>紫鸟自动采集</h2><p>${stores.length?stores.length+' 家店铺':esc(p.shop)} · 账单 · 各店币种独立</p></div><span class="ziniao-badge">${s.recipe_reviewed?(s.schedule_approved?'首批已审核':'等待首批审核'):'导出配方待实测'}</span></div>
     <div class="ziniao-grid"><div><small>连接</small><p>${esc(p.last_check?.message||'尚未在工作台检查')}</p></div><div><small>执行计划</small><p>每天 09:00 · 马来西亚时间</p><small>当月 1 日至当天（含当天）；当天截至导出时</small></div><div><small>定时状态（${(p.store_ids||[p.store_id]).length} 店）</small><p>${p.enabled?'已启用':'未启用 / 已暂停'}</p><small>下次：${p.enabled?esc(p.next_due):'首批核对后开启'}</small></div><div><small>自动 AI 用量限制</small><p>每天最多 1 次 / 店</p><small>输入 ≤16k · 输出 ≤2k token，不自动付费重试</small></div></div>
     <p class="notice">${esc(s.notice)} ${esc(p.last_schedule?.status==='missed'?'上次计划因离线或延迟未执行，可手动补跑。':'')}</p>
     <div class="form-actions"><button class="button" data-z="check">检查紫鸟连接</button><button class="button primary" data-z="run" ${s.batch_supported?'':'disabled'}>一键导出全部店铺账单</button><button class="button" data-z="plan">${p.enabled?'暂停定时':'启用定时'}</button><button class="button" data-z="data">查看当前账单</button><button class="button" data-z="refresh">刷新状态</button></div>
     <p>仅导出和分析，不修改店铺订单、商品或资金。一次建立全部店铺任务，按顺序下载；各店分别审核。马来西亚账单为 MYR / UTC+8，泰国账单为 THB / UTC+7，不跨币种合计。</p>
     ${!s.batch_supported?'<p class="notice">后台尚未加载六店版本，请先重启工作台；批量按钮暂不可用。</p>':''}
     <div class="table-wrap"><table class="data-table"><thead><tr><th>紫鸟店铺</th><th>页面登录名称</th><th>币种 / 时区</th><th>数据审核</th><th>操作</th></tr></thead><tbody>${stores.map(t=>'<tr><td>'+esc(t.shop)+'</td><td>'+esc(t.identity)+'</td><td>'+esc(t.currency)+' / '+esc(t.timezone)+'</td><td>'+(t.approved?'已审核':'待首批审核')+'</td><td><button class="button small" data-store-run="'+esc(t.store_id)+'">只导此店</button></td></tr>').join('')}</tbody></table></div>
     ${(s.batches||[]).map(b=>'<div class="notice"><strong>批量 '+esc(b.id.slice(0,8))+'</strong> · 文件 '+b.files_ready+'/'+b.run_ids.length+' · 已校验 '+(b.counts.pending_review+b.counts.complete)+' · 暂停 '+b.counts.paused+'<div class="form-actions"><button class="button small" data-batch-resume="'+esc(b.id)+'">继续未完成店铺</button>'+(b.files_ready===b.run_ids.length?'<a class="button small" href="/api/hub/ziniao/batches/'+esc(b.id)+'/download">下载全部原始账单 ZIP'+(b.all_validated?'':'（含待校验文件）')+'</a>':'')+'</div></div>').join('')}
     <div class="table-wrap"><table class="data-table"><thead><tr><th>采集范围</th><th>数据状态</th><th>AI 报告</th><th>操作</th></tr></thead><tbody>${s.runs.map(j=>`<tr><td>${esc(j.shop)} · ${esc(j.currency||'')}<br>${esc(j.report_name||'历史：订单列表 + 账单')}<br>${esc(j.start)} ～ ${esc(j.end)}<br><small>${esc(j.created_at)}</small></td><td>${esc(state[j.state]||j.state)}<br><small>${esc(j.error||'')}</small></td><td>${esc(ai[j.ai_status]||j.ai_status||'—')}${j.usage?'<br><small>'+esc(JSON.stringify(j.usage))+'</small>':''}</td><td><button class="button small" data-z-job="${esc(j.id)}">详情 / 处理</button>${j.conversation_id?`<button class="button small" data-z-chat="${esc(j.conversation_id)}">打开报告与追问</button>`:''}</td></tr>`).join('')||'<tr><td colspan="4">还没有采集任务。连接成功不代表报表已经导出。</td></tr>'}</tbody></table></div><div class="ziniao-detail"></div>`;
    node.querySelectorAll('[data-z]').forEach(b=>b.onclick=()=>act(async()=>{
     if(b.dataset.z==='check'){toast((await api('/check',post({}))).message);}
     if(b.dataset.z==='run'){if(!confirm('一次导出以下 '+stores.length+' 家店的账单：\n'+stores.map(t=>t.shop).join('\n')+'\n各店当月 1 日至当天，按顺序执行。首次只下载和校验，不自动调用 AI。'))return;await api('/batches',post({confirmed:true,store_ids:stores.map(t=>t.store_id)}));toast('全部店铺任务已登记，逐店下载');}
     if(b.dataset.z==='plan'){if(!confirm(p.enabled?'暂停后续定时任务？正在执行的任务不会中断。':'启用每天 9 点导出及 AI 分析？会使用现有 DeepSeek 额度。'))return;await api('/plan',post({enabled:!p.enabled,confirmed:true,store_ids:stores.length?stores.map(t=>t.store_id):null}));}
     if(b.dataset.z==='data'){detailId='data';await showData();return;}
     await refresh();
    }));
    node.querySelectorAll('[data-store-run]').forEach(button=>button.onclick=()=>act(async()=>{const t=stores.find(t=>t.store_id===button.dataset.storeRun);if(!confirm('只导出 '+t.shop+' 的当月账单？'))return;await api('/runs',post({confirmed:true,store_id:t.store_id}));await refresh();}));
    node.querySelectorAll('[data-batch-resume]').forEach(button=>button.onclick=()=>act(async()=>{if(!confirm('继续此批次尚未完成的店铺？已完成、待审核及已取消任务不会重复导出。'))return;await api('/batches/'+button.dataset.batchResume+'/resume',post({confirmed:true}));await refresh();}));
    node.querySelectorAll('[data-z-chat]').forEach(b=>b.onclick=()=>chat(b.dataset.zChat));
    if(!backendReady)node.querySelector('[data-z=plan]').disabled=true;
    node.querySelectorAll('[data-z-job]').forEach(b=>b.onclick=()=>act(async()=>{detailId=b.dataset.zJob;await showJob(detailId);}));
    if(detailId==='data')await showData();else if(detailId)await showJob(detailId);
    clearTimeout(timer);if(p.enabled||s.runs.some(j=>j.state==='running'||j.state==='queued'||j.ai_status==='running'))timer=setTimeout(refresh,s.runs.some(j=>j.state==='running'||j.state==='queued'||j.ai_status==='running')?4000:15000);
   }catch(e){if(node.isConnected)node.innerHTML='<h2>紫鸟自动采集</h2><p>'+esc(e.message)+'。若接口不存在，请重启工作台加载新版本。</p>';}
  }
  async function act(fn){if(busy)return;busy=true;try{await fn();}catch(e){toast(e.message);}finally{busy=false;}}
  async function showJob(id){
   const j=await api('/runs/'+id);const out=node.querySelector('.ziniao-detail');if(!out)return;
   out.innerHTML=`<h3>任务详情 · ${esc(state[j.state])}</h3><p>${esc(j.shop)} · ${esc(j.currency||'')} · ${esc(j.start)} ～ ${esc(j.end)}</p><p>${esc(j.error||'')}</p><div class="form-actions">${['paused','running'].includes(j.state)?'<button class="button" data-j="resume">恢复 / 检查下载</button>':''}${['paused','queued','pending_review'].includes(j.state)?'<button class="button" data-j="cancel">取消本地任务</button>':''}${j.state==='pending_review'?'<button class="button primary" data-j="activate">核对并导入，生成 AI 报告</button>':''}${j.state==='complete'&&!j.conversation_id&&j.ai_status!=='skipped_unchanged'?'<button class="button" data-j="analyze">手动调用 AI（可能计费）</button>':''}</div>
    ${j.files.map(f=>`<p><a href="${esc(f.url)}">下载原始 ${esc(f.kind==='settlement'?'账单':'历史订单列表')} · ${esc(f.name)}</a><br><small>SHA256 ${esc(f.sha256)}</small></p>`).join('')}
    ${summary(j.summary)}${fees(j.summary)}${Object.entries(j.preview||{}).map(([k,v])=>'<details><summary>'+esc(k==='orders'?'历史订单列表':'账单')+' · '+v.row_count+' 行 · 查看表头和前 5 行</summary><p>'+esc(v.header.join(' | '))+'</p>'+table(v.rows)+'</details>').join('')}`;
   out.querySelectorAll('[data-j]').forEach(b=>b.onclick=()=>act(async()=>{
    const op=b.dataset.j;
    const prompt=op==='activate'?'我已核对店铺、日期、币种、表头、行数和金额。同意保存新版本并调用 AI（可能计费）。':op==='analyze'?'本次手动请求可能再次计费，确认调用？':op==='cancel'?'取消本地任务？原始文件保留，平台上已发起的导出不会被取消。':'恢复本任务？仅检查已有导出，不重复提交不确定的导出请求。';
    if(!confirm(prompt))return;
    const body={confirmed:true};if(op==='activate'){await DataHub.reload();body.expected_version=DataHub.current.version;}
    await api('/runs/'+id+'/'+op,post(body));await DataHub.reload();await refresh();
   }));
   if(!backendReady){out.querySelectorAll('[data-j]').forEach(b=>b.disabled=true);out.insertAdjacentHTML('afterbegin','<p class="notice">请先重启后台加载六店版本；当前仅可查看和下载，不能提交新操作。</p>');}
  }
  async function showData(kind='summary',offset=0){
   const version=DataHub.current?.version||'';
   const d=await api('/data?'+new URLSearchParams({version,kind,offset,limit:50,store_id:selectedStore}));const out=node.querySelector('.ziniao-detail');if(!out)return;
   out.innerHTML='';
   const tabs=d.summary&&d.summary.orders_available!==false?['summary','settlement','orders','products','anomalies']:['summary','settlement'];
   const names={summary:'关键指标',settlement:'账单明细',orders:'历史订单明细',products:'SKU 分析',anomalies:'取消风险筛查'};
   const unavailable=d.available===false||!d.summary;
   out.innerHTML='<h3>TikTok 账单分析 · 独立口径</h3><p>版本 '+esc(d.version?.slice(0,8))+'；不混入马帮利润。来源行只含分析必需字段，完整原文件可在任务中下载。</p><div class="form-actions">'+tabs.map(k=>'<button class="button" data-kind="'+k+'">'+names[k]+'</button>').join('')+'</div>'+(unavailable?'<p>'+esc(d.note||'尚无已验证账单。')+'</p>':kind==='summary'?summary(d.summary):'<p>匹配 '+esc(d.total||0)+' 条 · 显示 '+(d.total?offset+1:0)+'—'+Math.min(offset+50,d.total||0)+'</p>'+table(d.rows))+(kind!=='summary'&&!unavailable?'<button class="button" data-page="'+Math.max(0,offset-50)+'" '+(offset===0?'disabled':'')+'>上一页</button><button class="button" data-page="'+(offset+50)+'" '+(offset+50>=(d.total||0)?'disabled':'')+'>下一页</button>':'');
   out.insertAdjacentHTML('afterbegin','<label>查看店铺 <select data-store-select>'+stores.map(t=>'<option value="'+esc(t.store_id)+'" '+(selectedStore===t.store_id?'selected':'')+'>'+esc(t.shop)+' · '+esc(t.currency)+'</option>').join('')+'</select></label>');
   const select=out.querySelector('[data-store-select]');if(select)select.onchange=()=>act(async()=>{selectedStore=select.value;await showData();});
   out.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>act(()=>showData(b.dataset.kind)));
   if(kind==='summary')out.insertAdjacentHTML('beforeend',fees(d.summary));
   out.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>act(()=>showData(kind,Number(b.dataset.page))));
  }
  await refresh();
 }
 function overview(host,masked){
  const box=document.createElement('section');box.className='notice ziniao-overview';host.prepend(box);
  function update(){if(!box.isConnected)return;api('/status').then(async s=>{if(!box.isConnected)return;const last=s.runs[0],saved=s.runs.find(j=>j.version===DataHub.current?.version);
   if(s.current_version&&DataHub.current?.version!==s.current_version&&s.runs.some(j=>j.version===s.current_version)){await DataHub.reload();if(!box.isConnected)return;}
   box.innerHTML=`<strong>紫鸟采集 · ${masked?'店铺已隐藏':esc(s.plan.shop)}</strong><p>${last?esc(state[last.state])+' · '+esc(last.start)+' ～ '+esc(last.end):'待联调 · 尚无真实报表采集'}${saved?' · 当前工作台版本包含本次采集':''}</p><a class="button small" href="#data">查看采集与原生分析 →</a>`;
   setTimeout(update,15000);
  }).catch(()=>{box.textContent='紫鸟采集入口等待新版本服务加载。';});}update();
 }
 root.ZiniaoCollection={mount,overview};
})(window);
