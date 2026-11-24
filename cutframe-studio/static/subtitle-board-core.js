'use strict';
const SubtitleBoardCore = {
 sameContext(a,b){
  try{const normalize=s=>{const v=JSON.parse(s);if(!Array.isArray(v.cues)||!v.voice)throw Error('上下文不完整');delete v.subtitle;for(const k of ['fps','voiceOffset','subtitleOffset'])v[k]=Number(v[k]);return JSON.stringify(this.stable(v));};return normalize(a)===normalize(b);}catch{return false;}
 },
 playbackPlan(tasks,shots,duration){
  const result=structuredClone(shots),errors=[],gaps=[];
  if(tasks.length&&tasks[0].start>.001)errors.push(`片头 0.00–${tasks[0].start.toFixed(2)} 秒没有上一镜头，需手动选片`);
  tasks.forEach((t,i)=>{const next=tasks[i+1],to=next?next.start:duration,extra=to-t.end;
   if(extra<-.001){errors.push(`第${i+1}条与下一条时间重叠，请先修正字幕`);return;}if(extra<=.001)return;
   const ss=result.filter(s=>s.task_ids?.length===1&&s.task_ids[0]===t.id),last=ss.at(-1),gap={start:t.end,end:to,task_id:t.id,extra};
   if(!last){gap.pending=true;gap.error=`第${i+1}条「${t.text}」待选镜头`;}
   else if(Math.abs(last.timeline_start+last.end-last.start-t.end)>.001)gap.error=`第${i+1}条「${t.text}」的镜头尚未覆盖字幕结尾，请补齐后再检查停顿`;
   else if(!Number.isFinite(last.source_duration)||last.end+extra>last.source_duration+.001)gap.error=`第${i+1}条「${t.text}」原片剩余不足，停顿需续播 ${extra.toFixed(2)} 秒；请提前该镜头开始位置或更换素材`;
   else {last.subtitle_end=last.end;last.gap_extension=extra;last.end+=extra;gap.source_end=last.end;}
   if(gap.error)errors.push(gap.error);gaps.push(gap);
  });return {shots:result,errors,gaps};
 },
 sameCandidate(a,b){return a.task_id===b.task_id&&a.asset_id===b.asset_id&&Math.round(a.start*1000)===Math.round(b.start*1000)&&Math.round(a.end*1000)===Math.round(b.end*1000);},
 candidatePlan(task,shots,candidate,target='append'){
  if(candidate.task_id!==task.id)throw Error('候选不属于当前字幕任务');
  if(!Number.isFinite(candidate.start)||!Number.isFinite(candidate.end)||candidate.start<0||candidate.end<=candidate.start)throw Error('候选时间范围无效');
  const next=structuredClone(shots),t=structuredClone(task),ss=next.filter(s=>s.task_ids?.includes(t.id));
  const shot={...structuredClone(candidate),task_ids:[t.id],available_end:candidate.end,fallback:!!candidate.fallback,fallback_confirmed:false};delete shot.task_id;delete shot.id;delete shot.rating;
  if(target==='append'){if(ss.length>=2)throw Error('本条已有两个镜头，请选择替换目标');next.push(shot);if(ss.length===1)t.split=(t.start+t.end)/2;}
  else{const index=Number(target);if(!Number.isInteger(index)||!ss[index])throw Error('替换目标已变化，请重新选择');next.splice(next.indexOf(ss[index]),1,shot);}
  if(t.planned_shots===2){t.split=task.split;shot.slot=target==='append'?[0,1].find(i=>!ss.some((s,j)=>(s.slot??j)===i)):(ss[Number(target)].slot??Number(target));}
  this.layout(t,next);t.accepted=null;return {task:t,shots:next,shot};
 },
 stable(v){return Array.isArray(v)?v.map(x=>this.stable(x)):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,this.stable(v[k])])):v;},
 signature(t,shots,context){return JSON.stringify(this.stable({text:t.text,start:t.start,end:t.end,need:t.need,split:t.split??null,shots:shots.filter(s=>s.task_ids?.includes(t.id)),context}));},
 layout(t,shots){
  const ss=shots.filter(s=>s.task_ids?.includes(t.id));if(!ss.length||ss.length>2)throw Error('每条需要一至两个镜头');
  const dual=t.planned_shots===2;
  if((dual||ss.length===2)&&!(Number.isFinite(t.split)&&t.split>t.start&&t.split<t.end))throw Error('双镜切点必须在字幕入出点之间');
  let at=t.start;const ranges=ss.map((s,i)=>{const slot=dual?(s.slot??i):i;
   if(dual){if(![0,1].includes(slot)||ss.some((x,j)=>j<i&&(x.slot??j)===slot))throw Error('镜头位置重复');at=slot===0?t.start:t.split;}
   const end=(dual?slot===0:ss.length===2&&i===0)?t.split:t.end,length=end-at;
   if(!Number.isFinite(end)||length<=0||s.start+length>Math.min(s.source_duration,s.available_end??Infinity)+.001)throw Error('所选源片段不够长或切点无效，请调整源出点或换片');
   const range={timeline_start:at,end:s.start+length,...(dual?{slot}:{})};at=end;return range;});
  ss.forEach((s,i)=>Object.assign(s,ranges[i]));shots.sort((a,b)=>(a.timeline_start??0)-(b.timeline_start??0));
 },
 errors(t,shots){const ss=shots.filter(s=>s.task_ids?.includes(t.id)),e=[];
  if(!ss.length)return ['本条字幕还没有选入镜头，请选入合适的素材。'];
  if(ss.length>2)e.push('需要一至两个镜头');if(t.planned_shots===2&&ss.length!==2)e.push('双镜字幕还缺一个镜头');let at=t.start;
  for(const s of ss){if(!Number.isFinite(s.timeline_start)||Math.abs(s.timeline_start-at)>.001)e.push('镜头位置与字幕不一致');if(!Number.isFinite(s.end-s.start)||s.end<=s.start||s.start<0||s.end>Math.min(s.source_duration,s.available_end??Infinity)+.001)e.push('源片段范围无效');if(s.fallback&&!s.fallback_confirmed)e.push('替代画面尚未确认');at+=s.end-s.start;}
  if(Math.abs(at-t.end)>.001)e.push('镜头未准确覆盖本条字幕');return [...new Set(e)];
 },
 gaps(tasks,duration){const e=[];let at=0;for(const t of tasks){if(t.start>at+.001)e.push(`时间间隙 ${at.toFixed(2)}–${t.start.toFixed(2)} 秒，等待你决定`);if(t.start<at-.001)e.push(`时间重叠 ${t.start.toFixed(2)}–${at.toFixed(2)} 秒，请回第三步处理`);at=t.end;}if(duration>at+.001)e.push(`末尾间隙 ${at.toFixed(2)}–${duration.toFixed(2)} 秒，等待你决定`);return e;},
 sync(tasks,cues,offset,id){
  const used=new Set();const fresh=cues.map((c,i)=>{let old=tasks.find(t=>!used.has(t.id)&&t.text===c.text&&Math.abs(t.start-c.start-offset)<.001&&Math.abs(t.end-c.end-offset)<.001);
   if(!old){const matching=tasks.filter(t=>!used.has(t.id)&&t.text===c.text);if(matching.length===1)old=matching[0];}
   if(!old&&tasks.length===cues.length&&!used.has(tasks[i]?.id))old=tasks[i];
   if(old)used.add(old.id);const changed=!old||old.text!==c.text||Math.abs(old.start-c.start-offset)>.001||Math.abs(old.end-c.end-offset)>.001;
   return {...(old||{id:id(),need:'',role:'字幕镜头',missing:false}),text:c.text,start:c.start+offset,end:c.end+offset,accepted:changed?null:old.accepted};
  });return {tasks:fresh,removed:tasks.filter(t=>!used.has(t.id))};
 }
};
if(typeof module!=='undefined')module.exports=SubtitleBoardCore;
