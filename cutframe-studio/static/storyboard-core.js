'use strict';
// 时间覆盖与确认签名独立于页面，便于检查跨段镜头和工程恢复。
const StoryboardCore = {
 signature(board, shots, context) {
  const stable=v=>Array.isArray(v)?v.map(stable):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,stable(v[k])])):v;
  return JSON.stringify(stable({tasks:board.tasks,candidates:board.candidates,shots,context}));
 },
 issues(board, shots, duration, fps=30) {
  const errors=[], tolerance=1/fps+.001, tasks=board.tasks||[];
  if(!tasks.length)errors.push('请先建立画面任务');
  let end=0;
  for(const t of [...tasks].sort((a,b)=>a.start-b.start)) {
   if(!Number.isFinite(t.start)||!Number.isFinite(t.end)||t.start<0||t.end<=t.start){errors.push('任务时间无效：'+t.text);continue;}
   if(t.start>end+tolerance)errors.push('画面任务有时间缺口');
   if(t.start<end-tolerance)errors.push('画面任务时间重叠');
   end=Math.max(end,t.end);
   if(!t.text.trim()||!t.need.trim())errors.push('请填写文案与画面需求');
   if(t.missing)errors.push('缺素材：'+t.text);
  }
  if(end<duration-tolerance||end>duration+tolerance)errors.push('画面任务需覆盖完整配音时长');
  let at=0;const intervals=[];
  for(const s of shots){
   const length=s.end-s.start;
   if(!Number.isFinite(length)||s.start<0||length<=0||Number.isFinite(s.source_duration)&&s.end>s.source_duration+tolerance)errors.push('镜头入出点超出可用范围');
   intervals.push({start:at,end:at+length,ids:s.task_ids||[]});at+=length;
   if(!(s.task_ids||[]).length||(s.task_ids||[]).some(id=>!tasks.some(t=>t.id===id)))errors.push('存在未关联画面任务的镜头');
  }
  if(!shots.length)errors.push('还没有采用镜头');
  if(Math.abs(at-duration)>tolerance)errors.push('镜头总时长与配音不一致，请修剪或补充镜头');
  for(const t of tasks){let cursor=t.start;for(const s of intervals){if(s.end<=t.start||s.start>=t.end)continue;if(!s.ids.includes(t.id)||s.start>cursor+tolerance)break;cursor=Math.max(cursor,Math.min(s.end,t.end));}if(cursor<t.end-tolerance)errors.push('对应时段未被关联镜头覆盖：'+t.text);}
  return [...new Set(errors)];
 }
};
if(typeof module!=='undefined')module.exports=StoryboardCore;
