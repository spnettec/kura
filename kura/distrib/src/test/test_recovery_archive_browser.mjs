/* SPDX-License-Identifier: EPL-2.0 */
// Actual production HTTPS/UI/private files and Root HMAC; Main, historical results and backup inspection are models.
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {createServer} from 'node:net';
import {createRequire} from 'node:module';
import {dirname,resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {mkdir,writeFile} from 'node:fs/promises';
const here=dirname(fileURLToPath(import.meta.url)),workspace=resolve(here,'../../../../..');
const {chromium,expect}=createRequire(resolve(workspace,'kura-management-console/frontend/package.json'))('@playwright/test');
const output=resolve(process.argv[2]||resolve(here,'../../target/recovery-archive-browser'));
await mkdir(output,{recursive:true,mode:0o700});
const id=randomUUID(),container='yofc-recovery-archive-browser-'+id,volume='kura-recovery-archive-browser-jdk-'+id;
const socket=createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
await writeFile(join(output,'owned.json'),JSON.stringify({container,volume,port,createdAt:new Date().toISOString()}));
let child,browser,lines,fixture,stderr='',volumeCreated=false;const cases=[],errors=[];
function docker(args){const result=spawnSync('docker',args,{encoding:'utf8',timeout:30000});if(result.status!==0)throw Error('Owned fixture Docker command failed: '+result.stderr);return result.stdout;}
async function read(){let timer;try{const row=await Promise.race([lines.next(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('fixture observation timeout: '+stderr)),45000);})]);if(row.done)throw Error('fixture stopped: '+stderr);return JSON.parse(row.value);}finally{clearTimeout(timer);}}
async function control(command,extra={}){child.stdin.write(JSON.stringify({command,...extra})+'\n');return read();}
const rootStats=async()=>{const value=await control('stats');assert.equal(value.privateOriginalsPreserved,true);assert.equal(value.secretsOnDisk,false);return value;};
const handoff=()=>fixture.reference.kind==='HANDOFF'||fixture.reference.kind==='ADMISSION'&&!['restore','start'].includes(fixture.reference.senderKind);
const responseFor=command=>r=>r.request().method()==='POST'&&['/api/archive','/api/handoff'].some(path=>r.url().endsWith(path))&&r.request().postDataJSON().command===command;
async function choose(page){
 if(handoff()){await page.locator('#handoff-token').fill(fixture.token);const done=page.waitForResponse(responseFor('archive-list'));await page.locator('#archive-refresh').click();await done;}
 await expect(page.locator('#archive-progress')).toBeHidden();
 const r=fixture.reference;
 try{await page.locator('#archive-records').selectOption(r.kind+(r.senderKind?':'+r.senderKind:'')+'|'+r.operationId);}
 catch(error){console.error(JSON.stringify({reference:r,errors,notice:await page.locator('#archive-notice').textContent(),options:await page.locator('#archive-records option').allTextContents()}));throw error;}
}
async function open(kind='RESTORE',options={},count=1){
 fixture=await control('reset',{kind,count});const context=await browser.newContext({ignoreHTTPSErrors:true,...options});context.setDefaultTimeout(10000);
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 page.on('console',message=>{if(message.type()==='error')console.error('BROWSER_CONSOLE '+message.text().slice(0,500));});
 page.on('requestfailed',request=>console.error('BROWSER_REQUEST_FAILED '+request.url()+' '+request.failure()?.errorText));
 await page.goto(fixture.url+(handoff()?'/handoff':'/'));
 await expect(page.locator('#archive-progress')).toBeHidden();if(count===1)await choose(page);return {context,page};
}
async function query(page){const done=page.waitForResponse(responseFor(handoff()?'archive-query':'query'));await page.locator('#archive-read').click();await done;await expect(page.locator('#archive-progress')).toBeHidden();}
async function material(page,password=fixture.passphrase){
 if(handoff())return;
 await page.locator('#archive-backup').setInputFiles({name:'original-backup.json',mimeType:'application/json',buffer:Buffer.from(fixture.backupJson)});
 await page.locator('#archive-password').fill(password);
}
async function dialog(page,continuing=false){
 await page.locator(continuing?'#archive-continue':'#archive-apply').click();await expect(page.locator('#archive-confirm')).toBeVisible();
 await expect(page.locator('#archive-confirm button[value=cancel]')).toBeFocused();
}
async function accept(page,continuing=false){
 const command=handoff()?(continuing?'archive-continue':'archive-confirm'):(continuing?'continue':'archive'),done=page.waitForResponse(responseFor(command));
 await page.locator('#archive-confirm-accept').click();await done;await expect(page.locator('#archive-progress')).toBeHidden();
}
async function archive(page,continuing=false){await material(page);await dialog(page,continuing);await accept(page,continuing);}
async function noBrowserSecrets(page){const saved=await page.evaluate(()=>Object.values(localStorage).join('\n'));assert.equal(saved.includes(fixture.passphrase),false);if(fixture.token)assert.equal(saved.includes(fixture.token),false);}
try{
 docker(['image','inspect','--format','{{.Id}}','yofc-kura-key-metadata-tests:ubuntu24.04']);
 docker(['image','inspect','--format','{{.Id}}','eclipse-temurin:21-jdk']);
 docker(['volume','create',volume]);volumeCreated=true;
 docker(['run','--rm','--pull=never','--network=none','--mount','type=volume,src='+volume+',dst=/jdk','eclipse-temurin:21-jdk','cp','-a','/opt/java/openjdk/.','/jdk/']);
 child=spawn('docker',['run','--rm','-i','--pull=never','--name',container,'--label','yofc.fixture=recovery-archive-browser','--read-only','--security-opt','no-new-privileges',
  '--tmpfs','/tmp:rw,nosuid,nodev,size=512m','--tmpfs','/run:rw,nosuid,nodev,size=16m','-p','127.0.0.1:'+port+':18443',
  '--mount','type=volume,src='+volume+',dst=/opt/jdk,readonly','--mount','type=bind,src='+resolve(workspace,'kura')+',dst=/workspace/kura,readonly',
  '--entrypoint','/usr/bin/python3','yofc-kura-key-metadata-tests:ubuntu24.04','-B','/workspace/kura/kura/distrib/src/test/recovery_archive_browser_server.py',
  '--repository','/workspace/kura','--java','/opt/jdk/bin/java','--cipher-jar','/workspace/kura/kura/distrib/kura-key-crypto/target/kura-key-crypto-6.0.0-SNAPSHOT.jar','--public-port',String(port)],{stdio:['pipe','pipe','pipe']});
 child.stderr.on('data',bytes=>{stderr=(stderr+bytes.toString()).slice(-4000);});lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();fixture=await read();
 browser=await chromium.launch({headless:true});
 {
  const {page,context}=await open();await query(page);await expect(page.locator('#archive-authorize-form')).toBeVisible();
  await page.locator('#archive-apply').click();await expect(page.locator('#archive-confirm')).toBeHidden();await expect(page.locator('#archive-backup')).toBeFocused();
  await material(page);await dialog(page);assert.equal(await page.locator('#archive-confirm').getAttribute('role'),null);assert.equal(await page.locator('#archive-confirm').getAttribute('aria-modal'),null);
  await page.keyboard.press('Tab');await expect(page.locator('#archive-confirm-accept')).toBeFocused();await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Escape');await expect(page.locator('#archive-confirm')).toBeHidden();await expect(page.locator('#archive-password')).toHaveValue('');
  assert.equal((await rootStats()).firstSends,0);await noBrowserSecrets(page);await context.close();cases.push('native required materials, labels, safe modal autofocus, Tab, Shift+Tab, Escape and no premature metadata send');
 }
 for(const kind of ['RESTORE','START','ADMISSION:restore','ADMISSION:start','HANDOFF','ADMISSION:publish','ADMISSION:handoff-start','ADMISSION:handoff-renewal','ADMISSION:continue']){
  const {page,context}=await open(kind);await query(page);await expect(page.locator('#archive-apply')).toBeEnabled();await archive(page);
  await expect(page.locator('#archive-notice')).toContainText('归档回执已确认');const before=await rootStats();assert.equal(before.firstSends,1);assert.equal(before.continuations,0);assert.equal(before.archiveIds.length,1);
  await noBrowserSecrets(page);await page.reload();await choose(page);await query(page);await expect(page.locator('#archive-notice')).toContainText('归档回执已确认');
  assert.deepEqual((await rootStats()).archiveIds,before.archiveIds);assert.equal((await rootStats()).firstSends,1);await context.close();
  cases.push(kind+' production HTTPS archive authorization, real Root HMAC and immutable private originals survive reload');
 }
 {
  const {page,context}=await open();await query(page);await control('mode',{value:'before'});await archive(page);await expect(page.locator('#archive-notice')).toContainText('原归档结果尚不确定');
  const before=await rootStats();await control('mode',{value:'healthy'});await query(page);await expect(page.locator('#archive-authorize-form')).toBeHidden();assert.equal((await rootStats()).firstSends,1);
  await control('mode',{value:'offline'});await query(page);await expect(page.locator('#archive-identities')).toContainText(before.archiveIds[0]);await expect(page.locator('#archive-authorize-form')).toBeHidden();
  await context.close();cases.push('missing Root metadata original remains query-only under the same retained ID, also offline');
 }
 {
  const {page,context}=await open();await query(page);await control('mode',{value:'after-intent'});await archive(page);await expect(page.locator('#archive-notice')).toContainText('明确继续');
  const before=await rootStats();await control('mode',{value:'healthy'});await query(page);assert.equal((await rootStats()).continuations,0);await expect(page.locator('#archive-apply')).toBeDisabled();
  await archive(page,true);await expect(page.locator('#archive-notice')).toContainText('归档回执已确认');const after=await rootStats();assert.deepEqual(after.archiveIds,before.archiveIds);assert.equal(after.firstSends,1);assert.equal(after.continuations,1);
  await context.close();cases.push('explicit same-ID metadata continuation only after an authenticated original Root intent');
 }
 {
  const {page,context}=await open();await query(page);await control('mode',{value:'lose-http'});await archive(page);await expect(page.locator('#archive-notice')).toContainText('原归档结果尚不确定');
  await expect(page.locator('#archive-authorize-form')).toBeHidden();await query(page);await expect(page.locator('#archive-notice')).toContainText('归档回执已确认');assert.equal((await rootStats()).firstSends,1);
  await context.close();cases.push('lost HTTP reply is recovered by an original read without another send');
 }
 {
  const {page,context}=await open();await query(page);await material(page,'incorrect synthetic material 52!');await dialog(page);await accept(page);
  await expect(page.locator('#archive-notice')).toContainText('未通过核验');assert.equal((await rootStats()).firstSends,0);await expect(page.locator('#archive-password')).toHaveValue('');await context.close();
  cases.push('incorrect backup authorization refuses before metadata intent or send and clears the passphrase');
 }
 {
  const {page,context}=await open();await query(page);await control('mode',{value:'stale'});await archive(page);await expect(page.locator('#archive-notice')).toContainText('已变化');
  assert.equal((await rootStats()).firstSends,0);await expect(page.locator('#archive-authorize-form')).toBeHidden();await context.close();cases.push('stale reviewed Root bytes cannot create a private intent or metadata send');
 }
 {
  const {page,context}=await open();await control('mode',{value:'delay'});const response=page.waitForResponse(responseFor('query')),request=page.waitForRequest(r=>r.url().endsWith('/api/archive')&&r.postDataJSON().command==='query');
  await page.locator('#archive-read').click();await request;await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')));await response;
  await expect(page.locator('#archive-authorize-form')).toBeHidden();assert.equal((await rootStats()).firstSends,0);await context.close();cases.push('page lifecycle changes invalidate a delayed preview and leave no write permission');
 }
 {
  const {page,context}=await open('RESTORE',{},23);await expect(page.locator('#archive-records option')).toHaveCount(21);await page.locator('#archive-next').click();
  await expect(page.locator('#archive-records option')).toHaveCount(4);await expect(page.locator('#archive-next')).toBeDisabled();await page.locator('#archive-previous').click();await expect(page.locator('#archive-records option')).toHaveCount(21);
  assert.equal((await rootStats()).firstSends,0);await context.close();cases.push('20-record physical history pages preserve originals and never archive on selection or navigation');
 }
 {
  const {page,context}=await open('RESTORE',{viewport:{width:390,height:844}});await page.locator('#language').selectOption('en');await query(page);await material(page);await dialog(page);
  await expect(page.locator('#archive-confirm button[value=cancel]')).toHaveAccessibleName('Cancel');await page.screenshot({path:join(output,'archive-mobile.png')});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await page.keyboard.press('Escape');assert.equal((await rootStats()).firstSends,0);await context.close();
  cases.push('bilingual 390px layout and native cancellation without horizontal overflow');
 }
 assert.deepEqual(errors,[]);
 const report={tests:cases.length,cases,actualHttps:true,productionAssets:true,actualRootArchiveHmac:true,actualInstalledMain:false,historicalResults:'modeled',backupInspection:'modeled',humanSessionAccepted:false,oldClosedOneTimeAcceptanceReplayed:false};
 await writeFile(join(output,'results.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
}catch(error){console.error(JSON.stringify({completed:cases,diagnostic:stderr.slice(-1500)}));throw error;}finally{
 if(browser)await browser.close();
 if(child&&child.exitCode===null&&child.signalCode===null){try{await control('stop');}catch(_){}}
 const exists=spawnSync('docker',['inspect',container],{stdio:'ignore'}).status===0;
 if(exists)docker(['stop','--time','5',container]);
 if(child&&child.exitCode===null&&child.signalCode===null)await Promise.race([new Promise(resolve=>child.once('exit',resolve)),new Promise(resolve=>setTimeout(resolve,6000))]);
 assert.notEqual(spawnSync('docker',['inspect',container],{stdio:'ignore'}).status,0,'Owned container must stop before removing its JDK volume');
 if(volumeCreated)docker(['volume','rm',volume]);
 await writeFile(join(output,'cleanup.json'),JSON.stringify({containerRemoved:true,jdkVolumeRemoved:volumeCreated})+'\n');
}
