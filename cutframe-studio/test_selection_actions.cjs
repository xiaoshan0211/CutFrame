const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const dir=process.argv[2]||path.join(__dirname,'static');
const read=name=>fs.readFileSync(path.join(dir,name),'utf8');
const source=read('local-selection.js'),board=read('subtitle-board.js');
async function main(){
 const controls={'manual-find':{},'manual-note':{},'manual-label':{value:'V03',selectedOptions:[{textContent:'团队上门'}]},'manual-dimension':{value:'画面类型'},'ai-scope':{value:'cloud'},'ai-count':{scrollIntoView(){}}};
 let key='task1',requests=0,reply;
 const env={$:id=>controls[id],aiTaskKey:()=>key,localTaskKey:key,localView:{},board:{context:'ctx'},sbContext:()=>'ctx',projectId:'p',localRequests:new Map(),localSearch:async(trigger,query)=>{
   requests++;assert.equal(query.conditions.must[0].tags[0],'V03');return reply();
 }};
 vm.createContext(env);vm.runInContext(source.slice(source.indexOf('async function localManualSearch'),source.indexOf('function localEnsurePanel')),env);
 assert.match(source,/\$\('manual-find'\)\.onclick=localManualSearch/);
 const note=controls['manual-note'];
 reply=()=>({result:{items:[1,2]}});await env.localManualSearch();assert.match(note.textContent,/2 条候选/);
 reply=()=>({result:{items:[]}});await env.localManualSearch();assert.match(note.textContent,/0 条候选/);
 reply=()=>{throw Error('连接中断')};await env.localManualSearch();assert.match(note.textContent,/检索失败.*连接中断/);assert.equal(controls['manual-find'].disabled,false);
 env.localRequests.set(key,{});await env.localManualSearch();assert.match(note.textContent,/正在检索/);assert.equal(requests,3);env.localRequests.clear();
 let finish;reply=()=>new Promise(r=>finish=r);const pending=env.localManualSearch();key='task2';note.textContent='下一条';finish({result:{items:[1]}});await pending;assert.equal(note.textContent,'下一条');
 const candidate={run:{id:'current',review:{records:{}}},item:{id:'c',slot:'A'}};
 const elements={'sb-in':{value:'0'},'sb-match':{value:'direct'},'sb-adopt':{}};
 let latest=false,resolveAspect,apiCalls=[];
 const edit={$:id=>elements[id],board:{mode:'subtitle',tasks:[]},aiRun:()=>candidate.run,slotIsLatest:()=>latest,sbMeta:{duration:5},sbFixedLength:()=>1.6,sbFixedUpdate(){},sbApprovedCandidate:()=>candidate,sbTask:()=>({}),subtitleTaskShots:()=>[],sbRange:()=>({asset_id:'asset'}),sbReplace:null,sbSelectVersion:0,aiTaskKey:()=>'t',shots:[],notice(){},api:async url=>{apiCalls.push(url);return new Promise(r=>resolveAspect=r)}};
 vm.createContext(edit);vm.runInContext(board.slice(board.indexOf('function sbAdoptProblem'),board.indexOf('function sbFixedLength')),edit);
 vm.runInContext(board.slice(board.indexOf('let sbSavingShot'),board.indexOf('const issuesOld')),edit);
 assert.match(edit.sbAdoptProblem(null),/历史批次/);await elements['sb-adopt'].onclick();assert.equal(apiCalls.length,0);
 latest=true;assert.equal(edit.sbAdoptProblem(candidate),'');const save=elements['sb-adopt'].onclick();await elements['sb-adopt'].onclick();assert.equal(apiCalls.length,1);
 edit.sbSelectVersion++;resolveAspect({allowed:true});await save;assert.equal(apiCalls.length,1);assert.equal(vm.runInContext('sbSavingShot',edit),false);
 const widgets=Object.fromEntries(['job-panel','job-title','job-message','cancel-job','progress'].map(id=>[id,{}]));
 const jobs={jobId:null,$:id=>widgets[id],notice(){},api:async()=>({status:'done',progress:100,kind:'生成单行字幕',result:{}})};
 vm.createContext(jobs);
 const app=read('app.js');vm.runInContext(app.slice(app.indexOf('async function watch('),app.indexOf("document.querySelectorAll('[data-view]')",app.indexOf('async function watch('))),jobs);
 let called=0;await jobs.watch('j1',()=>called++);assert.equal(called,1);assert.equal(widgets['job-panel'].hidden,true);
 jobs.api=async()=>({status:'failed',message:'字幕任务失败'});await jobs.watch('j2');assert.equal(widgets['job-panel'].hidden,false);
 console.log('通过：手动有结果、零结果、失败恢复、并发提示、跨字幕迟到响应、历史只读、可选当前镜头、连点保护、切换中止。');
}
main().catch(e=>{console.error(e);process.exitCode=1});
