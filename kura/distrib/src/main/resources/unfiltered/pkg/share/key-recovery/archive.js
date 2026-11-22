'use strict';
// Archive only retained metadata. Key writers and their browser intentions are separate.
(() => {
 const el=id=>document.getElementById('archive-'+id),handoff=document.body.dataset.view==='handoff';
 const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v);
 const hash=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
 const tokenPattern=/^KURA-HANDOFF-1\.[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.[0-9a-f]{64}$/;
 const choices=handoff?['HANDOFF','ADMISSION:publish','ADMISSION:continue','ADMISSION:handoff-start','ADMISSION:handoff-renewal']:['RESTORE','START','ADMISSION:restore','ADMISSION:start'];
 const labels={RESTORE:'restore',START:'start',HANDOFF:'handoff','ADMISSION:restore':'restoreAdmission','ADMISSION:start':'startAdmission','ADMISSION:publish':'publishAdmission','ADMISSION:continue':'continueAdmission','ADMISSION:handoff-start':'startAdmission','ADMISSION:handoff-renewal':'renewalAdmission'};
 const words={
  zh:{title:'归档已确认的历史',help:'归档可释放活动记录名额。原文件、原编号和密钥继续保留；结果不明的密钥操作不能归档或重发。',records:'保留的历史记录',refresh:'读取归档历史',previous:'上一页历史',next:'下一页历史',kind:'记录类型',restore:'原密钥恢复',start:'Kura 启动',handoff:'维护交接',restoreAdmission:'恢复发送回执',startAdmission:'启动发送回执',publishAdmission:'发布发送回执',continueAdmission:'原发布续接回执',renewalAdmission:'首次启动授权续期回执',identity:'原操作编号（必填）',archiveId:'原归档编号',read:'预览／查询原归档',authorize:'授权归档此原记录',file:'原加密备份 JSON 文件（必填）',password:'原备份解密口令（必填）',privacy:'仅核验原钥授权，不恢复或替换密钥；口令不会保存。',handoffMaterial:'归档须使用上方输入的原交接授权，不能用其他申请代替。',archive:'确认归档原记录',continue:'继续原归档元数据',confirmTitle:'归档此原记录？',continueTitle:'继续此原归档？',confirmHelp:'仅归档所示原记录的元数据，原文件和密钥保留。此操作不会恢复密钥、发布或启动 Kura。',cancel:'取消',confirm:'确认此归档操作',loaded:'历史已读取。请选择记录，再核对当前归档状态。',empty:'此页没有匹配的历史记录。',ready:'原历史已核对，可使用原授权材料确认归档。',continuable:'网关保留了原归档意图。可明确继续此原编号的元数据。',done:'归档回执已确认。原文件、编号和密钥继续保留。',pending:'原归档结果尚不确定。请保留原编号并重新查询，不能再次发送首次请求。',unavailable:'暂时无法确认归档状态。请保留原编号并重新查询。',stale:'原记录或证明已变化。请重新预览，再明确确认。',refused:'归档检查未通过，原记录仍保留。',invalidFile:'请选择原加密备份 JSON 文件，大小不超过 48 KiB。',invalidPassword:'口令须为 12–256 个字符。',invalidToken:'请先在上方输入完整的原交接授权。',authorizationFailed:'原备份或口令未通过核验，未归档此记录。',browser:'此浏览器无法打开原生确认窗口，请使用支持 dialog 的浏览器。'},
  en:{title:'Archive confirmed history',help:'Archiving frees active-record capacity. Original files, IDs and keys are retained. Unconfirmed key operations cannot be archived or resent.',records:'Retained archive records',refresh:'Read archive history',previous:'Previous archive page',next:'Next archive page',kind:'Record type',restore:'Original-key recovery',start:'Kura startup',handoff:'Maintenance handoff',restoreAdmission:'Recovery send receipt',startAdmission:'Startup send receipt',publishAdmission:'Publication send receipt',continueAdmission:'Original publication continuation receipt',renewalAdmission:'First-start authorization renewal receipt',identity:'Original operation ID (required)',archiveId:'Original archive ID',read:'Preview / query original archive',authorize:'Authorize archiving this original record',file:'Original encrypted backup JSON file (required)',password:'Original backup passphrase (required)',privacy:'Verify original-key authorization only. No keys are restored or replaced, and the passphrase is not saved.',handoffMaterial:'Archiving requires the original handoff authorization entered above. Another request cannot replace it.',archive:'Confirm archive of original record',continue:'Continue original archive metadata',confirmTitle:'Archive this original record?',continueTitle:'Continue this original archive?',confirmHelp:'Archive only metadata for the displayed original record; retain the original files and keys. This does not restore keys, publish or start Kura.',cancel:'Cancel',confirm:'Confirm this archive operation',loaded:'History loaded. Select a record, then review its current archive state.',empty:'No matching history on this page.',ready:'The original history is confirmed. Use the original authorization material to confirm archiving.',continuable:'The gateway retained the original archive intent. You may explicitly continue its metadata under the same ID.',done:'The archive receipt is confirmed. Original files, IDs and keys are retained.',pending:'The original archive outcome is unconfirmed. Retain its ID and query again; a first request cannot be sent again.',unavailable:'The archive state could not be confirmed. Retain the original ID and query again.',stale:'The original record or proof changed. Preview it again before confirming.',refused:'Archive checks did not pass. The original record is retained.',invalidFile:'Select the original encrypted backup JSON file, at most 48 KiB.',invalidPassword:'Use a passphrase of 12–256 characters.',invalidToken:'Enter the complete original handoff authorization above first.',authorizationFailed:'The original backup or passphrase was not verified. The record was not archived.',browser:'This browser cannot open the native confirmation. Use a browser with dialog support.'}
 };
 let current=null,busy=false,epoch=0,fileEpoch=0,raw='',proposal=null,noticeKey='',rows=[],pages=[null],page=0,nextCursor=null;
 const text=key=>words[document.getElementById('language').value==='en'?'en':'zh'][key]||'';
 const name=row=>row.kind+(row.senderKind?':'+row.senderKind:'');
 const selected=()=>{const parts=document.querySelector('input[name=archive-selector]:checked').value.split(':');return {kind:parts[0],operationId:el('reference').value,senderKind:parts[1]||null};};
 const same=(a,b)=>a&&b&&a.kind===b.kind&&a.operationId===b.operationId&&a.senderKind===b.senderKind;
 const live=g=>g===epoch&&el('flow').isConnected&&document.visibilityState==='visible';
 const ready=()=>!busy&&live(epoch);
 const permitted=continuing=>ready()&&current&&same(current,selected())&&hash(current.reviewSha256)&&(continuing?current.continueAllowed:current.archiveAllowed);
 const disabled=(node,value)=>node.setAttribute('aria-disabled',String(value));
 function notice(key){noticeKey=key;el('notice').textContent=text(key);}
 function clearMaterial(){raw='';fileEpoch++;el('backup').value='';el('password').value='';for(const field of [el('backup'),el('password')]){field.setCustomValidity('');field.removeAttribute('aria-invalid');}}
 function cancel(){proposal=null;if(el('confirm').open)el('confirm').close();}
 function reset(){epoch++;busy=false;current=null;cancel();clearMaterial();el('identities').textContent='';notice('');render();}
 function render(){
  el('progress').hidden=!busy;el('flow').setAttribute('aria-busy',String(busy));
  for(const id of ['refresh','read'])disabled(el(id),!ready());
  disabled(el('previous'),!ready()||page===0);disabled(el('next'),!ready()||!nextCursor);
  const authorized=current&&(current.archiveAllowed||current.continueAllowed);
  el('authorize-form').hidden=!authorized;disabled(el('apply'),!permitted(false));disabled(el('continue'),!permitted(true));
  for(const field of [el('backup'),el('password')])field.disabled=handoff||busy||!authorized;
 }
 function auth(){
  const value=document.getElementById('handoff-token').value;
  if(!tokenPattern.test(value)){document.getElementById('handoff-token').focus();throw Error('invalidToken');}
  return value;
 }
 async function api(command,extra={},reference=selected()){
  const body=command==='list'?{command,cursor:extra.cursor}:{command,kind:reference.kind,operationId:reference.operationId,...(reference.senderKind?{senderKind:reference.senderKind}:{}),...extra};
  if(handoff){body.command=command==='archive'?'archive-confirm':'archive-'+command;body.token=auth();}
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
  try{
   const response=await fetch(handoff?'/api/handoff':'/api/archive',{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal,
    headers:{'Content-Type':'application/json','X-Kura-Recovery-CSRF':document.querySelector('meta[name=kura-recovery-csrf]').content},body:JSON.stringify(body)});
   const raw=await response.text();if(raw.length>65536)throw Error();const result=JSON.parse(raw);
   if(!response.ok)throw Error(result?.error==='BACKUP_REJECTED'?'authorizationFailed':'unavailable');return result;
  }finally{clearTimeout(timer);if('passphrase'in body){body.passphrase='';body.backupJson='';}}
 }
 function validRow(row){return row&&Object.keys(row).sort().join(',')==='kind,operationId,senderKind'&&choices.includes(name(row))&&uuid(row.operationId);}
 function validate(view,reference){
  const keys=['schema','kind','operationId','senderKind','state','privateAttempt','archiveId','reviewSha256','archiveAllowed','continueAllowed','archived','error'];
  if(!view||Object.keys(view).some(k=>!keys.includes(k))||view.schema!==1||!same(view,reference)||!choices.includes(name(view))||!uuid(view.operationId)
   ||!['UNAVAILABLE','UNKNOWN','ARCHIVABLE','ARCHIVE_RECORDED'].includes(view.state)||['privateAttempt','archiveAllowed','continueAllowed','archived'].some(k=>typeof view[k]!=='boolean')
   ||(view.archiveId!==null&&!uuid(view.archiveId))||(view.reviewSha256!==null&&!hash(view.reviewSha256))
   ||((view.archiveAllowed||view.continueAllowed)&&!hash(view.reviewSha256))||(view.archiveAllowed&&view.continueAllowed)
   ||(view.privateAttempt&&!uuid(view.archiveId))||(view.archiveAllowed&&view.privateAttempt)||(view.continueAllowed&&!view.privateAttempt)
   ||(view.archived&&(!view.privateAttempt||view.archiveAllowed||view.continueAllowed))
   ||(view.error!==undefined&&!['STALE_REVIEW','ARCHIVE_NOT_ALLOWED','ARCHIVE_UNCONFIRMED','ARCHIVE_PREFLIGHT_REFUSED'].includes(view.error)))throw Error();
  return view;
 }
 function show(view){
  current=view;el('identities').textContent=text('identity')+': '+view.operationId+(view.archiveId?'\n'+text('archiveId')+': '+view.archiveId:'');
  notice(view.archived?'done':view.error==='STALE_REVIEW'?'stale':['ARCHIVE_NOT_ALLOWED','ARCHIVE_PREFLIGHT_REFUSED'].includes(view.error)?'refused':view.continueAllowed?'continuable':view.privateAttempt?'pending':view.archiveAllowed?'ready':'unavailable');
 }
 function options(){
  const previous=el('records').value;el('records').replaceChildren(new Option(text('records'),''));
  for(const row of rows)el('records').add(new Option(text(labels[name(row)])+' · '+row.operationId,name(row)+'|'+row.operationId));
  if([...el('records').options].some(option=>option.value===previous))el('records').value=previous;
 }
 async function load(){
  if(!ready())return;const generation=++epoch;busy=true;current=null;cancel();clearMaterial();render();
  try{
   const result=await api('list',{cursor:pages[page]});
   if(!live(generation))return;
   if(!result||result.schema!==1||result.state!=='ARCHIVE_HISTORY'||Object.keys(result).sort().join(',')!=='nextCursor,records,schema,state'
    ||!Array.isArray(result.records)||result.records.length>20||result.records.some(row=>!validRow(row))
    ||(result.nextCursor!==null&&(typeof result.nextCursor!=='string'||result.nextCursor.length>80)))throw Error();
   rows=result.records;nextCursor=result.nextCursor;options();notice(rows.length?'loaded':'empty');
  }catch(error){if(live(generation))notice(error.message==='invalidToken'?'invalidToken':'unavailable');}
  finally{if(live(generation)){busy=false;render();}}
 }
 async function read(){
  if(!ready())return;const reference=selected(),generation=++epoch;busy=true;current=null;cancel();clearMaterial();render();
  try{const value=validate(await api('query',{},reference),reference);if(live(generation))show(value);}
  catch(error){if(live(generation))notice(error.message==='invalidToken'?'invalidToken':'unavailable');}
  finally{if(live(generation)){busy=false;render();}}
 }
 function passwordValid(value){const chars=Array.from(value);return chars.length>=12&&chars.length<=256&&!value.includes('\0')&&chars.every(c=>c.length!==1||c.charCodeAt(0)<0xd800||c.charCodeAt(0)>0xdfff)&&new TextEncoder().encode(value).length<=1024;}
 function confirm(continuing){
  if(!permitted(continuing))return;
  if(handoff){try{auth();}catch(_){notice('invalidToken');return;}}
  else{
   el('backup').setCustomValidity(raw?'':text('invalidFile'));el('password').setCustomValidity(passwordValid(el('password').value)?'':text('invalidPassword'));
   if(!el('authorize-form').reportValidity())return;
  }
  if(typeof el('confirm').showModal!=='function'){notice('browser');return;}
  proposal={generation:epoch,reference:selected(),view:current,continuing};el('confirm-title').textContent=text(continuing?'continueTitle':'confirmTitle');
  el('confirm-identities').textContent=el('identities').textContent;el('confirm').returnValue='';el('confirm').showModal();
 }
 async function submit(chosen){
  if(!chosen||!live(chosen.generation)||chosen.view!==current||!same(chosen.reference,selected())||!permitted(chosen.continuing))return;
  const generation=++epoch,material={reviewSha256:chosen.view.reviewSha256,...(handoff?{}:{backupJson:raw,passphrase:el('password').value})};busy=true;current=null;clearMaterial();render();
  try{const value=validate(await api(chosen.continuing?'continue':'archive',material,chosen.reference),chosen.reference);if(live(generation))show(value);}
  catch(error){if(live(generation))notice(['invalidToken','authorizationFailed'].includes(error.message)?error.message:'pending');}
  finally{material.passphrase='';material.backupJson='';if(live(generation)){busy=false;render();}}
 }
 function translate(){for(const node of document.querySelectorAll('[data-archive-i18n]'))node.textContent=text(node.dataset.archiveI18n);el('progress').setAttribute('aria-label',text('read'));options();if(current)show(current);else notice(noticeKey);}
 el('read-form').addEventListener('submit',event=>{event.preventDefault();read();});
 el('authorize-form').addEventListener('submit',event=>{event.preventDefault();confirm(event.submitter?.value==='continue');});
 el('confirm').addEventListener('close',()=>{
  if(el('confirm').open)return;const choice=el('confirm').returnValue,chosen=proposal;el('confirm').returnValue='';proposal=null;
  if(choice==='confirm')submit(chosen);else el('password').value='';
 });
 el('refresh').addEventListener('click',()=>{if(ready()){pages=[null];page=0;load();}});
 el('previous').addEventListener('click',()=>{if(ready()&&page>0){page--;load();}});
 el('next').addEventListener('click',()=>{if(ready()&&nextCursor){pages=pages.slice(0,page+1);pages.push(nextCursor);page++;load();}});
 el('records').addEventListener('change',()=>{
  const value=el('records').value,at=value.indexOf('|');if(at<0)return;const selector=value.slice(0,at),identity=value.slice(at+1);
  if(!choices.includes(selector)||!uuid(identity))return;for(const radio of el('read-form').querySelectorAll('input[type=radio]'))radio.checked=radio.value===selector;
  el('reference').value=identity;reset();
 });
 for(const radio of el('read-form').querySelectorAll('input[type=radio]'))radio.addEventListener('change',reset);
 el('reference').addEventListener('input',reset);
 for(const field of [el('backup'),el('password')]){
  field.addEventListener('invalid',()=>field.setAttribute('aria-invalid','true'));
  field.addEventListener('input',()=>{field.setCustomValidity('');field.removeAttribute('aria-invalid');});
 }
 el('backup').addEventListener('change',async()=>{
  const generation=++fileEpoch;raw='';el('password').value='';el('backup').setCustomValidity('');const file=el('backup').files[0];
  if(!file||file.size<1||file.size>49152){el('backup').setCustomValidity(text('invalidFile'));return;}
  try{const value=await file.text();if(generation===fileEpoch)raw=value;}catch(_){if(generation===fileEpoch)el('backup').setCustomValidity(text('invalidFile'));}
 });
 if(handoff){document.getElementById('handoff-token').addEventListener('input',reset);document.getElementById('handoff-forget').addEventListener('click',reset);}
 document.getElementById('language').addEventListener('change',translate);
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')reset();});
 window.addEventListener('pagehide',reset);
 el('cold-kinds').hidden=handoff;el('cold-kinds').disabled=handoff;el('handoff-kinds').hidden=!handoff;el('handoff-kinds').disabled=!handoff;
 if(handoff)document.getElementById('archive-type-handoff').checked=true;
 el('backup-material').hidden=handoff;el('handoff-material').hidden=!handoff;
 for(const form of [el('read-form'),el('authorize-form')])form.action=handoff?'/api/handoff':'/api/archive';
 translate();render();if(!handoff)load();
})();
