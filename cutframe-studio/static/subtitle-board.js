'use strict';
// 逐条字幕人工选片；匹配与推荐模型不在本阶段启用。

function subtitlePlaybackPlan(){return board.mode==='subtitle'?SubtitleBoardCore.playbackPlan(board.tasks,shots,sbDuration()):{shots,errors:[],gaps:[]};}
const gapProjectBase=project;project=function(){const p=gapProjectBase();if(p.workflow?.storyboard?.mode==='subtitle')p.workflow.storyboard.gap_policy='continue_previous';return p;};
const subtitleTaskShots=t=>shots.filter(s=>s.task_ids?.includes(t.id));
const subtitleTaskErrors=t=>SubtitleBoardCore.errors(t,shots);
const subtitleLayout=t=>SubtitleBoardCore.layout(t,shots);
function subtitleRefresh(){wfPause();$('sb-player').pause();renderShots();sbTasks();sbChanged();}
let sbPlayingFilm=false;
const sbPlayback={
 get active(){return $('sb-player');},
 async show(key,url,target,next,force){
  const v=this.active,serial=sbSelectVersion;
  if(force||this.key!==key){
   await shotPreview.prepare(v,url,target);
   if(!sbPlayingFilm||serial!==sbSelectVersion)return null;
   this.key=key;
  }
  return v;
 }
};
function subtitleButton(label,fn){const b=el('button',label);b.onclick=async()=>{try{await fn();}catch(e){notice(e.message,true);}};return b;}
function subtitleResetReplace(){sbReplace=null;$('sb-cancel-replace').hidden=true;}
function subtitleSelectTask(t){sbClearSource();wf.playRange=null;subtitleResetReplace();board.selected=t.id;sbTasks();wfChanged();}
async function subtitlePlay(t,neighbors){
 const i=board.tasks.indexOf(t),group=neighbors==='all'?board.tasks:neighbors==='previous'?board.tasks.slice(Math.max(0,i-1),i+1):neighbors?board.tasks.slice(Math.max(0,i-1),i+2):[t];
 for(const item of group)if(subtitleTaskErrors(item).length)throw Error('播放范围内仍有未选镜头或时长问题，请先完成这些任务');
 const plan=subtitlePlaybackPlan();for(const gap of plan.gaps)if(gap.error&&gap.start>=group[0].start&&gap.start<group.at(-1).end)throw Error(gap.error);
 sbClearSource();sbPlayingFilm=true;sbPlayback.key=null;shotPreview.entries.delete($('sb-player'));sbFixedUpdate();
 const serial=sbSelectVersion;await wfSeek(group[0].start);if(serial!==sbSelectVersion||!sbPlayingFilm)return;wf.playRange={start:group[0].start,end:group.at(-1).end};await $('wf-play').onclick();
}
const oldTasks=sbTasks;
sbTasks=function(){
 if(board.mode!=='subtitle'){oldTasks();return;}
 const box=$('sb-tasks');box.replaceChildren();
 board.tasks.forEach((t,i)=>{
  // 取消尚未采用镜头的旧双镜预规划；已有镜头与切点不变。
  if(t.planned_shots===2&&!subtitleTaskShots(t).length){t.planned_shots=1;delete t.split;t.accepted=null;}
  const c=el('article',undefined,'sb-task'+(board.selected===t.id?' selected':'')),ss=subtitleTaskShots(t),errs=subtitleTaskErrors(t),good=ss.length>0&&!errs.length;
  c.append(subtitleButton(`${i+1} · ${t.start.toFixed(2)}–${t.end.toFixed(2)} 秒 · ${good?'已选片':ss.length?'待补齐':'待选片'}`,()=>subtitleSelectTask(t)),el('p',t.text));
  if(board.selected===t.id){
   c.append(el('p',`本条 ${(t.end-t.start).toFixed(2)} 秒 · ${ss.length?'已选 '+ss.length+' 个镜头':'尚未选镜头'}`));
   const gap=subtitlePlaybackPlan().gaps.find(g=>g.task_id===t.id);if(gap)c.append(el('p',gap.pending?`句后停顿 ${gap.extra.toFixed(2)} 秒，选入镜头后检查能否续播。`:gap.error||`镜头续播 ${gap.extra.toFixed(2)} 秒，画面接至 ${gap.end.toFixed(2)} 秒。`,gap.error&&!gap.pending?'wf-pending':'small'));
   c.append(sbInput('希望画面出现什么',t.need||'',v=>{t.need=v;t.accepted=null;},'textarea'));
   if(ss.length===2||t.planned_shots===2){const l=el('label','两个镜头中间切点／成片秒'),input=el('input');input.type='number';input.step='.01';input.value=Number(t.split).toFixed(3);input.min=t.start+.01;input.max=t.end-.01;input.onchange=()=>{const old=t.split;t.split=Number(input.value);try{if(ss.length)subtitleLayout(t);t.accepted=null;subtitleRefresh();}catch(e){t.split=old;input.value=old;notice(e.message,true);}};l.append(input);c.append(l);}
   ss.forEach((s,j)=>{
    c.append(el('p',`镜头${j+1} ${s.name} · 成片 ${Number(s.timeline_start).toFixed(2)}–${(Number(s.timeline_start)+s.end-s.start).toFixed(2)} 秒 · 源 ${s.start.toFixed(2)}–${s.end.toFixed(2)} 秒`,'small'));
    const l=el('label',`镜头${j+1}源入点／秒`),input=el('input');input.type='number';input.min=0;input.step='.01';input.value=s.start;input.onchange=()=>{const prior=s.start;s.start=Number(input.value);try{subtitleLayout(t);t.accepted=null;subtitleRefresh();}catch(e){s.start=prior;input.value=prior;notice(e.message,true);}};l.append(input);c.append(l);
    c.append(subtitleButton(`预览镜头${j+1}原片`,()=>sbSelect(s)),subtitleButton(`替换镜头${j+1}`,()=>{sbReplace=shots.indexOf(s);$('sb-cancel-replace').hidden=false;sbFixedUpdate();notice('选择新素材、打点后点击替换；采用前保留旧镜头。');}),subtitleButton(`移除镜头${j+1}`,()=>{wfPause();shots.splice(shots.indexOf(s),1);t.accepted=null;subtitleResetReplace();subtitleRefresh();}));
    if(s.fallback)c.append(el('p','替代画面理由：'+(s.reason||'未填写'),'small'));
   });
   if(ss.length&&errs.length){
    const covered=ss.reduce((sum,s)=>sum+Math.max(0,Math.min(t.end,s.timeline_start+s.end-s.start)-Math.max(t.start,s.timeline_start)),0),missing=Math.max(0,t.end-t.start-covered);
    c.append(el('p',errs.join('；')+(missing>.001?`；本条尚缺 ${missing.toFixed(2)} 秒画面。可增加镜头，或手动重新分配；不会自动延长。`:''),'wf-pending'),subtitleButton('按本条时间重新分配镜头',()=>{if(ss.length===2&&!(t.split>t.start&&t.split<t.end))t.split=(t.start+t.end)/2;subtitleLayout(t);t.accepted=null;subtitleRefresh();}));
   }
   c.append(subtitleButton('预览本条',()=>subtitlePlay(t,false)));
   if(i+1<board.tasks.length)c.append(subtitleButton('下一条字幕',()=>subtitleSelectTask(board.tasks[i+1])));
  }box.append(c);
 });
 if(board.archived?.length)box.append(el('p',`${board.archived.length} 条旧任务已归档保留，不参与当前导出。`,'small'));
};
function syncSavedSubtitleTasks(){
 if(!wf.cues.length||wf.dirtySubtitle||!imports.subtitle)throw Error('请先保存第三步字幕');

 const result=SubtitleBoardCore.sync(board.tasks,wf.cues,Number($('subtitle-offset').value),()=>crypto.randomUUID());
 board.archived=board.archived||[];
 for(const t of result.removed){board.archived.push({task:t,shots:structuredClone(subtitleTaskShots(t)),candidates:structuredClone(board.candidates.filter(c=>c.task_id===t.id))});if(board.mode==='subtitle')for(let i=shots.length-1;i>=0;i--)if(shots[i].task_ids?.includes(t.id))shots.splice(i,1);}
 board.tasks=result.tasks;board.mode='subtitle';board.version=2;board.enabled=true;board.context=sbContext();board.confirmed=null;
 if(!board.tasks.some(t=>t.id===board.selected))board.selected=board.tasks[0]?.id;subtitleRefresh();
}

