/* The original views receive the same server-selected batch as the parent workbench. */
(function(){
 'use strict';
 const config=window.HUB_MODULE;
 const notify=(type,payload={})=>parent.postMessage({type,version:config.version,...payload},location.origin);
 document.addEventListener('click',ev=>{
   const el=ev.target.closest('input[type=file],button,label');
   if(!el)return;
   if(el.matches('input[type=file]')||/上传|导入|开始处理|保存数据|清空数据/.test(el.textContent||'')){
     ev.preventDefault();ev.stopImmediatePropagation();notify('hub:import');
   }
 },true);
 window.addEventListener('load',()=>{
   for(const node of [...document.body.childNodes])if(node.nodeType===3&&/^\s*\\n\s*$/.test(node.textContent))node.remove();
   const note=document.createElement('div');note.id='hubModuleNote';
   const key={creator:'creator',profit:'bill',marketing:'creator',gmv:'gmv',daily:'daily',after:'after'}[config.kind];
   const meta=config.meta[key]||{};
   note.textContent=`统一数据版本 ${config.version.slice(0,8)} · ${meta.period||'周期未标注'} · ${config.kind==='daily'?'国家与店铺筛选联动本页和导出':'原计算口径与导出保留。筛选在本模块内生效。'}`;
   if(meta.completeness)note.textContent+=' '+meta.completeness;
   const upload=document.createElement('button');upload.textContent='更新数据 →';upload.onclick=()=>notify('hub:import');note.append(upload);document.body.prepend(note);
   const ask=document.createElement('button');ask.textContent='带当前范围询问 AI';ask.style.marginRight='20px';ask.onclick=()=>{
     let question='';
     if(config.kind==='daily')question=(typeof selectedShop!=='undefined'&&selectedShop!=='__ALL__'?selectedShop+' ':'')+'日销哪些商品需要核查？';
     else if(config.kind==='gmv')question=(typeof filters!=='undefined'&&filters.shop!=='全部店铺'?filters.shop+' ':'')+(typeof filters!=='undefined'&&filters.product!=='全部商品'?filters.product+' ':'')+'广告经营数据有什么需要核查的？';
     else if(config.kind==='profit')question=(document.getElementById('pfStore')?.value||'')+' 账单利润有哪些需要核查的？';
     else if(config.kind==='after')question=(typeof gStore!=='undefined'&&gStore!=='all'?gStore+' ':'')+'售后退包数据有哪些需要核查的？';
     else question='达人数据有哪些需要核查的？';
     notify('hub:ask',{question});
   };note.append(ask);
   try{
     if(config.after&&typeof rebuildFromWorkbook==='function'){
       const wb=XLSX.utils.book_new();XLSX.utils.book_append_sheet(wb,XLSX.utils.aoa_to_sheet([config.after.header,...config.after.rows]),'售后');rebuildFromWorkbook(wb);
       const monthSelect=document.getElementById('globalMonth');if(monthSelect){monthSelect.replaceChildren(new Option('全部月份','all'),...config.months.map(m=>new Option(m,m)));}
     }
     if(typeof showView==='function')showView({profit:'profit',after:'after',creator:'marketing',marketing:'marketing'}[config.kind]||'overview');
     if(config.kind==='daily'){
       const legacySave=document.getElementById('saveDashboardData');if(legacySave)legacySave.hidden=true;
       if(typeof window.openDetail==='function'){
         const originalOpen=window.openDetail;
         window.openDetail=function(name,store,...rest){
           const result=originalOpen.call(this,name,store,...rest);
           note.querySelector('[data-hub-product]')?.remove();
           const group=document.createElement('span');group.dataset.hubProduct='true';
           const shops=[...new Set(RAW.daily.filter(r=>r['SKU中文名']===name).map(r=>r['店铺']).filter(Boolean))];
           const select=document.createElement('select');select.setAttribute('aria-label','商品档案店铺');
           for(const shop of shops)select.add(new Option(shop,shop));if(shops.includes(store))select.value=store;
           const open=document.createElement('button');open.textContent='打开该商品全景档案';open.disabled=!shops.length;
           open.onclick=()=>notify('hub:product',{shop:select.value,product:name});
           group.append(select,open);note.append(group);return result;
         };
       }
     }
     notify('hub:ready');
   }catch(e){note.textContent+=' · 初始化失败：'+e.message;notify('hub:error',{message:e.message});}
 });
})();
