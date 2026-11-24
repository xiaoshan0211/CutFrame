const assert=require('node:assert/strict'),C=require('./static/subtitle-board-core.js');
let serial=0;const id=()=>`t${++serial}`;
const cues=[{start:0,end:1.14,text:'第一句'},{start:1.14,end:4,text:'第二句'}];let {tasks}=C.sync([],cues,0,id);tasks.forEach(t=>t.need='测试画面');
const shots=[{task_ids:[tasks[0].id],start:1,end:3,source_duration:9,available_end:3},{task_ids:[tasks[0].id],start:4,end:7,source_duration:9,available_end:7}];tasks[0].split=.4;C.layout(tasks[0],shots);assert.equal(shots[0].end,1.4);assert.equal(shots[1].timeline_start,.4);assert.equal(C.errors(tasks[0],shots).length,0);
const signature=C.signature(tasks[0],shots,'context');const restored=JSON.parse(JSON.stringify({tasks,shots}));assert.equal(C.signature(restored.tasks[0],restored.shots,'context'),signature);
const snapshot=JSON.stringify(shots);tasks[0].split=NaN;assert.throws(()=>C.layout(tasks[0],shots));assert.equal(JSON.stringify(shots),snapshot);tasks[0].split=.4;
tasks[0].accepted=signature;let synced=C.sync(tasks,[{...cues[0],end:1.3},{...cues[1],start:1.3}],0,id);assert.equal(synced.tasks[0].id,tasks[0].id);assert.equal(synced.tasks[0].accepted,null);assert.equal(shots[0].end,1.4);
synced=C.sync(tasks,[cues[1]],0,id);assert.equal(synced.tasks[0].id,tasks[1].id);assert.equal(synced.removed[0].id,tasks[0].id);
assert.equal(C.gaps(cues,4).length,0);assert(C.gaps([{start:.2,end:1},{start:1.5,end:3}],4).length===3);
shots[0].fallback=true;assert(C.errors(tasks[0],shots).some(x=>x.includes('替代')));shots[0].fallback_confirmed=true;assert.equal(C.errors(tasks[0],shots).length,0);
shots[0].start=8;assert.throws(()=>C.layout(tasks[0],shots));
console.log('字幕任务：固定时间、双镜、原子回退、保存恢复、同步保留、删除归档、间隙、替代确认检查通过');
// 候选直接选入：不能回退到原片零秒，也不能在确认前修改工程。
const task={id:'direct',text:'再过一个月',need:'人物',start:0,end:.78};
const originalShots=[{asset_id:'old',task_ids:['direct'],start:0,end:.78,timeline_start:0,available_end:1,source_duration:9}];
const candidate={id:'c',task_id:'direct',asset_id:'new',name:'人物',start:1.5,end:2.3,source_duration:9};
const originalJSON=JSON.stringify(originalShots);const plan=C.candidatePlan(task,originalShots,candidate,'0');
assert.equal(plan.shot.start,1.5);assert(Math.abs(plan.shot.end-2.28)<1e-9);assert.equal(plan.shot.timeline_start,0);assert.equal(JSON.stringify(originalShots),originalJSON);
assert(C.sameCandidate(candidate,{...candidate,id:'different',reason:'changed'}));assert(!C.sameCandidate(candidate,{...candidate,task_id:'other'}));assert(!C.sameCandidate(candidate,{...candidate,start:1.6}));
assert.throws(()=>C.candidatePlan(task,originalShots,{...candidate,end:1.6},'0'));assert.equal(JSON.stringify(originalShots),originalJSON);
console.log('候选源入点保留、确认前无修改、短素材拒绝、同任务去重与跨任务独立通过');
const t={id:'dual',text:'旧房',need:'沟通加旧房',start:1.84,end:5.2,split:3.52,planned_shots:2};
const c={task_id:'dual',asset_id:'b',start:1,end:3,source_duration:32};
const first=C.candidatePlan(t,[],c);assert(Math.abs(first.shot.end-2.68)<1e-8);assert(C.errors(first.task,first.shots).length>0);
const saved=JSON.parse(JSON.stringify(first));const second=C.candidatePlan(saved.task,saved.shots,{...c,asset_id:'room'});assert.equal(C.errors(second.task,second.shots).length,0);assert.equal(second.task.split,3.52);
const remaining=second.shots.slice(1);C.layout(second.task,remaining);assert.equal(remaining[0].timeline_start,3.52);assert(C.errors(second.task,remaining).length>0);
const refilled=C.candidatePlan(second.task,remaining,c);assert.equal(C.errors(refilled.task,refilled.shots).length,0);
assert.throws(()=>C.candidatePlan({...t,split:6},[],c));console.log('双镜分步选入、保存恢复、缺口阻止确认、删除后补原槽位通过');

