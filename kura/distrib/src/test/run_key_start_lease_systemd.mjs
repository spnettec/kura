/* SPDX-License-Identifier: EPL-2.0 */
// One new installed-Core/recovery-Main browser scenario. Never adopt existing containers or IDs.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomUUID,createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {connect as tlsConnect} from 'node:tls';
import {readFileSync,writeFileSync,mkdirSync,openSync,closeSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const here=dirname(fileURLToPath(import.meta.url)),workspace=resolve(here,'../../../../..');
const args=process.argv.slice(2),option=name=>{const i=args.indexOf(name);assert.ok(i>=0&&args[i+1],name+' required');return args[i+1];};
assert.ok(args.includes('--disposable-fixture'));
const pkg=resolve(option('--package')),sha=option('--package-sha256'),sourceHead=option('--source-head'),legacy=resolve(option('--legacy-baseline')),out=resolve(option('--results'));
assert.equal(createHash('sha256').update(readFileSync(pkg)).digest('hex'),sha);
mkdirSync(out,{recursive:true,mode:0o700});
const save=(name,value)=>writeFileSync(resolve(out,name),JSON.stringify(value,null,2)+'\n',{mode:0o600});
const event=(stage,extra={})=>{const value={stage,at:new Date().toISOString(),...extra};save('progress.json',value);process.stdout.write(JSON.stringify(value)+'\n');};
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const name='yofc-start-lease-installed-'+randomUUID().slice(0,8),volume=name+'-jdk';
let cid,worker,proxy,browser,token='',success=false;
const relays=new Set(),pageErrors=[],writerCommands=[];
async function command(argv,{acceptFailure=false,input}={}){
 return await new Promise((resolve,reject)=>{
  const child=spawn(argv[0],argv.slice(1),{stdio:['pipe','pipe','pipe']});let stdout='',stderr='';
  child.stdout.on('data',v=>{stdout+=v;});child.stderr.on('data',v=>{stderr=(stderr+v).slice(-5000);});
  child.on('error',reject);child.on('close',code=>code===0||acceptFailure?resolve({code,stdout,stderr}):reject(Error(argv[0]+' failed: '+stderr)));
  child.stdin.end(input);
 });
}
const docker=(argv,options)=>command(['docker',...argv],options);
async function marker(path){return (await docker(['exec',cid,'test','-f',path],{acceptFailure:true})).code===0;}
async function waitFor(check,seconds,label){
 const deadline=Date.now()+seconds*1000;
 while(Date.now()<deadline){if(await check())return;if(worker&&worker.exitCode!==null)throw Error('Original worker is terminal before '+label);await sleep(500);}
 throw Error('Observation deadline at '+label+'; retain the same original process and fixture');
}
const relayCode=String.raw`import os,socket,sys,threading
s=socket.create_connection(('127.0.0.1',9443),timeout=10);s.settimeout(None)
def inbound():
 try:
  while True:
   b=os.read(0,65536)
   if not b:break
   s.sendall(b)
 except OSError:pass
 finally:
  try:s.shutdown(socket.SHUT_WR)
  except OSError:pass
threading.Thread(target=inbound,daemon=True).start()
try:
 while True:
  b=s.recv(65536)
  if not b:break
  sys.stdout.buffer.write(b);sys.stdout.buffer.flush()
except OSError:pass
finally:s.close()
`;

try{
 const existing=await docker(['inspect',name],{acceptFailure:true});assert.notEqual(existing.code,0);
 await docker(['volume','create','--label','yofc.purpose=installed-start-lease',volume]);
 await docker(['run','--rm','--pull=never','--network=none','--mount',`type=volume,src=${volume},dst=/jdk`,'eclipse-temurin:21-jdk','cp','-a','/opt/java/openjdk/.','/jdk/']);
 cid=(await docker(['run','--detach','--pull=never','--name',name,'--label','yofc.purpose=installed-start-lease',
  '--privileged','--cgroupns=private','--memory=1g','--cpus=2','--tmpfs','/run:rw,nosuid,nodev,mode=755,size=64m','--tmpfs','/run/lock:rw,nosuid,nodev,mode=755,size=2m',
  '--mount',`type=bind,src=${resolve(workspace,'kura')},dst=/source,readonly`,'--mount',`type=bind,src=${pkg},dst=/candidate.deb,readonly`,
  '--mount',`type=bind,src=${legacy},dst=/legacy.deb,readonly`,'--mount',`type=volume,src=${volume},dst=/java,readonly`,
  '--env','PYTHONDONTWRITEBYTECODE=1','--entrypoint','/bin/sh','yofc-empty-systemd:g028-20261114','-c','mount --make-rshared /run && exec /sbin/init'])).stdout.trim();
 save('owned-fixture.json',{containerId:cid,name,volume,package:pkg,sha256:sha,sourceHead,automaticReplayForbidden:true});
 await waitFor(async()=>(await docker(['exec',cid,'systemctl','show-environment'],{acceptFailure:true})).code===0,20,'PID1 readiness');
 const log=openSync(resolve(out,'worker.log'),'wx',0o600);
 worker=spawn('docker',['exec',cid,'python3','-B','/source/kura/distrib/src/test/test_key_start_lease_systemd.py',
  '--package','/candidate.deb','--package-sha256',sha,'--source-head',sourceHead,'--legacy-baseline','/legacy.deb','--java','/java/bin/java','--disposable-fixture','-v'],{stdio:['ignore',log,log]});
 closeSync(log);
 event('INSTALLING',{containerId:cid,workerHostPid:worker.pid});
 await waitFor(()=>marker('/run/kura-generation-install-ready'),600,'declared package installation');
 await docker(['network','disconnect','bridge',cid]);
 const devices=JSON.parse((await docker(['exec',cid,'python3','-B','-c',"from pathlib import Path;import json;print(json.dumps(sorted(p.name for p in Path('/sys/class/net').iterdir())))"])).stdout);
 assert.deepEqual(devices,['lo']);await docker(['exec',cid,'touch','/run/kura-generation-network-off']);
 proxy=createServer(socket=>{
  const relay=spawn('docker',['exec','-i',cid,'python3','-B','-c',relayCode],{stdio:['pipe','pipe','ignore']});relays.add(relay);
  socket.on('error',()=>{});relay.stdin.on('error',()=>{});relay.stdout.on('error',()=>{});
  socket.pipe(relay.stdin);relay.stdout.pipe(socket);relay.on('error',()=>socket.destroy());
  relay.once('close',()=>{relays.delete(relay);socket.destroy();});socket.once('close',()=>{relay.stdin.destroy();});
 });
 await new Promise((resolve,reject)=>{proxy.once('error',reject);proxy.listen(9443,'127.0.0.1',resolve);});
 event('ISOLATED',{interfaces:devices,tlsForwarding:'opaque TCP only through docker exec; no response replacement'});
 await waitFor(()=>marker('/run/kura-start-lease-native/browser-session.json'),180,'actual Main and authority');
 const session=JSON.parse((await docker(['exec',cid,'cat','/run/kura-start-lease-native/browser-session.json'])).stdout);token=session.token;
 const fingerprint=await new Promise((resolve,reject)=>{
  const socket=tlsConnect({host:'127.0.0.1',port:9443,servername:'localhost',rejectUnauthorized:false},()=>{
   const digest=createHash('sha256').update(socket.getPeerCertificate(true).raw).digest('hex');socket.destroy();resolve(digest);
  });socket.on('error',reject);socket.setTimeout(15000,()=>{socket.destroy();reject(Error('TLS observation deadline'));});
 });
 assert.equal(fingerprint,session.certificateSha256);
 const {chromium,expect}=createRequire(resolve(workspace,'kura-management-console/frontend/package.json'))('@playwright/test');
 browser=await chromium.launch({headless:true});const context=await browser.newContext({ignoreHTTPSErrors:true});context.setDefaultTimeout(15000);
 const page=await context.newPage();page.on('pageerror',error=>pageErrors.push(error.message.replaceAll(token,'<redacted>')));
 page.on('request',request=>{if(request.url().endsWith('/api/handoff')&&request.method()==='POST'){const command=request.postDataJSON().command;if(command!=='query')writerCommands.push(command);}});
 await page.goto('https://localhost:9443/handoff');await page.locator('#handoff-token').fill(token);
 async function query(){
  const response=page.waitForResponse(r=>r.url().endsWith('/api/handoff')&&r.request().postDataJSON().command==='query');
  await page.locator('#handoff-query').click();const r=await response;assert.equal(r.status(),200);
  const value=await r.json();assert.equal(value.state,'HANDOFF_STATUS');await expect(page.locator('#handoff-progress')).toBeHidden();return value;
 }
 async function write(command){
  await page.locator('#handoff-'+command).click();await expect(page.locator('#handoff-confirm button[value=cancel]')).toBeFocused();
  const sent=page.waitForRequest(r=>r.url().endsWith('/api/handoff')&&r.postDataJSON().command===command);
  await page.locator('#handoff-confirm-accept').click();await sent;await expect(page.locator('#handoff-progress')).toBeHidden({timeout:90000});
 }
 const initial=await query();assert.equal(initial.handoff.handoffId,session.handoffId);assert.equal(initial.allowed.publish,true);
 await write('publish');const published=await query();assert.equal(published.publication.state,'SUCCEEDED');assert.equal(published.start.state,'NOT_RECORDED');
 event('PUBLISHED_REAL_WINDOW_WAIT',{handoffId:session.handoffId,publicationId:published.handoff.publicationId});
 let current=published,lastProgress=0;
 while(current.handoff.mutationWindowOpen){
  if(Date.now()-lastProgress>40000){event('WAITING_FOR_ORIGINAL_GRANT_EXPIRY',{workerLive:worker.exitCode===null});lastProgress=Date.now();}
  await sleep(15000);current=await query();if(worker.exitCode!==null)throw Error('Original worker terminal during grant window');
 }
 assert.equal(current.renewalAllowed,true);await expect(page.locator('#handoff-start')).toBeDisabled();
 await write('start-renew');current=await query();assert.equal(current.startRenewals.length,1);assert.equal(current.startRenewals[0].state,'SUCCEEDED');
 assert.equal(current.handoff.startOperationId,published.handoff.startOperationId);assert.equal(current.allowed.start,true);
 await waitFor(()=>marker('/run/kura-start-lease-native/lease-verified.json'),45,'original lease and ordinary-start fence');
 event('REAL_LEASE_VERIFIED',{leaseOperationId:current.startRenewals[0].operationId,originalStartupId:current.handoff.startOperationId});
 await write('start');current=await query();assert.equal(current.start.state,'SUCCEEDED');
 await waitFor(()=>marker('/run/kura-start-lease-native/providers-ready.json'),90,'new actual Core providers');
 const complete=page.waitForResponse(r=>r.url().endsWith('/api/handoff')&&r.request().postDataJSON().command==='complete');
 await page.locator('#handoff-complete').click();assert.equal((await (await complete).json()).completed,true);
 await waitFor(()=>marker('/run/kura-start-lease-native/result.json'),45,'owned final result');
 await new Promise((resolve,reject)=>{if(worker.exitCode!==null)return worker.exitCode===0?resolve():reject(Error('Original worker failed'));worker.once('exit',code=>code===0?resolve():reject(Error('Original worker failed')));});
 assert.deepEqual(writerCommands,['publish','start-renew','start','complete']);assert.deepEqual(pageErrors,[]);
 const storage=await page.evaluate(()=>Object.values(localStorage).join('\n'));assert.equal(storage.includes(token),false);
 const result=JSON.parse((await docker(['exec',cid,'cat','/run/kura-start-lease-native/result.json'])).stdout);
 result.actualHttpsAndProductionBrowser=true;result.browserWriterCommands=writerCommands;result.certificateFingerprintPinned=true;
 result.browserBearerPersisted=false;result.networkInterfaces=devices;save('result.json',result);success=true;
 event('SUCCESS',{actualNativeLease:true,actualRecoveryMain:true,actualCoreProviders:true});
}catch(error){
 const message=String(error.stack||error).replaceAll(token||'\0','<redacted>');save('failure.json',{message,containerId:cid,workerHostPid:worker?.pid,retainOriginalFixture:true,automaticReplayForbidden:true});process.stderr.write(message+'\n');process.exitCode=1;
}finally{
 if(browser)await browser.close();if(proxy)proxy.close();
 for(const relay of relays){relay.stdin.destroy();relay.kill('SIGTERM');}
 let retain=false;
 if(cid){retain=!success&&(worker?.exitCode===null||await marker('/run/kura-start-lease-native/original-ids.json'));
  if(!retain){const removed=await docker(['rm','-f',cid],{acceptFailure:true});assert.ok(removed.code===0||removed.stderr.includes('No such container'));}
 }
 if(!retain){const removed=await docker(['volume','rm',volume],{acceptFailure:true});save('cleanup.json',{containerRemoved:true,jdkVolumeRemoved:removed.code===0,originalGatewaysUntouched:true,backupCreated:false});}
 else save('retained.json',{containerId:cid,name,volume,workerHostPid:worker?.pid,automaticReplayForbidden:true,readOriginalStateOnly:true});
}
