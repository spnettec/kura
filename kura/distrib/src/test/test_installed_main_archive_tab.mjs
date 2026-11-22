/* SPDX-License-Identifier: EPL-2.0 */
// Read-only real Main/GWT/Root integration. Never dispatch a key request.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const args=process.argv.slice(2);
assert.ok(args.includes('--disposable-fixture'));
function option(name){const i=args.indexOf(name);assert.ok(i>=0&&args[i+1],name+' required');return args[i+1];}
const output=resolve(option('--fixture')),report=resolve(option('--report'));
const workspace=resolve(dirname(fileURLToPath(import.meta.url)),'../../../../..');
const {chromium,expect}=createRequire(resolve(workspace,'kura-management-console/frontend/package.json'))('@playwright/test');
const owned=JSON.parse(await readFile(resolve(output,'owned-fixture.json'),'utf8'));
const login=JSON.parse(await readFile(resolve(output,'fixture-login.json'),'utf8'));
assert.match(owned.name,/^yofc-installed-main-archive-[a-f0-9]{10}$/);
assert.match(owned.containerId,/^[a-f0-9]{64}$/);
async function command(argv,input){return await new Promise((resolve,reject)=>{
 const child=spawn(argv[0],argv.slice(1),{stdio:['pipe','pipe','pipe']});let stdout='',stderr='';
 child.stdout.on('data',v=>stdout+=v);child.stderr.on('data',v=>stderr+=v);
 child.on('error',reject);child.once('close',code=>code===0?resolve(stdout):reject(Error(argv[0]+' failed '+stderr.slice(-1500))));child.stdin.end(input);
});}
const details=JSON.parse(await command(['docker','inspect',owned.containerId]));
assert.equal(details[0].Name,'/'+owned.name);
assert.equal(details[0].Config.Labels['yofc.purpose'],'installed-main-archive');
assert.equal(details[0].HostConfig.Memory,1536*1024*1024);
assert.deepEqual(Object.keys(details[0].NetworkSettings.Networks),[]);
const inspector=await readFile(resolve(workspace,'kura/kura/distrib/src/test/inspect_installed_main_fixture.py'),'utf8');
const before=JSON.parse(await command(['docker','exec','-i',owned.containerId,'python3','-B','-','--stage','before-backup'],inspector));
const relays=new Set(),requests=[],replies=[],errors=[];
const relayCode=`import os,socket,sys,threading
s=socket.create_connection(('127.0.0.1',443),timeout=10);s.settimeout(None)
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
const proxy=createServer(socket=>{
 const child=spawn('docker',['exec','-i',owned.containerId,'python3','-B','-c',relayCode],{stdio:['pipe','pipe','ignore']});relays.add(child);
 socket.on('error',()=>{});child.stdin.on('error',()=>{});child.stdout.on('error',()=>{});child.on('error',()=>socket.destroy());
 socket.pipe(child.stdin);child.stdout.pipe(socket);child.once('close',()=>{relays.delete(child);socket.destroy();});socket.once('close',()=>child.stdin.destroy());
});
let browser,result={success:false,containerId:owned.containerId,readOnly:true,nativeKeyRequests:0};
try{
 await new Promise((resolve,reject)=>{proxy.once('error',reject);proxy.listen(0,'127.0.0.1',resolve);});
 const origin='https://localhost:'+proxy.address().port;
 browser=await chromium.launch({headless:true});const context=await browser.newContext({ignoreHTTPSErrors:true,locale:'en-US'});
 const page=await context.newPage();page.setDefaultTimeout(15000);
 const methods=['getStatus','listAdmissions','listOperations','listArchives','getArchive','createBackup','restoreBackup','archiveRecord'];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.url().endsWith('/gatewayKey')){const values=(request.postData()||'').split('|');requests.push(methods.find(x=>values.includes(x))||'other');}});
 const reads=[];page.on('response',response=>{if(response.url().endsWith('/gatewayKey'))reads.push((async()=>{
  const text=await response.text(),parts=(response.request().postData()||'').split('|');
  replies.push({method:methods.find(x=>parts.includes(x))||'other',status:response.status(),success:text.startsWith('//OK'),
   ...(text.startsWith('//OK')?{}:{failure:text.slice(0,1200)})});
 })());});
 await page.goto(origin+'/',{waitUntil:'domcontentloaded'});
 await page.locator('#login-user').fill(login.username);await page.locator('#login-password').fill(login.password);
 await page.locator('#login-button').click();await page.waitForURL(/\/admin\/console/,{waitUntil:'domcontentloaded'});
 await page.getByText('Security',{exact:true}).click();
 await expect(page.locator('#gatewayKeyPanel')).toBeHidden();
 await page.getByText('Master-key backup and recovery',{exact:true}).click();
 const archive=page.locator('.gateway-key-archive');
 await expect(archive).toBeVisible();
 await expect(archive.getByRole('button',{name:'Refresh archive history',exact:true})).toHaveAttribute('aria-disabled','false');
 await expect(archive).toContainText('No owned records on this page.');
 assert.ok(requests.includes('listArchives'),'First visible selection must load archive history');
 await expect(page.locator('#gatewayKeyPanel')).toContainText('The gateway key is available.');
 // Leaving and returning must perform a new read only after the pane is shown.
 const originalReads=requests.filter(x=>x==='listArchives').length;
 await page.getByText('Certificates List',{exact:true}).click();await expect(archive).toBeHidden();
 await page.getByText('Master-key backup and recovery',{exact:true}).click();
 await expect(archive).toBeVisible();await expect(archive).toContainText('No owned records on this page.');
 await expect.poll(()=>requests.filter(x=>x==='listArchives').length).toBe(originalReads+1);
 await Promise.all(reads);
 assert.ok(replies.length>0&&replies.every(x=>x.status===200&&x.success));
 assert.ok(!requests.some(x=>['createBackup','restoreBackup','archiveRecord'].includes(x)));
 assert.deepEqual(errors,[]);
 const after=JSON.parse(await command(['docker','exec','-i',owned.containerId,'python3','-B','-','--stage','before-backup'],inspector));
 assert.deepEqual(after.main,before.main);
 result={...result,success:true,actualHttps:true,actualAdminLogin:true,actualMainUid:after.mainUid,
  mainPid:after.main.MainPID,privateFilesUnchanged:after.privateFilesUnchanged,loadedCanonicalKeyMatches:true,
  firstHiddenToVisibleSelection:true,repeatTabSelection:true,requests,replies,mainProcessPreserved:true,
  certificateValidation:'isolated self-signed fixture; opaque TCP relay; browser ignores trust errors',fullPlatformAcceptance:false};
}catch(error){result={...result,requests,replies,errors,error:String(error.stack||error).replaceAll(login.password,'<redacted>')};process.exitCode=1;}
finally{
 if(browser)await browser.close();proxy.close();for(const child of relays){child.stdin.destroy();child.kill('SIGTERM');}
 await writeFile(report,JSON.stringify(result,null,2)+'\n',{mode:0o600,flag:'wx'});
 process.stdout.write(JSON.stringify(result)+'\n');
}
