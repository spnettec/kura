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
  const names=['schema','state','kind','operationId','phase','closeAllowed','closed','expectedKeySha256','expectedRingSha256','restoreOperationId','startSchema','predecessorStartOperationId','maintenanceId','manifestSha256'];
  if(!value||Object.keys(value).some(n=>!names.includes(n))||value.schema!==1||value.state!=='SENDER_ADMISSION'||value.kind!==backendKind()
   ||!uuid(value.operationId)||!['UNKNOWN','NOT_RECORDED','RESERVED','INTAKE','TERMINAL','NOT_ADMITTED'].includes(value.phase)
   ||typeof value.closeAllowed!=='boolean'||typeof value.closed!=='boolean'||(!handoff&&value.operationId!==el('reference').value)
   ||(value.expectedKeySha256!==undefined&&!hash(value.expectedKeySha256))||(value.restoreOperationId!==undefined&&!uuid(value.restoreOperationId))
   ||(value.expectedRingSha256!==undefined&&(value.kind!=='restore'||!hash(value.expectedRingSha256)))
   ||(value.closed&&value.phase!=='NOT_ADMITTED')||(value.closeAllowed&&!['RESERVED','NOT_ADMITTED'].includes(value.phase)))throw Error();
  if(value.kind==='start'&&value.phase!=='NOT_RECORDED'){
   if(![1,2].includes(value.startSchema))throw Error();
   const extra=['predecessorStartOperationId','maintenanceId','manifestSha256'];
   if(value.startSchema===2?(!uuid(value.predecessorStartOperationId)||!uuid(value.maintenanceId)||!hash(value.manifestSha256)):extra.some(n=>n in value))throw Error();
  }else if(['startSchema','predecessorStartOperationId','maintenanceId','manifestSha256'].some(n=>n in value))throw Error();
  return value;
 }
 function authorization(){
  const value=document.getElementById('handoff-token').value;
  if(!tokenPattern.test(value)){document.getElementById('handoff-token').focus();notice('invalidToken');throw Error('invalidToken');}
  return value;
 }
 async function api(command,material={}){
  const body=handoff?{command:'admission-'+command,step:kind(),token:authorization()}:{command,kind:kind(),operationId:el('reference').value,...material};
  if(!handoff){
   const saved=JSON.parse(localStorage.getItem(store[kind()]));
   if(saved?.operationId===body.operationId&&hash(saved.namespaceSha256))body.expectedNamespaceSha256=saved.namespaceSha256;
  }
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
  try{
   const response=await fetch(handoff?'/api/handoff':'/api/admission',{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal,
    headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':document.querySelector('meta[name=kura-recovery-csrf]').content},body:JSON.stringify(body)});
   const raw=await response.text();if(raw.length>65536)throw Error();const value=JSON.parse(raw);
   if(!response.ok||value.error)throw Error(value.error==='BUSY'?'busy':value.error==='BACKUP_REJECTED'?'authorizationFailed':'unavailable');
   return validate(value);
  }finally{clearTimeout(timer);if('passphrase'in body)body.passphrase='';}
 }
 function apply(value){current=value;notice(value.closed?handoff?'closedHandoff':'closed':value.phase==='RESERVED'&&value.closeAllowed?'reserved':value.phase==='NOT_ADMITTED'&&value.closeAllowed?'notAdmitted':value.phase==='NOT_RECORDED'?'missing':value.phase==='TERMINAL'?'terminal':'unknown');}
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
   const generation=kind()==='restore'&&saved?.schema===2;
   const names=['schema','operationId','expectedKeySha256'];
   if(kind()==='start')names.push('restoreOperationId');
   if(modern)names.push('maintenanceId','manifestSha256','predecessorStartOperationId');
   if(generation)names.push('expectedRingSha256','namespaceSha256');
   if(kind()==='start'&&hash(saved?.namespaceSha256))names.push('namespaceSha256');
   if(!saved||Object.keys(saved).sort().join(',')!==names.sort().join(',')||(!modern&&!generation&&saved.schema!==1)
    ||(generation&&(!hash(saved.namespaceSha256)||!hash(saved.expectedRingSha256)||saved.expectedRingSha256!==current.expectedRingSha256))
    ||(modern&&(!uuid(saved.maintenanceId)||!uuid(saved.predecessorStartOperationId)||!hash(saved.manifestSha256))))throw Error();
   if(saved.operationId!==current.operationId||saved.expectedKeySha256!==current.expectedKeySha256
    ||(kind()==='start'&&(saved.restoreOperationId!==current.restoreOperationId||saved.schema!==current.startSchema
      ||(modern&&['predecessorStartOperationId','maintenanceId','manifestSha256'].some(n=>saved[n]!==current[n]))))
    ||localStorage.getItem(name)!==raw)throw Error();
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
   const names=['expectedKeySha256','operationId','restoreOperationId','schema'];
   if(modern)names.push('maintenanceId','manifestSha256','predecessorStartOperationId');
   if(v&&digest(v.namespaceSha256))names.push('namespaceSha256');
   if(!v||Object.keys(v).sort().join(',')!==names.sort().join(',')||(!modern&&v.schema!==1)||!uuid(v.operationId)||!uuid(v.restoreOperationId)||!digest(v.expectedKeySha256)
      ||(modern&&(!uuid(v.maintenanceId)||!uuid(v.predecessorStartOperationId)||!digest(v.manifestSha256))))throw Error();
   return v;
  } catch(_){storageFault=true;return null;}
 }
 function startTerminal() {
  return startIntent&&sameRoot(startIntent)&&startResult&&startResult.operationId===startIntent.operationId
   &&startResult.restoreOperationId===startIntent.restoreOperationId&&startResult.keySha256===startIntent.expectedKeySha256
   &&startResult.state==='SUCCEEDED'&&startResult.action===(startIntent.schema===2?'core-start-after-maintenance':'core-start')&&startResult.resultSource==='ROOT_ORIGINAL'
   &&(startIntent.schema!==2||['maintenanceId','predecessorStartOperationId','manifestSha256'].every(k=>startIntent[k]===startResult[k]))
   &&startResult.scope==='SYSTEMD_JOB_ACCEPTED';
 }
 Object.assign(words.zh,{upgradeConfirm:'我确认安装升级已停止 Kura，并为本次维护创建新的启动请求。',startAfterMaintenance:'升级后启动 Kura'});
 Object.assign(words.en,{upgradeConfirm:'I confirm the package upgrade stopped Kura and authorize a new start request for this maintenance.',startAfterMaintenance:'Start Kura after upgrade'});
 Object.assign(words.zh,{
  activeFingerprint:'原活跃钥指纹（SHA-256）',ringFingerprint:'原密钥集合指纹（SHA-256）',
  generationMissing:'活跃钥和密钥集合都缺失。请核验原多代备份。',
  activeMissing:'活跃钥缺失，原密钥集合仍在。请核验原多代备份。',
  ringMissing:'原密钥集合缺失，活跃钥仍在。请核验原多代备份。',
  generationReady:'活跃钥和原密钥集合均已就绪。',
  generationReviewed:'多代备份的两个指纹均匹配。密钥数量',
  unresolved:'仍有原操作待确认。请按原编号查询。',
  rootMismatch:'当前网关与浏览器保存的原操作不配对。请回到原网关查询。',
  restoreSet:'恢复原密钥集合',restoreTitle:'恢复网关原密钥集合？',
  restoreHelp:'确认两个指纹与原备份一致。网关只补回缺失的凭据。恢复后可单独启动 Kura。',
  cancelRestore:'取消',restoreAccept:'确认恢复',
  generationRestored:'原密钥集合恢复已完成，原回执已确认。',
  invalidPassword:'请输入 12–256 个字符的备份解密口令。',startFenced:'启动尚未获准。请核对原启动授权。'
 });
 Object.assign(words.en,{
  activeFingerprint:'Retained active key fingerprint (SHA-256)',ringFingerprint:'Retained key-set fingerprint (SHA-256)',
  generationMissing:'The active key and key set are both missing. Inspect your original multi-generation backup.',
  activeMissing:'The active key is missing. The original key set is still present. Inspect your original multi-generation backup.',
  ringMissing:'The original key set is missing. The active key is still present. Inspect your original multi-generation backup.',
  generationReady:'The active key and original key set are ready.',
  generationReviewed:'Both fingerprints match the multi-generation backup. Keys in the backup',
  unresolved:'An original operation is still unconfirmed. Query its original ID.',
  rootMismatch:'The saved operation belongs to a different gateway. Return to the original gateway to query it.',
  restoreSet:'Restore the original key set',restoreTitle:'Restore this gateway’s original key set?',
  restoreHelp:'Check both fingerprints against the original backup. The gateway only restores missing credentials. You can start Kura separately after recovery.',
  cancelRestore:'Cancel',restoreAccept:'Confirm restoration',
  generationRestored:'The original key set was restored and its receipt was confirmed.',
  invalidPassword:'Enter a backup passphrase of 12–256 characters.',
  startFenced:'Startup is unavailable. Check the original startup authorization.'
 });
 function maintenanceReady(){return startTerminal()&&startPlan&&startPlan.startAllowed===true
  &&startPlan.predecessorStartOperationId===startIntent.operationId&&pendingRestore
  &&pendingRestore.operationId===startIntent.restoreOperationId&&currentCredentials(pendingRestore)
  &&pendingRestore.expectedKeySha256===startIntent.expectedKeySha256;}
 let language = 'zh', noticeKey = '', statusKey = '', raw = '', reviewed = null, reviewedRaw = '';
 let available = false, keyReady = false, fingerprint = '', generation = null, busy = false, storageFault = false;
 let intent = null, result = null, statusEpoch = 0, fileEpoch = 0;
 let restoreProposal = null;
 const text = key => words[language][key] || '';
 const generationFormat = 'yofc-kura-gateway-key-generations-v1';
 const scopeOf = value => value?.namespaceSha256 ? {expectedNamespaceSha256:value.namespaceSha256} : {};
 const sameRoot = value => !value?.namespaceSha256 || generation?.namespaceSha256 === value.namespaceSha256;
 const scoped = value => generation ? {...value,namespaceSha256:generation.namespaceSha256} : value;
 const rootMismatch = () => available && (!sameRoot(intent) || !sameRoot(startIntent));
 const currentCredentials = value => value?.expectedKeySha256 === fingerprint
    && (value.expectedRingSha256 ?? null) === (generation?.ringSha256 ?? null);
 function announce(id,value) {
  if(el(id).textContent!==value)el(id).textContent=value;
 }
 function intentFields(value, requireNamespace = false) {
  if (!value || !uuid(value.operationId) || !digest(value.expectedKeySha256)) return false;
  const names = ['expectedKeySha256','operationId','schema'];
  if (value.schema === 2) {
   if (!digest(value.expectedRingSha256)) return false;
   names.push('expectedRingSha256');
   if (requireNamespace) {
    if (!digest(value.namespaceSha256)) return false;
    names.push('namespaceSha256');
   }
  } else if (value.schema !== 1) return false;
  return Object.keys(value).sort().join(',') === names.sort().join(',');
 }
 function readIntent() {
  try {
   const value = localStorage.getItem(storeKey);
   if (value === null) return null;
   const parsed = JSON.parse(value);
   if (!intentFields(parsed,true)) throw Error();
   return parsed;
  } catch (_) {storageFault = true; return null;}
 }
 function restoreReceipt(value, binding) {
  if (!value || value.state !== 'SUCCEEDED' || value.resultSource !== 'ROOT_ORIGINAL'
      || value.existingReceiptPreserved !== true || !uuid(value.operationId)) return false;
  if (binding && (!sameRoot(binding) || value.operationId !== binding.operationId)) return false;
  if (value.action === 'generation-restore') {
   return digest(value.activeKeySha256) && digest(value.ringSha256)
    && typeof value.activeKeyRestored === 'boolean' && typeof value.keyringRestored === 'boolean'
    && (!binding || binding.schema === 2 && value.activeKeySha256 === binding.expectedKeySha256
        && value.ringSha256 === binding.expectedRingSha256);
  }
  return value.action === 'restore' && digest(value.keySha256) && typeof value.keyChanged === 'boolean'
   && (!binding || binding.schema === 1 && value.keySha256 === binding.expectedKeySha256);
 }
 function terminal() {
  return intent && sameRoot(intent) && result && result.operationId === intent.operationId
   && (restoreReceipt(result,intent)
    || (result.state === 'REJECTED' && result.resultSource === 'SERVER_PREFLIGHT' && typeof result.error === 'string'));
 }
 function render() {
  const mismatch = rootMismatch();
  const draft = available && !keyReady && !busy && !intent && !storageFault && !mismatch;
  for (const id of ['backup','password']) el(id).disabled = !draft;
  el('inspect').disabled = !draft;
  el('inspect-form').setAttribute('aria-busy',String(busy));
  const canRestore = draft && reviewed?.restoreAllowed && reviewedRaw === raw;
  el('confirm-row').hidden = !!generation;
  el('confirm').disabled = !canRestore || !!generation;
  el('restore').textContent = text(generation ? 'restoreSet' : 'restore');
  el('restore').disabled = !canRestore || (!generation && !el('confirm').checked) || !password(el('password').value);
  el('refresh').disabled = busy; el('query-pending').disabled = busy || !intent || !sameRoot(intent);
  el('acknowledge').disabled = busy || storageFault || mismatch || !terminal();
  el('original').disabled = busy || mismatch; el('query-original').disabled = busy || mismatch || !uuid(el('original').value);
  el('operation').textContent = intent ? intent.operationId : result && uuid(result.operationId) ? result.operationId : '';
  el('fingerprint').textContent = fingerprint;
  el('fingerprint-label').textContent = text(generation ? 'activeFingerprint' : 'fingerprint');
  el('generation-status').hidden = !generation;
  el('ring-fingerprint').textContent = generation?.ringSha256 ?? '';
  announce('status',text(statusKey));
  announce('notice',text(mismatch ? 'rootMismatch' : storageFault ? 'storage' : intent && !terminal() ? 'pending' : noticeKey));
  const initial=!startIntent&&currentCredentials(pendingRestore)&&restoreReceipt(result,pendingRestore)
   &&(result.keyChanged===true||result.activeKeyRestored===true||result.keyringRestored===true);
  const maintenance=maintenanceReady();
  el('upgrade-confirm-row').hidden=!maintenance;el('upgrade-confirm').disabled=busy||!maintenance;
  el('start-core').textContent=text(maintenance?'startAfterMaintenance':'startCore');
  el('start-core').disabled=busy||storageFault||mismatch||!available||!keyReady
   ||(generation&&!generation.startAllowed)||!(initial||(maintenance&&el('upgrade-confirm').checked));
  el('query-start').disabled=busy||!startIntent||!sameRoot(startIntent);
  el('complete').disabled=busy||storageFault||mismatch||!startTerminal();
  el('start-operation').textContent=startIntent?startIntent.operationId:'';
  announce('start-notice',startIntent?text(startTerminal()?'startAccepted':'startPending')
   : initial&&generation&&!generation.startAllowed?text('startFenced'):'');
  const review = reviewed && (reviewed.restoreAllowed
   ? generation ? `${text('generationReviewed')} ${reviewed.keyCount}` : `${text('reviewed')} ${reviewed.keySha256}`
   : text(reviewed.restoreBlockedByUnresolvedOperation ? 'unresolved' : 'mismatch'));
  announce('review',review || '');
 }
 function invalidate() {
  reviewed = null; reviewedRaw = ''; restoreProposal = null; el('confirm').checked = false;
  if(el('restore-dialog').open)el('restore-dialog').close();
  render();
 }
 async function request(endpoint, value) {
  const response = await fetch('/api/' + endpoint, {method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',
   headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':csrf},body:JSON.stringify(value)});
  const data = await response.json();
  if (!response.ok || !data || data.schema !== 1 || (data.error && data.state !== 'REJECTED')) throw Error(data && data.error === 'BUSY' ? 'busy' : 'unavailable');
  return data;
 }
 async function status() {
  const epoch = ++statusEpoch; available = false; keyReady = false; fingerprint = ''; generation = null; invalidate();
  try {
   const value = await request('status', {});
   if (epoch !== statusEpoch) return;
   if (value.state !== 'STATUS' || !digest(value.keySha256) || typeof value.keyReady !== 'boolean') throw Error();
   if (value.generation !== undefined) {
    const g = value.generation;
    if (!g || !digest(g.ringSha256) || !digest(g.namespaceSha256) || g.activeKeySha256 !== value.keySha256
        || typeof g.activeKeyReady !== 'boolean' || typeof g.keyringReady !== 'boolean' || typeof g.startAllowed !== 'boolean'
        || value.keyReady !== (g.activeKeyReady && g.keyringReady)) throw Error();
    generation = g;
   }
   available = true; keyReady = value.keyReady; fingerprint = value.keySha256; statusKey = keyReady ? 'ready' : 'missing';
   if (generation) {
    statusKey = keyReady ? 'generationReady' : generation.activeKeyReady ? 'ringMissing'
       : generation.keyringReady ? 'activeMissing' : 'generationMissing';
   }
   const pending=value.pendingRestore;
   if(pending&&!intentFields(pending))throw Error();
   pendingRestore=pending&&currentCredentials(pending)?scoped(pending):null;
   startPlan=value.startPlan||null;
   if(startPlan&&(startPlan.state!=='START_PLAN'||typeof startPlan.startAllowed!=='boolean'
       ||(startPlan.startAllowed&&(!uuid(startPlan.maintenanceId)||!uuid(startPlan.predecessorStartOperationId)||!digest(startPlan.manifestSha256)))))throw Error();
   const signature=JSON.stringify(startPlan);if(signature!==planSignature)el('upgrade-confirm').checked=false;planSignature=signature;
   if(!intent&&pendingRestore)intent=pendingRestore;
   if(!startIntent&&value.pendingStart){
    const v=value.pendingStart;
    if(!uuid(v.operationId)||!uuid(v.restoreOperationId)||!digest(v.expectedKeySha256)||![1,2].includes(v.schema))throw Error();
    if (!generation || v.restoreOperationId===pendingRestore?.operationId)startIntent=scoped(v);
   }
  } catch (_) {if (epoch !== statusEpoch) return; available=false;statusKey = 'unavailable';}
  render();
  if(!busy&&intent&&!terminal())await original(intent.operationId);
  if(!busy&&startIntent)await readStart();
 }
 async function original(id) {
  if (busy || rootMismatch() || !uuid(id)) return;
  const binding = intent?.operationId===id ? intent : pendingRestore?.operationId===id ? pendingRestore : null;
  if(!sameRoot(binding))return;
  busy = true; render();
  try {
   const value = await request('original', {operationId:id,...scopeOf(binding || scoped({}))});
   result = value.operationId === id && restoreReceipt(value,binding)
    ? value : {operationId:id,state:'UNKNOWN'};
   noticeKey = result.state === 'SUCCEEDED' ? result.action==='generation-restore' ? 'generationRestored' : 'succeeded' : 'pending';
  } catch (_) {result = {operationId:id,state:'UNKNOWN'}; noticeKey = 'pending';}
  busy = false; render();
 }
 el('backup').addEventListener('change', async () => {
  const epoch = ++fileEpoch; raw = ''; el('password').value = '';
  el('backup').setCustomValidity('');el('password').setCustomValidity('');invalidate();
  const file = el('backup').files[0];
  if (!file || file.size <= 0 || file.size > 49152) {noticeKey = 'invalidFile';render();return;}
  try {
   const value = await file.text();
   if (epoch !== fileEpoch) return;
   raw = value;el('backup').setCustomValidity('');noticeKey = '';
  }
  catch (_) {noticeKey = 'invalidFile';}
  render();
 });
 el('password').addEventListener('input',()=>{el('password').setCustomValidity('');invalidate();});
 el('original').addEventListener('input', render);
 el('confirm').addEventListener('change', render);
 el('refresh').addEventListener('click', status);
 el('query-pending').addEventListener('click', () => {if (intent) original(intent.operationId);});
 el('query-original').addEventListener('click', () => original(el('original').value));
 el('inspect-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (el('inspect').disabled) return;
  el('backup').setCustomValidity(raw ? '' : text('invalidFile'));
  el('password').setCustomValidity(password(el('password').value) ? '' : text('invalidPassword'));
  if(!el('inspect-form').reportValidity())return;
  busy = true; invalidate(); const selected = raw;
  try {
   const value = await request('inspect', {backupJson:selected,passphrase:el('password').value});
   if (value.state !== 'INSPECTED' || !digest(value.keySha256) || !uuid(value.backupOperationId)
       || typeof value.restoreAllowed !== 'boolean' || value.keySha256 !== fingerprint) throw Error();
   if (generation) {
    if (value.format !== generationFormat || value.ringSha256 !== generation.ringSha256
        || typeof value.sameDeviceKey !== 'boolean' || value.activeKeyReady !== generation.activeKeyReady
        || value.keyringReady !== generation.keyringReady || !Number.isInteger(value.keyCount)
        || value.keyCount < 2 || value.keyCount > 8
        || typeof value.restoreBlockedByUnresolvedOperation !== 'boolean'
        || (value.restoreAllowed && (!value.sameDeviceKey || value.restoreBlockedByUnresolvedOperation))) throw Error();
   } else if (value.format === generationFormat) throw Error();
   reviewed = value; reviewedRaw = selected; noticeKey = value.restoreAllowed ? '' : 'mismatch';
  } catch (error) {noticeKey = error.message === 'busy' ? 'busy' : 'mismatch';}
  busy = false; render();
 });
 async function persist(key,value,predecessor=null) {
  const save = () => {
   if (!sameRoot(value)) throw Error();
   const saved = localStorage.getItem(key);
   if(saved!==null&&(!predecessor||JSON.parse(saved)?.operationId!==predecessor))throw Error();
   const serialized=JSON.stringify(value);
   localStorage.setItem(key,serialized);
   if (localStorage.getItem(key)!==serialized) throw Error();
  };
  if(value.namespaceSha256){
   if(typeof navigator.locks?.request!=='function')throw Error();
   await navigator.locks.request(key,{ifAvailable:true},lock=>{if(!lock)throw Error();save();});
  }else save();
 }
 async function submitRestore() {
  if (el('restore').disabled) return;
  const pair = generation ? {expectedRingSha256:reviewed.ringSha256} : {};
  const value = scoped({schema:generation ? 2 : 1,operationId:crypto.randomUUID(),expectedKeySha256:reviewed.keySha256,...pair});
  const payload = {operationId:value.operationId,expectedKeySha256:value.expectedKeySha256,
   ...pair,...scopeOf(value),backupJson:raw,passphrase:el('password').value};
  busy = true; render();
  try {await persist(storeKey,value); intent = value;}
  catch (_) {storageFault = true; busy = false; payload.passphrase='';el('password').value = ''; render(); return;}
  el('password').value = '';el('backup').value='';raw='';result = null; invalidate();
  try {
   const received = await request('restore', payload);
   result = received.operationId === value.operationId ? received : {operationId:value.operationId,state:'UNKNOWN'};
   noticeKey = terminal() ? result.state === 'SUCCEEDED'
    ? result.action==='generation-restore' ? 'generationRestored' : 'succeeded' : 'rejected' : 'pending';
  } catch (_) {result = {operationId:value.operationId,state:'UNKNOWN'};noticeKey = 'pending';}
  payload.passphrase = ''; busy = false; available = false; render();await status();
 }
 el('restore').addEventListener('click', () => {
  if (el('restore').disabled) return;
  if (!generation) {submitRestore();return;}
  const dialog=el('restore-dialog');
  if(typeof dialog.showModal!=='function'){noticeKey='unavailable';render();return;}
  restoreProposal=reviewed;
  el('confirm-key').textContent=reviewed.keySha256;
  el('confirm-ring').textContent=reviewed.ringSha256;
  dialog.returnValue='';
  dialog.showModal();
 });
 el('restore-dialog').addEventListener('close',()=>{
  const dialog=el('restore-dialog');
  const confirmed=dialog.returnValue==='restore'&&restoreProposal&&restoreProposal===reviewed;
  dialog.returnValue='';restoreProposal=null;
  if(confirmed)submitRestore();
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
  if(busy||rootMismatch()||!startIntent||!sameRoot(startIntent))return;
  busy=true;render();
  try{startResult=await request('start-original',{operationId:startIntent.operationId,...scopeOf(startIntent)});}
  catch(_){startResult=null;}
  busy=false;render();
 }
 el('query-start').addEventListener('click',readStart);
 el('upgrade-confirm').addEventListener('change',render);
 el('start-core').addEventListener('click',async()=>{
  if(el('start-core').disabled)return;
  const maintenance=maintenanceReady();
  const value=scoped({schema:maintenance?2:1,operationId:crypto.randomUUID(),restoreOperationId:pendingRestore.operationId,
                     expectedKeySha256:pendingRestore.expectedKeySha256});
  if(maintenance)for(const k of ['predecessorStartOperationId','maintenanceId','manifestSha256'])value[k]=startPlan[k];
  busy=true;render();
  try{await persist(startStoreKey,value,maintenance?startIntent.operationId:null);startIntent=value;}
  catch(_){storageFault=true;busy=false;render();return;}
  const payload={operationId:value.operationId,restoreOperationId:value.restoreOperationId,
                 expectedKeySha256:value.expectedKeySha256,...scopeOf(value)};
  if(maintenance)for(const k of ['predecessorStartOperationId','maintenanceId','manifestSha256'])payload[k]=value[k];
  try{startResult=await request(maintenance?'start-after-maintenance':'start',payload);} 
  catch(_){startResult=null;}
  busy=false;render();
 });
 el('complete').addEventListener('click',async()=>{
  if(el('complete').disabled)return;
  busy=true;render();
  try{
   const value=await request('complete',{operationId:startIntent.operationId,...scopeOf(startIntent)});
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
 window.addEventListener('pagehide', () => {el('password').value = '';raw = '';invalidate();});
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
 Object.assign(words.zh,{revoke:'撤销未使用的交接授权',revokeTitle:'永久撤销此未使用的交接授权？',revokeHelp:'仅在发布和启动均未进入处理时，永久撤销旧授权和固定编号。保留原准备、备份核验和全部记录；返回原控制台后由原管理员手动重新签发。',revoked:'旧授权已撤销，固定编号已永久禁用。原准备、备份核验和记录仍保留，请返回原控制台手动重新签发。',revoking:'撤销尚未完成。保留原授权，可再次点击完成撤销；不会重新发布或启动。'});
 Object.assign(words.en,{revoke:'Revoke unused handoff authorization',revokeTitle:'Permanently revoke this unused handoff authorization?',revokeHelp:'Only publication and startup that never entered processing can be revoked. Old authorization and fixed IDs are permanently blocked. Preparation, backup verification and all records remain. Return to the original console for the original administrator to explicitly reissue.',revoked:'Old authorization and fixed IDs are permanently blocked. Preparation, backup verification and records remain. Return to the original console to explicitly reissue.',revoking:'Revocation is incomplete. Retain the original authorization and explicitly finish revocation. Publication and startup are not resent.'});
 Object.assign(words.zh,{renew:'续期原首次启动授权',renewHelp:'发布已确认且尚未申请启动时，可单独续期原首次启动授权15分钟。保留原启动编号；续期不会启动Kura，也不允许再次发布。','start-renewTitle':'续期原首次启动授权？','start-renewHelp':'核对原发布回执、当前密钥集合和原启动编号后，另存15分钟的首次启动授权。全部原记录保留；续期后仍须单独确认启动。',renewed:'原首次启动授权已续期。请单独确认原启动请求；发布不会重发。',renewalIdentity:'原续期申请编号',leaseSucceeded:'原续期已确认',leaseClosed:'原续期预留已确认未受理，编号保留',closeRenewal:'确认未受理并关闭原续期预留','renewal-closeTitle':'关闭此原续期预留？','renewal-closeHelp':'仅在Root确认原续期尚未受理时永久关闭此编号。保留原记录，不会续期、发布或启动Kura。之后可手动创建新的续期申请。'});
 Object.assign(words.en,{renew:'Renew original first-start authorization',renewHelp:'After publication is confirmed and before startup is requested, renew only the original first-start authorization for 15 minutes. The original startup ID is retained. Renewal does not start Kura or permit another publication.','start-renewTitle':'Renew the original first-start authorization?','start-renewHelp':'After checking the original publication receipt, current key set and fixed startup ID, retain a separate 15-minute first-start authorization. All originals remain. Startup still requires separate confirmation.',renewed:'The original first-start authorization is renewed. Confirm startup separately; publication is not resent.',renewalIdentity:'Original renewal request ID',leaseSucceeded:'Original renewal confirmed',leaseClosed:'Original renewal was not admitted; its ID is retained',closeRenewal:'Confirm not admitted and close original renewal reservation','renewal-closeTitle':'Close this original renewal reservation?','renewal-closeHelp':'Permanently close this ID only after Root confirms the original renewal was not admitted. All originals remain. This does not renew, publish or start Kura. A new renewal can then be created manually.'});
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
 function localRenewals() {
  if (!current) return [];
  const result=[], start=key('renewal')+'.';
  try {
   for (let i=0;i<localStorage.length;i++) {
    const name=localStorage.key(i); if (!name?.startsWith(start)) continue;
    const raw=localStorage.getItem(name), value=JSON.parse(raw), names=[...fields,'command','operationId','expectedPublicationSha256'];
    if (!value || Object.keys(value).length!==names.length || names.some(k=>!Object.hasOwn(value,k))
      || fields.some(k=>value[k]!==current.handoff[k]) || value.command!=='start-renew' || !uuid(value.operationId)
      || name!==start+value.operationId || ids.some(k=>current.handoff[k]===value.operationId) || !hash(value.expectedPublicationSha256)
      || observedIntents.has(name) && observedIntents.get(name)!==raw) throw Error();
    observedIntents.set(name,raw); result.push(value); if(result.length>256)throw Error();
   }
  } catch (_) {storageFault=true;}
  return result;
 }
 function unsettledLocalRenewal() {
  return localRenewals().some(value=>!current.startRenewals.some(row=>row.operationId===value.operationId&&row.expectedPublicationSha256===value.expectedPublicationSha256
    && (row.state==='SUCCEEDED' && row.resultSource==='ROOT_ORIGINAL' || row.state==='NOT_ADMITTED' && row.resultSource==='ROOT_ADMISSION_CLOSED' && row.closed)));
 }
 function persistRenewal(identity,publication) {
  const name=key('renewal')+'.'+identity, value={...binding(current.handoff),command:'start-renew',operationId:identity,expectedPublicationSha256:publication};
  try {
   if(localStorage.getItem(name)!==null)throw Error();
   const raw=JSON.stringify(value);localStorage.setItem(name,raw);if(localStorage.getItem(name)!==raw)throw Error();observedIntents.set(name,raw);
  } catch (_) {storageFault=true;throw Error();}
 }
 function platform() { return window.isSecureContext && navigator.locks && typeof navigator.locks.request === 'function' && typeof crypto.randomUUID==='function' && typeof el('confirm').showModal === 'function'; }
 function allowed(command,identity) {
  if (!current || busy || stale || storageFault || !platform() || current.completed) return false;
  if (command === 'revoke') return current.revocationAllowed && !current.retired;
  if (current.retired || current.handoff.state !== 'GRANT_RECORDED') return false;
  if (command==='renewal-close')return current.startRenewals.some(row=>row.operationId===identity && row.closeAllowed && row.state!=='SUCCEEDED');
  if (command === 'complete') return current.publication.state === 'SUCCEEDED' && current.start.state === 'SUCCEEDED';
  if (command==='start-renew')return current.renewalAllowed && !unsettledLocalRenewal() && !storageFault;
  if (command==='start' && unsettledLocalRenewal())return false;
  return current.allowed[command] === true && intent(command) === null && !storageFault;
 }
 function render() {
  if (current) {for (const command of writers) intent(command);localRenewals();}
  el('query').disabled = busy; el('token').disabled = busy; el('forget').disabled = busy;
  el('progress').hidden = !busy; el('details').hidden = !current;
  for (const command of [...writers,'complete','revoke','start-renew']) el(command).disabled = !allowed(command);
  el('renewals').replaceChildren();
  if(current)for(const row of current.startRenewals){
   const item=document.createElement('li'),code=document.createElement('code');code.textContent=row.operationId;
   item.append(code,document.createTextNode(' — '+words[language][row.state==='SUCCEEDED'?'leaseSucceeded':row.state==='NOT_ADMITTED'?'leaseClosed':'unknown']));
   if(row.closeAllowed){const button=document.createElement('button');button.type='button';button.textContent=words[language].closeRenewal;
    button.setAttribute('aria-label',words[language].closeRenewal+' '+row.operationId);button.disabled=!allowed('renewal-close',row.operationId);
    button.addEventListener('click',()=>confirm('renewal-close',row.operationId));item.append(' ',button);}
   el('renewals').append(item);
  }
  if (current) {
   const info = current.handoff;
   el('id').textContent = info.handoffId; el('operator').textContent = info.operator;
   el('ring').textContent = info.ringSha256; el('cohort').textContent = info.cohortSha256;
   const pendingPublication = current.publication.state === 'UNKNOWN' || !!intent('publish') || !!intent('continue');
   el('publication-state').textContent = words[language][stale ? 'unknown' : current.retired ? 'revoked' : current.publication.state === 'SUCCEEDED' ? 'published' : pendingPublication ? 'unknown' : 'notRecorded'];
   el('start-state').textContent = words[language][stale ? 'unknown' : current.retired ? 'revoked' : current.start.state === 'SUCCEEDED' ? 'started' : current.start.state === 'UNKNOWN' || !!intent('start') ? 'unknown' : 'notRecorded'];
  }
  if (!busy && (storageFault || (current && !platform()))) message('storage');
 }
 function validate(value) {
  if (!value || value.schema !== 1 || value.state !== 'HANDOFF_STATUS') throw Error();
  const info = value.handoff;
  if (!info || Object.keys(info).length !== 16 || info.schema !== 1 || !['GRANT_RECORDED','GRANT_REVOKING','GRANT_REVOKED'].includes(info.state)
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
    || typeof value.retired !== 'boolean' || typeof value.revocationAllowed !== 'boolean'
    || writers.some(name => typeof value.allowed[name] !== 'boolean' || typeof value.senderIntents[name] !== 'boolean')) throw Error();
  if(typeof value.renewalAllowed!=='boolean' || !Array.isArray(value.startRenewals) || value.startRenewals.length>256)throw Error();
  const renewalIds=new Set();
  for(const row of value.startRenewals){
   if(!uuid(row.operationId)||renewalIds.has(row.operationId)||ids.some(k=>info[k]===row.operationId)||!hash(row.expectedPublicationSha256)||typeof row.closed!=='boolean'||typeof row.closeAllowed!=='boolean'
    ||!['UNKNOWN','SUCCEEDED','NOT_ADMITTED'].includes(row.state)
    ||row.state==='SUCCEEDED'&&(row.resultSource!=='ROOT_ORIGINAL'||row.closed||row.closeAllowed||!Number.isInteger(row.issuedAt)||row.expiresAt-row.issuedAt!==900)
    ||row.state==='NOT_ADMITTED'&&(row.resultSource!=='ROOT_ADMISSION_CLOSED'||!row.closed||row.closeAllowed)
    ||row.state==='UNKNOWN'&&row.resultSource!=='UNCONFIRMED')throw Error();
   renewalIds.add(row.operationId);
  }
  const lease=value.startAuthorization;
  if(lease!==null&&(!lease||lease.schema!==1||lease.state!=='START_LEASE_STATUS'||lease.scope!=='ORIGINAL_FIRST_START_ONLY'
    ||['handoffId','publicationId','startOperationId'].some(k=>lease[k]!==info[k])||typeof lease.windowOpen!=='boolean'||typeof lease.renewalAllowed!=='boolean'
    ||lease.publicationSha256!==null&&lease.publicationSha256!==value.publication.publicationSha256
    ||lease.renewalOperationId!==null&&!uuid(lease.renewalOperationId)
    ||lease.windowOpen&&(!uuid(lease.renewalOperationId)||!hash(lease.publicationSha256))
    ||lease.renewalAllowed&&(lease.windowOpen||info.mutationWindowOpen||!hash(lease.publicationSha256))))throw Error();
  if(value.renewalAllowed&&(!lease?.renewalAllowed||value.completed||value.retired||value.start.state!=='NOT_RECORDED'||value.senderIntents.start))throw Error();
  if (value.allowed.publish && (!info.mutationWindowOpen || value.senderIntents.publish || value.publication.state !== 'NOT_RECORDED')) throw Error();
  if (value.allowed.start && ((!info.mutationWindowOpen && !lease?.windowOpen) || value.senderIntents.start || value.publication.state !== 'SUCCEEDED' || value.start.state !== 'NOT_RECORDED')) throw Error();
  if (value.allowed.continue && (value.senderIntents.continue || value.publication.state !== 'UNKNOWN' || !hash(value.publication.recoveryReceiptSha256))) throw Error();
  if (info.state !== 'GRANT_RECORDED' && (info.mutationWindowOpen || writers.some(name=>value.allowed[name]))) throw Error();
  if (value.retired && (info.state !== 'GRANT_REVOKED' || value.completed || value.revocationAllowed || writers.some(name=>value.allowed[name]))) throw Error();
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
  message(value.retired ? 'revoked' : value.handoff.state !== 'GRANT_RECORDED' ? 'revoking' : value.completed ? 'completed' : value.originalRecoveryPending ? 'recoveryPending' : unsettledLocalRenewal() ? 'unknown' : value.startAuthorization?.windowOpen ? 'renewed' : !value.handoff.mutationWindowOpen ? 'expired'
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
    if (command === 'revoke') {
     if (!fresh.revocationAllowed || fresh.retired) { message('blocked'); return; }
     const value = await api('revoke'); if (generation === epoch) apply(value); return;
    }
    if(command==='renewal-close'){
     if(!fresh.startRenewals.some(row=>row.operationId===selected.renewalId&&row.closeAllowed&&row.state!=='SUCCEEDED')){message('blocked');return;}
     const value=await api('renewal-close',{operationId:selected.renewalId});if(generation===epoch)apply(value);return;
    }
    if(command==='start-renew'){
     if(!fresh.renewalAllowed||unsettledLocalRenewal()||storageFault||fresh.publication.publicationSha256!==selected.publication){message('blocked');return;}
     const identity=crypto.randomUUID();persistRenewal(identity,selected.publication);
     const value=await api('start-renew',{operationId:identity,expectedPublicationSha256:selected.publication});if(generation===epoch)apply(value);return;
    }
    // The browser records its own immutable intent before the first HTTPS writer
    // request. A timeout or Root/server absence never authorizes a second send.
    if (!fresh.allowed[command] || intent(command) !== null || storageFault
      || (command === 'continue' && extra.expectedRecoveryReceiptSha256 !== selected.receipt)) { message('unknown'); return; }
    persist(command,extra);
    const value = await api(command,extra); if (generation === epoch) apply(value);
   });
  } catch (_) { if (generation === epoch) { stale = true; message('unknown'); } }
  finally { if (generation === epoch) { busy = false; render(); if (selected.command === 'revoke' && current?.retired) el('console').focus();
   if(selected.command==='start-renew')el(allowed('start')?'start':'query').focus();
   if(selected.command==='renewal-close')el(allowed('start-renew')?'start-renew':'query').focus(); } }
 }
 function confirm(command,renewalId) {
  if (!allowed(command,renewalId)) return;
  const dialog = el('confirm'); proposal = {command,binding:JSON.stringify(binding(current.handoff)),receipt:current.publication.recoveryReceiptSha256,publication:current.publication.publicationSha256,renewalId};
  el('confirm-title').textContent = words[language][command === 'continue' ? 'continue' : command + 'Title'];
  el('confirm-help').textContent = words[language][command === 'continue' ? 'continueHelp' : command + 'Help'];
  el('confirm-id').textContent = current.handoff.handoffId; el('confirm-ring').textContent = current.handoff.ringSha256;
  el('confirm-renewal').hidden=command!=='renewal-close';el('confirm-renewal-id').textContent=renewalId||'';
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
 for (const command of [...writers,'revoke','start-renew']) el(command).addEventListener('click',() => confirm(command));
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
