// 在真实的第四步前端函数间交错接口返回，覆盖手机切步、切句和断网重试。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const directory = process.argv[2] || path.join(__dirname, 'static');
const local = fs.readFileSync(path.join(directory,'local-selection.js'),'utf8').replaceAll('\r\n','\n');
const cards = fs.readFileSync(path.join(directory,'ai-candidates.js'),'utf8').replaceAll('\r\n','\n');
const turn = () => new Promise(resolve=>setImmediate(resolve));
function section(code, from, until) {
  const a=code.indexOf(from), b=code.indexOf(until,a+1);
  assert.ok(a>=0 && b>a, from);
  return code.slice(a,b);
}
function make() {
  const elements=new Map(), pending=[], calls=[], histories=[], searches=[], timers=new Set();
  function element(id){
    if(!elements.has(id))elements.set(id,{replaceChildren(){},append(){},querySelector(){return {};},closest(){return {};}});
    return elements.get(id);
  }
  const tasks={A:{text:'甲'},B:{text:'乙'}};
  const view=(action='核对甲')=>({id:'P0001',title:'测试',action,entry_id:'P0001',primary:['V01'],defaults:['V01'],status:'人工确认'});
  const box={wf:{step:4},projectId:'p',board:{context:'board'},imports:{subtitle:'s'},materialScope:'xiaoq',localTree:{labels:[]},
    localTaskKey:'',localTaskPromise:null,localView:null,localAppliedTypes:[],localSuggestion:null,localLoading:0,localTypeChanges:[],
    localRequests:new Map(),aiContextKey:'',aiRuns:[],selected:'A',localCleanVersion:'',
    sbTask:()=>tasks[box.selected],aiTaskKey:()=>box.selected+':'+(tasks[box.selected].need||''),sbContext:()=>'board',
    annotationEntryControl(){},localNeighbors:()=>({}),localEnsurePanel(){},localSetConditions(){},localNode:()=>element('local-node'),el:()=>element('node'),
    sbTasks(){},sbChanged(){box.aiSyncTask();},showMaterialScope(){},aiRender(){box.slotButtons();},sbFixedUpdate(){},
    $:element,aiRun:()=>null,localTypesEdited:()=>false,localSelectedTypes:()=>['V01'],
    aiHistory:async()=>{histories.push(box.selected);},localSearch:async trigger=>{searches.push([box.selected,trigger]);},
    setTimeout:fn=>{timers.add(fn);return fn;},clearTimeout:fn=>timers.delete(fn),
    api:(url,body)=>{const type=url.includes('labels?')?'labels':url.split('/').at(-1);calls.push(type);return new Promise((resolve,reject)=>pending.push({type,body,resolve,reject}));},
  };
  vm.createContext(box);
  vm.runInContext([section(local,"let localRetryKey=",'function annotationEntryControl'),
    section(local,'async function localStatus(', 'function localSummary'),
    section(local,'async function localSearchButton(', 'async function localSearch('),
    section(local,'function slotButtons(', 'let reserveKey='),section(cards,'let aiSyncVersion=', 'const selectionRefresh=')].join('\n'),box);
  async function reply(type,value,method='resolve',index=0){
    const p=pending.filter(p=>p.type===type)[index];assert.ok(p, '应发出 '+type);pending.splice(pending.indexOf(p),1);p[method](value);await turn();
  }
  async function metadata(){await reply('labels',{labels:[]});await reply('status',{clean_version:'v'});}
  return {box,element,pending,calls,histories,searches,view,metadata,reply,timers,tasks};
}

async function leaveAndReturn(){
  for(const phase of ['labels','status','viewpoint']){
    const h=make();const first=h.box.aiSyncTask();
    if(phase!=='labels')await h.reply('labels',{labels:[]});
    if(phase==='viewpoint')await h.reply('status',{clean_version:'v'});
    h.box.wf.step=3;h.box.aiSyncTask();
    await h.reply(phase,phase==='labels'?{labels:[]}:phase==='status'?{}:h.view('旧结果'));await first;
    assert.equal(h.pending.length,0);assert.equal(h.histories.length,0);assert.equal(h.box.localView,null);
    h.box.wf.step=4;const again=h.box.aiSyncTask();await h.metadata();await h.reply('viewpoint',h.view());await again;
    assert.equal(h.box.localView.action,'核对甲');assert.notEqual(h.element('local-search-state').textContent,'正在对照观点标注表…');
    assert.equal(h.element('ai-search').disabled,false);assert.deepEqual(h.histories,['A']);
    if(local.includes("await localSearch('auto');"))assert.deepEqual(h.searches,[['A','auto']]);
  }
}

async function revisit(){
  const h=make();const a=h.box.aiSyncTask();await h.metadata();
  h.box.selected='B';const b=h.box.aiSyncTask();await h.metadata();
  h.box.selected='A';const newA=h.box.aiSyncTask();await h.metadata();
  await h.reply('viewpoint',h.view('甲的最新动作'),'resolve',2);
  await h.reply('viewpoint',Error('过期错误'),'reject');await h.reply('viewpoint',h.view('乙动作'));
  await Promise.all([a,b,newA]);assert.equal(h.tasks.A.need,'甲的最新动作');assert.equal(h.tasks.B.need,undefined);assert.deepEqual(h.histories,['A']);
  assert.equal(h.element('ai-search').disabled,false);
}

async function failures(){
  for(const phase of ['labels','status','viewpoint','timeout']){
    const h=make();const first=h.box.aiSyncTask();
    if(phase!=='labels')await h.reply('labels',{labels:[]});
    if(!['labels','status'].includes(phase))await h.reply('status',{clean_version:'v'});
    if(phase==='timeout'){for(const fn of h.timers)fn();await turn();}else await h.reply(phase,Error('模拟网络中断'),'reject');
    await first;assert.match(h.element('local-search-state').textContent,/加载失败/);assert.equal(h.element('ai-search').disabled,false);
    assert.equal(h.element('ai-search').textContent,'重新加载本句选片');const count=h.calls.length;h.box.aiSyncTask();assert.equal(h.calls.length,count);
    const retry=h.box.localSearchButton();await h.metadata();
    if(phase==='timeout')await h.reply('viewpoint',h.view('超时旧结果'));
    await h.reply('viewpoint',h.view('重试成功'));await retry;
    assert.equal(h.box.localView.action,'重试成功');assert.deepEqual(h.histories,['A']);assert.equal(h.timers.size,0);
  }
}

Promise.all([leaveAndReturn(),revisit(),failures()]).then(()=>console.log('切步、同句重入、过期响应、接口失败、超时和重试通过')).catch(e=>{console.error(e);process.exitCode=1;});
