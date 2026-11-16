'use strict';
// The shared reservation panel is separate from every key writer and uses only metadata endpoints.
(() => {
 const el=id=>document.getElementById('admission-'+id),handoff=document.body.dataset.view==='handoff';
 const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v);
 const hash=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
 const tokenPattern=/^KURA-HANDOFF-1\.[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.[0-9a-f]{64}$/;
 const store={restore:'yofc.kura.cold-key-recovery.intent.v1',start:'yofc.kura.cold-key-recovery.start.v1'};
 const words={
  zh:{title:'核对原预留',help:'回复丢失后，只按原编号核对。关闭仅适用于尚未发送密钥操作的预留，原编号会永久保留且不再发送。',kind:'原操作类型',restore:'原密钥恢复',start:'Kura 启动',step:'原交接步骤',publish:'发布',continue:'原认证续接（仅核对）',identity:'原操作编号',read:'核对原预留',authorize:'授权关闭此原预留',file:'原加密备份 JSON 文件（必填）',password:'原备份解密口令（必填）',privacy:'仅使用原备份和口令核验授权，不恢复或替换密钥，也不保存口令。',handoffMaterial:'关闭须使用上方输入的原交接授权。备份口令不能代替交接授权。',close:'确认未发送并关闭',acknowledge:'保留原记录并返回原流程',confirmTitle:'关闭此原预留？',confirmHelp:'服务端将核实原请求尚未进入密钥处理，永久阻止此原编号。此操作不会恢复密钥、发布或启动 Kura。',keep:'保留预留',reserved:'原预留已核对。关闭前须核验原授权材料。',unknown:'原结果尚不确定，或已有发送记录。保留原编号，只能继续核对，禁止关闭或重发。',missing:'尚无可确认的原预留。保留原编号，不要重新提交。',terminal:'已有匹配的原结果，请在原流程查询。',notAdmitted:'已确认未发送；完成授权关闭后，才能确认此原记录。',closed:'已确认未发送，原编号已永久保留。可确认此原记录，再返回原流程手动创建新申请。',closedHandoff:'已确认未发送，原编号已永久保留。此原授权不能再次发送该步骤；请在管理端处理原授权，原记录仍保留。',unavailable:'暂时无法核实原预留。保留原编号，重新核对；没有重发密钥请求。',busy:'服务正在处理核验，请稍后重新核对。',invalidFile:'请选择原加密备份 JSON 文件（最大 48 KiB）。',invalidPassword:'口令须为 12–256 个字符。',invalidToken:'请在上方输入完整的原交接授权。',authorizationFailed:'原备份或口令未通过核验，未关闭预留。',storage:'浏览器中的原记录不匹配或无法保存，保留原编号。',returned:'原记录已确认。请返回原恢复或启动流程，手动创建新申请。'},
  en:{title:'Check original reservation',help:'After a lost reply, check only the original ID. Only a confirmed unsent key request can be closed; its original ID is permanently retained and never sent again.',kind:'Original operation type',restore:'Original-key recovery',start:'Kura startup',step:'Original handoff step',publish:'Publication',continue:'Original authenticated continuation (read only)',identity:'Original operation ID',read:'Check original reservation',authorize:'Authorize closing this original reservation',file:'Original encrypted backup JSON file (required)',password:'Original backup passphrase (required)',privacy:'The original backup and passphrase verify authorization only. No key is restored or replaced, and the passphrase is not saved.',handoffMaterial:'Closing requires the original handoff authorization entered above. A backup passphrase cannot replace it.',close:'Confirm not sent and close',acknowledge:'Retain the original record and return',confirmTitle:'Close this original reservation?',confirmHelp:'The server checks that the original request never entered key processing, then permanently blocks its ID. This does not restore keys, publish or start Kura.',keep:'Keep reservation',reserved:'The original reservation is confirmed. Closing requires verification of the original authorization material.',unknown:'The original outcome is unconfirmed or a send record exists. Retain the original ID; closing and resending are blocked.',missing:'No original reservation can be confirmed. Retain the ID and do not resubmit.',terminal:'A matching original result exists. Read it in the original workflow.',notAdmitted:'Confirmed not sent. Complete authorized closure before acknowledging this original record.',closed:'Confirmed not sent; the original ID is permanently retained. Acknowledge this original record, then return to manually make a new request.',closedHandoff:'Confirmed not sent; the original ID is permanently retained. This original authorization cannot send that step again. Retain it for resolution in the management console.',unavailable:'The original reservation could not be confirmed. Retain the ID and check again; no key request was resent.',busy:'Verification is busy. Check the original reservation again later.',invalidFile:'Select the original encrypted backup JSON file (at most 48 KiB).',invalidPassword:'Use a passphrase of 12–256 characters.',invalidToken:'Enter the complete original handoff authorization above.',authorizationFailed:'The original backup or passphrase was not verified. The reservation was not closed.',storage:'The original browser record does not match or cannot be saved. Retain the ID.',returned:'The original record is acknowledged. Return to the original recovery or startup workflow to manually make a new request.'}
 };
 let current=null,busy=false,epoch=0,fileEpoch=0,raw='',proposal=null,noticeKey='';
 const language=()=>document.getElementById('language').value==='en'?'en':'zh';
 const text=key=>words[language()][key]||'';
 const kind=()=>handoff?document.querySelector('input[name=admission-step]:checked').value:document.querySelector('input[name=admission-kind]:checked').value;
 const backendKind=()=>handoff&&kind()==='start'?'handoff-start':kind();
 const notice=key=>{noticeKey=key;el('notice').textContent=text(key);};
 function clearMaterial(){raw='';fileEpoch++;el('backup').value='';el('password').value='';el('backup').setCustomValidity('');el('password').setCustomValidity('');}
 function render(){
  for(const node of el('read-form').querySelectorAll('input,button'))node.disabled=busy||(handoff&&node.id==='admission-reference');
  el('cold-kinds').disabled=handoff||busy;el('handoff-kinds').disabled=!handoff||busy;
  el('progress').hidden=!busy;el('flow').setAttribute('aria-busy',String(busy));
  const allowed=!!current&&current.closeAllowed===true;
  el('close-form').hidden=!allowed;el('close').disabled=busy||!allowed;
  el('backup').disabled=handoff||busy||!allowed;el('password').disabled=handoff||busy||!allowed;
  el('acknowledge').hidden=handoff||!current||current.phase!=='NOT_ADMITTED'||!current.closed;
  el('acknowledge').disabled=busy;el('operation').textContent=current?current.operationId:'';
 }
 function reset(){epoch++;busy=false;current=null;proposal=null;clearMaterial();if(el('confirm').open){el('confirm').returnValue='';el('confirm').close();}notice('');render();}
 function selectStored(){
  if(handoff)return;
  try{const value=JSON.parse(localStorage.getItem(store[kind()]));el('reference').value=value&&uuid(value.operationId)?value.operationId:'';}
  catch(_){el('reference').value='';}
 }
 function validate(value){
  const names=['schema','state','kind','operationId','phase','closeAllowed','closed','expectedKeySha256','restoreOperationId'];
  if(!value||Object.keys(value).some(n=>!names.includes(n))||value.schema!==1||value.state!=='SENDER_ADMISSION'||value.kind!==backendKind()
   ||!uuid(value.operationId)||!['UNKNOWN','NOT_RECORDED','RESERVED','INTAKE','TERMINAL','NOT_ADMITTED'].includes(value.phase)
   ||typeof value.closeAllowed!=='boolean'||typeof value.closed!=='boolean'||(!handoff&&value.operationId!==el('reference').value)
   ||(value.expectedKeySha256!==undefined&&!hash(value.expectedKeySha256))||(value.restoreOperationId!==undefined&&!uuid(value.restoreOperationId))
   ||(value.closed&&value.phase!=='NOT_ADMITTED')||(value.closeAllowed&&!['RESERVED','NOT_ADMITTED'].includes(value.phase)))throw Error();
  return value;
 }
 function authorization(){
  const value=document.getElementById('handoff-token').value;
  if(!tokenPattern.test(value)){document.getElementById('handoff-token').focus();notice('invalidToken');throw Error('invalidToken');}
  return value;
 }
 async function api(command,material={}){
  const body=handoff?{command:'admission-'+command,step:kind(),token:authorization()}:{command,kind:kind(),operationId:el('reference').value,...material};
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
  try{
   const response=await fetch(handoff?'/api/handoff':'/api/admission',{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal,
    headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':document.querySelector('meta[name=kura-recovery-csrf]').content},body:JSON.stringify(body)});
   const raw=await response.text();if(raw.length>65536)throw Error();const value=JSON.parse(raw);
   if(!response.ok||value.error)throw Error(value.error==='BUSY'?'busy':value.error==='BACKUP_REJECTED'?'authorizationFailed':'unavailable');
   return validate(value);
  }finally{clearTimeout(timer);if('passphrase'in body)body.passphrase='';}
 }
 function apply(value){current=value;notice(value.closed?handoff?'closedHandoff':'closed':value.phase==='RESERVED'&&value.closeAllowed?'reserved':value.phase==='NOT_ADMITTED'?'notAdmitted':value.phase==='NOT_RECORDED'?'missing':value.phase==='TERMINAL'?'terminal':'unknown');}
 async function read(){
  if(busy)return;const generation=++epoch;busy=true;current=null;notice('');render();
  try{const value=await api('read');if(generation===epoch)apply(value);}
  catch(error){if(generation===epoch)notice(['busy','invalidToken'].includes(error.message)?error.message:'unavailable');}
  finally{if(generation===epoch){busy=false;render();}}
 }
 function passwordValid(value){const chars=Array.from(value);return chars.length>=12&&chars.length<=256&&!value.includes('\0')&&chars.every(c=>c.length!==1||c.charCodeAt(0)<0xd800||c.charCodeAt(0)>0xdfff)&&new TextEncoder().encode(value).length<=1024;}
 function confirm(){
  if(busy||!current||!current.closeAllowed)return;
  if(!handoff){
   el('backup').setCustomValidity(raw?'':text('invalidFile'));el('password').setCustomValidity(passwordValid(el('password').value)?'':text('invalidPassword'));
   if(!el('close-form').reportValidity())return;
  }else{try{authorization();}catch(_){return;}}
  if(typeof el('confirm').showModal!=='function'){notice('unavailable');return;}
  proposal={generation:epoch,kind:kind(),identity:current.operationId};el('confirm-id').textContent=current.operationId;el('confirm').returnValue='';el('confirm').showModal();
 }
 async function close(selected){
  if(!selected||busy||selected.generation!==epoch||selected.kind!==kind()||!current||selected.identity!==current.operationId)return;
  const generation=++epoch,material=handoff?{}:{backupJson:raw,passphrase:el('password').value};busy=true;current=null;clearMaterial();notice('');render();
  try{const value=await api('close',material);if(value.phase!=='NOT_ADMITTED'||!value.closed)throw Error();if(generation===epoch)apply(value);}
  catch(error){if(generation===epoch)notice(['busy','authorizationFailed','invalidToken'].includes(error.message)?error.message:'unavailable');}
  finally{material.passphrase='';if(generation===epoch){busy=false;render();}}
 }
 el('read-form').addEventListener('submit',event=>{event.preventDefault();read();});
 el('close-form').addEventListener('submit',event=>{event.preventDefault();confirm();});
 el('confirm').addEventListener('close',()=>{const chosen=el('confirm').returnValue,selected=proposal;el('confirm').returnValue='';proposal=null;if(chosen==='close')close(selected);else el('password').value='';});
 el('reference').addEventListener('input',reset);
 for(const field of document.querySelectorAll('input[name=admission-kind],input[name=admission-step]'))field.addEventListener('change',()=>{reset();selectStored();});
 for(const input of [el('backup'),el('password')]){
  input.addEventListener('invalid',()=>input.setAttribute('aria-invalid','true'));
  input.addEventListener('input',()=>{input.setCustomValidity('');input.removeAttribute('aria-invalid');});
 }
 el('backup').addEventListener('change',async()=>{
  const generation=++fileEpoch;raw='';el('password').value='';el('backup').setCustomValidity('');const file=el('backup').files[0];
  if(!file||file.size<1||file.size>49152){el('backup').setCustomValidity(text('invalidFile'));return;}
  try{const value=await file.text();if(generation===fileEpoch)raw=value;}catch(_){if(generation===fileEpoch)el('backup').setCustomValidity(text('invalidFile'));}
 });
 el('acknowledge').addEventListener('click',()=>{
  if(busy||handoff||!current||!current.closed||current.phase!=='NOT_ADMITTED')return;
  try{
   const name=store[kind()],raw=localStorage.getItem(name),saved=JSON.parse(raw);
   const modern=kind()==='start'&&saved&&saved.schema===2;
   const names=kind()==='restore'?'expectedKeySha256,operationId,schema':modern?'expectedKeySha256,maintenanceId,manifestSha256,operationId,predecessorStartOperationId,restoreOperationId,schema':'expectedKeySha256,operationId,restoreOperationId,schema';
   if(!saved||Object.keys(saved).sort().join(',')!==names||(!modern&&saved.schema!==1)
    ||(modern&&(!uuid(saved.maintenanceId)||!uuid(saved.predecessorStartOperationId)||!hash(saved.manifestSha256))))throw Error();
   if(saved.operationId!==current.operationId||saved.expectedKeySha256!==current.expectedKeySha256
    ||(kind()==='start'&&saved.restoreOperationId!==current.restoreOperationId)||localStorage.getItem(name)!==raw)throw Error();
   localStorage.removeItem(name);if(localStorage.getItem(name)!==null)throw Error();current=null;render();notice('returned');window.dispatchEvent(new Event('kura-recovery-intent-changed'));
  }catch(_){notice('storage');}
 });
 function translate(){for(const node of document.querySelectorAll('[data-admission-i18n]'))node.textContent=text(node.dataset.admissionI18n);el('progress').setAttribute('aria-label',text('read'));el('notice').textContent=text(noticeKey);}
 document.getElementById('language').addEventListener('change',translate);
 if(handoff)document.getElementById('handoff-token').addEventListener('input',reset);
 window.addEventListener('storage',event=>{if(Object.values(store).includes(event.key)){reset();selectStored();}});
 window.addEventListener('pagehide',()=>{epoch++;busy=false;current=null;proposal=null;clearMaterial();if(el('confirm').open){el('confirm').returnValue='';el('confirm').close();}render();});
 el('cold-kinds').hidden=handoff;el('handoff-kinds').hidden=!handoff;el('reference-row').hidden=handoff;
 el('backup-material').hidden=handoff;el('handoff-material').hidden=!handoff;
 if(!handoff){try{if(localStorage.getItem(store.start)!==null)document.querySelector('input[name=admission-kind][value=start]').checked=true;}catch(_){}}
 selectStored();translate();render();
})();

(() => {
 if (document.body.dataset.view === 'handoff') return;
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
 window.addEventListener('kura-recovery-intent-changed',()=>{intent=readIntent();startIntent=readStartIntent();result=null;startResult=null;raw='';el('backup').value='';el('password').value='';invalidate();status();});
 window.addEventListener('pagehide', () => {el('password').value = '';raw = '';});
 el('console').href = `https://${location.hostname.includes(':') ? '[' + location.hostname.replace(/^\[|\]$/g,'') + ']' : location.hostname}/admin/console`;
 intent = readIntent();startIntent=readStartIntent();
 for(const node of document.querySelectorAll('[data-i18n]'))node.textContent=text(node.dataset.i18n);
 render();status();
})();

(() => {
 if (document.body.dataset.view !== 'handoff') return;
 const el = id => document.getElementById('handoff-' + id);
 const prefix = 'yofc.kura.handoff.intent.v1.';
 const uuid = v => typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v);
 const hash = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
 const tokenPattern = /^KURA-HANDOFF-1\.[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.[0-9a-f]{64}$/;
 const ids = ['handoffId','preparationId','verificationId','publicationId','startOperationId'];
 const fields = ['schema','operator','ringSha256','cohortSha256','historySha256',...ids];
 const writers = ['publish','continue','start'];
 const csrf = document.querySelector('meta[name=kura-recovery-csrf]').content;
 const words = {
  zh: {
   title:'网关密钥轮换交接',intro:'请先核对浏览器证书与此前保存的证书指纹，再输入从 HTTPS 管理控制台取得的本次交接授权。',token:'本次交接授权',safety:'授权仅保留在本页内存中。刷新或关闭页面前，请保留原授权材料；查询始终使用原申请编号。',query:'核对原交接申请',forget:'清除此页授权',details:'本次申请',identity:'交接申请编号',operator:'已登录操作人',ring:'准备密钥集合指纹（SHA-256）',cohort:'安装组件指纹（SHA-256）',publishTitle:'停止 Kura 并发布准备密钥集合',publishHelp:'确认已保存并核验加密备份后，明确停止 Kura，保留原密钥及旧数据，再发布本次准备的密钥集合。',publish:'确认停机发布',continue:'按原认证回执继续发布',continueHelp:'仅按本次原发布的认证回执继续尚未完成的固定文件，不重新发起发布或停机。',startTitle:'单独申请启动 Kura',startHelp:'原发布回执确认后，可单独申请启动。收到系统启动请求回执后，请回到控制台核对 Kura 是否就绪。',start:'确认申请启动',completeTitle:'确认原请求回执',completeHelp:'核对原发布与启动请求回执后，确认结束本次交接申请。',complete:'确认本次请求回执',console:'返回网关控制台',cancel:'取消',accept:'确认本次操作',loading:'正在读取交接信息',unknown:'结果尚未核定。请保留原申请并继续查询；已保存的操作不会重新提交。',unavailable:'交接信息暂时不可用。请保留原授权与申请编号，稍后继续查询。',recorded:'原交接授权已核对。请逐项确认本次操作。',expired:'原交接授权窗口已关闭。可继续查询原结果，请保留原申请。',recoveryPending:'请先在原密钥恢复页确认已有恢复回执，再继续本次交接。',completed:'原发布和启动请求回执已确认。请在管理控制台核对 Kura 是否就绪。',notRecorded:'尚无本次操作的已确认回执。',published:'原发布回执已确认；启动需要单独申请。',started:'系统已接收原启动请求。请在管理控制台核对 Kura 是否就绪。',storage:'浏览器无法可靠保存本次操作，已禁用新的写入。原申请仍可查询。',changed:'原操作记录已在其他页面变更，请重新查询本次申请。',otherTab:'另一个页面正在处理交接，请查询原申请。',invalid:'请输入本次完整交接授权。',blocked:'本次操作的条件尚未满足，请核对原申请及备份。'
  },
  en: {
   title:'Gateway key rotation handoff',intro:'Compare the browser certificate with your retained certificate fingerprint before entering the handoff authorization from the HTTPS management console.',token:'Original handoff authorization',safety:'Authorization stays in this page memory only. Retain the original authorization material before closing or refreshing. Queries always use the original request.',query:'Check original handoff request',forget:'Clear authorization from this page',details:'Original request',identity:'Handoff request ID',operator:'Authenticated operator',ring:'Prepared key-set fingerprint (SHA-256)',cohort:'Installed component fingerprint (SHA-256)',publishTitle:'Stop Kura and publish the prepared key set',publishHelp:'After saving and verifying the encrypted backup, explicitly stop Kura, retain the original keys and data, and publish this prepared key set.',publish:'Confirm stop and publication',continue:'Continue using the original authenticated receipt',continueHelp:'Continue only the remaining fixed files using the original publication receipt. This does not issue another publication or stop request.',startTitle:'Request Kura startup separately',startHelp:'After the original publication receipt is confirmed, request startup separately. Check Kura readiness in the console after the system accepts the request.',start:'Confirm startup request',completeTitle:'Acknowledge original request receipts',completeHelp:'Check the original publication and startup-request receipts, then acknowledge this handoff request.',complete:'Acknowledge original request receipts',console:'Return to the gateway console',cancel:'Cancel',accept:'Confirm this operation',loading:'Reading handoff information',unknown:'The outcome is unconfirmed. Retain the original request and query it. Saved operations will not be submitted again.',unavailable:'Handoff information is unavailable. Retain the authorization and original request ID and query again later.',recorded:'The original handoff authorization is verified. Confirm each operation separately.',expired:'The original authorization window is closed. Original results remain available; retain the request.',recoveryPending:'Acknowledge the existing original-key recovery receipts on the recovery page before continuing.',completed:'The original publication and startup-request receipts are confirmed. Check Kura readiness in the management console.',notRecorded:'There is no confirmed receipt for this operation.',published:'The original publication receipt is confirmed. Startup requires a separate request.',started:'The system accepted the original startup request. Check Kura readiness in the management console.',storage:'The browser cannot reliably retain this operation. New writes are disabled; original queries remain available.',changed:'Another page changed the original operation record. Query the original request again.',otherTab:'Another page is handling this handoff. Query the original request.',invalid:'Enter the complete original handoff authorization.',blocked:'This operation is not currently allowed. Check the original request and backup.'
  }
 };
 let language = 'zh', authorization = '', current = null, busy = false, stale = false, storageFault = false, epoch = 0, proposal = null, noticeKey = '';
 const observedIntents = new Map();
 const message = key => { noticeKey = key; el('notice').textContent = key ? words[language][key] : ''; };
 const binding = info => Object.fromEntries(fields.map(name => [name, info[name]]));
 const key = command => prefix + current.handoff.handoffId + '.' + command;
 function intent(command) {
  if (!current) return null;
  try {
   const name = key(command), raw = localStorage.getItem(name);
   if (observedIntents.has(name) && observedIntents.get(name) !== raw) throw Error();
   if (raw === null) return null;
   const value = JSON.parse(raw), names = [...fields,'command',...(command === 'continue' ? ['expectedRecoveryReceiptSha256'] : [])];
   if (!value || Object.keys(value).length !== names.length || names.some(name => !Object.hasOwn(value,name))
     || fields.some(name => value[name] !== current.handoff[name]) || value.command !== command
     || (command === 'continue' && !hash(value.expectedRecoveryReceiptSha256))) throw Error();
   observedIntents.set(name,raw); return value;
  } catch (_) { storageFault = true; return null; }
 }
 function platform() { return window.isSecureContext && navigator.locks && typeof navigator.locks.request === 'function' && typeof el('confirm').showModal === 'function'; }
 function allowed(command) {
  if (!current || busy || stale || storageFault || !platform() || current.completed) return false;
  if (command === 'complete') return current.publication.state === 'SUCCEEDED' && current.start.state === 'SUCCEEDED';
  return current.allowed[command] === true && intent(command) === null && !storageFault;
 }
 function render() {
  if (current) for (const command of writers) intent(command);
  el('query').disabled = busy; el('token').disabled = busy; el('forget').disabled = busy;
  el('progress').hidden = !busy; el('details').hidden = !current;
  for (const command of [...writers,'complete']) el(command).disabled = !allowed(command);
  if (current) {
   const info = current.handoff;
   el('id').textContent = info.handoffId; el('operator').textContent = info.operator;
   el('ring').textContent = info.ringSha256; el('cohort').textContent = info.cohortSha256;
   const pendingPublication = current.publication.state === 'UNKNOWN' || !!intent('publish') || !!intent('continue');
   el('publication-state').textContent = words[language][stale ? 'unknown' : current.publication.state === 'SUCCEEDED' ? 'published' : pendingPublication ? 'unknown' : 'notRecorded'];
   el('start-state').textContent = words[language][stale ? 'unknown' : current.start.state === 'SUCCEEDED' ? 'started' : current.start.state === 'UNKNOWN' || !!intent('start') ? 'unknown' : 'notRecorded'];
  }
  if (!busy && (storageFault || (current && !platform()))) message('storage');
 }
 function validate(value) {
  if (!value || value.schema !== 1 || value.state !== 'HANDOFF_STATUS') throw Error();
  const info = value.handoff;
  if (!info || Object.keys(info).length !== 16 || info.schema !== 1 || info.state !== 'GRANT_RECORDED'
    || info.scope !== 'ORIGINAL_AUTHORIZATION_ONLY' || info.startupAuthorized !== false || typeof info.mutationWindowOpen !== 'boolean'
    || ids.some(name => !uuid(info[name])) || new Set(ids.map(name => info[name])).size !== 5
    || ['ringSha256','cohortSha256','historySha256'].some(name => !hash(info[name]))
    || info.handoffId !== authorization.split('.')[1] || typeof info.operator !== 'string') throw Error();
  for (const [name,identity] of [['publication',info.publicationId],['start',info.startOperationId]]) {
   const row = value[name];
   if (!row || row.operationId !== identity || !['UNKNOWN','NOT_RECORDED','SUCCEEDED'].includes(row.state)
     || (row.state === 'SUCCEEDED' && (row.resultSource !== 'ROOT_ORIGINAL' || !hash(row.activeKeySha256)))
     || (row.recoveryReceiptSha256 !== null && !hash(row.recoveryReceiptSha256))) throw Error();
  }
  if (value.start.state === 'SUCCEEDED' && (value.start.scope !== 'SYSTEMD_JOB_ACCEPTED' || !/^\/org\/freedesktop\/systemd1\/job\/[0-9]+$/.test(value.start.jobPath))) throw Error();
  if (value.publication.state === 'SUCCEEDED' && value.start.state === 'SUCCEEDED' && value.publication.activeKeySha256 !== value.start.activeKeySha256) throw Error();
  if (typeof value.completed !== 'boolean' || typeof value.originalRecoveryPending !== 'boolean'
    || writers.some(name => typeof value.allowed[name] !== 'boolean' || typeof value.senderIntents[name] !== 'boolean')) throw Error();
  if (value.allowed.publish && (!info.mutationWindowOpen || value.senderIntents.publish || value.publication.state !== 'NOT_RECORDED')) throw Error();
  if (value.allowed.start && (!info.mutationWindowOpen || value.senderIntents.start || value.publication.state !== 'SUCCEEDED' || value.start.state !== 'NOT_RECORDED')) throw Error();
  if (value.allowed.continue && (value.senderIntents.continue || value.publication.state !== 'UNKNOWN' || !hash(value.publication.recoveryReceiptSha256))) throw Error();
  return value;
 }
 async function api(command, extra = {}) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30000);
  try {
   const response = await fetch('/api/handoff',{method:'POST',credentials:'same-origin',cache:'no-store',signal:controller.signal,
    headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':csrf},body:JSON.stringify({token:authorization,command,...extra})});
   const text = await response.text(); if (!response.ok || text.length > 65536) throw Error();
   return validate(JSON.parse(text));
  } finally { clearTimeout(timer); }
 }
 function apply(value) {
  current = value; stale = false;
  for (const command of writers) intent(command);
  message(value.completed ? 'completed' : value.originalRecoveryPending ? 'recoveryPending' : !value.handoff.mutationWindowOpen ? 'expired'
    : value.publication.state === 'UNKNOWN' || value.start.state === 'UNKNOWN' ? 'unknown' : 'recorded');
 }
 async function query() {
  if (busy) return; const candidate = el('token').value;
  if (!tokenPattern.test(candidate)) { message('invalid'); return; }
  if (authorization !== candidate) { authorization = candidate; current = null; storageFault = false; }
  const generation = ++epoch; busy = true; message(''); render();
  try { const value = await api('query'); if (generation === epoch) apply(value); }
  catch (_) { if (generation === epoch) { stale = true; message('unavailable'); } }
  finally { if (generation === epoch) { busy = false; render(); } }
 }
 function persist(command, extra) {
  if (intent(command) !== null || storageFault) throw Error();
  const value = {...binding(current.handoff),command,...extra}, raw = JSON.stringify(value), name = key(command);
  try {
   localStorage.setItem(name,raw);
   if (localStorage.getItem(name) !== raw) throw Error();
   observedIntents.set(name,raw);
  } catch (_) { storageFault = true; throw Error(); }
 }
 async function forward(selected) {
  if (!selected || busy || !current || JSON.stringify(binding(current.handoff)) !== selected.binding) return;
  const generation = ++epoch; busy = true; message(''); render();
  try {
   await navigator.locks.request('yofc.kura.handoff.forward.v1',{mode:'exclusive',ifAvailable:true},async lock => {
    if (!lock) { if (generation === epoch) { stale = true; message('otherTab'); } return; }
    const fresh = await api('query'); if (generation !== epoch) return;
    if (JSON.stringify(binding(fresh.handoff)) !== selected.binding) throw Error();
    apply(fresh);
    const command = selected.command, extra = command === 'continue' ? {expectedRecoveryReceiptSha256:fresh.publication.recoveryReceiptSha256} : {};
    // The browser records its own immutable intent before the first HTTPS writer
    // request. A timeout or Root/server absence never authorizes a second send.
    if (!fresh.allowed[command] || intent(command) !== null || storageFault
      || (command === 'continue' && extra.expectedRecoveryReceiptSha256 !== selected.receipt)) { message('unknown'); return; }
    persist(command,extra);
    const value = await api(command,extra); if (generation === epoch) apply(value);
   });
  } catch (_) { if (generation === epoch) { stale = true; message('unknown'); } }
  finally { if (generation === epoch) { busy = false; render(); } }
 }
 function confirm(command) {
  if (!allowed(command)) return;
  const dialog = el('confirm'); proposal = {command,binding:JSON.stringify(binding(current.handoff)),receipt:current.publication.recoveryReceiptSha256};
  el('confirm-title').textContent = words[language][command === 'continue' ? 'continue' : command + 'Title'];
  el('confirm-help').textContent = words[language][command === 'continue' ? 'continueHelp' : command + 'Help'];
  el('confirm-id').textContent = current.handoff.handoffId; el('confirm-ring').textContent = current.handoff.ringSha256;
  dialog.returnValue = ''; dialog.showModal();
 }
 function forget() {
  epoch++; authorization = ''; current = null; busy = false; stale = false; storageFault = false; proposal = null;
  el('token').value = ''; message(''); render();
 }
 function translate() {
  language = document.getElementById('language').value === 'en' ? 'en' : 'zh'; document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
  for (const node of document.querySelectorAll('[data-handoff-i18n]')) node.textContent = words[language][node.dataset.handoffI18n];
  document.querySelector('[data-i18n="language"]').textContent = language === 'en' ? 'Language' : '语言';
  document.title = 'Kura · ' + words[language].title; el('progress').setAttribute('aria-label',words[language].loading);
  message(noticeKey); render();
 }
 el('auth').addEventListener('submit',event => { event.preventDefault(); query(); });
 el('forget').addEventListener('click',forget);
 el('token').addEventListener('input',() => { epoch++; authorization = ''; current = null; stale = false; storageFault = false; proposal = null; render(); });
 for (const command of writers) el(command).addEventListener('click',() => confirm(command));
 el('confirm').addEventListener('close',() => {
  const accepted = el('confirm').returnValue === 'accept', selected = proposal;
  el('confirm').returnValue = ''; proposal = null; if (accepted && selected) forward(selected);
 });
 el('complete').addEventListener('click',async () => {
  if (!allowed('complete')) return; const generation = ++epoch; busy = true; message(''); render();
  try { const value = await api('complete'); if (generation === epoch) apply(value); }
  catch (_) { if (generation === epoch) { stale = true; message('unavailable'); } }
  finally { if (generation === epoch) { busy = false; render(); } }
 });
 document.getElementById('language').addEventListener('change',translate);
 window.addEventListener('storage',event => {
  const identity = authorization.split('.')[1];
  if (identity && (event.key === null || event.key.startsWith(prefix + identity + '.'))) {
   if (event.key === null || event.newValue === null || event.oldValue !== null && event.oldValue !== event.newValue) storageFault = true;
   stale = true; message('changed'); render();
  }
 });
 window.addEventListener('pagehide',forget);
 const consoleUrl = new URL('/admin/console',location.href); consoleUrl.port = ''; el('console').href = consoleUrl.href;
 translate();
})();
