(function(){
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 window.HubActions={enhance:async function(task,reopen,toast){
   const shortcuts=document.getElementById('actionShortcuts'),form=document.getElementById('actionForm');if(!shortcuts||!form)return;
   const native=(task.origin?.query_evidence||[]).some(e=>e.tool==='native_tiktok_data');
   const route=native?'data':{ads:'ads',inventory:'inventory',finance:'finance',creators:'creators',daily:'inventory',after:'after'}[task.module];
   const dirty=()=>Object.entries(Object.fromEntries(new FormData(form))).some(([k,v])=>k in task&&String(v)!==String(task[k]));
   const leave=()=>!dirty()||confirm('当前有未保存的编辑，确定离开吗？');
   const button=(label,fn)=>{const b=document.createElement('button');b.type='button';b.className='button';b.textContent=label;b.onclick=fn;shortcuts.append(b);};
   if(task.origin?.conversation_id)button('返回来源聊天',()=>{if(leave())window.dispatchEvent(new CustomEvent('workspace:chat',{detail:{id:task.origin.conversation_id,turn:task.origin.turn_id}}));});
   button('继续问 AI',()=>{if(!leave())return;const question='请继续讨论行动「'+task.entity+' · '+task.title+'」。当前阶段：'+task.state+'；本地方案：'+(task.action||task.suggested_action)+'。\n已记录的验收要求：'+(task.acceptance||'待补充')+'。\n请先给下一步具体动作，再解释依据；没有数据支撑的原因请标为假设。';
     if(task.origin?.conversation_id)window.dispatchEvent(new CustomEvent('workspace:chat',{detail:{id:task.origin.conversation_id,turn:task.origin.turn_id,question}}));
     else window.dispatchEvent(new CustomEvent('workspace:ask',{detail:{question}}));
   });
   if(route)button('打开业务模块',()=>{if(!leave())return;document.getElementById('detailDialog').close();location.hash=route;});
   if(native)button('查看本批原生明细',async()=>{
     async function show(kind='summary',offset=0){try{const result=await DataHub.api('/ziniao/data?'+new URLSearchParams({version:task.data_version,kind,offset,limit:50}));const target=document.getElementById('actionSourceResults');if(!target||!shortcuts.isConnected)return;
       target.innerHTML='<h3>本任务固定引用的原生报表</h3><p>版本 '+esc(task.data_version)+'；不是当前最新数据。订单创建窗口与结算窗口不同。</p><div>'+['summary','orders','settlement','anomalies'].map(k=>'<button type="button" class="button" data-native-kind="'+k+'">'+({summary:'汇总',orders:'订单明细',settlement:'账单明细',anomalies:'取消风险'}[k])+'</button>').join('')+'</div><pre>'+esc(JSON.stringify(result,null,2))+'</pre>'+(result.total>offset+50?'<button type="button" class="button" data-native-next>下一页</button>':'');
       target.querySelectorAll('[data-native-kind]').forEach(b=>b.onclick=()=>show(b.dataset.nativeKind));const next=target.querySelector('[data-native-next]');if(next)next.onclick=()=>show(kind,offset+50);target.scrollIntoView({block:'nearest'});
     }catch(e){toast(e.message);}}await show();
   });
   if(task.module==='daily'&&!task.origin&&task.evidence[0]?.shop&&task.data_version===window.DataHub?.current?.version)button('查看商品档案',()=>{if(leave())window.dispatchEvent(new CustomEvent('workspace:product',{detail:{shop:task.evidence[0].shop,product:task.entity}}));});
   if(!task.origin&&window.DataHub?.current)button('查看业务明细',async()=>{try{
     const kind={ads:'gmv',inventory:'inventory',finance:'bill',creators:'creator',daily:'daily',after:'after'}[task.module];
     const shop=task.module==='daily'?task.evidence[0].shop:(['ads','finance'].includes(task.module)?task.entity_key.split('|')[0]:'');
     const result=await DataHub.api('/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:task.data_version||DataHub.current.version,kind,shop,product:task.entity,limit:100})});
     const target=document.getElementById('actionSourceResults');if(target&&target.closest('.action-shell')===shortcuts.closest('.action-shell')){target.innerHTML='<details open><summary>任务来源明细 · 匹配 '+result.total+' 条</summary><pre>'+esc(JSON.stringify(result,null,2))+'</pre></details>';target.scrollIntoView({block:'nearest'});}
   }catch(e){toast(e.message);}});
   const attachments=document.getElementById('actionAttachments');
   attachments.innerHTML='<div class="action-uploads"><label class="action-field">补充处理截图或文件<input type="file" id="actionFile" accept=".png,.jpg,.jpeg,.pdf,.xlsx,.csv,.txt,.md"></label><button type="button" class="button" id="actionUpload">保存附件</button><div id="actionFileList"></div><small>附件只保存到本机，不上传给模型。</small></div>';
   attachments.querySelector('#actionUpload').onclick=async()=>{if(dirty())return toast('请先保存当前编辑，再添加附件，避免重新打开时丢失内容。');const file=attachments.querySelector('#actionFile').files[0];if(!file)return toast('请选择文件');const data=new FormData();data.append('file',file);data.append('version',task.version);try{await DataHub.api('/actions/'+task.id+'/attachments',{method:'POST',body:data});toast('附件已保存，请在结果记录中引用文件名。');if(shortcuts.isConnected)await reopen(task.id);}catch(e){toast(e.message);}};
   const comparison=document.getElementById('actionComparison');comparison.innerHTML='<button type="button" class="button" id="actionCheckResult">检查后续数据是否支持复核</button><p id="actionCheckNote"></p>';
   comparison.querySelector('button').onclick=async()=>{try{const r=await DataHub.api('/actions/'+task.id+'/comparison');if(comparison.isConnected)comparison.querySelector('p').textContent=r.reason;}catch(e){toast(e.message);}};
   try{const d=await DataHub.api('/actions/'+task.id+'/attachments');if(!attachments.isConnected)return;attachments.querySelector('#actionFileList').innerHTML=d.items.map(a=>'<p><a href="/api/hub/actions/'+task.id+'/attachments/'+a.id+'">'+esc(a.name)+'</a> · '+Math.ceil(a.size/1024)+' KB</p>').join('');}catch(e){toast(e.message);}
 }};
})();
