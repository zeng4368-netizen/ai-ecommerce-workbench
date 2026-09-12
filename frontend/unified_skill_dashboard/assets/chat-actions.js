(function(root){
 'use strict';
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const modules={daily:'日销核查',ads:'广告诊断',inventory:'库存核查',creators:'达人复盘',finance:'结算核查',after:'售后核查',general:'综合运营'};
 function open(chat,turn,selectedText,{toast,onSaved}){
  const dialog=document.createElement('dialog');dialog.className='chat-action-dialog';
  const suggested=selectedText||turn.content;
  dialog.innerHTML=`<form id="chatActionForm"><div class="chat-action-head"><div><small>CHAT → ACTION</small><h2>将建议加入行动中心</h2></div><button type="button" data-close aria-label="关闭">×</button></div><p>选取可执行的建议，确认后进入「待复核候选」。本次不调用模型，不自动执行业务操作。</p><div class="chat-action-grid"><label class="action-field">行动标题 *<input name="title" required maxlength="200" placeholder="例如：核查 adiey_466 退款订单并整理原因"></label><label class="action-field">商品 / 达人 / 工作对象 *<input name="entity" required maxlength="500" placeholder="明确这项行动针对谁"></label><label class="action-field">所属模块<select name="module">${Object.entries(modules).map(([k,v])=>`<option value="${k}" ${k==='general'?'selected':''}>${v}</option>`).join('')}</select></label><label class="action-field">优先级<select name="priority"><option>P1</option><option>P0</option><option>P2</option></select></label></div><label class="action-field">要执行什么 *<textarea name="action" required maxlength="6000" rows="7">${esc(suggested)}</textarea></label>${suggested.length>6000?'<p class="chat-action-error">建议内容超过 6000 字，请精简为本次要执行的动作。</p>':''}<div class="chat-action-grid"><label class="action-field">负责人<input name="owner" maxlength="100" placeholder="可稍后分配"></label><label class="action-field">截止日期<input name="due_date" type="date"></label></div><label class="action-field">怎样算完成<textarea name="acceptance" maxlength="2000" rows="2" placeholder="例如：形成退款原因表并完成订单抽查，记录样本数与发现"></textarea></label><details><summary>来源问题与说明</summary><p>${esc(turn.question)}</p><p>原回复与查询依据由服务端保留，编辑行动不会改写聊天内容。没有业务证据时仅作为待验证建议。</p></details><label class="action-confirm"><input type="checkbox" name="confirmed" required> 我确认将上述建议保存为待复核候选。</label><p id="chatActionError" role="alert" class="chat-action-error"></p><div class="chat-action-footer"><button type="button" data-close class="button">取消</button><button class="button primary" type="submit">确认加入行动中心</button></div></form>`;
  document.body.append(dialog);dialog.showModal();dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>dialog.close());
  const form=dialog.querySelector('form');let sending=false;
  dialog.addEventListener('cancel',e=>{if(sending)e.preventDefault();});
  form.onsubmit=async event=>{event.preventDefault();if(sending)return;const values=Object.fromEntries(new FormData(form).entries());if(values.action.length>6000){dialog.querySelector('#chatActionError').textContent='请将行动精简至 6000 字以内。';return;}
   sending=true;dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
   try{const r=await fetch('/api/actions/from-analysis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...values,analysis_id:turn.analysis_id,conversation_id:chat.id,confirmed:values.confirmed==='on'})});const d=await r.json();if(r.status===404)throw Error('当前服务尚未加载新接口，或来源记录不可用；请先重启工作台服务后再试。');if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请检查行动字段');toast(d.note);dialog.close();await onSaved(d.item);root.dispatchEvent(new CustomEvent('workspace:actions-changed'));}
   catch(e){if(dialog.isConnected)dialog.querySelector('#chatActionError').textContent=e.message;}
   finally{sending=false;dialog.querySelectorAll('button').forEach(b=>b.disabled=false);}
  };
 }
 root.ChatActions={open};
})(window);
