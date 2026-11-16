/* SPDX-License-Identifier: EPL-2.0 */
// Production HTTPS page/handler with a synthetic Root. No native mutation acceptance.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const here=dirname(fileURLToPath(import.meta.url));
const workspace=resolve(here,'../../../../..');
const require=createRequire(resolve(workspace,'kura-management-console/frontend/package.json'));
const {chromium,expect}=require('@playwright/test');
const child=spawn(process.argv[2]||'python3',['-B',resolve(here,'key_handoff_browser_server.py')],{stdio:['pipe','pipe','pipe']});
let stderr='';child.stderr.on('data',data=>{stderr+=data;});
const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
async function bounded(promise){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Fixture observation timed out')),10000);})]);}finally{clearTimeout(timer);}}
async function read(){const value=await bounded(lines.next());if(value.done)throw Error('Fixture stopped: '+stderr.slice(-1500));return JSON.parse(value.value);}
async function control(command,extra={}){child.stdin.write(JSON.stringify({command,...extra})+'\n');return read();}
let fixture=await read();
const browser=await chromium.launch({headless:true});
const results=[];
async function setup(options={},lease=false){
 fixture=await control(lease?'lease-reset':'reset');
 const context=await browser.newContext({ignoreHTTPSErrors:true,...options});
 context.setDefaultTimeout(10000);
 return {context,page:await context.newPage()};
}
async function load(page){await page.goto(fixture.url+'/handoff');await expect(page.getByRole('heading',{level:1,name:'网关密钥轮换交接'})).toBeVisible();}
async function query(page){await page.getByLabel('本次交接授权',{exact:true}).fill(fixture.token);await page.locator('#handoff-query').click();await expect(page.locator('#handoff-id')).toHaveText(fixture.handoffId);await expect(page.locator('#handoff-progress')).toBeHidden();}
const responseFor=command=>response=>response.url().endsWith('/api/handoff')&&response.request().method()==='POST'&&response.request().postDataJSON().command===command;
async function confirm(page,command,forwarded=true){
 await page.locator('#handoff-'+command).click();await expect(page.locator('#handoff-confirm')).toBeVisible();
 if(forwarded){const response=page.waitForResponse(responseFor(command));await page.locator('#handoff-confirm-accept').click();await (await response).finished();}
 else{await page.locator('#handoff-confirm-accept').click();await expect(page.locator('#handoff-notice')).toContainText('浏览器无法可靠保存');}
 await expect(page.locator('#handoff-confirm')).toBeHidden();await expect(page.locator('#handoff-progress')).toBeHidden();
}
async function dismiss(page){
 await page.locator('#handoff-confirm').evaluate(dialog=>{window.handoffFixtureClose=new Promise(resolve=>dialog.addEventListener('close',()=>resolve(),{once:true}));});
 await page.keyboard.press('Escape');await bounded(page.evaluate(()=>window.handoffFixtureClose));await expect(page.locator('#handoff-confirm')).toBeHidden();await expect(page.locator('#handoff-progress')).toBeHidden();
}
async function stats(){const value=await control('stats');assert.equal(value.bearerOnDisk,false);return value;}
async function noBrowserBearer(page){const values=await page.evaluate(()=>Object.keys(localStorage).map(key=>localStorage.getItem(key)).join('\n'));assert.equal(values.includes(fixture.token),false);}

try{
 {
  const {context,page}=await setup();await load(page);
  await expect(page.locator('#cold-flow')).toBeHidden();await expect(page.locator('#restore')).toBeHidden();
  assert.equal((await stats()).rootCalls,0);
  await page.locator('#language').selectOption('en');await expect(page.getByRole('heading',{level:1,name:'Gateway key rotation handoff'})).toBeVisible();
  await expect(page.locator('#handoff-token')).toHaveAccessibleName('Original handoff authorization');
  assert.equal(await page.locator('#handoff-query').evaluate(node=>node.tagName),'BUTTON');
  await context.close();results.push('semantic controls, page isolation, bilingual labels, no automatic RPC');
 }
 {
  const {context,page}=await setup();await load(page);await query(page);
  await page.locator('#handoff-publish').click();await expect(page.locator('#handoff-confirm')).toBeVisible();
  await expect(page.getByRole('button',{name:'取消',exact:true})).toBeFocused();
  await dismiss(page);
  await expect(page.locator('#handoff-publish')).toBeFocused();assert.equal((await stats()).writes.publish,0);
  await confirm(page,'publish');await expect(page.locator('#handoff-publication-state')).toContainText('原发布回执已确认');
  await page.locator('#handoff-start').click();await dismiss(page);
  assert.equal((await stats()).writes.start,0); // prior accept must not leak through Esc
  await confirm(page,'start');await expect(page.locator('#handoff-start-state')).toContainText('系统已接收');
  await page.locator('#handoff-complete').click();await expect(page.locator('#handoff-notice')).toContainText('原发布和启动请求回执已确认');
  const value=await stats();assert.deepEqual(value.writes,{publish:1,start:1,continue:0});
  await noBrowserBearer(page);await page.locator('#handoff-forget').click();await expect(page.locator('#handoff-token')).toHaveValue('');
  await context.close();results.push('explicit publication/start/receipt acknowledgement and native safe-focus/Esc returnValue reset');
 }
 {
  const {context,page}=await setup();await control('set',{values:{absent:true,loss:true}});await load(page);await query(page);await confirm(page,'publish');
  await expect(page.locator('#handoff-publication-state')).toContainText('结果尚未核定');
  await page.reload();await expect(page.locator('#handoff-token')).toHaveValue('');await query(page);
  await expect(page.locator('#handoff-publish')).toBeDisabled();await page.locator('#handoff-publish').evaluate(node=>node.click());
  await page.locator('#handoff-query').click();await expect(page.locator('#handoff-progress')).toBeHidden();
  assert.equal((await stats()).writes.publish,1);await noBrowserBearer(page);
  await context.close();results.push('lost response and Root absence remain query-only after reload');
 }
 {
  const {context,page}=await setup();await control('set',{values:{partial:true}});await load(page);await query(page);await confirm(page,'publish');
  await expect(page.locator('#handoff-continue')).toBeEnabled();await control('set',{values:{partial:false}});await confirm(page,'continue');
  await expect(page.locator('#handoff-publication-state')).toContainText('原发布回执已确认');
  assert.deepEqual((await stats()).writes,{publish:1,start:0,continue:1});await noBrowserBearer(page);
  await context.close();results.push('explicit continuation binds original receipt without a second publication/start');
 }
 {
  const {context,page}=await setup();await control('set',{values:{partial:true,loss:true}});await load(page);await query(page);await confirm(page,'publish');await confirm(page,'continue');
  await expect(page.locator('#handoff-continue')).toBeDisabled();await page.reload();await query(page);await expect(page.locator('#handoff-continue')).toBeDisabled();
  assert.equal((await stats()).writes.continue,1);await context.close();results.push('uncertain continuation is never forwarded again');
 }
 {
  const {context,page}=await setup();await page.addInitScript(()=>{Storage.prototype.setItem=function(){throw new DOMException('Fixture quota','QuotaExceededError');};});
  await load(page);await query(page);await confirm(page,'publish',false);await expect(page.locator('#handoff-publish')).toBeDisabled();
  assert.equal((await stats()).writes.publish,0);await expect(page.locator('#handoff-query')).toBeEnabled();
  await context.close();results.push('storage failure prevents the first HTTPS writer');
 }
 {
  const {context,page}=await setup();const other=await context.newPage();await load(page);await load(other);await query(page);await query(other);
  await page.locator('#handoff-publish').click();await other.locator('#handoff-publish').click();
  const publication=Promise.race([page.waitForResponse(responseFor('publish')),other.waitForResponse(responseFor('publish'))]);
  await Promise.all([page.locator('#handoff-confirm-accept').click(),other.locator('#handoff-confirm-accept').click()]);await (await publication).finished();
  await expect(page.locator('#handoff-progress')).toBeHidden();await expect(other.locator('#handoff-progress')).toBeHidden();
  assert.equal((await stats()).writes.publish,1);await noBrowserBearer(page);await context.close();results.push('two tabs forward at most once');
 }
 {
  const {context,page}=await setup();await control('set',{values:{absent:true,loss:true}});await load(page);await query(page);await confirm(page,'publish');
  const other=await context.newPage();await load(other);await other.evaluate(()=>localStorage.clear());
  await page.locator('#handoff-query').click();await expect(page.locator('#handoff-progress')).toBeHidden();
  await expect(page.locator('#handoff-publish')).toBeDisabled();assert.equal((await stats()).writes.publish,1);
  await context.close();results.push('another tab clearing storage does not release an uncertain operation');
 }
 {
  const {context,page}=await setup({viewport:{width:390,height:844}});await load(page);await query(page);
  await page.locator('#handoff-publish').click();await expect(page.locator('#handoff-confirm')).toBeVisible();
  const size=await page.locator('#handoff-confirm').boundingBox();assert.ok(size.width<=390&&size.height<=844);
  await page.keyboard.press('Escape');await control('set',{values:{expired:true}});await page.locator('#handoff-query').click();
  await expect(page.locator('#handoff-notice')).toContainText('授权窗口已关闭');await expect(page.locator('#handoff-publish')).toBeDisabled();
  assert.equal((await stats()).writes.publish,0);await context.close();results.push('mobile native confirmation and expired authority stay read-only');
 }
 {
  const {context,page}=await setup({},true);await load(page);await query(page);
  await expect(page.locator('#handoff-start')).toBeDisabled();await expect(page.locator('#handoff-start-renew')).toBeEnabled();
  await page.locator('#handoff-start-renew').click();await expect(page.locator('#handoff-confirm button[value=cancel]')).toBeFocused();
  await dismiss(page);assert.equal((await stats()).leaseWrites,0);
  await confirm(page,'start-renew');await expect(page.locator('#handoff-start')).toBeFocused();
  await expect(page.locator('#handoff-notice')).toContainText('原首次启动授权已续期');
  assert.equal((await stats()).writes.start,0);assert.equal((await stats()).writes.publish,0);
  await page.reload();await query(page);await noBrowserBearer(page);
  await confirm(page,'start');assert.equal((await stats()).writes.start,1);assert.equal((await stats()).leaseWrites,1);
  await context.close();results.push('explicit 15-minute original-start renewal, safe native confirmation, retained browser history and separate fixed-ID startup');
 }
 {
  const {context,page}=await setup({},true);await control('set',{values:{lose_lease_reply:true}});await load(page);await query(page);
  await confirm(page,'start-renew');await page.reload();await query(page);
  await expect(page.locator('#handoff-start')).toBeEnabled();assert.equal((await stats()).leaseWrites,1);
  await context.close();results.push('lost successful renewal reply resolves from the original receipt across reload without redispatch');
 }
 {
  const {context,page}=await setup({},true);await control('set',{values:{drop_lease_native:true}});await load(page);await query(page);
  await confirm(page,'start-renew');await expect(page.locator('#handoff-notice')).toContainText('结果尚未核定');
  await page.reload();await query(page);await expect(page.locator('#handoff-start-renew')).toBeDisabled();await expect(page.locator('#handoff-start')).toBeDisabled();
  await expect(page.locator('#handoff-renewals button')).toHaveCount(0);assert.equal((await stats()).leaseWrites,1);
  await context.close();results.push('renewal intake without original remains query-only across reload and cannot be closed, replaced or used to start');
 }
 {
  const {context,page}=await setup({},true);await control('set',{values:{lose:true}});await load(page);await query(page);
  await confirm(page,'start-renew');await page.locator('#handoff-query').click();await expect(page.locator('#handoff-progress')).toBeHidden();
  const original=await page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.includes('.renewal.')).map(k=>[k,localStorage.getItem(k)])));
  assert.equal(Object.keys(original).length,1);await page.locator('#handoff-renewals button').click();
  await expect(page.locator('#handoff-confirm button[value=cancel]')).toBeFocused();await expect(page.locator('#handoff-confirm-renewal-id')).toHaveText(JSON.parse(Object.values(original)[0]).operationId);
  const closed=page.waitForResponse(responseFor('renewal-close'));await page.locator('#handoff-confirm-accept').click();await (await closed).finished();
  await expect(page.locator('#handoff-progress')).toBeHidden();await expect(page.locator('#handoff-start-renew')).toBeFocused();
  assert.equal((await stats()).leaseCloses,1);assert.equal((await stats()).leaseWrites,0);
  for(const [key,value]of Object.entries(original))assert.equal(await page.evaluate(k=>localStorage.getItem(k),key),value);
  await control('set',{values:{lose:false}});await confirm(page,'start-renew');assert.equal((await stats()).leaseWrites,1);
  assert.equal(await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.includes('.renewal.')).length),2);
  await context.close();results.push('unconsumed renewal requires explicit original non-admission closure; old bytes remain before a manual fresh renewal');
 }
 {
  const {context,page}=await setup({},true);await page.addInitScript(()=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.includes('.renewal.'))throw Error('modeled storage failure');return original.call(this,k,v);};});
  await load(page);await query(page);await confirm(page,'start-renew',false);assert.equal((await stats()).leaseWrites,0);
  await expect(page.locator('#handoff-start')).toBeDisabled();await context.close();results.push('browser storage failure blocks renewal before the first HTTPS metadata writer');
 }
 {
  const {context,page}=await setup({},true),other=await context.newPage();await load(page);await query(page);await load(other);await query(other);
  await page.locator('#handoff-start-renew').click();await other.locator('#handoff-start-renew').click();
  const first=page.waitForResponse(responseFor('start-renew'));await page.locator('#handoff-confirm-accept').click();await (await first).finished();await expect(page.locator('#handoff-progress')).toBeHidden();
  await other.locator('#handoff-confirm-accept').click();await expect(other.locator('#handoff-confirm')).toBeHidden();await expect(other.locator('#handoff-progress')).toBeHidden();
  assert.equal((await stats()).leaseWrites,1);await context.close();results.push('two browser tabs recheck the original publication under one lock and mint at most one current renewal');
 }
 {
  const {context,page}=await setup({},true);await load(page);await query(page);await confirm(page,'start-renew');
  const before=await page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.includes('.renewal.')).map(k=>[k,localStorage.getItem(k)])));
  await control('set',{values:{lease_window:false}});await page.locator('#handoff-query').click();await expect(page.locator('#handoff-progress')).toBeHidden();
  await confirm(page,'start-renew');assert.equal((await stats()).leaseWrites,2);assert.equal((await stats()).writes.start,0);
  for(const [key,value]of Object.entries(before))assert.equal(await page.evaluate(k=>localStorage.getItem(k),key),value);
  await context.close();results.push('a later expired lease permits an explicitly new renewal while retaining every prior receipt and original startup ID');
 }
 {
  const {context,page}=await setup({viewport:{width:390,height:844}},true);await load(page);await query(page);await page.locator('#language').selectOption('en');
  await expect(page.getByRole('button',{name:'Renew original first-start authorization',exact:true})).toBeEnabled();
  await page.locator('#handoff-start-renew').click();await expect(page.locator('#handoff-confirm button[value=cancel]')).toBeFocused();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await dismiss(page);assert.equal((await stats()).leaseWrites,0);
  await context.close();results.push('English mobile renewal labels, non-overflow layout, safe cancel focus and Escape never mint an authorization');
 }
 console.log(JSON.stringify({tests:results.length,cases:results,root:'synthetic replies',realHttps:true,productionPageAndHandler:true,nativeGenerationAcceptance:false}));
}finally{
 await browser.close();await control('stop');child.stdin.end();
}
