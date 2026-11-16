/* SPDX-License-Identifier: EPL-2.0 */
// New production HTTPS metadata panel; decryption, Root and native results are explicit models.
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {createServer} from 'node:net';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const here=dirname(fileURLToPath(import.meta.url)),workspace=resolve(here,'../../../../..');
const {chromium,expect}=createRequire(resolve(workspace,'kura-management-console/frontend/package.json'))('@playwright/test');
const linux=process.argv.includes('--linux'),container='kura-receiver-browser-'+randomUUID();let port;
if(linux){const socket=createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));port=socket.address().port;await new Promise(resolve=>socket.close(resolve));}
const command=linux?'docker':process.argv[2]||'python3';
const args=linux?['run','--rm','-i','--pull','never','--name',container,'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
 '--tmpfs','/tmp:rw,nosuid,nodev,size=128m','-p',`127.0.0.1:${port}:18443`,
 '--mount',`type=bind,source=${resolve(workspace,'kura/kura/distrib/src')},target=/src,readonly`,
 '--entrypoint','/usr/bin/python3','yofc-empty-systemd:g028-20261114','-B','/src/test/receiver_admission_browser_server.py',
 '--listen-host','0.0.0.0','--listen-port','18443','--public-port',String(port)]:['-B',resolve(here,'receiver_admission_browser_server.py')];
