'use strict';
// AI只推荐；正式采用继续走已有的人工确认与时间校验。
const aiPanel=el('section');aiPanel.id='ai-panel';
aiPanel.innerHTML=`<h3>按画面类型选片</h3><label>检索范围 · 画面类型素材库<select id="ai-scope"><option value="all">全部已分类来源</option></select></label>
<div id="ai-blocked" class="small" aria-live="polite"></div><p id="ai-current"></p><p id="ai-status" class="small"></p>
<label class="ai-check"><input id="ai-experience" type="checkbox" checked>使用已审核经验</label><label>审核人姓名或昵称<input id="ai-reviewer" maxlength="80" autocomplete="off" placeholder="填写本次看片人的名字"></label>
<div class="button-row"><button id="ai-search" class="primary">找 5 条素材</button><button id="ai-next" class="primary">再检索 5 条素材</button></div>
<p id="ai-next-help" class="small" role="status"></p><div id="ai-batch-note"></div>
<div id="ai-count" role="status"></div><p id="rank-progress" role="status" hidden></p><div id="ai-cards"></div><section id="training-receipt" aria-live="polite" hidden></section><div id="review-footer" hidden></div>
<details id="ai-past"><summary>本句检索历史</summary><p class="small">查看这句字幕以前找过的素材和当时保存的审核结论。</p><button id="ai-history">刷新本句历史</button><label>查看批次<select id="ai-runs"></select></label><p id="ai-summary" class="small"></p></details>
<details><summary>导出审核记录</summary><a href="/api/local/slot-export" download>导出已保存审核记录 JSONL</a> <button id="ranking-refresh" type="button">重新导出并训练排序</button><span id="ranking-status" role="status"></span></details>`;
$('sb-middle').prepend(aiPanel);
$('ranking-refresh').onclick=async()=>{
 const button=$('ranking-refresh');button.disabled=true;
 try{const r=await api('/api/local/ranking-refresh',{});$('ranking-status').textContent=r.可训练对比+' 条可训练对比 · '+r.模型.模型版本;await aiHistory(aiRun()?.id);}
 catch(e){notice(e.message,true);}finally{button.disabled=false;}
};
let aiRuns=[],aiContextKey='',aiHistoryVersion=0,aiLastAdopted=new Map(),aiReady=false;
const reviewerKey='cutframe-reviewer-name-v2';
$('ai-reviewer').value=localStorage.getItem(reviewerKey)||'';
function reviewerName(){const name=$('ai-reviewer').value.trim();return board.tasks.some(t=>t.text.trim()===name)?'':name;}
$('ai-reviewer').onchange=()=>{const name=reviewerName();localStorage.setItem(reviewerKey,name);if(!name&&$('ai-reviewer').value.trim()){notice('请填写看片人的名字，这里填入的是字幕。',true);$('ai-reviewer').value='';}};
function aiProject(){return projectId||'unsaved';}
function aiTaskKey(){const t=sbTask();return JSON.stringify([aiProject(),materialScope,t?.id,t?.text,t?.start,t?.end,t?.need,board.context,board.context===sbContext(),localNeighbors()]);}
function aiReviewer(){const name=reviewerName();if(!name){$('ai-reviewer').focus();throw Error('请先填写审核人姓名或昵称');}return name;}
function aiRun(){return aiRuns.find(r=>r.id===$('ai-runs').value);}
function aiAssert(run){const t=sbTask();if(!t||run.payload.project_id!==aiProject()||run.payload.task_id!==t.id||run.payload.text!==t.text||(run.payload.need||'')!==(t.need||'')||Math.abs(run.payload.duration-(t.end-t.start))>.001||run.payload.board_context!==board.context||board.context!==sbContext())throw Error('字幕、配音或任务已变化，请同步任务后重新检索；旧批次保留供追溯');return t;}
async function aiHistory(preferred=null){
 const version=++aiHistoryVersion,key=aiTaskKey(),t=sbTask();if(!t)return;
 const d=await api('/api/ai/runs?project_id='+encodeURIComponent(aiProject())+'&task_id='+encodeURIComponent(t.id));
 if(version!==aiHistoryVersion||key!==aiTaskKey())return;
 const select=$('ai-runs'),prev=preferred||select.value;aiRuns=d.items.filter(r=>(r.payload.scope||'all')===materialScope);select.replaceChildren();
 const latest=aiRuns.find(slotIsLatest);
 for(const r of aiRuns){
  const round=r.result.round?'第 '+r.result.round+' 轮':'旧样本';
  localOption(select,r.id,(r===latest?'当前 · ':'历史 · ')+round+' · '+new Date(r.created).toLocaleString()+' · '+r.result.items.length+' 条');
 }
 if(aiRuns.some(r=>r.id===prev))select.value=prev;
 if(preferred===false||!aiRuns.length){const empty=el('option','本句尚未检索');empty.value='';select.prepend(empty);select.value='';}
 $('ai-past').querySelector('summary').textContent='本句检索历史（'+aiRuns.length+' 批）';
 aiRender();
}
function aiCandidate(run,c){return {slot_review:!!run.result.slot_review,id:c.id,task_id:run.payload.task_id,asset_id:c.asset_id,name:c.name,start:c.start,end:c.end,source_duration:c.duration,reason:c.reason,fallback:false,ai_run_id:run.id,ai_candidate_id:c.id,ai_project_id:run.payload.project_id};}
function showTraining(run){
 const progress=$('rank-progress'),receipt=$('training-receipt'),training=run?.training;
 progress.hidden=!training;receipt.hidden=!training?.details?.length;
 receipt.replaceChildren();if(!training)return;
 const version=run.result.rank_version;
 const method=!version?'本批未记录排序版本':version==='原排序'?'本批使用原排序':'本批使用模型排序';
 progress.textContent=method+'。'+(receipt.hidden?training.progress:'');
 if(!receipt.hidden){
  receipt.append(el('strong','本批已保存的反馈'));
  for(const line of training.details)receipt.append(el('p',line));
  receipt.append(el('p',training.progress));
 }
}
function aiRender(){$('review-footer').hidden=true;if(typeof slotButtons==='function')slotButtons();const box=$('ai-cards');box.replaceChildren();for(const id of ['ai-blocked','ai-count','ai-batch-note'])$(id).replaceChildren();const r=aiRun();showTraining(r);if(!r){$('ai-summary').textContent='';return;}let stale='';try{aiAssert(r);if(!slotIsLatest(r))stale='正在回看以前的批次，只供查阅。';}catch(e){stale=e.message;}
 if(stale){const latest=aiRuns.find(slotIsLatest);$('ai-batch-note').append(el('p',stale));if(latest)$('ai-batch-note').append(subtitleButton('返回本句当前批次',()=>{$('ai-runs').value=latest.id;sbClearSource();localRestoreBatch(latest);aiRender();}));}
 $('ai-summary').textContent=stale||('历史批次 · '+r.result.items.length+' 条');
 if(r.payload.provider==='local'&&!stale)$('ai-summary').textContent=localSummary(r.result);
 if(r.result.slot_review)slotSummary(box,r,stale);
 r.result.items.forEach((c,i)=>{const card=el('article',undefined,'ai-card'),img=el('img');img.src=`/api/ai/thumb/${r.id}/${c.id}`;img.alt=`候选${i+1}的抽帧`;img.loading='lazy';card.append(img,el('strong',r.result.slot_review?`${c.slot}(${c.asset_id})`:`${i+1}. ${c.name}`),el('p',`${c.start.toFixed(2)}–${c.end.toFixed(2)}秒 · ${(c.end-c.start).toFixed(2)}秒`,'small'),el('p',c.rel||c.name,'small'),el('p',(r.payload.provider==='local'?c.local_kind:c.identity_evidence||`相似分 ${Number(c.base_score||0).toFixed(3)}（不是正确率）${c.rule_ids?.length?' · 审核经验参与排序':''}`),'small'));
 if(r.result.slot_review){
  const before=c.rank_input_order;
  card.append(el('strong',(Number.isInteger(before)?'原第 '+before+' 名':'原名次未记录')+' → 本批第 '+(i+1)+' 名','candidate-rank'));
 }
 if(r.payload.provider==='local')localCardDetails(card,c);
 if(c.experience_ids?.length){const known=[...(r.result.knowledge_snapshot?.facts||[]),...(r.result.knowledge_snapshot?.general||[])];card.append(el('p','调用的人工知识：'+c.experience_ids.map(id=>{const k=known.find(x=>x.id===id);return k?`${k.sample_id||k.kind}：${k.description}`:id;}).join('；'),'small'));}
 if(c.scene_group)card.append(el('p','项目／场景分组（按目录推定）：'+c.scene_group,'small'));
 if(r.result.slot_review&&typeof workflowCompactCard==='function')workflowCompactCard(card);
 const selected=shots.some(s=>s.ai_run_id===r.id&&s.ai_candidate_id===c.id);
 const verdict=r.review?.records?.[c.slot]?.verdict;
 const status=r.review?.group?'本批已记缺口':selected?'已选入当前字幕':verdict==='采用'?'已确认采用':verdict==='不合适'?'已确认不合适':r.result.slot_review?'未采用，不代表不合适':'';
 if(status){const label=el('p',status,'hint');label.dataset.savedStatus=status;card.append(label);}
 card.append(subtitleButton('看这一条',async()=>{
  const version=sbSelectVersion+1;await sbSelect(aiCandidate(r,c));
  if(version===sbSelectVersion)await aiPlayCandidate(r,c);
 }));
 if(r.result.slot_review){slotCard(card,r,c,stale);box.append(card);return;}
 const oldCodes={semantic:'画面语义不符',duplicate:'与本片重复',blur:'画面模糊',product:'不是我们的产品',action:'动作不明确',good:'画面直接清楚',other:'其他'};
 const reviews=r.feedback.filter(x=>x.candidate_id===c.id);
 for(const f of reviews)card.append(el('p',[f.reviewer,({suitable:'合适',unsuitable:'不合适',unreviewed:'未评价'})[f.verdict],oldCodes[f.reason_code]||f.reason_code,f.reason].filter(Boolean).join(' · '),'small'));
 if(!reviews.length)card.append(el('p','尚未评价','small'));
 box.append(card);});
 if(r.result.slot_review&&!stale&&!r.review.group)updateReviewFooter(r);
}
action('ai-search',localSearchButton);action('ai-next',()=>localSearch('next'));
action('ai-history',()=>aiHistory());$('ai-runs').onchange=()=>{sbClearSource();if(aiRun()&&slotIsLatest(aiRun()))localRestoreBatch(aiRun());aiRender();};
// 采用、移除、调整另记事件，不据此推断合适或不合适。工程快照保留候选来源。
function aiObserve(){if(!aiReady)return;let changed=false;const current=new Map(shots.filter(s=>s.ai_run_id).map(s=>[s.ai_run_id+':'+s.ai_candidate_id,{...s}]));for(const [key,s]of current){const before=aiLastAdopted.get(key);if(!before||JSON.stringify(before)!==JSON.stringify(s)){changed=true;aiAdoption(s,before?'adjusted':'adopted');}}for(const [key,s]of aiLastAdopted)if(!current.has(key)){changed=true;aiAdoption(s,'removed');}aiLastAdopted=current;if(changed)aiRender();}
function aiAdoption(s,action){api('/api/ai/adoption',{run_id:s.ai_run_id,candidate_id:s.ai_candidate_id,task_id:s.task_ids[0],project_id:s.ai_project_id,action,shot:s}).catch(e=>notice('镜头操作已在工程中保留，但经验事件写入失败：'+e.message,true));}
const aiChangedBase=wfChanged;wfChanged=function(){const result=aiChangedBase();aiObserve();return result;};
const aiOpenBase=wfOpen;wfOpen=async function(d){aiReady=false;try{return await aiOpenBase(d);}finally{aiLastAdopted=new Map(shots.filter(s=>s.ai_run_id).map(s=>[s.ai_run_id+':'+s.ai_candidate_id,{...s}]));aiReady=true;aiContextKey='';}};
let aiSyncVersion=0;
function aiSyncTask(){
 if(wf.step!==4){aiSyncVersion++;aiContextKey='';localTaskKey='';localLoading++;localTaskPromise=null;localView=null;localRetryKey='';return;}
 const key=aiTaskKey();if(key===aiContextKey)return;
 const version=++aiSyncVersion;
 const current=()=>version===aiSyncVersion&&wf.step===4&&aiContextKey===aiTaskKey();
 aiContextKey=key;localTaskKey='';localTaskPromise=null;localLoading++;localView=null;localRetryKey='';aiRuns=[];aiRender();const t=sbTask();
 $('ai-current').textContent=t?t.text:'请先建立字幕任务';
 return localStatus(current).catch(e=>{if(current()&&localRetryKey!==aiTaskKey())localLoadFailure(e);});
}
const selectionRefresh=wfRefresh;wfRefresh=function(){selectionRefresh();aiSyncTask();};
if(typeof workflowCompactLayout==='function')workflowCompactLayout();aiReady=true;aiSyncTask();
async function aiPlayCandidate(run,c){
 const version=sbSelectVersion,v=$('sb-player');if(v.readyState<1){await new Promise((resolve,reject)=>{const cleanup=()=>{clearTimeout(timer);v.removeEventListener('loadedmetadata',ok);v.removeEventListener('error',bad);};const ok=()=>{cleanup();resolve();};const bad=()=>{cleanup();reject(Error('原片无法直接播放，请点击右侧的生成本地兼容预览，再预览选段'));};const timer=setTimeout(bad,12000);v.addEventListener('loadedmetadata',ok,{once:true});v.addEventListener('error',bad,{once:true});});}
 if(version!==sbSelectVersion||sbAsset?.id!==c.asset_id)throw Error('候选已切换，请重新预览');v.currentTime=c.start;sbStop=c.end;await v.play();
}


