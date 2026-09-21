(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const json=(body,method='POST')=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const api=async(path,options)=>{const r=await fetch('/api/hub'+path,options);const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;};
 let ticket=0,controller=null,timer=null,selected='',seed='',focusTurn='',jump=false;
 try{selected=localStorage.getItem('chat.active')||'';}catch{}
 const setSelected=id=>{selected=id;try{localStorage.setItem('chat.active',id);}catch{}};
 function cancel(){ticket++;controller?.abort();controller=null;clearTimeout(timer);timer=null;}
 function seedQuestion(question){seed=String(question||'');}
 const draftKey=id=>'chat.draft.'+(id||'new');
 function getDraft(){try{return sessionStorage.getItem(draftKey(selected))||'';}catch{return '';}}
 function draft(value){try{sessionStorage.setItem(draftKey(selected),value);}catch{}}
 function markdown(raw){
  const blocks=String(raw).split(/```/g);
  return blocks.map((s,i)=>{if(i%2){const nl=s.indexOf('\n'),code=nl<0?s:s.slice(nl+1),lang=nl<0?'':s.slice(0,nl);return `<div class="chat-code"><div><span>${esc(lang||'code')}</span><button type="button" data-copy-code>复制代码</button></div><pre><code>${esc(code)}</code></pre></div>`;}
   return WorkbenchReport.render(s).replace(/\[([^\]<]+)\]\((https?:\/\/[^\s<)]+)\)/g,(all,label,url)=>{try{const parsed=new URL(url.replace(/&amp;/g,'&'));if(!['http:','https:'].includes(parsed.protocol))return all;return `<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;}catch{return all;}});
  }).join('');
 }
 async function mount(node,{toast,masked}){
  cancel();const mine=ticket,valid=()=>mine===ticket&&node.isConnected;
  if(masked){node.innerHTML='<div class="empty">聊天记录可能包含真实业务数据和个人信息。请关闭演示脱敏后使用；本页不会假装已脱敏。</div>';return;}
  let current=null,deleted=false,search='',isSending=false,selectRequest=0,listRequest=0;
  node.classList.add('chat-host');node.innerHTML=`<section class="chat-app"><aside class="chat-sidebar"><div class="chat-brand">商策 <span>CHAT</span></div><button class="chat-new" id="chatNew">＋ 新聊天</button><label class="chat-search"><span>⌕</span><input id="chatSearch" aria-label="搜索聊天" placeholder="搜索聊天记录"></label><div class="chat-list-label"><span id="chatListLabel">你的聊天</span><button id="chatTrash" title="回收站">回收站</button></div><div id="chatList" class="chat-list">正在加载…</div></aside>
   <div class="chat-main"><header class="chat-header"><button id="chatToggle" class="chat-icon" aria-label="显示聊天列表">☰</button><div class="chat-heading"><h1>AI 聊天</h1></div><span id="chatTitle">新对话</span><div class="chat-menu"><button id="chatRename" title="重命名" class="chat-icon">重命名</button><button id="chatExport" title="导出聊天" class="chat-icon">导出</button><button id="chatDelete" title="移入回收站" class="chat-icon">删除</button></div></header>
   <div id="chatMessages" class="chat-messages" aria-live="polite"></div><button id="chatBottom" class="chat-bottom" hidden>↓ 回到最新消息</button><div class="chat-compose-area"><div id="chatStatus" class="chat-status" role="status"></div><form id="chatForm" class="chat-composer"><textarea id="chatInput" aria-label="发送消息" placeholder="有什么想聊的？也可以直接问工作台里的数据" rows="2" maxlength="20000"></textarea><div class="chat-composer-tools"><button id="chatStop" type="button" hidden>停止生成 ■</button><button id="chatSend" type="submit" aria-label="发送消息">↑</button></div></form></div></div></section>`;
  const $=id=>node.querySelector('#'+id),input=$('chatInput'),messages=$('chatMessages');
  input.value=getDraft();
  const capture=fn=>async e=>{try{await fn(e);}catch(error){if(valid())toast(error.message);}};
  const atBottom=()=>messages.scrollHeight-messages.scrollTop-messages.clientHeight<130;
  const bottom=()=>{messages.scrollTop=messages.scrollHeight;};
  function inputSize(){input.style.height='auto';input.style.height=Math.min(190,input.scrollHeight)+'px';}
  function controls(){const busy=isSending||current?.busy,archived=current?.deleted;input.disabled=!!archived;$('chatSend').disabled=!!busy||!!archived;$('chatStop').hidden=!busy;$('chatRename').disabled=!current||!!busy;$('chatExport').disabled=!current;$('chatDelete').disabled=!current||!!busy;$('chatDelete').textContent=archived?'恢复':'删除';}
  function copyButtons(){messages.querySelectorAll('[data-copy-code]').forEach(b=>b.onclick=capture(async()=>{await navigator.clipboard.writeText(b.closest('.chat-code').querySelector('code').textContent);toast('代码已复制');}));messages.querySelectorAll('[data-chat-copy]').forEach(b=>b.onclick=capture(async()=>{await navigator.clipboard.writeText(current.turns.find(t=>t.id===b.dataset.chatCopy).content);toast('回复已复制');}));}
  function render(scroll=true){
   $('chatTitle').textContent=current?.title||'新对话';
   const turns=current?.turns||[];
   if(!turns.length){messages.innerHTML=`<div class="chat-welcome"><div class="chat-mark">✦</div><h2>今天有什么想聊的？</h2><p>聊想法、写文案、学知识，也可以直接分析你的业务数据。</p><div class="chat-starters">${['帮我润色一段面试自我介绍','EXPOSE TK 日销哪些产品异常？','用简单的例子解释什么是机器学习','帮我梳理今天的工作安排'].map(q=>`<button data-chat-prompt="${esc(q)}">${esc(q)} ↗</button>`).join('')}</div></div>`;messages.querySelectorAll('[data-chat-prompt]').forEach(b=>b.onclick=()=>{input.value=b.dataset.chatPrompt;draft(input.value);inputSize();input.focus();});}
   else messages.innerHTML='<div class="chat-thread">'+turns.map((t,i)=>`<article class="chat-turn" data-chat-turn="${esc(t.id)}"><div class="chat-user"><div>${esc(t.question).replace(/\n/g,'<br>')}</div></div><div class="chat-answer"><span class="chat-avatar">✦</span><div class="chat-answer-body"><div class="chat-answer-content">${t.content?markdown(t.content):t.status==='pending'?'<span class="chat-pulse">正在回复…</span>':''}</div>${['error','stopped'].includes(t.status)?`<p class="chat-error">${esc(t.error||'本次回复已中断')}</p>${i===turns.length-1?`<button class="button small" data-chat-retry="${esc(t.id)}">重试这条消息</button>`:''}`:''}${t.status==='complete'?`<div class="chat-answer-actions"><button data-chat-copy="${esc(t.id)}">复制</button>${t.analysis_id?`<button data-chat-action="${esc(t.id)}">＋ 加入行动中心</button>`:''}${(t.linked_actions||[]).map(a=>`<button data-action-link="${esc(a.id)}" title="${esc(a.title)}">查看行动 ↗</button>`).join('')}<small>${esc(t.model||'历史回复')} ${t.usage?.total_tokens?'· '+t.usage.total_tokens+' tokens':''}${t.version?' · 数据 '+esc(t.version.slice(0,8)):''}</small></div>`:''}${t.evidence?.length?`<details class="chat-evidence"><summary>查看本次查数依据 · ${t.evidence.length} 次只读查询</summary><pre>${esc(JSON.stringify(t.evidence,null,2))}</pre></details>`:''}</div></div></article>`).join('')+'</div>';
   copyButtons();messages.querySelectorAll('[data-chat-action]').forEach(b=>b.onclick=capture(()=>{if(isSending||current.busy)return toast('请等待本聊天回复完成后再加入行动。');const t=turns.find(t=>t.id===b.dataset.chatAction),selection=window.getSelection();const article=b.closest('[data-chat-turn]');const text=selection?.rangeCount&&article.contains(selection.anchorNode)&&article.contains(selection.focusNode)?selection.toString():'';root.ChatActions.open(current,t,text,{toast,onSaved:async()=>{const p=await api('/conversations/'+current.id);if(!valid())return;current=p;render(false);}});}));messages.querySelectorAll('[data-action-link]').forEach(b=>b.onclick=()=>root.dispatchEvent(new CustomEvent('workspace:action',{detail:{id:b.dataset.actionLink}})));messages.querySelectorAll('[data-chat-retry]').forEach(b=>b.onclick=capture(()=>send(current.turns.find(t=>t.id===b.dataset.chatRetry))));
   messages.querySelectorAll('[data-chat-turn]').forEach(article=>{const t=turns.find(t=>t.id===article.dataset.chatTurn);if(t?.evidence?.length)root.Operations?.enhanceAnswer(t,article.querySelector('.chat-evidence'));});
   if(current?.deleted)$('chatStatus').textContent='此聊天在回收站；恢复后可以继续对话。';
   controls();if(scroll)bottom();
  }
  async function list(){const request=++listRequest;const r=await api('/conversations?'+new URLSearchParams({q:search,deleted:String(deleted)}));if(!valid()||request!==listRequest)return [];
   $('chatList').innerHTML=r.items.map(c=>`<button class="chat-list-item ${c.id===selected?'active':''}" data-chat-id="${esc(c.id)}" title="${esc(c.title)}"><b>${esc(c.title)}</b><small>${c.busy?'正在回复 · ':''}${esc(new Date(c.updated_at).toLocaleDateString())} · ${c.turn_count} 条提问</small></button>`).join('')||'<p class="chat-list-empty">'+(deleted?'回收站为空':search?'没有匹配聊天':'从一条消息开始')+'</p>';
   $('chatList').querySelectorAll('[data-chat-id]').forEach(b=>b.onclick=capture(()=>open(b.dataset.chatId)));return r.items;
  }
  async function open(id){const request=++selectRequest;controller?.abort();controller=null;clearTimeout(timer);draft(input.value);isSending=false;setSelected(id);const p=await api('/conversations/'+id);if(!valid()||request!==selectRequest)return;current=p;input.value=seed||getDraft();seed='';inputSize();$('chatStatus').textContent='';render();if(focusTurn){const target=messages.querySelector('[data-chat-turn="'+CSS.escape(focusTurn)+'"]');target?.scrollIntoView({block:'center'});focusTurn='';}await list();node.querySelector('.chat-app').classList.remove('show-list');if(p.busy)poll(id);}
  function poll(id){clearTimeout(timer);timer=setTimeout(async()=>{try{if(!valid()||selected!==id)return;const p=await api('/conversations/'+id);if(!valid()||selected!==id)return;const near=atBottom();current=p;render(near);if(p.busy)poll(id);else{$('chatStatus').textContent='';await list();}}catch(error){if(valid())$('chatStatus').textContent='暂时无法更新回复状态，可以刷新重试。';}},2000);}
  function fresh(reset=true){controller?.abort();controller=null;clearTimeout(timer);draft(input.value);selectRequest++;current=null;isSending=false;setSelected('');if(reset)draft('');input.value=seed||getDraft();seed='';inputSize();$('chatStatus').textContent='';render();list().catch(e=>toast(e.message));input.focus();}
  async function send(retry){
   if(isSending||current?.busy)return;
   const question=retry?retry.question:input.value.trim();if(!question)return;
   const sendingView=selectRequest;isSending=true;controls();$('chatStatus').textContent='正在发送…';
   try{
    if(!current){current=await api('/conversations',json({workspace_enabled:true}));if(!valid()||sendingView!==selectRequest)return;setSelected(current.id);}
    const id=current.id,requestId=retry?retry.id:crypto.randomUUID();const expected=current.revision;
    const turn=retry||{id:requestId,question,created_at:new Date().toISOString()};turn.status='pending';turn.content='';turn.error='';if(!retry)current.turns.push(turn);
    input.value='';draft('');inputSize();render();controller=new AbortController();
    const response=await fetch('/api/hub/assistant/stream',{...json({question,conversation_id:id,request_id:requestId,expected_revision:expected,workspace_enabled:true,version:DataHub.current?.version||''}),signal:controller.signal});
    if(!response.ok)throw Error('请求失败，请重试');
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',terminal=false,paint=0;
    while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const frames=buffer.split('\n\n');buffer=frames.pop();for(const frame of frames){if(!frame.startsWith('data: '))continue;const event=JSON.parse(frame.slice(6));if(!valid()||selected!==id)return;
     if(event.type==='delta'){turn.content+=event.text;const near=atBottom();if(Date.now()-paint>70){const target=messages.querySelector('[data-chat-turn="'+requestId+'"] .chat-answer-content');if(target)target.innerHTML=markdown(turn.content);paint=Date.now();if(near)bottom();}}
     if(event.type==='reset'){turn.content='';render(false);}
     if(event.type==='status')$('chatStatus').textContent=event.text;
     if(event.type==='done'){terminal=true;current=await api('/conversations/'+id);if(!valid()||selected!==id)return;$('chatStatus').textContent='';render();}
     if(event.type==='error'){terminal=true;current=await api('/conversations/'+id);if(!valid()||selected!==id)return;$('chatStatus').textContent=event.message;render();}
    }}
    if(!terminal)throw Error('连接中断；消息已保存，正在检查后台回复状态。');
    if(valid()&&selected===id)await list();
   }catch(error){if(error.name==='AbortError')return;if(valid()&&sendingView===selectRequest){$('chatStatus').textContent=error.message;if(current){current.busy=true;poll(current.id);}else toast(error.message);}}
   finally{if(valid()&&sendingView===selectRequest){isSending=false;controls();input.focus();}}
  }
  $('chatForm').onsubmit=e=>{e.preventDefault();send();};input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();send();}};input.oninput=()=>{draft(input.value);inputSize();};
  $('chatNew').onclick=fresh;$('chatToggle').onclick=()=>node.querySelector('.chat-app').classList.toggle('show-list');
  $('chatBottom').onclick=bottom;messages.onscroll=()=>{$('chatBottom').hidden=atBottom();};
  let searchTimer;$('chatSearch').oninput=e=>{search=e.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>list().catch(x=>toast(x.message)),200);};
  $('chatTrash').onclick=()=>{deleted=!deleted;$('chatListLabel').textContent=deleted?'回收站':'你的聊天';$('chatTrash').textContent=deleted?'返回聊天':'回收站';list().catch(e=>toast(e.message));};
  $('chatRename').onclick=capture(async()=>{const title=prompt('聊天名称',current.title);if(!title?.trim())return;current=await api('/conversations/'+current.id,json({expected_revision:current.revision,title},'PATCH'));if(!valid())return;render(false);await list();});
  $('chatDelete').onclick=capture(async()=>{const restore=current.deleted;if(!restore&&!confirm('将此聊天移入回收站？可以恢复，原分析审计不会删除。'))return;await api('/conversations/'+current.id,json({expected_revision:current.revision,deleted:!restore},'PATCH'));if(!valid())return;toast(restore?'聊天已恢复':'已移入回收站，可恢复');deleted=false;$('chatTrash').textContent='回收站';$('chatListLabel').textContent='你的聊天';fresh();});
  $('chatExport').onclick=()=>{if(current)location.href='/api/hub/conversations/'+current.id+'/export';};
  $('chatStop').onclick=capture(async()=>{if(!current)return;const r=await api('/conversations/'+current.id+'/stop',json({}));if(valid())$('chatStatus').textContent=r.note;});
  try{const items=await list();if(!valid())return;if(jump){jump=false;await open(selected);}else if(selected&&items.some(c=>c.id===selected))await open(selected);else if(seed)fresh(false);else if(items.length)await open(items[0].id);else fresh(false);}catch(error){if(valid())$('chatStatus').textContent=error.message;}
 }
 root.ChatUI={mount,cancel,seed:seedQuestion,markdown,navigate:(id,turn)=>{setSelected(id);focusTurn=turn||'';jump=true;}};
})(window);
