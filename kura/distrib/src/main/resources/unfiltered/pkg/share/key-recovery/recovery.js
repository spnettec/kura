'use strict';
(() => {
 const el = id => document.getElementById(id);
 const storeKey = 'yofc.kura.cold-key-recovery.intent.v1';
 const startStoreKey = 'yofc.kura.cold-key-recovery.start.v1';
 const csrf = document.querySelector('meta[name=kura-recovery-csrf]').content;
 const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
 const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
 const password = value => {
  const chars = Array.from(value);
  return chars.length >= 12 && chars.length <= 256 && !value.includes('\0')
   && chars.every(c => c.length !== 1 || c.charCodeAt(0) < 0xd800 || c.charCodeAt(0) > 0xdfff)
   && new TextEncoder().encode(value).length <= 1024;
 };
 const words = {
  zh: {language:'语言',title:'恢复网关原密钥',intro:'上传此前下载的加密备份并输入口令。网关将校验保留的原指纹，只补回与本网关匹配的密钥。',refresh:'读取密钥状态',fingerprint:'网关保留的原指纹（SHA-256）',file:'加密备份 JSON 文件',password:'备份解密口令',privacy:'口令仅用于本次核验和恢复，不保存在页面或操作记录中。',inspect:'核验备份',confirm:'我已核对指纹，确认补回本网关的原密钥。',restore:'恢复原密钥',operation:'恢复操作编号',queryPending:'查询待确认的原操作',acknowledge:'确认此结果',original:'原恢复操作编号',queryOriginal:'查询此原操作',console:'返回网关控制台',missing:'原密钥缺失，可核验此前保存的备份。',ready:'原密钥已存在。可查询原恢复操作或返回控制台。',unavailable:'暂时无法读取密钥服务，请保留原操作编号。',invalidFile:'备份文件无法读取或格式不受支持。',reviewed:'备份指纹匹配，可确认恢复。',mismatch:'备份与本网关原密钥不匹配，恢复已禁用。',pending:'结果待确认。只按原编号查询，请勿重新提交。',succeeded:'原密钥恢复已完成，原回执已确认。',rejected:'本次请求在投递前被拒绝。确认此结果后可重新核验。',storage:'无法可靠保存原操作编号，新恢复操作已禁用。',busy:'服务正在处理请求，请稍后再读取状态或核验。'},
  en: {language:'Language',title:'Restore the gateway original key',intro:'Upload your previously downloaded encrypted backup and enter its passphrase. The gateway matches its retained original fingerprint before restoring the key.',refresh:'Read key status',fingerprint:'Retained original fingerprint (SHA-256)',file:'Encrypted backup JSON file',password:'Backup passphrase',privacy:'The passphrase is used for this inspection and recovery only. It is not saved in page storage or operation records.',inspect:'Inspect backup',confirm:'I checked the fingerprint and confirm restoration of this gateway original key.',restore:'Restore original key',operation:'Recovery operation ID',queryPending:'Read the pending original operation',acknowledge:'Acknowledge this result',original:'Original recovery operation ID',queryOriginal:'Read this original operation',console:'Return to the gateway console',missing:'The original key is missing. Inspect your retained backup.',ready:'The original key is present. Read the original recovery operation or return to the console.',unavailable:'The key service is unavailable. Retain the original operation ID.',invalidFile:'The backup cannot be read or its format is unsupported.',reviewed:'The backup fingerprint matches. You can confirm recovery.',mismatch:'The backup does not match the gateway original key. Recovery is disabled.',pending:'The result is unconfirmed. Read only the original operation ID; do not resubmit.',succeeded:'The original key was restored and its original receipt was confirmed.',rejected:'The request was rejected before dispatch. Acknowledge the result before inspecting again.',storage:'The original operation ID cannot be saved reliably. New recovery is disabled.',busy:'The service is handling a request. Read status or inspect again later.'}
 };
 Object.assign(words.zh,{startIntro:'确认原密钥恢复回执后，可在此启动 Kura。系统接收启动请求后，请进入控制台检查是否就绪。',startCore:'启动 Kura',startOperation:'启动操作编号',queryStart:'查询原启动回执',complete:'确认启动回执并结束恢复',startAccepted:'系统已接收原启动请求。请进入控制台检查 Kura 是否就绪。',startPending:'启动结果待确认。只能查询原编号，请勿重新提交。'});
 Object.assign(words.en,{startIntro:'After confirming the original key recovery receipt, start Kura here. Once the system accepts the start request, open the console to check readiness.',startCore:'Start Kura',startOperation:'Start operation ID',queryStart:'Read the original start receipt',complete:'Acknowledge the start receipt and finish recovery',startAccepted:'The system accepted the original start request. Open the console to check Kura readiness.',startPending:'The start result is unconfirmed. Read the original operation ID; do not resubmit.'});
 let pendingRestore=null,startIntent=null,startResult=null,startPlan=null,planSignature="";
 function readStartIntent() {
  try {
   const raw=localStorage.getItem(startStoreKey);if(raw===null)return null;
   const v=JSON.parse(raw);
   const modern=v&&v.schema===2;
   const names=modern?'expectedKeySha256,maintenanceId,manifestSha256,operationId,predecessorStartOperationId,restoreOperationId,schema':'expectedKeySha256,operationId,restoreOperationId,schema';
   if(!v||Object.keys(v).sort().join(',')!==names||(!modern&&v.schema!==1)||!uuid(v.operationId)||!uuid(v.restoreOperationId)||!digest(v.expectedKeySha256)
      ||(modern&&(!uuid(v.maintenanceId)||!uuid(v.predecessorStartOperationId)||!digest(v.manifestSha256))))throw Error();
   return v;
  } catch(_){storageFault=true;return null;}
 }
 function startTerminal() {
  return startIntent&&startResult&&startResult.operationId===startIntent.operationId
   &&startResult.restoreOperationId===startIntent.restoreOperationId&&startResult.keySha256===startIntent.expectedKeySha256
   &&startResult.state==='SUCCEEDED'&&startResult.action===(startIntent.schema===2?'core-start-after-maintenance':'core-start')&&startResult.resultSource==='ROOT_ORIGINAL'
   &&(startIntent.schema!==2||['maintenanceId','predecessorStartOperationId','manifestSha256'].every(k=>startIntent[k]===startResult[k]))
   &&startResult.scope==='SYSTEMD_JOB_ACCEPTED';
 }
 Object.assign(words.zh,{upgradeConfirm:'我确认安装升级已停止 Kura，并为本次维护创建新的启动请求。',startAfterMaintenance:'升级后启动 Kura'});
 Object.assign(words.en,{upgradeConfirm:'I confirm the package upgrade stopped Kura and authorize a new start request for this maintenance.',startAfterMaintenance:'Start Kura after upgrade'});
 function maintenanceReady(){return startTerminal()&&startPlan&&startPlan.startAllowed===true
  &&startPlan.predecessorStartOperationId===startIntent.operationId&&pendingRestore
  &&pendingRestore.operationId===startIntent.restoreOperationId&&pendingRestore.expectedKeySha256===startIntent.expectedKeySha256;}
 let language = 'zh', noticeKey = '', statusKey = '', raw = '', reviewed = null, reviewedRaw = '';
 let available = false, keyReady = false, fingerprint = '', busy = false, storageFault = false;
 let intent = null, result = null, statusEpoch = 0, fileEpoch = 0;
 const text = key => words[language][key] || '';
 function readIntent() {
  try {
   const value = localStorage.getItem(storeKey);
   if (value === null) return null;
   const parsed = JSON.parse(value);
   if (!parsed || Object.keys(parsed).sort().join(',') !== 'expectedKeySha256,operationId,schema'
       || parsed.schema !== 1 || !uuid(parsed.operationId) || !digest(parsed.expectedKeySha256)) throw Error();
   return parsed;
  } catch (_) {storageFault = true; return null;}
 }
 function terminal() {
  return intent && result && result.operationId === intent.operationId
   && ((result.state === 'SUCCEEDED' && result.action === 'restore' && result.resultSource === 'ROOT_ORIGINAL'
        && result.keySha256 === intent.expectedKeySha256 && result.existingReceiptPreserved === true)
    || (result.state === 'REJECTED' && result.resultSource === 'SERVER_PREFLIGHT' && typeof result.error === 'string'));
 }
 function render() {
  const draft = available && !keyReady && !busy && !intent && !storageFault;
  for (const id of ['backup','password']) el(id).disabled = !draft;
  el('inspect').disabled = !draft || !raw || !password(el('password').value);
  el('confirm').disabled = !draft || !reviewed || !reviewed.restoreAllowed || reviewedRaw !== raw;
  el('restore').disabled = el('confirm').disabled || !el('confirm').checked || !password(el('password').value);
  el('refresh').disabled = busy; el('query-pending').disabled = busy || !intent;
  el('acknowledge').disabled = busy || storageFault || !terminal();
  el('original').disabled = busy; el('query-original').disabled = busy || !uuid(el('original').value);
  el('operation').textContent = intent ? intent.operationId : result && uuid(result.operationId) ? result.operationId : '';
  el('fingerprint').textContent = fingerprint;
  el('status').textContent = text(statusKey);
  el('notice').textContent = text(storageFault ? 'storage' : intent && !terminal() ? 'pending' : noticeKey);
  const initial=!startIntent&&pendingRestore&&result&&result.state==='SUCCEEDED'&&result.resultSource==='ROOT_ORIGINAL'
   &&result.action==='restore'&&result.keyChanged===true&&result.operationId===pendingRestore.operationId&&result.keySha256===pendingRestore.expectedKeySha256;
  const maintenance=maintenanceReady();
  el('upgrade-confirm-row').hidden=!maintenance;el('upgrade-confirm').disabled=busy||!maintenance;
  el('start-core').textContent=text(maintenance?'startAfterMaintenance':'startCore');
  el('start-core').disabled=busy||storageFault||!available||!keyReady||!(initial||(maintenance&&el('upgrade-confirm').checked));
  el('query-start').disabled=busy||!startIntent;
  el('complete').disabled=busy||storageFault||!startTerminal();
  el('start-operation').textContent=startIntent?startIntent.operationId:'';
  el('start-notice').textContent=startIntent?text(startTerminal()?'startAccepted':'startPending'):'';
  el('review').textContent = reviewed ? `${text(reviewed.restoreAllowed ? 'reviewed' : 'mismatch')} ${reviewed.keySha256}` : '';
 }
 function invalidate() {reviewed = null; reviewedRaw = ''; el('confirm').checked = false; render();}
 async function request(endpoint, value) {
  const response = await fetch('/api/' + endpoint, {method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',
   headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':csrf},body:JSON.stringify(value)});
  const data = await response.json();
  if (!response.ok || !data || data.schema !== 1 || (data.error && data.state !== 'REJECTED')) throw Error(data && data.error === 'BUSY' ? 'busy' : 'unavailable');
  return data;
 }
 async function status() {
  const epoch = ++statusEpoch; available = false; keyReady = false; fingerprint = ''; invalidate();
  try {
   const value = await request('status', {});
   if (epoch !== statusEpoch) return;
   if (value.state !== 'STATUS' || !digest(value.keySha256) || typeof value.keyReady !== 'boolean') throw Error();
   available = true; keyReady = value.keyReady; fingerprint = value.keySha256; statusKey = keyReady ? 'ready' : 'missing';
   pendingRestore=value.pendingRestore;
   startPlan=value.startPlan||null;
   if(startPlan&&(startPlan.state!=='START_PLAN'||typeof startPlan.startAllowed!=='boolean'
       ||(startPlan.startAllowed&&(!uuid(startPlan.maintenanceId)||!uuid(startPlan.predecessorStartOperationId)||!digest(startPlan.manifestSha256)))))throw Error();
   const signature=JSON.stringify(startPlan);if(signature!==planSignature)el('upgrade-confirm').checked=false;planSignature=signature;
   if(pendingRestore&&(!uuid(pendingRestore.operationId)||!digest(pendingRestore.expectedKeySha256)||pendingRestore.schema!==1))throw Error();
   if(!intent&&pendingRestore)intent=pendingRestore;
   if(!startIntent&&value.pendingStart){
    const v=value.pendingStart;
    if(!uuid(v.operationId)||!uuid(v.restoreOperationId)||!digest(v.expectedKeySha256)||![1,2].includes(v.schema))throw Error();
    startIntent=v;
   }
  } catch (_) {if (epoch !== statusEpoch) return; available=false;statusKey = 'unavailable';}
  render();
  if(!busy&&intent)await original(intent.operationId);
  if(!busy&&startIntent)await readStart();
 }
 async function original(id) {
  if (busy || !uuid(id)) return;
  busy = true; render();
  try {
   const value = await request('original', {operationId:id});
   result = value.operationId === id && value.state === 'SUCCEEDED' && value.action === 'restore'
    && value.resultSource === 'ROOT_ORIGINAL' && digest(value.keySha256) && value.existingReceiptPreserved === true
    ? value : {operationId:id,state:'UNKNOWN'};
   noticeKey = result.state === 'SUCCEEDED' ? 'succeeded' : 'pending';
  } catch (_) {result = {operationId:id,state:'UNKNOWN'}; noticeKey = 'pending';}
  busy = false; render();
 }
 el('backup').addEventListener('change', async () => {
  const epoch = ++fileEpoch; raw = ''; el('password').value = ''; invalidate();
  const file = el('backup').files[0];
  if (!file || file.size <= 0 || file.size > 49152) {noticeKey = 'invalidFile';render();return;}
  try {const value = await file.text(); if (epoch !== fileEpoch) return; raw = value;noticeKey = '';}
  catch (_) {noticeKey = 'invalidFile';}
  render();
 });
 el('password').addEventListener('input', invalidate);
 el('original').addEventListener('input', render);
 el('confirm').addEventListener('change', render);
 el('refresh').addEventListener('click', status);
 el('query-pending').addEventListener('click', () => {if (intent) original(intent.operationId);});
 el('query-original').addEventListener('click', () => original(el('original').value));
 el('inspect').addEventListener('click', async () => {
  if (el('inspect').disabled) return;
  busy = true; invalidate(); const selected = raw;
  try {
   const value = await request('inspect', {backupJson:selected,passphrase:el('password').value});
   if (value.state !== 'INSPECTED' || !digest(value.keySha256) || !uuid(value.backupOperationId)
       || typeof value.restoreAllowed !== 'boolean' || value.keySha256 !== fingerprint) throw Error();
   reviewed = value; reviewedRaw = selected; noticeKey = value.restoreAllowed ? '' : 'mismatch';
  } catch (error) {noticeKey = error.message === 'busy' ? 'busy' : 'mismatch';}
  busy = false; render();
 });
 el('restore').addEventListener('click', async () => {
  if (el('restore').disabled) return;
  const value = {schema:1,operationId:crypto.randomUUID(),expectedKeySha256:reviewed.keySha256};
  busy = true; render();
  try {localStorage.setItem(storeKey,JSON.stringify(value)); if (localStorage.getItem(storeKey) !== JSON.stringify(value)) throw Error(); intent = value;}
  catch (_) {storageFault = true; busy = false; el('password').value = ''; render(); return;}
  const payload = {operationId:value.operationId,expectedKeySha256:value.expectedKeySha256,backupJson:raw,passphrase:el('password').value};
  el('password').value = ''; result = null; invalidate();
  try {
   const received = await request('restore', payload);
   result = received.operationId === value.operationId ? received : {operationId:value.operationId,state:'UNKNOWN'};
   noticeKey = terminal() ? result.state === 'SUCCEEDED' ? 'succeeded' : 'rejected' : 'pending';
  } catch (_) {result = {operationId:value.operationId,state:'UNKNOWN'};noticeKey = 'pending';}
  payload.passphrase = ''; busy = false; available = false; render();await status();
 });
 el('acknowledge').addEventListener('click', () => {
  if (el('acknowledge').disabled) return;
  try {
   const stored = readIntent(); if (!stored || stored.operationId !== intent.operationId) throw Error();
   localStorage.removeItem(storeKey); if (localStorage.getItem(storeKey) !== null) throw Error();
   intent = null;result = null;raw = '';el('backup').value = '';el('password').value = '';invalidate();status();
  } catch (_) {storageFault = true;render();}
 });
 async function readStart() {
  if(busy||!startIntent)return;
  busy=true;render();
  try{startResult=await request('start-original',{operationId:startIntent.operationId});}
  catch(_){startResult=null;}
  busy=false;render();
 }
 el('query-start').addEventListener('click',readStart);
 el('upgrade-confirm').addEventListener('change',render);
 el('start-core').addEventListener('click',async()=>{
  if(el('start-core').disabled)return;
  const maintenance=maintenanceReady();
  const value={schema:maintenance?2:1,operationId:crypto.randomUUID(),restoreOperationId:pendingRestore.operationId,
               expectedKeySha256:pendingRestore.expectedKeySha256};
  if(maintenance)for(const k of ['predecessorStartOperationId','maintenanceId','manifestSha256'])value[k]=startPlan[k];
  busy=true;render();
  try{localStorage.setItem(startStoreKey,JSON.stringify(value));if(localStorage.getItem(startStoreKey)!==JSON.stringify(value))throw Error();startIntent=value;}
  catch(_){storageFault=true;busy=false;render();return;}
  const payload={operationId:value.operationId,restoreOperationId:value.restoreOperationId,expectedKeySha256:value.expectedKeySha256};
  if(maintenance)for(const k of ['predecessorStartOperationId','maintenanceId','manifestSha256'])payload[k]=value[k];
  try{startResult=await request(maintenance?'start-after-maintenance':'start',payload);} 
  catch(_){startResult=null;}
  busy=false;render();
 });
 el('complete').addEventListener('click',async()=>{
  if(el('complete').disabled)return;
  busy=true;render();
  try{
   const value=await request('complete',{operationId:startIntent.operationId});
   if(value.state!=='SUCCEEDED'||value.resultSource!=='ROOT_ORIGINAL'||value.operationId!==startIntent.operationId
      ||value.restoreOperationId!==startIntent.restoreOperationId||value.keySha256!==startIntent.expectedKeySha256)throw Error();
   localStorage.removeItem(startStoreKey);localStorage.removeItem(storeKey);
   if(localStorage.getItem(startStoreKey)!==null||localStorage.getItem(storeKey)!==null)throw Error();
   startIntent=null;startResult=null;intent=null;pendingRestore=null;
  }catch(_){startResult=null;}
  busy=false;render();
 });
 el('language').addEventListener('change', () => {
  language = el('language').value === 'en' ? 'en' : 'zh';document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
  for (const node of document.querySelectorAll('[data-i18n]')) node.textContent = text(node.dataset.i18n);render();
 });
 window.addEventListener('storage', event => {if(event.key===startStoreKey){startIntent=readStartIntent();startResult=null;render();} if (event.key === storeKey) {intent = readIntent();result = null;el('password').value = '';invalidate();}});
 window.addEventListener('pagehide', () => {el('password').value = '';raw = '';});
 el('console').href = `https://${location.hostname.includes(':') ? '[' + location.hostname.replace(/^\[|\]$/g,'') + ']' : location.hostname}/admin/console`;
 intent = readIntent();startIntent=readStartIntent();
 for(const node of document.querySelectorAll('[data-i18n]'))node.textContent=text(node.dataset.i18n);
 render();status();
})();
