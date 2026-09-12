(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const post=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const api=async(path,options)=>{const r=await fetch('/api/hub/content'+path,options);const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));return d;};
 function markdown(raw){return raw.split('\n').map(line=>{const s=esc(line);if(/^#{1,6} /.test(line)){const n=Math.min(4,line.match(/^#+/)[0].length+1);return `<h${n}>${s.replace(/^#+ /,'')}</h${n}>`;}if(line.startsWith('- '))return '<div class="ce-bullet">• '+s.slice(2)+'</div>';return '<div class="ce-copy-line">'+(s||'<br>')+'</div>';}).join('');}
 function create(node,{toast,onSaved}){
  node.innerHTML=`<section class="panel cs-section"><div class="eyebrow">FINISHED EXAMPLE / 原样归档</div><h2>导入已有成品实例</h2><p>保存现成文案，再按位置批量上传图片。此入口不调用 AI，不要求编造生成提示词。</p><form id="ceCreate" class="cs-form"><label>实例名称<input name="name" required maxlength="180"></label><label>详情图数量<select name="detail_count">${[6,7,8,9,10].map(n=>`<option ${n===8?'selected':''}>${n}</option>`).join('')}</select></label><label class="cs-wide">标题原文<textarea name="title" required maxlength="500" rows="3"></textarea></label><label class="cs-wide">详情原文（保留 Markdown）<textarea name="description" required maxlength="20000" rows="12"></textarea></label><button class="button primary">创建实例并上传成品图</button></form></section>`;
  node.querySelector('form').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{const f=new FormData(e.target);const p=await api('/examples',post({brief:{name:f.get('name'),detail_count:Number(f.get('detail_count'))},title:f.get('title'),description:f.get('description')}));await onSaved(p.id);}catch(error){toast(error.message);if(e.submitter.isConnected)e.submitter.disabled=false;}};
 }
 function show(node,p,{toast,refresh,valid}){
  const base='/projects/'+p.id,assetUrl=a=>'/api/hub/content'+base+'/assets/'+a.id;
  const latest=s=>p.assets.filter(a=>a.role==='result'&&a.slot===s.id).at(-1);
  node.innerHTML=`<section class="cs-example-cover"><span class="cs-pill">用户提供的成品 · 不再生成图片</span><h2>${esc(p.brief.name)}</h2><p>主图 1 张 · 副图 8 张 · 详情图 ${p.brief.detail_count} 张</p><div class="cs-row"><b>已归档 ${p.example_count}/${p.slots.length} 张</b><a class="button primary" href="/api/hub/content${base}/export?mode=example">下载整套实例 · 原文原图</a></div><p class="cs-muted">${esc(p.example.provenance)}。图片原始字节保存，刷新或重启不丢失。</p></section>
   ${p.example.issues.length?`<details class="panel cs-section ce-issues"><summary>规格与素材核对提示（${p.example.issues.length}）· 不改动原素材</summary>${p.example.issues.map(s=>`<p>${esc(s)}</p>`).join('')}</details>`:''}
   <section class="panel cs-section"><div class="cs-row"><h2>产品标题</h2><button class="button small" id="ceCopyTitle">复制标题</button></div><p class="ce-title">${esc(p.example.title)}</p><small class="cs-muted">${p.example.title.length} 字符 · 用户原文</small></section>
   <section class="panel cs-section"><div class="cs-row"><h2>商品图册</h2><div class="ce-tabs"><button class="button small primary" data-ce-filter="all">全部</button><button class="button small" data-ce-filter="square">主图与副图</button><button class="button small" data-ce-filter="detail">详情图</button></div></div><p class="cs-muted">按用户指定顺序排列。点击查看原尺寸；不拉伸、不裁切、不改变图片中的文字。</p><div class="ce-gallery">${p.slots.map((s,i)=>{const a=latest(s);return `<article class="ce-tile" data-ce-kind="${s.id.split('-')[0]}"><div class="cs-row"><b>${String(i+1).padStart(2,'0')} · ${esc(s.label)}</b><small>${s.ratio}</small></div>${a?`<a href="${assetUrl(a)}" target="_blank" rel="noopener"><img src="${assetUrl(a)}" alt="第${i+1}张：${esc(s.label)}" loading="lazy"></a><small>${a.width}×${a.height} · 原图已保存</small>`:'<div class="cs-slot-empty">待归档<small>请选择对应原图文件</small></div>'}</article>`;}).join('')}</div></section>
   <section class="panel cs-section"><div class="cs-row"><h2>详情介绍</h2><button class="button small" id="ceCopyDescription">复制详情原文</button></div><div class="ce-description">${markdown(p.example.description)}</div></section>
   <details class="panel cs-section"><summary>补充图片 / 上传新版本</summary><p>选择多张图片后核对每张位置，再确认归档。已有图片不删除，新上传保留旧版。</p><label>选择成品文件<input id="ceFiles" type="file" accept="image/png,image/jpeg,image/webp" multiple></label><div id="ceFileMap"></div><p id="ceUploadStatus" role="status"></p></details>
   <details class="panel cs-section"><summary>来源与审计记录</summary>${p.events.slice().reverse().map(e=>`<p>r${e.revision} · ${esc(e.at)} · ${esc(e.event)}</p>`).join('')}</details>`;
  for(const [id,text] of [['ceCopyTitle',p.example.title],['ceCopyDescription',p.example.description]])node.querySelector('#'+id).onclick=async()=>{try{await navigator.clipboard.writeText(text);toast('已复制原文');}catch{toast('浏览器禁止剪贴板，请下载实例包或手动选择文本。');}};
  node.querySelectorAll('[data-ce-filter]').forEach(b=>b.onclick=()=>{node.querySelectorAll('[data-ce-filter]').forEach(x=>x.classList.toggle('primary',x===b));node.querySelectorAll('[data-ce-kind]').forEach(x=>{x.hidden=b.dataset.ceFilter!=='all'&&x.dataset.ceKind!==b.dataset.ceFilter;});});
  node.querySelector('#ceFiles').onchange=e=>{
   const files=Array.from(e.target.files).sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
   if(files.length>p.slots.length){toast('一次最多选择 '+p.slots.length+' 张图片');return;}
   const map=node.querySelector('#ceFileMap');map.innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>原文件名</th><th>归档位置（请确认）</th></tr></thead><tbody>${files.map((f,i)=>`<tr><td>${esc(f.name)}</td><td><select data-ce-slot="${i}">${p.slots.map((s,j)=>`<option value="${s.id}" ${j===i?'selected':''}>${j+1} · ${esc(s.label)}</option>`).join('')}</select></td></tr>`).join('')}</tbody></table></div>${files.length?'<button class="button primary" id="ceUpload">确认图序并原样归档</button>':''}`;
   if(!files.length)return;
   map.querySelector('#ceUpload').onclick=async e=>{
    const selection=Array.from(map.querySelectorAll('[data-ce-slot]')).map(x=>x.value);
    if(new Set(selection).size!==selection.length){toast('同一批次的图片位置不能重复。');return;}
    e.target.disabled=true;let current=p;let saved=0;
    try{for(let i=0;i<files.length;i++){if(!valid())break;const body=new FormData();body.set('expected_revision',current.revision);body.set('role','result');body.set('slot',selection[i]);body.set('file',files[i]);current=await api(base+'/assets',{method:'POST',body});saved++;if(valid())node.querySelector('#ceUploadStatus').textContent=`已归档 ${saved}/${files.length} 张…`;}if(valid()){toast('已保存 '+saved+' 张原图');await refresh();}}
    catch(error){toast(`已保存 ${saved} 张，后续未完成：${error.message}`);if(valid())await refresh();}
   };
  };
 }
 root.ContentExamples={create,show};
})(window);
