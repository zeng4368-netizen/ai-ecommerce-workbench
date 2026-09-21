/* Country scope is a view over immutable source rows. Shop mappings stay local. */
(() => {
  const names = {ALL:'全部国家', MY:'马来西亚', TH:'泰国', ID:'印度尼西亚', UNKNOWN:'待确认'};
  let mappings = {};
  try { mappings = JSON.parse(localStorage.getItem('daily.shopCountries.v1') || '{}'); } catch (_) {}
  const state = window.dailyScope = {country:'ALL', shop:'__ALL__', mappings};
  let original = {daily:[],erp:[],warn:[]};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const shopName = r => String(r['店铺'] || r['店铺名称'] || '').trim();
  function country(value) {
    const v = String(value || '').trim();
    if (/马来|Malaysia|^MY$/i.test(v)) return 'MY';
    if (/泰国|Thailand|^TH$/i.test(v)) return 'TH';
    if (/印尼|印度尼西亚|Indonesia|^ID$/i.test(v)) return 'ID';
    return 'UNKNOWN';
  }
  function shopCountry(r) {
    const name = shopName(r);
    if (Object.hasOwn(state.mappings,name)) return state.mappings[name];
    const explicit = country(r['国家'] || r['国家/地区'] || r['市场']);
    if (explicit !== 'UNKNOWN') return explicit;
    // Only explicit country tokens; ambiguous names remain unassigned.
    if (/(?:^|[ ._-])TH(?:$|[ ._-])|Thailand|泰国/i.test(name)) return 'TH';
    if (/(?:^|[ ._-])MY(?:$|[ ._-])|Malaysia|马来/i.test(name)) return 'MY';
    return 'UNKNOWN';
  }
  function scopeCountry(raw) {
    if (state.country !== 'ALL') return state.country;
    const rows = raw.daily.filter(r => state.shop === '__ALL__' || shopName(r) === state.shop);
    const countries = new Set(rows.map(shopCountry));
    return countries.size === 1 ? [...countries][0] : 'ALL';
  }
  window.dailyScopedRaw = raw => {
    const daily = (raw.daily || []).filter(r => (state.country === 'ALL' || shopCountry(r) === state.country) && (state.shop === '__ALL__' || shopName(r) === state.shop));
    const c = scopeCountry(raw);
    // The all-country view represents the whole business and therefore uses all
    // warehouses. A country/shop view is narrowed to its matching warehouse.
    if (c === 'ALL') return {daily, erp: raw.erp || [], warn: raw.warn || []};
    // An unassigned single shop must not borrow inventory from another country.
    const matched = c !== 'ALL' && c !== 'UNKNOWN';
    const productNames = new Set(daily.map(r=>r['SKU中文名'] || r['中文名称'] || r['商品名称']));
    const relevant = r => state.shop === '__ALL__' || productNames.has(r['中文名称'] || r['商品名称'] || r['SKU中文名']);
    return {daily,
      erp: matched ? (raw.erp || []).filter(r => country(r['国家'] || r['仓库']) === c && relevant(r)) : [],
      warn: matched ? (raw.warn || []).filter(r => country(r['国家']) === c && relevant(r)) : []};
  };
  window.dailyCurrency = () => window.HUB_MODULE?.meta?.warn?.currency || '原表金额';
  const options = (all=true) => Object.entries(names).filter(([k]) => all || k !== 'ALL').map(([k,v]) => `<option value="${k}">${v}</option>`).join('');
  window.refreshDailyScope = () => { selectedShop = '__ALL__'; selectedOverdueScope = '__ALL__'; ['shopSearch','shopTrendFilter','shopRiskFilter','searchSku','trendFilter','turnoverFilter'].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';}); rerenderAll(); switchTemplate(currentTemplate); };
  window.renderDailyScope = raw => {
    original = raw;
    let panel = document.getElementById('dailyScopePanel');
    if (!panel) {
      panel = document.createElement('section'); panel.id='dailyScopePanel'; panel.className='daily-scope-panel';
      document.querySelector('.fixed-top').after(panel);
      panel.innerHTML = `<div class="daily-scope-controls"><label>国家<select id="dailyCountry">${options()}</select></label><label>店铺<select id="dailyShop"></select></label><details id="countryMapping"><summary>店铺国家归属</summary><p>含 MY / TH 等国家标记的名称自动识别，其余请确认；修改保存在当前浏览器。</p><div id="countryMappingRows"></div><span id="countryMappingStatus" role="status"></span></details></div><p id="dailyScopeNote"></p>`;
      document.getElementById('dailyCountry').onchange=e=>{state.country=e.target.value;state.shop='__ALL__';window.refreshDailyScope();};
      document.getElementById('dailyShop').onchange=e=>{state.shop=e.target.value;window.refreshDailyScope();};
    }
    const shops = [...new Map(raw.daily.filter(r=>shopName(r)).map(r=>[shopName(r),r])).entries()].sort((a,b)=>a[0].localeCompare(b[0]));
    const available = shops.filter(([,r])=>state.country==='ALL'||shopCountry(r)===state.country);
    if (!available.some(([s])=>s===state.shop)) state.shop='__ALL__';
    document.getElementById('dailyCountry').value=state.country;
    const select=document.getElementById('dailyShop');
    select.innerHTML=`<option value="__ALL__">全部店铺（${available.length}）</option>`+available.map(([s])=>`<option value="${escape(s)}">${escape(s)}</option>`).join('');select.value=state.shop;
    const mapping=document.getElementById('countryMappingRows');
    mapping.innerHTML=shops.map(([s,r])=>`<label><span>${escape(s)}</span><select data-shop="${escape(s)}" aria-label="${escape(s)} 国家">${options(false)}</select></label>`).join('');
    mapping.querySelectorAll('select').forEach(el=>{
      el.value=shopCountry(shops.find(([s])=>s===el.dataset.shop)[1]);
      el.onchange=()=>{state.mappings[el.dataset.shop]=el.value;try{localStorage.setItem('daily.shopCountries.v1',JSON.stringify(state.mappings));}catch(_){document.getElementById('countryMappingStatus').textContent='未能保存，仅本次有效';}window.refreshDailyScope();};
    });
    const data=window.dailyScopedRaw(raw), c=scopeCountry(raw);
    document.getElementById('dailyScopeNote').textContent=`${names[state.country]} · ${state.shop==='__ALL__'?'全部店铺':state.shop} · ${data.daily.length} 行日销` +
      (c==='UNKNOWN'?' ｜ 当前店铺国家待确认，确认后显示对应库存和超期。':` ｜ ${data.erp.length} 行库存 / ${data.warn.length} 行超期；库存为国家共享仓，不是店铺独占库存。`);
  };
  window.renderDailyVisuals = data => {
    let panel=document.getElementById('dailyVisuals');
    if (!panel) { panel=document.createElement('section');panel.id='dailyVisuals';panel.className='daily-visuals';document.querySelector('#shopPage .shop-kpi-layout').after(panel); }
    const dates=[...new Set(data.daily.flatMap(r=>Object.keys(r).filter(k=>/^\d{4}-\d{2}-\d{2}$/.test(k))))].sort();
    const totals=dates.map(d=>data.daily.reduce((s,r)=>s+(Number(r[d])||0),0));
    const total=totals.reduce((a,b)=>a+b,0), max=Math.max(1,...totals), recent=totals.slice(-7).reduce((a,b)=>a+b,0);
    const contiguous = dates.length>=14 && (new Date(dates.at(-1))-new Date(dates.at(-14)))/86400000===13;
    const prev=contiguous?totals.slice(-14,-7).reduce((a,b)=>a+b,0):null;
    const comparison=prev===null?'不足连续14天':prev===0?(recent>0?'前期为0，新增销量':'两期均无销量'):`${((recent-prev)/prev*100).toFixed(1)}%`;
    const stores=new Map();data.daily.forEach(r=>{const s=shopName(r);if(s)stores.set(s,(stores.get(s)||0)+dates.slice(-7).reduce((v,d)=>v+(Number(r[d])||0),0));});
    const top=[...stores].sort((a,b)=>b[1]-a[1]).slice(0,8), topMax=Math.max(1,...top.map(x=>x[1]));
    panel.innerHTML=`<article><h2>销量趋势 <small>件</small></h2><div class="sales-summary"><span>周期销量 <b>${total.toLocaleString()}</b></span><span>近7个数据日 <b>${recent.toLocaleString()}</b></span><span>较前7天 <b>${comparison}</b></span></div><div class="daily-bars">${dates.map((d,i)=>`<div title="${d}：${totals[i]} 件"><span>${totals[i]}</span><i style="height:${totals[i]/max*110}px"></i><small>${d.slice(5)}</small></div>`).join('')||'暂无日销数据'}</div></article><article><h2>店铺销量 Top 8 <small>近7个数据日</small></h2><div class="sales-rank">${top.map(([s,v])=>`<div><span title="${escape(s)}">${escape(s)}</span><meter min="0" max="${topMax}" value="${v}"></meter><b>${v}</b></div>`).join('')||'暂无店铺'}</div></article>`;
    const currency=window.dailyCurrency();
    document.querySelectorAll('#shopRiskOverdueUnit').forEach(el=>el.textContent=currency);
    if (!data.erp.length) ['shopRiskStockout','shopRiskOversell','shopRiskLt25','shopRisk50to90','shopRiskGt90'].forEach(id=>{document.getElementById(id).textContent='—';document.getElementById(id+'Note').textContent='当前范围无已匹配库存';});
    if (!data.warn.length) {document.getElementById('shopRiskOverdue').textContent='—';document.getElementById('shopRiskOverdueNote').textContent='当前范围无超期数据';}
    const compact=document.getElementById('compactShopSelect');
    if(compact){compact.innerHTML=document.getElementById('dailyShop').innerHTML;compact.value=state.shop;}
    document.getElementById('shopCountNote').textContent=state.shop==='__ALL__'?names[state.country]:state.shop;
    ['shopChangeScope','shopRiskScope','shopTableScope'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent=state.shop==='__ALL__'?names[state.country]:state.shop;});
  };
})();
