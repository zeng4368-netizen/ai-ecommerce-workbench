// Local UI regression test. Set NODE_PATH to a Playwright installation; uses Edge.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const context=await browser.newContext({viewport:{width:1200,height:900}}), page=await context.newPage(), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765/api/hub/modules/daily');
  await page.locator('#dailyCountry').waitFor();
  await page.locator('[data-template="shop"]').click();
  const original=await page.evaluate(()=>JSON.stringify(RAW));
  assert.equal(await page.locator('#shopCount').innerText(),'22');
  assert(await page.evaluate(()=>RAW.erp.length > 0));
  assert(await page.evaluate(()=>analysisRaw().erp.length === RAW.erp.length));
  assert.notEqual(await page.locator('#totalSku').innerText(),'—');
  assert.notEqual(await page.locator('#totalSku').innerText(),'0');
  for(const width of [1200,860,600]) {
   await page.setViewportSize({width,height:900});
   assert(await page.locator('.shop-base-panel').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'shop card overflow at '+width);
  }
  await page.setViewportSize({width:1200,height:900});
  await page.selectOption('#dailyCountry','TH');
  assert.equal(await page.locator('#shopCount').innerText(),'6');
  assert.notEqual(await page.locator('#shopRiskStockout').innerText(),'—');
  assert(await page.evaluate(()=>analysisRaw().erp.length > 0));
  assert(await page.evaluate(()=>analysisRaw().erp.every(r=>/泰国|Thailand|^TH$/i.test(String(r['国家']||r['仓库']||'')))));
  await page.selectOption('#dailyShop','COMO TH');
  assert.equal(await page.locator('#shopCount').innerText(),'1');
  assert.deepEqual(await page.evaluate(()=>[...buildShopExportRows().shops.keys()]),['COMO TH']);
  assert.equal(await page.locator('#compactShopSelect').inputValue(),'COMO TH');
  await page.selectOption('#compactShopSelect','__ALL__');
  assert.equal(await page.locator('#shopCount').innerText(),'6');
  await page.selectOption('#dailyCountry','MY');
  assert(await page.evaluate(()=>analysisRaw().erp.length > 0));
  assert(await page.evaluate(()=>analysisRaw().erp.every(r=>/马来|Malaysia|^MY$/i.test(String(r['国家']||r['仓库']||'')))));
  await page.locator('#countryMapping summary').click();
  await page.locator('#countryMappingRows select[data-shop="EXPOSE.TK"]').selectOption('MY');
  assert(await page.evaluate(()=>analysisRaw().daily.some(r=>r['店铺']==='EXPOSE.TK')));
  await page.reload();await page.locator('#dailyCountry').waitFor();
  await page.selectOption('#dailyCountry','MY');
  assert(await page.evaluate(()=>analysisRaw().daily.some(r=>r['店铺']==='EXPOSE.TK')),'mapping must survive reload');
  assert.equal(await page.evaluate(()=>JSON.stringify(RAW)),original,'filters must not mutate source data');
  const math=await page.evaluate(()=>{
   const cols=Array.from({length:14},(_,i)=>`2026-09-${String(i+1).padStart(2,'0')}`);
   return [previousWeekAverage(cols,Array(7).fill(10).concat(Array(7).fill(20))),previousWeekAverage(cols.slice(1),Array(13).fill(1)),previousWeekAverage(cols.slice(0,13).concat('2026-09-15'),Array(14).fill(1))];
  });assert.deepEqual(math,[10,null,null]);
  await page.locator('[data-template="shop"]').click();
  await page.screenshot({path:'data/screenshots/daily-scope-verified.png',fullPage:false});
  assert.deepEqual(errors,[]);
  console.log('PASS: 22 shops; 3 responsive widths; MY/TH isolation; unknown inventory; shop export; persistent mapping; immutable RAW; comparison windows; zero JS errors.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