let sbSavingShot=false;
$('sb-adopt').onclick=async()=>{
 if(sbSavingShot)return;
 try{
  const candidate=sbApprovedCandidate(),t=sbTask(),ss=t?subtitleTaskShots(t):[];
  const problem=sbAdoptProblem(candidate);if(problem)throw Error(problem);
  const r=sbRange(),target=sbReplace,match=$('sb-match').value,serial=sbSelectVersion;
  const identity=JSON.stringify([aiTaskKey(),r,shots,target,match]);
  sbSavingShot=true;sbFixedUpdate();
  const aspect=await api('/api/ai/portrait/'+r.asset_id);if(!aspect.allowed)throw Error('仅允许原始9:16竖屏素材');
  if(serial!==sbSelectVersion||candidate.run.id!==sbApprovedCandidate()?.run.id)throw Error('字幕或批次已变化，请重新选择镜头');
  await api('/api/local/slot-adopt',{run_id:candidate.run.id,candidate_id:candidate.item.id});
  if(serial!==sbSelectVersion||candidate.run.id!==sbApprovedCandidate()?.run.id||sbAdoptProblem(sbApprovedCandidate())||
     identity!==JSON.stringify([aiTaskKey(),sbRange(),shots,sbReplace,$('sb-match').value]))throw Error('字幕或片段已变化，请重新选入');
  Object.assign(r,{slot_review:true,ai_run_id:candidate.run.id,ai_candidate_id:candidate.item.id,ai_project_id:aiProject()});
  const s={...r,available_end:r.end,task_ids:[t.id],fallback:match==='fallback',fallback_confirmed:match==='fallback'};if(t.planned_shots===2)s.slot=sbReplace!==null?(shots[sbReplace].slot??ss.indexOf(shots[sbReplace])):[0,1].find(i=>!ss.some((x,j)=>(x.slot??j)===i));const backup=structuredClone(shots),split=t.split;
  try{if(sbReplace!==null){if(!shots[sbReplace]||board.tasks.some(other=>other.id!==t.id&&shots[sbReplace].task_ids?.includes(other.id)))throw Error('替换目标不属于当前任务');shots.splice(sbReplace,1,s);}else{shots.push(s);if(ss.length===1&&t.planned_shots!==2)t.split=(t.start+t.end)/2;}subtitleLayout(t);}catch(e){shots.splice(0,shots.length,...backup);t.split=split;throw e;}
  wfPause();subtitleResetReplace();
  const complete=!subtitleTaskErrors(t).length&&(t.planned_shots!==2||subtitleTaskShots(t).length===2);
  t.accepted=null;
  subtitleRefresh();
  const next=board.tasks[board.tasks.indexOf(t)+1];
  if(complete&&next)subtitleSelectTask(next);
  wfSaveDraft();
  notice(complete?(next?'已保存镜头，已到下一条字幕。':'已保存最后一条镜头。'):'已保存镜头，请继续补齐本条字幕。');
 }catch(e){notice(e.message,true);}finally{sbSavingShot=false;sbFixedUpdate();}
};
const issuesOld=sbIssues;
sbIssues=function(){
 if(board.mode!=='subtitle')return issuesOld();const plan=subtitlePlaybackPlan(),pending=new Set(plan.gaps.filter(g=>g.pending).map(g=>g.error)),e=plan.errors.filter(msg=>!pending.has(msg));
 const offset=Number($('subtitle-offset').value);
 if(imports.subtitle&&!wf.dirtySubtitle && (board.tasks.length!==wf.cues.length || board.tasks.some((t,i)=>{
  const cue=wf.cues[i];return !cue||cue.text!==t.text||Math.abs(t.start-cue.start-offset)>.001||Math.abs(t.end-cue.end-offset)>.001;
 })))e.push('选片任务与已保存字幕不一致，请同步任务');
 if(!imports.voice)e.push('请先采用或导入配音');const subtitleIssue=wfSubtitleIssue();if(subtitleIssue)e.push(subtitleIssue);
 if(!board.tasks.length)e.push('请先按字幕建立任务');
 for(const [i,t] of board.tasks.entries()){if(!subtitleTaskShots(t).length){e.push(`第${i+1}条「${t.text}」待选镜头`);continue;}e.push(...subtitleTaskErrors(t).map(x=>`${t.text}：${x}`));}
 if(shots.some(s=>s.task_ids?.length!==1||!board.tasks.some(t=>t.id===s.task_ids[0])))e.push('存在未关联当前字幕的镜头');return [...new Set(e)];
};
const statusOld=sbStatus;
sbStatus=function(){if(board.mode!=='subtitle'){statusOld();if(!board.tasks.length)$('sb-status').textContent='请先在第三步保存字幕。';return;}const e=sbIssues();$('sb-status').textContent=e.length?'请查看底部待处理项':'已选镜头覆盖所有字幕，可以进入配乐。';if(e.length)$('render-film').disabled=true;};
// 新字幕工程的已选镜头在当前任务下操作；旧工程保留来源和镜头引用。
renderShots=function(){
 $('shots').replaceChildren();
 for(const s of shots.filter(s=>board.mode!=='subtitle'||!board.tasks.some(t=>s.task_ids?.includes(t.id)))){
  const row=el('div');row.append(el('span',s.name),subtitleButton('查看已选镜头',()=>sbSelect(s)),
   subtitleButton('替换镜头',()=>{sbReplace=shots.indexOf(s);$('sb-cancel-replace').hidden=false;sbFixedUpdate();}),
   subtitleButton('移除镜头',()=>{shots.splice(shots.indexOf(s),1);subtitleRefresh();}));$('shots').append(row);
 }
 updateFilmDuration();wfChanged();
};
function sbApprovedCandidate(){
 if(typeof aiRun!=='function')return null;
 const run=aiRun();
 if(!run?.result.slot_review||!slotMatchesCurrent(run)||run!==aiRuns.find(r=>r.result.slot_review&&slotMatchesCurrent(r)))return null;
 const item=run.result.items.find(c=>c.asset_id===sbAsset?.id);
 return {run,item};
}
function sbAdoptProblem(candidate){
 if(board.mode!=='subtitle')return '请按已保存字幕同步任务后选入。';
 if(typeof aiRun==='function'&&aiRun()&&!slotIsLatest(aiRun()))return '当前为历史批次，仅供预览。请在「查看批次」切回「当前」，再选择镜头。';
 if(!candidate)return '请先选择当前字幕并检索本轮 候选镜头。';
 const {run,item}=candidate;
 if(!item)return '请点本轮候选的「看这一条」选择镜头。';
 if(run.review.group||run.review.records[item.slot]?.verdict==='不合适')return '这条素材已确认不合适，请选择其他候选。';
 if(!$('sb-in').value.trim()||!sbMeta||sbFixedLength()<=0||Number($('sb-in').value)<0||Number($('sb-in').value)+sbFixedLength()>sbMeta.duration+.000001)return '请检查原片开始位置、剩余时长或选择替换镜头。';
 if(!$('sb-match').value)return '请选择直接对应文案或替代画面。';
 if($('sb-match').value==='fallback'&&!$('sb-reason').value.trim())return '请填写替代画面理由。';
 return '';
}
function sbFixedLength(){
 const t=sbTask();if(!t)return 0;const ss=subtitleTaskShots(t);
 if(ss.length===0)return t.end-t.start;
 if(sbReplace!==null){const old=shots[sbReplace];if(!old||board.tasks.some(other=>other.id!==t.id&&old.task_ids?.includes(other.id)))return 0;if(ss.length===1&&t.planned_shots!==2)return t.end-t.start;const slot=old.slot??ss.indexOf(old);return slot===0?t.split-t.start:t.end-t.split;}
 if(ss.length===1)return t.end-(Number.isFinite(t.split)?t.split:(t.start+t.end)/2);
 return 0;
}
function sbFixedUpdate(){
 const duration=sbFixedLength(),start=Number($('sb-in').value),end=start+duration;
 $('sb-out').value=Number.isFinite(end)?end.toFixed(3):'';
 const ready=sbAsset&&sbMeta&&duration>0&&Number.isFinite(start)&&start>=0&&end<=sbMeta.duration+.000001;
 const problem=sbAdoptProblem(sbApprovedCandidate());
 $('sb-fixed-status').textContent=sbSavingShot?'正在保存所选镜头…':problem;
 $('sb-adopt').disabled=sbSavingShot||!ready||!!problem;
 $('sb-adopt').textContent=sbTask()?.planned_shots===2&&!subtitleTaskShots(sbTask()).length?'选入第一个镜头':board.tasks.at(-1)===sbTask()?'选入镜头':'选入并继续';const t=sbTask();$('sb-current-caption').textContent=t?t.text+' · '+(t.end-t.start).toFixed(2)+' 秒':'请选择字幕';
 $('sb-position').max=Math.max(0,(sbMeta?.duration||0)-duration);$('sb-position').value=Number.isFinite(start)?start:0;$('sb-position').disabled=!sbMeta||sbMeta.duration<duration;
}
const position=$('sb-position');$('sb-match').onchange=()=>{$('sb-reason-label').hidden=$('sb-match').value!=='fallback';sbFixedUpdate();};
$('sb-reason').oninput=sbFixedUpdate;
position.oninput=()=>{$('sb-in').value=Number(position.value).toFixed(3);sbFixedUpdate();};position.onchange=()=>{if(sbMeta)$('sb-player').currentTime=Number(position.value);};
$('sb-in').addEventListener('input',sbFixedUpdate);$('sb-in').addEventListener('change',()=>{if(sbMeta&&Number($('sb-in').value)>=0&&Number($('sb-in').value)<sbMeta.duration)$('sb-player').currentTime=Number($('sb-in').value);});
action('sb-mark-in',()=>{$('sb-in').value=$('sb-player').currentTime.toFixed(3);sbFixedUpdate();});
function sbRange(){sbFixedUpdate();if(!sbAsset||!sbMeta)throw Error('请先打开原素材');const start=Number($('sb-in').value),length=sbFixedLength(),end=start+length;if(!Number.isFinite(start)||start<0||length<=0||end>sbMeta.duration+.000001)throw Error('素材剩余不足固定时长，请前移开始位置或更换素材');return {asset_id:sbAsset.id,name:sbAsset.name,rel:sbAsset.rel,root:sbAsset.root,path:sbAsset.source_path||sbAsset.rel,start,end,source_duration:sbMeta.duration,reason:$('sb-reason').value};};
const fixedRefreshBase=wfRefresh;wfRefresh=function(){fixedRefreshBase();sbFixedUpdate();};
const selectionStepBase=wfStep;wfStep=function(n){sbClearSource();wf.playRange=null;selectionStepBase(n);root.classList.toggle('sb-studio',wf.step===4);
 if(wf.step===4){
  if(imports.subtitle&&wf.cues.length&&!wf.dirtySubtitle&&(board.mode!=='subtitle'||!board.tasks.length||board.context!==sbContext()))syncSavedSubtitleTasks();
  for(const video of shotPreview.videos){
   shotPreview.entries.get(video)?.cancel?.();shotPreview.entries.delete(video);
   if(video.hasAttribute('src')){video.removeAttribute('src');video.load();}
  }
  shotPreview.activeKey=null;
 }
};
$('sb-proxy').hidden=true;$('sb-player').onerror=()=>{$('sb-proxy').hidden=false;$('sb-source-info').textContent+=' · 当前格式无法直接播放，可生成本地兼容预览';};$('sb-player').addEventListener('loadeddata',()=>{$('sb-proxy').hidden=true;});
action('sb-play-all',async()=>{if(wf.playing){wfPause();return;}if(!board.tasks.length)throw Error('请先同步字幕任务');await subtitlePlay(sbTask()||board.tasks[0],'all');});
sbFixedUpdate();
// 浏览器 timeupdate 有间隔，停止后回到精确选段出点，避免停留在范围之外。
$('sb-player').ontimeupdate=()=>{if(sbStop!==null&&$('sb-player').currentTime>=sbStop){const end=sbStop;sbStop=null;$('sb-player').pause();$('sb-player').currentTime=end;}};