const child=spawn(command,args,{stdio:['pipe','pipe','pipe']});
let stderr='';child.stderr.on('data',value=>{stderr=(stderr+value.toString()).slice(-2000);});
const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
async function read(){let timer;try{const row=await Promise.race([lines.next(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('fixture timeout: '+stderr)),15000);})]);if(row.done)throw Error('fixture stopped: '+stderr);return JSON.parse(row.value);}finally{clearTimeout(timer);}}
async function control(command,extra={}){child.stdin.write(JSON.stringify({command,...extra})+'\n');return read();}
let fixture=await read();const browser=await chromium.launch({headless:true}),cases=[],errors=[];
const restoreStore='yofc.kura.cold-key-recovery.intent.v1',startStore='yofc.kura.cold-key-recovery.start.v1';
async function setup(kind='restore',options={},scenario={}){
 fixture=await control('reset',{kind,...scenario});const context=await browser.newContext({ignoreHTTPSErrors:true,...options});context.setDefaultTimeout(10000);
 if(['restore','start'].includes(kind))await context.addInitScript(({restoreStore,startStore,fixture})=>{
  if(!sessionStorage.getItem('fixture-seeded')){
   localStorage.setItem(restoreStore,JSON.stringify({schema:1,operationId:fixture.kind==='restore'?fixture.operationId:fixture.restoreOperationId,expectedKeySha256:fixture.expectedKeySha256}));
   if(fixture.kind==='start')localStorage.setItem(startStore,JSON.stringify(fixture.startIntent));
   sessionStorage.setItem('fixture-seeded','yes');
  }
 },{restoreStore,startStore,fixture});
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 await page.goto(fixture.url+(['restore','start'].includes(kind)?'/':'/handoff'));await expect(page.locator('#admission-read')).toBeEnabled();
 if(!['restore','start'].includes(kind)){
  await page.locator('#handoff-token').fill(fixture.token);
  await page.locator(`input[name=admission-step][value="${kind==='handoff-start'?'start':kind}"]`).check();
 }
 return {page,context};
}
async function query(page){await page.locator('#admission-read').click();await expect(page.locator('#admission-progress')).toBeHidden();await expect(page.locator('#admission-operation')).toHaveText(fixture.operationId);}
async function material(page,password=fixture.passphrase,backup=fixture.backupJson){
 await page.locator('#admission-backup').setInputFiles({name:'original-backup.json',mimeType:'application/json',buffer:Buffer.from(backup)});
 await page.locator('#admission-password').fill(password);
}
async function dialog(page){await page.locator('#admission-close').click();await expect(page.locator('#admission-confirm')).toBeVisible();await expect(page.locator('#admission-confirm button[value=cancel]')).toBeFocused();}
async function accept(page){
 const completed=page.waitForResponse(response=>response.request().method()==='POST'&&['/api/admission','/api/handoff'].some(path=>response.url().endsWith(path))&&['close','admission-close'].includes(response.request().postDataJSON().command));
 await page.locator('#admission-confirm button[value=close]').click();await (await completed).finished();
 await expect(page.locator('#admission-confirm')).toBeHidden();await expect(page.locator('#admission-progress')).toBeHidden();
}
async function stats(){const v=await control('stats');assert.equal(v.nativeKeyWrites,0);assert.equal(v.credentialsOnDisk,false);assert.equal(v.reservations,1);return v;}
async function privateBrowser(page){const value=await page.evaluate(()=>Object.values(localStorage).join('\n'));for(const secret of [fixture.passphrase,fixture.token,'fixture-ciphertext'])assert.equal(value.includes(secret),false);}
try{
 {
  const {page,context}=await setup();
  const value=await page.evaluate(async f=>{
   const response=await fetch('/api/restore',{method:'POST',headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':document.querySelector('meta[name=kura-recovery-csrf]').content},body:JSON.stringify({operationId:f.operationId,expectedKeySha256:f.expectedKeySha256,backupJson:f.backupJson,passphrase:f.passphrase})});return response.json();
  },fixture);
  assert.equal(value.state,'UNKNOWN');assert.equal(value.resultSource,'UNCONFIRMED');assert.equal((await stats()).closes,0);
  await context.close();cases.push('reservation reply loss without private key intent is UNKNOWN, never generic server preflight rejection');
 }
 for(const kind of ['restore','start']){
  const {page,context}=await setup(kind);await query(page);await expect(page.locator('#admission-close-form')).toBeVisible();
  if(kind==='restore'){
   await page.locator('#admission-close').click();await expect(page.locator('#admission-confirm')).toBeHidden();await expect(page.locator('#admission-backup')).toBeFocused();
   await material(page);await dialog(page);await privateBrowser(page);await page.keyboard.press('Escape');await expect(page.locator('#admission-confirm')).toBeHidden();await expect(page.locator('#admission-password')).toHaveValue('');assert.equal((await stats()).closes,0);
  }
  await material(page);await dialog(page);await accept(page);await expect(page.locator('#admission-notice')).toContainText('已确认未发送');
  assert.equal((await stats()).closedReceipts,1);await privateBrowser(page);
  await page.reload();await query(page);await expect(page.locator('#admission-acknowledge')).toBeVisible();await expect(page.locator('#admission-close-form')).toBeHidden();
  await page.locator('#admission-acknowledge').click();await expect(page.locator('#admission-notice')).toContainText('原记录已确认');
  assert.equal(await page.evaluate(key=>localStorage.getItem(key),kind==='restore'?restoreStore:startStore),null);
  if(kind==='restore')await expect(page.locator('#backup')).toBeEnabled();
  else{assert.notEqual(await page.evaluate(key=>localStorage.getItem(key),restoreStore),null);await expect(page.locator('#start-core')).toBeEnabled();}
  assert.equal((await stats()).closes,1);await context.close();cases.push(kind+' original backup/password authorization, native confirm, durable close across reload, explicit browser acknowledgement and return');
 }
 for(const failure of ['password','backup']){
  const {page,context}=await setup();await query(page);
  const wrong=JSON.stringify({...JSON.parse(fixture.backupJson),encrypted:'foreign-backup'});
  await material(page,failure==='password'?'wrong but long password':fixture.passphrase,failure==='backup'?wrong:fixture.backupJson);
  await dialog(page);await accept(page);await expect(page.locator('#admission-notice')).toContainText('原备份或口令未通过');assert.equal((await stats()).closes,0);assert.equal((await stats()).closedReceipts,0);
  await context.close();cases.push('wrong '+failure+' never closes or saves a not-admitted receipt');
 }
 {
  const {page,context}=await setup();await query(page);await material(page);await control('set',{loseClose:true});await dialog(page);await accept(page);
  await expect(page.locator('#admission-notice')).toContainText('暂时无法核实');assert.equal((await stats()).closes,1);assert.equal((await stats()).closedReceipts,0);
  await query(page);await control('set',{loseClose:false,releaseThrottle:true});await material(page);await dialog(page);await page.keyboard.press('Escape');await expect(page.locator('#admission-confirm')).toBeHidden();await expect(page.locator('#admission-password')).toHaveValue('');assert.equal((await stats()).closes,1);
  await page.locator('#admission-password').fill(fixture.passphrase);await dialog(page);await accept(page);await expect(page.locator('#admission-notice')).toContainText('已确认未发送');
  assert.equal((await stats()).closes,2);assert.equal((await stats()).closedReceipts,1);await context.close();cases.push('lost close reply requires fresh read and explicit authenticated metadata completion; Escape does not reuse an old confirmation');
 }
 for(const kind of ['publish','handoff-start']){
  const {page,context}=await setup(kind);await query(page);await expect(page.locator('#admission-backup-material')).toBeHidden();await dialog(page);await accept(page);
  await expect(page.locator('#admission-notice')).toContainText('此原授权不能再次发送');assert.equal((await stats()).closes,1);assert.equal((await stats()).closedReceipts,1);await expect(page.locator('#admission-acknowledge')).toBeHidden();
  await page.locator('#handoff-query').click();await expect(page.locator(kind==='publish'?'#handoff-publish':'#handoff-start')).toBeDisabled();await privateBrowser(page);
  await context.close();cases.push(kind+' needs original bearer, saves close receipt and keeps all fixed operation IDs blocked');
 }
 {
  const {page,context}=await setup('continue');await query(page);await expect(page.locator('#admission-close-form')).toBeHidden();assert.equal((await stats()).closes,0);await context.close();cases.push('original authenticated continuation is read-only, not an absent native original');
 }
 for(const change of [{phase:'INTAKE'},{privateIntent:true},{foreignNamespace:true}]){
  const {page,context}=await setup();await control('set',change);await query(page);await expect(page.locator('#admission-close-form')).toBeHidden();assert.equal((await stats()).closes,0);await context.close();cases.push(JSON.stringify(change)+' cannot enable closure or resend');
 }
 {
  const {page,context}=await setup();const response=await page.evaluate(async f=>{
   const r=await fetch('/api/admission',{method:'POST',headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':document.querySelector('meta[name=kura-recovery-csrf]').content},body:JSON.stringify({command:'close',kind:'restore',operationId:f.operationId})});return r.ok;
  },fixture);assert.equal(response,false);assert.equal((await stats()).closes,0);await context.close();cases.push('same-origin CSRF and original UUID alone do not authorize a close');
 }
 {
  const {page,context}=await setup('restore',{viewport:{width:390,height:844}});await query(page);await material(page);await dialog(page);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await page.keyboard.press('Escape');await expect(page.locator('#admission-confirm')).toBeHidden();
  await page.locator('#language').selectOption('en');await expect(page.locator('#admission-title')).toHaveText('Check original reservation');await expect(page.locator('#admission-password')).toHaveAccessibleName('Original backup passphrase (required)');
  await page.locator('#admission-password').fill(fixture.passphrase);await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide')));await expect(page.locator('#admission-password')).toHaveValue('');await privateBrowser(page);assert.equal((await stats()).closes,0);
  await context.close();cases.push('Chinese mobile layout, English native labels and secret clearing on cancel/pagehide');
 }
 for(const mismatch of ['identity','shape']){
  const {page,context}=await setup();await query(page);await material(page);await dialog(page);await accept(page);
  await expect(page.locator('#admission-acknowledge')).toBeVisible();
  const before=await page.evaluate(({key,mismatch})=>{const saved=JSON.parse(localStorage.getItem(key));if(mismatch==='identity')saved.operationId=crypto.randomUUID();else saved.unexpected='damaged';const raw=JSON.stringify(saved);localStorage.setItem(key,raw);return raw;},{key:restoreStore,mismatch});
  await page.locator('#admission-acknowledge').click();await expect(page.locator('#admission-notice')).toContainText('浏览器中的原记录不匹配');
  assert.equal(await page.evaluate(key=>localStorage.getItem(key),restoreStore),before);assert.equal((await stats()).closes,1);
  await context.close();cases.push('mismatched browser '+mismatch+' is retained, not acknowledged or silently removed');
 }
 {
  const {page,context}=await setup('start');await control('set',{privateIntent:true});const before=(await stats()).privateStartFiles;
  assert.equal(Object.keys(before).length,1);await query(page);await material(page);await dialog(page);await accept(page);
  assert.deepEqual((await stats()).privateStartFiles,before);await page.reload();await query(page);
  await expect(page.locator('#admission-acknowledge')).toBeVisible();await page.locator('#admission-acknowledge').click();
  await expect(page.locator('#start-core')).toBeEnabled();assert.equal(await page.evaluate(k=>localStorage.getItem(k),startStore),null);
  assert.notEqual(await page.evaluate(k=>localStorage.getItem(k),restoreStore),null);assert.deepEqual((await stats()).privateStartFiles,before);
  await privateBrowser(page);await context.close();cases.push('original private startup intent closes before Root intake, survives reload byte-for-byte, then explicit acknowledgement permits a manual new startup');
 }
 {
  const {page,context}=await setup('start');await control('set',{privateIntent:true,phase:'INTAKE'});const before=(await stats()).privateStartFiles;
  await query(page);await expect(page.locator('#admission-close-form')).toBeHidden();assert.equal((await stats()).closes,0);
  assert.deepEqual((await stats()).privateStartFiles,before);await context.close();cases.push('private startup plus Root INTAKE remains query-only and its intent is retained');
 }
 for(const mismatch of ['schema','maintenanceId','manifestSha256','predecessorStartOperationId']){
  const {page,context}=await setup('start',{}, {maintenance:true});await control('set',{privateIntent:true});const before=(await stats()).privateStartFiles;
  await query(page);await material(page);await dialog(page);await accept(page);await expect(page.locator('#admission-acknowledge')).toBeVisible();
  const stored=await page.evaluate(({key,mismatch})=>{
   let value=JSON.parse(localStorage.getItem(key));
   if(mismatch==='schema')value={schema:1,operationId:value.operationId,restoreOperationId:value.restoreOperationId,expectedKeySha256:value.expectedKeySha256};
   else value[mismatch]=mismatch==='manifestSha256'?'b'.repeat(64):crypto.randomUUID();
   const raw=JSON.stringify(value);localStorage.setItem(key,raw);return raw;
  },{key:startStore,mismatch});
  await page.locator('#admission-acknowledge').click();await expect(page.locator('#admission-notice')).toContainText('浏览器中的原记录不匹配');
  assert.equal(await page.evaluate(k=>localStorage.getItem(k),startStore),stored);assert.deepEqual((await stats()).privateStartFiles,before);
  await context.close();cases.push('closed maintenance startup cannot acknowledge a browser record with a different '+mismatch);
 }
 {
  const {page,context}=await setup('start');await query(page);await material(page);await dialog(page);await accept(page);
  const stored=await page.evaluate(key=>{const value={...JSON.parse(localStorage.getItem(key)),schema:2,maintenanceId:crypto.randomUUID(),predecessorStartOperationId:crypto.randomUUID(),manifestSha256:'b'.repeat(64)};const raw=JSON.stringify(value);localStorage.setItem(key,raw);return raw;},startStore);
  await page.locator('#admission-acknowledge').click();await expect(page.locator('#admission-notice')).toContainText('浏览器中的原记录不匹配');
  assert.equal(await page.evaluate(k=>localStorage.getItem(k),startStore),stored);await context.close();cases.push('closed initial startup cannot acknowledge a maintenance-shaped browser record');
 }
 if(fixture.platform==='linux'){
  for(const detailed of [false,true]){
   const {page,context}=await setup();await control('set',{pendingMarker:true,...(detailed?{privateIntent:true}:{})});const before=(await stats()).privateRestoreFiles;
   await query(page);await material(page);await dialog(page);await accept(page);await expect(page.locator('#admission-acknowledge')).toBeVisible();
   const after=await stats();assert.equal(after.pendingMarkerActive,false);assert.equal(after.archivedPendingMarkers,1);assert.deepEqual(after.privateRestoreFiles,before);
   await page.reload();await query(page);await page.locator('#admission-acknowledge').click();await expect(page.locator('#backup')).toBeEnabled();
   assert.equal(await page.evaluate(k=>localStorage.getItem(k),restoreStore),null);assert.deepEqual((await stats()).privateRestoreFiles,before);
   await privateBrowser(page);await context.close();cases.push((detailed?'private restore intent':'early pending marker')+' is retained under its original authorization, then explicit acknowledgement returns to manual recovery');
  }
  {
   const {page,context}=await setup();await control('set',{pendingMarker:true,privateIntent:true,archiveInterrupted:true});
   await query(page);await material(page);await dialog(page);await accept(page);await expect(page.locator('#admission-notice')).toContainText('暂时无法核实');
   await query(page);await expect(page.locator('#admission-acknowledge')).toBeHidden();assert.equal((await stats()).pendingMarkerActive,true);
   await control('set',{releaseArchive:true,releaseThrottle:true});await material(page);await dialog(page);await accept(page);
   await expect(page.locator('#admission-acknowledge')).toBeVisible();assert.equal((await stats()).pendingMarkerActive,false);assert.equal((await stats()).archivedPendingMarkers,1);
   await context.close();cases.push('local closed receipt without marker retirement cannot be acknowledged and requires explicit original authorization to finish');
  }
  {
   const {page,context}=await setup();await control('set',{pendingMarker:true,privateIntent:true,phase:'INTAKE'});const before=(await stats()).privateRestoreFiles;
   await query(page);await expect(page.locator('#admission-close-form')).toBeHidden();assert.equal((await stats()).pendingMarkerActive,true);assert.equal((await stats()).archivedPendingMarkers,0);
   assert.deepEqual((await stats()).privateRestoreFiles,before);await context.close();cases.push('Root INTAKE keeps the cold restore and pending marker unresolved without any archive or resend');
  }
 }
 assert.deepEqual(errors,[]);console.log(JSON.stringify({tests:cases.length,cases,productionPageAndHandler:true,actualHttps:true,receiverPlatform:fixture.platform,rootAndDecryption:'modeled',humanMainSessionAcceptance:false,nativeKeyWrites:0,oldClosedScenariosReplayed:false}));
}finally{
 await browser.close();try{await control('stop');}catch(_){}child.stdin.end();if(child.exitCode===null){await new Promise(resolve=>{const timer=setTimeout(()=>{child.kill('SIGTERM');resolve();},4000);child.once('exit',()=>{clearTimeout(timer);resolve();});});}
 if(linux)spawnSync('docker',['rm','-f',container],{stdio:'ignore'});
}