// 下一步只导航，不代用户确认；把真实缺项和处理入口放在导航旁。
const sbGatePanel=el('section',undefined,'hint');sbGatePanel.id='sb-next-check';sbGatePanel.setAttribute('aria-live','polite');
const sbGateList=el('div');sbGateList.id='sb-next-issues';
sbGatePanel.append(el('strong','进入配乐前检查'),sbGateList);
root.querySelector('.wf-navigation').before(sbGatePanel);

function sbNavigationIssues(){
 const issues=sbIssues().map(text=>({text,step:text==='请先采用或导入配音'?2:text===wfSubtitleIssue()?3:4}));
 if(!projectId)issues.unshift({text:'尚未保存工程',step:1});
 return issues;
}
function sbNavigationRefresh(){
 const active=wf.step===4;sbGatePanel.hidden=!active;
 if(!active)return;
 const issues=sbNavigationIssues();
 sbGateList.replaceChildren();
 for(const issue of issues){
  const row=el('div',undefined,'button-row');
  row.append(subtitleButton(issue.step===1?'去填写并保存工程':issue.text,()=>{
   if(issue.step!==4){wfStep(issue.step);$(issue.step===1?'project-name':issue.step===2?'voice':wf.dirtySubtitle?'wf-save-subtitles':'wf-generate-subtitles').focus();return;}
   const t=board.tasks.find((task,i)=>issue.text.startsWith(task.text+'：')||issue.text.startsWith(`第${i+1}条「${task.text}」`));
   if(t)subtitleSelectTask(t);
   const target=t?$('sb-tasks'):$('sb-tools').querySelector('summary');
   if(target.closest('details'))target.closest('details').open=true;
   target.scrollIntoView({block:'center'});target.focus();
  }));sbGateList.append(row);
 }
 if(!issues.length)sbGateList.append(el('p','检查通过，可以点击下一步进入配乐。'));
}
const sbNavigationRefreshBase=wfRefresh;wfRefresh=function(){sbNavigationRefreshBase();sbNavigationRefresh();};
const sbNavigationStepBase=wfStep;wfStep=function(n){
 if(n>4&&board.enabled&&sbNavigationIssues().length){
  sbNavigationStepBase(4);
  const remaining=sbNavigationIssues();
  if(remaining.length){
   sbNavigationRefresh();sbGatePanel.scrollIntoView({block:'center'});
   notice(`还有 ${remaining.length} 项待处理，详见“进入配乐前检查”。`,true);return;
  }
 }
 return sbNavigationStepBase(n);
};
sbNavigationRefresh();
