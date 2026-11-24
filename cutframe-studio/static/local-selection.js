'use strict';
// 本机查询入口。只调用 /api/local/*，三槽位审核与旧批次分别读取。
let localLabelsRequest=null,localTree=null,localTaskKey='',localSuggestion=null,localLoading=0,localTaskPromise=null,localTypeChanges=[],localControlNumber=0;
let localCleanVersion='';
let localView=null,localAppliedTypes=[];
const localRequests=new Map();
let materialRoots={},materialScope='all';
let cloudPage=1,cloudRequest=0,cloudPreview='';
async function loadCloudSegments(id){
 const box=$('cloud-segments'),player=$('cloud-player');
 box.replaceChildren();
 try{
  const {items}=await api('/api/materials/aliyun/segments/'+encodeURIComponent(id));
  if(cloudPreview!==id)return;
  box.append(el('h4','镜头内容 · 点击时间定位'));
  if(!items.length)box.append(el('p','这条原片还没有导入云端秒段。'));
  for(const row of items){
   const line=el('p'),jump=el('button',row.start+'–'+row.end+' 秒');
   jump.type='button';jump.onclick=()=>{
    const seek=()=>{if(cloudPreview===id){player.currentTime=row.start;player.play().catch(()=>{});}};
    if(player.readyState)seek();else player.addEventListener('loadedmetadata',seek,{once:true});
   };
   line.append(jump,document.createTextNode(' '+row.text));box.append(line);
  }
 }catch(e){if(cloudPreview===id)box.textContent=e.message;}
}
async function loadCloudLibrary(){
 const serial=++cloudRequest,shown=materialScope==='aliyun-import',player=$('cloud-player');
 $('cloud-library').hidden=!shown;cloudPreview='';player.pause();player.removeAttribute('src');player.load();player.hidden=true;
 $('cloud-proxy').hidden=true;$('cloud-playing').textContent='';$('cloud-list').replaceChildren();$('cloud-segments').replaceChildren();
 if(!shown)return;
 try{
  const params=new URLSearchParams({root:materialScope,page:String(cloudPage),q:$('cloud-query').value.trim()});
  const data=await api('/api/assets?'+params);
  if(serial!==cloudRequest)return;
  $('cloud-count').textContent=data.total?'共 '+data.total+' 条 · 第 '+cloudPage+' 页':$('cloud-query').value?'没有匹配的原片。':'还没有导入原片。';
  $('cloud-prev').disabled=cloudPage<=1;$('cloud-next').disabled=cloudPage*60>=data.total;
  for(const row of data.items){
   const b=el('button',row.name);b.type='button';b.title=row.rel.split('/').slice(1).join('/');
   b.onclick=()=>{cloudPreview=row.id;$('cloud-playing').textContent=b.title;player.hidden=false;player.src='/media/'+row.id;
    $('cloud-proxy').hidden=true;player.play().catch(()=>{});loadCloudSegments(row.id);};$('cloud-list').append(b);
  }
 }catch(e){if(serial===cloudRequest)$('cloud-count').textContent=e.message;}
}
$('cloud-player').onerror=()=>{$('cloud-proxy').hidden=!cloudPreview;};
action('cloud-proxy',async()=>{
 if(jobId)throw Error('请先等待当前任务完成');
 const id=cloudPreview;if(!id)return;
 const data=await api('/api/proxy/'+id,{});
 const play=r=>{if(cloudPreview===id){$('cloud-player').src=r.url;$('cloud-player').play().catch(()=>{});}};
 if(data.url)play(data);else await watch(data.job_id,play);
});
$('cloud-query').oninput=()=>{cloudPage=1;loadCloudLibrary();};
$('cloud-prev').onclick=()=>{cloudPage=Math.max(1,cloudPage-1);loadCloudLibrary();};
$('cloud-next').onclick=()=>{cloudPage++;loadCloudLibrary();};
function materialScopeOptions(select){
 select.replaceChildren();
 localOption(select,'all','本地素材 · 全部原片库',materialScope==='all');
 const raw=Object.entries(materialRoots).filter(([,r])=>r.role==='raw');
 for(const [id,r] of raw)localOption(select,id,(r.origin==='cloud'?'云端素材 · ':'本地素材 · ')+r.label,id===materialScope);
 if(!raw.some(([,r])=>r.origin==='cloud')){
  localOption(select,'','云端素材 · 尚未连接');select.lastElementChild.disabled=true;
 }
 if(materialScope!=='all'&&!raw.some(([id])=>id===materialScope)){
  localOption(select,materialScope,'工程已选素材库 · '+materialScope+'（暂不可用）',true);
 }
}
function showMaterialScope(){
 const link=document.querySelector('a[download][href*="slot-export"]');if(link)link.href='/api/local/slot-export?scope='+encodeURIComponent(materialScope);
 for(const id of ['wf-material-scope','ai-scope'])if($(id))materialScopeOptions($(id));
}
function changeMaterialScope(scope){
 if(!scope||scope===materialScope)return;
 materialScope=scope;showMaterialScope();
 cloudPage=1;loadCloudLibrary();
 sbRequest++;$('sb-results').replaceChildren();$('sb-file-search').open=false;
 $('sb-root').replaceChildren();sbClearSource();
 wfChanged();
}
$('wf-material-scope').onchange=e=>changeMaterialScope(e.target.value);
api('/api/state').then(s=>{materialRoots=s.roots;showMaterialScope();}).catch(e=>notice(e.message,true));
const materialProject=project;
project=function(){const data=materialProject();data.workflow.material_scope=materialScope;return data;};
const materialOpen=wfOpen;
wfOpen=async function(data){
 if(jobId)return materialOpen(data);
 materialScope=data.workflow?.material_scope||'all';showMaterialScope();$('sb-root').replaceChildren();
 cloudPage=1;$('cloud-query').value='';loadCloudLibrary();
 return materialOpen(data);
};
async function importCloudMaterials(files,links){
 const buttons=['cloud-pick-files','cloud-pick-folder','cloud-fetch'].map($);
 if(buttons.some(b=>b.disabled))return;
 const queue=files?Array.from(files).filter(f=>/\.(mp4|mov|mkv|avi|wmv|m4v|mts|m2ts|webm)$/i.test(f.name)):links;
 const result=$('cloud-result'),errors=$('cloud-errors');errors.replaceChildren();
 if(!queue.length){result.textContent=files?'没有找到可导入的视频文件。':'请粘贴 OSS 视频下载链接。';return;}
 const startProject=projectId,startScope=materialScope;
 let added=0,duplicates=0,failed=0;
 buttons.forEach(b=>b.disabled=true);
 try{
  for(const [i,v] of queue.entries()){
   const name=files?(v.webkitRelativePath||v.name):'链接 '+(i+1);
   result.textContent='正在导入 '+(i+1)+' / '+queue.length+' · '+name;
   try{
    let data;
    if(files){
     const response=await fetch('/api/materials/aliyun/file?'+new URLSearchParams({name}),{
      method:'POST',headers:{'X-Local-Token':token,'Content-Type':'application/octet-stream'},body:v});
     data=await response.json();if(!response.ok)throw Error(data.error||response.statusText);
    }else{
     const parts=v.split('\t');data=await api('/api/materials/aliyun/oss',parts.length===2?{name:parts[0],url:parts[1]}:{url:v});
    }
    if(data.duplicate)duplicates++;else added++;
   }catch(e){failed++;errors.append(el('li',name+' · '+e.message));}
  }
  result.textContent='已导入 '+added+' 条，已有 '+duplicates+' 条，失败 '+failed+' 条。';
  if(added+duplicates){
   if(materialScope==='aliyun-import')await loadCloudLibrary();
   else if(startProject&&projectId===startProject&&materialScope===startScope)changeMaterialScope('aliyun-import');
   result.textContent+=' 在「按文件名找一条」可浏览原片，标好画面类型和秒段后可按文案推荐。';
  }
  if(!files&&!failed)$('cloud-urls').value='';
 }finally{buttons.forEach(b=>b.disabled=false);}
}
for(const [button,input] of [['cloud-pick-files','cloud-files'],['cloud-pick-folder','cloud-folder']]){
 $(button).onclick=()=>$(input).click();
 $(input).onchange=()=>{const files=Array.from($(input).files);$(input).value='';return importCloudMaterials(files,null);};
}
$('cloud-fetch').onclick=()=>importCloudMaterials(null,$('cloud-urls').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean));
function localSelectedTypes(){return localChecks().filter(o=>o.checked).map(o=>o.value);}
function localTypesEdited(run){
 const types=localSelectedTypes();
 if(!types.length)return false;
 if(types.length!==localAppliedTypes.length||types.some(t=>!localAppliedTypes.includes(t)))return true;
 if(!run)return false;
 const query=localReadConditions(),prior=run.payload;
 const rows=conditions=>['must','prefer','forbid'].map(group=>(conditions[group]||[]).map(r=>[r.dimension,[...r.tags].sort()]));
 return JSON.stringify(rows(query.conditions))!==JSON.stringify(rows(prior.conditions))||
  JSON.stringify(query.keywords)!==JSON.stringify(prior.keywords||[])||
  ($('ai-scope').value||'all')!==(prior.scope||'all')||$('ai-experience').checked!==!!prior.use_experience;
}
function localChecks(){return [...$('local-picture').querySelectorAll('input')];}
function localNeighbors(){
 const tasks=[...board.tasks].sort((a,b)=>a.start-b.start||a.end-b.end),i=tasks.indexOf(sbTask());
 function side(step){
  const parts=[];let chars=0;
  for(let j=i+step;i>=0&&j>=0&&j<tasks.length&&chars<128&&parts.length<128;j+=step){
   const value=tasks[j].text;parts.push(value);chars+=value.replace(/[\s，。！？、]/g,'').length;
  }
  return step<0?parts.reverse():parts;
 }
 return {leading:side(-1),trailing:side(1)};
}
function localNode(tag,text,attrs={}){const n=el(tag,text);if(typeof attrs==='string')n.className=attrs;else for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;}
function localOption(select,value,label,selected=false){const o=localNode('option',label,{value});o.selected=selected;select.append(o);}
function localRuleConditions(input){const result={must:[],prefer:[],forbid:[]};let omitted=0;for(const group of Object.keys(result)){for(const r of input?.[group]||[]){if(r.explanation_only||r.structure_status==='只作说明，不参与判断')continue;if(!r.tags?.length){omitted++;continue;}result[group].push({dimension:r.dimension,tags:[...r.tags],raw:r.raw||''});}}return {conditions:result,omitted};}
async function localManualSearch(){
 const button=$('manual-find'),note=$('manual-note'),choice=$('manual-label');
 const label=choice.value,key=aiTaskKey(),scope=$('ai-scope').value,dimension=$('manual-dimension').value;
 const current=()=>key===aiTaskKey()&&scope===$('ai-scope').value&&dimension===$('manual-dimension').value&&label===choice.value;
 if(!label){note.textContent='请先选择一个检索条件。';return;}
 if(!localView||localTaskKey!==key||board.context!==sbContext()||!projectId){note.textContent='当前字幕任务尚未就绪。';return;}
 if(localRequests.has(key)){note.textContent='当前字幕正在检索，请稍候。';return;}
 const name=choice.selectedOptions[0]?.textContent||label;
 button.disabled=true;note.textContent='正在查找「'+name+'」…';
 try{
  const result=await localSearch('changed',{manual_browse:true,conditions:{must:[{dimension,tags:[label]}],prefer:[],forbid:[]},keywords:[]});
  if(!current())return;
  if(!result){note.textContent='字幕任务已变化，请重新检索。';return;}
  const count=result.result.items.length;
  note.textContent='「'+name+'」找到 '+count+' 条候选。'+(count?'':'可展开「查看过滤原因」核对本次条件。');
  if(count)$('ai-count').scrollIntoView({block:'nearest'});
 }catch(e){if(current())note.textContent='检索失败：'+e.message;}
 finally{button.disabled=!choice.value;}
}
function localEnsurePanel(){
 if($('local-conditions'))return;
 const box=localNode('section',undefined,{id:'local-conditions',class:'local-conditions'});
 box.innerHTML='<div id="local-viewpoint" aria-live="polite"></div><p id="local-search-state" role="status"></p><details id="local-edit-types"><summary>改这一句的类型</summary><p id="local-alternatives" class="small"></p><fieldset><legend>必须的画面类型</legend><div id="local-picture"></div></fieldset><div class="button-row"><button type="button" id="types-once">仅本次检索</button></div><p id="types-feedback" role="status"></p><div id="local-extra"></div><button id="local-add" type="button">添加其他维度条件行</button><label>描述关键词（逗号或空格分隔）<input id="local-keywords" placeholder="例如：批刮、垃圾、厨房"></label><details><summary>草稿规则建议</summary><div id="local-suggestion">先选择字幕。</div><button id="local-apply" type="button" disabled>套用为本条条件</button></details><p id="local-condition-note" class="small"></p><p id="local-draft-applied" class="small"></p></details>';

 const channels=el('div');channels.id='annotation-channels';
 $('ai-status').after(box);
 box.querySelector('#local-search-state').before(channels);
 async function applyTypes(){
  const key=aiTaskKey(),view=localView,task=sbTask(),status=$('types-feedback');
  if(!task||!view||key!==localTaskKey||!projectId||board.context!==sbContext()){status.textContent='请先打开当前工程的已保存字幕。';return;}
  if(localRequests.has(key)){status.textContent='当前检索进行中，请稍候。';return;}
  const primary=localSelectedTypes(),query={...localReadConditions(),manual_browse:true};
  if(!query.conditions.must.length&&!query.keywords.length){status.textContent='请选择一项素材表条件或填写关键词。';return;}
  $('types-once').disabled=true;
  try{
   await localSearch('changed',query);
   if(key===aiTaskKey())status.textContent=primary.length?'已按 '+primary.join('、')+' 检索。':'已按本次条件检索。';
  }catch(e){if(key===aiTaskKey())status.textContent=e.message;}
  finally{$('types-once').disabled=false;}
 }
 $('types-once').onclick=applyTypes;

 const manual=el('details');manual.id='manual-shots';
 manual.innerHTML='<summary>手动选镜头</summary><label>按什么找<select id="manual-dimension"><option>画面类型</option><option>素材类别</option></select></label><label>选择名称<select id="manual-label"></select></label><button type="button" id="manual-find">查看候选镜头</button><p id="manual-note" role="status"></p>';
 $('sb-file-search').before(manual);
 let request=0;
 async function fill(){
  const seq=++request,dim=$('manual-dimension').value,scope=$('ai-scope').value,select=$('manual-label');
  select.replaceChildren();$('manual-find').disabled=true;
  try{
   const tree=await api('/api/local/labels?scope='+encodeURIComponent(scope));
   if(seq!==request||scope!==$('ai-scope').value)return;
   const dimensions=$('manual-dimension');
   dimensions.replaceChildren();
   for(const d of [...tree.dimensions].sort((a,b)=>Number(b.id==='画面类型')-Number(a.id==='画面类型')))localOption(dimensions,d.id,d.name,d.id===dim);
   if(!dimensions.value&&dimensions.options.length)dimensions.selectedIndex=0;
   const options=tree.labels.filter(t=>t.dimension===dimensions.value).map(t=>[t.id,t.name]);
   if(seq!==request||scope!==$('ai-scope').value)return;
   for(const [value,name] of options)localOption(select,value,name);
   select.selectedIndex=0;
   if(dim==='画面类型'&&options.some(([id])=>id===localAppliedTypes[0]))select.value=localAppliedTypes[0];
   $('manual-find').disabled=!options.length;
   $('manual-note').textContent=options.length?'':'当前素材库没有可选名称。';
  }catch(e){if(seq===request)$('manual-note').textContent='读取名称失败：'+e.message;}
 }
 manual.ontoggle=()=>{if(manual.open)fill();};
 $('manual-dimension').onchange=fill;
 $('ai-scope').addEventListener('change',()=>{if(manual.open)fill();});
 $('manual-find').onclick=localManualSearch;
 const info=el('details');info.append(el('summary','检索设置与详情'));const tools=el('div',undefined,'selection-tools');box.after(tools);tools.append(info,manual);
 info.append($('ai-blocked'),$('ai-status'),$('ai-experience').closest('label'),$('ai-reviewer').closest('label'));
 $('ai-current').hidden=true;if(typeof workflowCompactSelection==='function')workflowCompactSelection();

 $('ai-search').textContent='找 5 条素材';
 box.addEventListener('input',slotButtons);
 $('ai-scope').addEventListener('change',e=>changeMaterialScope(e.target.value));
 $('ai-experience').addEventListener('change',slotButtons);
 $('local-picture').onchange=e=>{if(e.target.type==='checkbox')localTypeChanges.push({type:e.target.value,action:e.target.checked?'追加':'取消'});slotButtons();};
 $('local-add').onclick=()=>localExtraRow({dimension:localTree.dimensions.find(d=>d.id==='素材类别')?.id||localTree.dimensions[0]?.id,tags:[]},'must');
 $('local-apply').onclick=()=>{if(!localSuggestion)return;const compiled=localRuleConditions(localSuggestion.conditions);const keep=localChecks().filter(o=>o.checked).map(o=>o.value);compiled.conditions.must=compiled.conditions.must.filter(r=>r.dimension!=='画面类型');if(keep.length)compiled.conditions.must.unshift({dimension:'画面类型',tags:keep});localSetConditions(compiled.conditions,[]);slotButtons();$('local-draft-applied').textContent='已按你的操作套用草稿条件；'+(compiled.omitted?'其中 '+compiled.omitted+' 行未结构化，未作为查询条件，请查看原文补充判断。':'请核对原文限定语。');};
}
function localExtraRow(row,group){
 const box=localNode('div',undefined,{class:'local-condition-row'}),g=localNode('select',undefined,{'aria-label':'条件组'}),dimension=localNode('select',undefined,{'aria-label':'条件维度'}),tags=localNode('select',undefined,{multiple:'multiple','aria-label':'条件标签'});
 for(const [value,label]of [['must','必须'],['prefer','优先'],['forbid','禁止']])localOption(g,value,label,value===group);
 for(const d of localTree.dimensions||[])localOption(dimension,d.id,d.name||d.id,d.id===row.dimension);
 const pictures=localNode('div',undefined,{class:'local-extra-types'});
 function fill(selected=[]){pictures.replaceChildren();pictures.hidden=dimension.value!=='画面类型';tags.hidden=!pictures.hidden;
  if(!pictures.hidden){for(const option of localChecks()){
   const id='local-extra-type-'+(++localControlNumber),input=localNode('input',undefined,{type:'checkbox',id,value:option.value});
   input.checked=selected.includes(option.value);pictures.append(input,localNode('label',option.labels[0].textContent,{for:id}));
  }return;}
  tags.replaceChildren();for(const t of localTree.labels.filter(t=>t.dimension===dimension.value&&!t.group&&t.enabled))localOption(tags,t.id,t.id+' · '+t.name,selected.includes(t.id));}
 fill(row.tags);dimension.onchange=()=>fill();const remove=localNode('button','删除',{type:'button'});remove.onclick=()=>{box.remove();slotButtons();};box.append(g,dimension,tags,pictures,remove);box._local={group:g,dimension,tags,pictures};$('local-extra').append(box);
}
function localSetConditions(conditions,keywords){
 localEnsurePanel();$('local-extra').replaceChildren();const c=localRuleConditions(conditions).conditions;let picture=false;
 for(const o of localChecks())o.checked=false;
 for(const g of ['must','prefer','forbid'])for(const row of c[g]){if(g==='must'&&row.dimension==='画面类型'&&!picture){for(const o of localChecks())o.checked=row.tags.includes(o.value);picture=true;}else localExtraRow(row,g);}
 $('local-keywords').value=(keywords||[]).join('，');
}
function localReadConditions(){const conditions={must:[],prefer:[],forbid:[]};const picture=localChecks().filter(o=>o.checked).map(o=>o.value);if(picture.length)conditions.must.push({dimension:'画面类型',tags:picture});for(const box of $('local-extra').children){const row=box._local;const tags=[...(row.dimension.value==='画面类型'?row.pictures.querySelectorAll('input:checked'):row.tags.selectedOptions)].map(o=>o.value);if(tags.length)conditions[row.group.value].push({dimension:row.dimension.value,tags});}return {conditions,keywords:$('local-keywords').value.split(/[,，、\s]+/).filter(Boolean)};}
let localRetryKey='';
async function localLookup(url, body){
 let timer;
 try{
  return await Promise.race([api(url,body),new Promise((_,reject)=>{
   timer=setTimeout(()=>reject(Error('等待标注服务超过 30 秒')),30000);
  })]);
 }finally{clearTimeout(timer);}
}
function localLoadFailure(error){
 localRetryKey=aiTaskKey();localTaskKey='';localView=null;localAppliedTypes=[];
 $('local-search-state').textContent='本句选片加载失败 · '+error.message;
 $('local-edit-types').hidden=true;slotButtons();
}
function localLoadTask(){
 if(wf.step!==4)return;
 const t=sbTask(),key=aiTaskKey();
 if(key!==localTaskKey&&$('manual-note'))$('manual-note').textContent='';
 if(!t||!localTree||key!==localTaskKey)$('annotation-channels').replaceChildren();
 if(!t||!localTree){localTaskKey='';localLoading++;localView=null;localAppliedTypes=[];$('local-search-state').textContent='';$('local-edit-types').hidden=true;$('local-viewpoint').textContent='先选择字幕。';localSetConditions({},[]);return;}
 if(key===localTaskKey&&(localView||localTaskPromise))return localTaskPromise;
 localTaskKey=key;const serial=++localLoading;localView=null;localAppliedTypes=[];$('local-edit-types').open=false;$('local-edit-types').hidden=true;$('local-search-state').textContent='正在对照观点标注表…';$('local-viewpoint').replaceChildren();
 localTaskPromise=localFillTask(t,key,serial).catch(err=>{
  if(serial!==localLoading||wf.step!==4||localTaskKey!==aiTaskKey())return;
  localLoadFailure(err);throw err;
 }).finally(()=>{
  if(serial!==localLoading)return;
  localTaskPromise=null;
  if(!localView)localTaskKey='';
 });return localTaskPromise;
}
async function localFillTask(t,key,serial){
 const view=await localLookup('/api/local/viewpoint',{text:t.text,...localNeighbors()});
 if(serial!==localLoading||key!==aiTaskKey()||wf.step!==4)return;
 t=sbTask();
 const need=(t.need||'').trim(),oldPlaceholder='待核对原句的可见动作与对象：'+t.text;
 if(view.id&&view.action&&view.action!==oldPlaceholder&&(!need||need===oldPlaceholder)){
  t.need=view.action;t.accepted=null;
  key=aiTaskKey();localTaskKey=key;aiContextKey=key;sbTasks();sbChanged();
 }
 localView=view;localTypeChanges=[];localSuggestion=null;
 const edit=$('local-edit-types'),status=$('local-search-state'),box=$('local-viewpoint');
 const ambiguous=view.alternatives_by_id||[];
 box.replaceChildren(localNode('strong',view.joined?'本句属于 '+view.id:view.id?'本句 '+view.id+' · '+view.title:ambiguous.length?'对应多个观点 · '+t.text:'未匹配代表句 · '+t.text));
 if(view.joined)box.append(localNode('p',(view.equivalent?'按同义表达对上标注表整句：':'标注表整句：')+view.title),localNode('p','字幕原文：'+view.joined,'small'));
 for(const candidate of ambiguous)box.append(localNode('p',candidate.id+' · '+candidate.title+' · 主类型 '+(candidate.primary.join('、')||'空')));

 if(view.id)box.append(localNode('p',view.category+' · '+view.polarity+' · '+view.status,'small'));
 const typeRow=el('div',undefined,'annotation-type-row');
 const types=view.structured?.[0]?.['主画面类型']||view.primary.join('、');
 const typeText=view.primary.length?(view.entry_id?'主画面类型 · ':'相关代表句主类型 · ')+types:
  view.entry_id?view.entry_id+' · 主画面类型待定':ambiguous.length?'这句对应多个观点。':'尚未找到对应代表句。';
 const primaryText=el('span',typeText);primaryText.id='local-primary-text';typeRow.append(primaryText);$('types-feedback').textContent='';box.append(typeRow);
 if(view.fallback_types)box.append(localNode('p','可以直接找素材，本次先用 V01 · 人物对镜头、V02 · 握手与客户沟通、V05 · 施工批刮覆盖。','small'));
 annotationEntryControl($('annotation-channels'),t,key,view);
 if(!view.primary.length)for(const n of view.neighbors)box.append(localNode('p',n.label+' · '+(n.text?(n.id||'未匹配观点')+' · '+n.text+' · 主类型 '+(n.primary.join('、')||'空'):'无'),'small'));
 if(view.inherited)box.append(localNode('p','承接自 '+view.source_id+'「'+view.inherited+'」，使用 '+view.defaults.join('、')));
 edit.hidden=false;edit.querySelector('summary').textContent='高级条件 · 修改自动检索范围';
 $('local-alternatives').textContent=view.alternatives?.length?'标注表备选 · '+view.alternatives.join('、'):'';
 $('local-draft-applied').textContent='';
 const guidance=[view.action,view.forbidden?'禁止作为正面证明 · '+view.forbidden:''].filter(Boolean).join('　');
 $('local-condition-note').textContent=guidance?'标注表看片参考（供人工核对） · '+guidance:'';
 localAppliedTypes=[...view.defaults];
 localSetConditions({must:view.defaults.length?[{dimension:'画面类型',tags:view.defaults}]:[]},[]);
 $('local-suggestion').textContent='展开后读取本句草稿建议。';$('local-apply').disabled=true;
 const draft=$('local-suggestion').closest('details');draft.open=false;
 draft.ontoggle=async()=>{
  if(!draft.open||localSuggestion)return;
  try{const response=await api('/api/local/suggestion?text='+encodeURIComponent(t.text));
   if(serial!==localLoading||key!==aiTaskKey())return;
   localSuggestion=response.suggestion;const box=$('local-suggestion');box.replaceChildren();
   $('local-apply').disabled=!localSuggestion;
   if(!localSuggestion){box.textContent='没有匹配的规则建议。';return;}
   box.append(localNode('strong',localSuggestion.notice),localNode('p',localSuggestion.rule_id+' · '+localSuggestion.text));
   for(const [g,name] of [['must','必须'],['prefer','优先'],['forbid','禁止']])for(const row of localSuggestion.conditions[g]||[])box.append(localNode('p',name+' · '+row.raw+' · '+row.structure_status,'small'));
  }catch(e){if(serial===localLoading)notice(e.message,true);}
 };
 if(!projectId||board.context!==sbContext()){status.textContent=!projectId?'保存工程后即可检索。':wf.dirtySubtitle?'请先保存第三步修改过的字幕。':'本句任务待同步，点击下方按钮即可同步并检索。';slotButtons();return;}
 status.textContent='';await aiHistory(false);
 if(key!==aiTaskKey()||serial!==localLoading)return;
 const previous=aiRuns.find(r=>slotMatchesCurrent(r)&&r.payload.viewpoint?.id===view.id&&(r.payload.viewpoint?.joined||'')===view.joined&&!ambiguous.length);
 if(previous){$('ai-runs').value=previous.id;localRestoreBatch(previous);aiRender();}
 slotButtons();
}
function annotationEntryControl(host,task,key,view){
 const targets=view.annotation_targets;
 const query={text:task.text,...localNeighbors(),project_id:projectId,task_id:task.id,start:task.start,end:task.end};
 const status=localNode('p',undefined,{role:'status'});
 const active=()=>host.isConnected&&wf.step===4&&key===aiTaskKey()&&localView===view;
 host.replaceChildren();
 if(!Array.isArray(targets)){
  host.append(el('p','当前服务未返回代表句标注入口，请刷新后重试。'));return;
 }
 if(!targets.length){
  const submit=subtitleButton('送入文案表「待标注」',async()=>{
   if(!active())return;
   submit.disabled=true;
   try{
    const result=await api('/api/local/annotation-pending',{...query,reviewer:aiReviewer()});
    if(active()){submit.textContent='已在待标注表';status.textContent=result.message;}
   }catch(error){if(active()){status.textContent=error.message;submit.disabled=false;}}
  });
  if(view.annotation_pending){submit.disabled=true;submit.textContent='已在待标注表';}
  host.append(submit,status);
  return;
 }
 const details=el('details'),summary=el('summary','人工修订代表句标签');
 details.append(summary);host.append(details);
 const choose=el('select'),label=el('label','要修订的代表句'),form=el('div');
 if(targets.length>1)localOption(choose,'','请选择代表句',true);
 for(const target of targets)localOption(choose,target.id,target.id+' · '+target.title,targets.length===1);
 label.append(choose);details.append(label,form,status);
 let seq=0,loaded='';
 async function load(){
  const id=choose.value,generation=++seq;
  loaded='';form.replaceChildren();status.replaceChildren();
  if(!id)return;
  const current=()=>active()&&generation===seq;
  status.textContent='正在读取 '+id+' 的标注…';
  try{
   const entry=await api('/api/local/annotation-edit',{...query,id});
   if(!current())return;
   if(entry.id!==id)throw Error('代表句已变化，请重新选择。');
   loaded=id;status.replaceChildren();form.append(el('p',entry.id+' · '+entry.text));
   const writable=annotationCanRevise();
   if(!writable){
    form.append(el('p','请工作台管理员修订这条代表句的标签。'));
   }
   const fields={};
   function field(name,title,options){
    const control=el(options?'select':'textarea'),label=el('label',title);
    if(options)for(const [value,caption] of options)localOption(control,value,caption);
    control.value=entry.form[name]||'';control.disabled=!writable;
    label.append(control);form.append(label);fields[name]=control;
   }
   field('category','素材类别',[['','请选择素材类别'],...Object.entries(entry.categories).map(([code,row])=>[code,row['素材类别']])]);
   field('nature','对应性质',entry.natures.map(value=>[value,value]));
   field('polarity','肯否',entry.polarities.map(value=>[value,value]));
   const types=localTree.labels.filter(t=>t.dimension==='画面类型'&&/^V\d\d$/.test(t.id)&&!t.group&&t.enabled);
   function pictures(name,title){
    const group=el('details'),legend=el('summary'),inputs=[],names=new Map(types.map(t=>[t.id,t.name]));
    const selected=(entry.form[name]||'').match(/V\d\d/g)||[];
    for(const code of selected)if(!names.has(code))names.set(code,'原有标签');
    group.append(legend);form.append(group);
    const value=()=>inputs.filter(c=>c.checked).map(c=>c.value).join('、');
    const describe=()=>{legend.textContent=title+' · '+(value()||'未选择');};
    for(const [code,text] of [...names].sort(([a],[b])=>a.localeCompare(b))){
     const label=el('label',undefined,'ai-check'),input=localNode('input',undefined,{type:'checkbox',value:code});
     input.checked=selected.includes(code);input.disabled=!writable;input.onchange=describe;
     label.append(input,' '+code+' · '+text);group.append(label);inputs.push(input);
    }
    describe();return value;
   }
   const primary=pictures('primary','主画面类型'),alternative=pictures('alternative','备选画面类型');
   field('action','必须看见的动作或对象');field('limit','禁用与限制');
   if(!writable)return;
   const save=subtitleButton('保存 '+id+' 的标注',async()=>{
    if(!current())return;
    save.disabled=true;choose.disabled=true;
    const edited=Object.fromEntries(Object.entries(fields).map(([name,c])=>[name,c.value]));
    try{
     const result=await api('/api/local/annotation-revise',{...query,id,version:entry.version,reviewer:aiReviewer(),form:{...entry.form,...edited,primary:primary(),alternative:alternative()}});
     if(!current())return;
     notice(result.message||id+' 的标签已保存。');
     // 即使检索条件没有变化，也要重新读取修订后的代表句和候选批次。
     if(task.need===view.action&&result.view?.action!==undefined){task.need=result.view.action;sbTasks();sbChanged();}
     localTaskKey='';await localLoadTask();
    }catch(error){if(current()){status.textContent=error.message;save.disabled=false;choose.disabled=false;loaded='';}}
   });
   form.append(save);
  }catch(error){if(current())status.textContent=error.message+'。请收起后重新展开以重试。';}
 }
 choose.onchange=load;
 details.ontoggle=()=>{if(details.open&&loaded!==choose.value)load();};
}
function annotationCanRevise(){
 return typeof memberUser==='undefined'||memberUser?.role==='admin';
}
function localRestoreBatch(run){
 localAppliedTypes=run.payload.type_selection?.selected||[];
 localSetConditions({...run.payload.conditions,must:run.payload.conditions.must.filter(r=>r.dimension!=='素材类别')},run.payload.keywords);
 $('ai-experience').checked=!!run.payload.use_experience;
 localTypeChanges=[];
 const inherited=run.payload.viewpoint?.inherited;
 const manual=run.payload.type_source==='manual'||run.payload.trigger==='changed';
 const origin=manual?'手动指定':run.payload.type_source==='fallback'?'缺少主类型时的默认范围':inherited?'承接自 '+run.payload.viewpoint.source_id:'标注表 '+(localView?.source_id||'');
 $('local-search-state').textContent='本轮候选 '+run.result.items.length+'/'+(run.result.capacity||3)+(localAppliedTypes.length?' · '+localAppliedTypes.join('、'):'');
}
async function localStatus(isCurrent=()=>wf.step===4){
 if(!isCurrent())return;
 localEnsurePanel();$('local-conditions').hidden=false;
 const requestedScope=materialScope;const tree=await localLookup('/api/local/labels?scope='+encodeURIComponent(requestedScope));if(!isCurrent()||requestedScope!==materialScope)return;
 if(!localTree||JSON.stringify(tree)!==JSON.stringify(localTree)){localTree=tree;localTaskKey='';const picture=$('local-picture');picture.replaceChildren();for(const t of localTree.labels.filter(t=>t.dimension==='画面类型'&&/^V(?:0[1-9]|1\d|2[0-4])$/.test(t.id)&&!t.group&&t.enabled).sort((a,b)=>a.id.localeCompare(b.id))){const wrap=localNode('span'),id='local-type-'+t.id,input=localNode('input',undefined,{id,type:'checkbox',value:t.id});wrap.append(input,localNode('label',t.id+' · '+t.name,{for:id}));picture.append(wrap);}}
 const scope=materialScope,s=await localLookup('/api/local/status');if(!isCurrent()||scope!==materialScope)return;
 localCleanVersion=s.clean_version;
 $('ai-status').textContent=[s.message,s.classification_book,s.semantic_book&&('共用文案表 · '+s.semantic_book)].filter(Boolean).join(' · ');
 showMaterialScope();
 await localLoadTask();
}
function localSummary(r){return `${r.message} · 三层 ${r.layer_counts['1']} / ${r.layer_counts['2']} / ${r.layer_counts['3']} 条 · ${r.notice||''} · 过滤：${Object.entries(r.filters).map(([k,v])=>k+' '+v).join('；')||'无'}。`;}
function localCardDetails(card,c){
 if(c.root)card.append(localNode('p',(materialRoots[c.root]?.origin==='cloud'?'云端导入 · ':'本地素材 · ')+(materialRoots[c.root]?.label||c.root),'small'));
 if(c.matched_view)card.append(localNode('p','对应代表句 · '+c.matched_view));
 card.classList.add('local-card');card.append(localNode('strong',`第 ${c.layer} 层 · ${c.local_kind}`,{class:'local-layer'}));
 for(const r of c.condition_rows||[])card.append(localNode('p',`${({must:'必须',prefer:'优先',forbid:'禁止'})[r.group]} · ${r.dimension}：${r.tags.join(' / ')} · ${r.group==='forbid'?'未命中禁止标签':r.status}`));
 if(c.inherited)card.append(localNode('p','承接自「'+c.inherited+'」'));
 if(c.view_rules?.length)card.append(localNode('p','命中已确认选片规律 '+c.view_rules.join('、')));
 if(c.machine_description)card.append(localNode('p','机器描述原文：'+c.machine_description));
 if(c.classified_table)card.append(localNode('p','分类依据：'+c.classification_description),localNode('p',c.classified_table+' · '+c.classification_basis,'small'));
 for(const warning of c.warnings||[])card.append(localNode('p',warning,{class:'local-warning'}));
 if(c.history_text)card.append(localNode('p','历史采用时原句：'+c.history_text,{class:'local-history'}));

}
function exhaustedBatch(run){
 return run?.result.classified_pool&&run.result.items.length===0&&run.result.remaining===0&&run.result.unchecked_sources===0;
}
async function localSearchButton(){
 if(localRetryKey&&localRetryKey===aiTaskKey()){aiContextKey='';return aiSyncTask();}
 const run=aiRun();
 if(board.context===sbContext()&&run&&slotMatchesCurrent(run)&&exhaustedBatch(run)&&!localTypesEdited(run)){
  const edit=$('local-edit-types');edit.open=true;
  $('types-feedback').textContent='当前范围已无新候选。勾选其他合适类型后点「仅本次检索」，或在手动选镜头中查看已展示素材。';
  edit.scrollIntoView({block:'center'});localChecks().find(c=>c.checked)?.focus({preventScroll:true});return;
 }
 if(board.context===sbContext())return localSearch('changed');
 if(!wf.cues.length||wf.dirtySubtitle||!imports.subtitle)throw Error('请先在第三步保存字幕。');
 const task=sbTask();
 // 同步会触发正常的选句和自动检索，复用该请求。
 syncSavedSubtitleTasks();
 if(board.context!==sbContext()||!sbTask())return;
 await localLoadTask();
 if(sbTask()?.text===task?.text&&!aiRun())await localSearch('changed');
}
async function localSearch(trigger='changed',manualQuery=null){
 const t=sbTask(),key=aiTaskKey(),view=localView;
 if(!view||key!==localTaskKey||wf.step!==4||!t||!projectId||board.context!==sbContext())return;
 const run=aiRun();const current=run?.result.slot_review&&slotMatchesCurrent(run)?run:null;
 if(!manualQuery&&trigger==='changed'&&!localSelectedTypes().length){
  $('local-edit-types').open=true;
  $('local-search-state').textContent='先为本句勾选画面类型，再找 5 条素材。';
  localChecks()[0]?.focus();
  return;
 }
 if(!manualQuery&&trigger==='changed'&&!localTypesEdited(current)){
  if(current?.result.items.length||!localSelectedTypes().length)return;
  trigger=current?'retry':'auto';
 }
 if(trigger==='next'&&(!current||!slotIsLatest(current)))return;
 const query=manualQuery||(trigger==='auto'?{conditions:{must:[{dimension:'画面类型',tags:view.defaults}],prefer:[],forbid:[]},keywords:[]}:
              trigger==='next'?{manual_browse:!!current.payload.manual_browse,conditions:current.payload.conditions,keywords:current.payload.keywords}:localReadConditions());
 const index=board.tasks.indexOf(t),types=query.conditions.must.filter(r=>r.dimension==='画面类型').flatMap(r=>r.tags);
 $('local-search-state').textContent=(view.joined?'本句属于 ':'本句 ')+(view.id||'新增观点')+'，正在用 '+types.join('、')+' 找素材…';
 let job=localRequests.get(key);
 const annotationRevision=view.annotation_revision||'';
 if(job&&job.annotationRevision!==annotationRevision)job=null;
 if(!job){
  job=api('/api/local/discover',{trigger,...(trigger==='retry'?{retry_of:current.id}:trigger==='next'?{previous_run:current.id}:{}),text:t.text,context:board.tasks.slice(Math.max(0,index-1),index+2).map(x=>x.text).join('，'),
   need:t.need||'',scope:$('ai-scope').value,board_context:board.context,duration:t.end-t.start,project_id:projectId,task_id:t.id,
   exclude_assets:[...new Set(shots.map(s=>s.asset_id))],reviewer:reviewerName(),
   use_experience:$('ai-experience').checked,...localNeighbors(),type_changes:trigger==='changed'?localTypeChanges:[],...query});
  job.annotationRevision=annotationRevision;
  localRequests.set(key,job);
 }
 slotButtons();
 try{
  const result=await job;
  if(key!==aiTaskKey()||wf.step!==4||localView!==view)return;
  localCleanVersion=result.clean_version||localCleanVersion;
  await aiHistory(result.run_id);
  if(key===aiTaskKey()&&aiRun()?.id===result.run_id){localRestoreBatch(aiRun());return aiRun();}
 }catch(e){
  if(key===aiTaskKey()&&wf.step===4&&localView===view){$('local-search-state').textContent='检索未完成 · '+e.message;throw e;}
 }finally{
  if(localRequests.get(key)===job)localRequests.delete(key);
  slotButtons();
 }
}
function slotMatchesCurrent(run){
 if((localView?.annotation_revision||'')!==(run.payload?.viewpoint?.annotation_revision||''))return false;
 if(['人工确认','自动初标，待核对'].includes(localView?.status)&&localView.primary?.length&&localView.entry_id&&run.payload?.viewpoint?.id===localView.entry_id&&!run.payload.viewpoint.primary?.length)return false;
 try{aiAssert(run);return run.result.capacity===5&&!!localCleanVersion&&run.result.clean_version===localCleanVersion;}catch{return false;}
}
function slotIsLatest(run){return run===aiRuns.find(r=>r.result.slot_review&&slotMatchesCurrent(r));}
function slotButtons(){
 if(localRetryKey&&localRetryKey===aiTaskKey()&&wf.step===4&&sbTask()){
  const search=$('ai-search');search.textContent='重新加载本句选片';search.hidden=false;search.disabled=false;
  $('ai-next').hidden=true;$('ai-next').disabled=true;$('ai-next-help').textContent='';sbFixedUpdate();return;
 }
 const run=aiRun();const current=run?.result.slot_review&&slotMatchesCurrent(run)?run:null;
 const history=!!run&&!slotIsLatest(run);
 const busy=localRequests.has(aiTaskKey()),ready=!!localView&&localTaskKey===aiTaskKey()&&!!projectId&&!!sbTask()&&board.context===sbContext();
 const edited=ready&&localTypesEdited(current),empty=current?.result.items?.length===0;
 const needsChoice=ready&&!localSelectedTypes().length&&!current?.payload.conditions.must.some(r=>r.dimension==='素材类别');
 $('ai-search').hidden=history||!!current&&!empty&&!edited&&!needsChoice;
 $('ai-search').textContent=needsChoice?'选类型找 5 条素材':empty&&!edited&&exhaustedBatch(current)?'调整检索范围':empty&&!edited?'重新检索 5 条素材':edited?'按当前条件找 5 条素材':'找 5 条素材';
 $('ai-search').disabled=!ready||busy||$('ai-search').hidden;
 $('ai-next').hidden=history||!current||empty||edited||needsChoice;
 $('ai-next').disabled=!ready||busy||$('ai-next').hidden;
 $('ai-next').textContent=busy?'正在检索…':'再检索 5 条素材';
 $('ai-next-help').textContent=$('ai-next').hidden?'':'评价选填。可以直接选入镜头或换一批。想保留评价，请先点「确认并保存」。';
 if(projectId&&sbTask()&&board.context!==sbContext()){
  $('ai-search').hidden=false;$('ai-next').hidden=true;
  $('ai-search').textContent=wf.dirtySubtitle?'请先保存第三步字幕':'同步字幕并找 5 条素材';
  $('ai-search').disabled=busy||!wf.cues.length||wf.dirtySubtitle||!imports.subtitle;
 }
 sbFixedUpdate();
}
let reserveKey='',reserveQuery=null;
function slotReserve(run,stale){
 const box=$('ai-count'),r=run.result;
 function display(verified,unchecked){
  const skipped=r.filters?.['历史检索已展示的原片']||0;
  box.textContent='本轮展示 '+r.items.length+' 条'+(verified?'，另有 '+verified+' 个原片已核验可候选':'')+(unchecked?'，还有 '+unchecked+' 个匹配原片待核验':'')+(!verified&&!unchecked?'，当前条件下已无其他匹配原片':'')+'。'+(skipped?'已跳过历史检索展示过的 '+skipped+' 条原片。':'');
 }
 if(r.classified_pool){display(r.remaining,r.unchecked_sources);return;}
 box.textContent='本轮展示 '+r.items.length+' 条。'+(stale?'旧批次未记录完整余量。':'正在核对同类型的剩余素材…');
 if(stale)return;
 const exclude=[...new Set(shots.map(s=>s.asset_id))].sort(),key=JSON.stringify([run.id,exclude]);
 if(reserveKey!==key){reserveKey=key;reserveQuery=api('/api/local/reserve',{run_id:run.id,exclude_assets:exclude});}
 reserveQuery.then(d=>{if(reserveKey===key&&aiRun()?.id===run.id)display(d.remaining,d.unchecked_sources);}).catch(()=>{if(reserveKey===key&&aiRun()?.id===run.id){box.textContent='本轮展示 '+r.items.length+' 条。剩余素材暂未核实。';reserveKey='';}});
}
function slotSummary(box,run,stale){
 const r=run.result, s=run.review;
 slotReserve(run,stale);
 if(!r.items.length&&!stale){
  $('manual-shots').open=true;
 }
 if(r.gap){
  const details=el('details');details.append(el('summary','查看过滤原因'));box.append(details);
  const counts=r.filters||{};
  details.append(el('p','非竖屏过滤 '+((counts['非竖屏预筛']||0)+(counts['非原生9比16']||0))+' 个，时长不足 '+((counts['片段长度不足']||0)+(counts['真实时长不足']||0))+' 个。'));
  for(const [type,n] of Object.entries(r.type_counts||{}))details.append(el('p',type+' · 当前条件下够长且可用的原生 9:16 素材 '+(n['可用竖屏']||0)+' 条，非竖屏 '+(n['非竖屏']||0)+' 个，时长不足 '+(n['时长不足']||0)+' 个。'));
 }
 const excluded=$('ai-blocked'),blocked=r.blocked||[];
 if(blocked.length){
  const list=el('details');list.append(el('summary','已确认审核记录排除 '+new Set(blocked.map(x=>x.asset_id)).size+' 个原片'));
  for(const b of blocked)list.append(el('p',`${b.asset_id} ← 记录 ${b.id} · ${b.codes.join('、')} · ${b.sentence}`));
  excluded.append(list);
 }else excluded.textContent='本轮没有原片被已确认审核记录排除。';
 if(s.group)box.append(el('strong',s.group.sentence));
 if(!stale&&!s.complete&&!s.missing.length&&!s.chosen.length){
  const label=el('label','这批还缺哪种能看见的动作'),input=el('input');input.id='local-group-missing';input.placeholder='还缺哪种动作、空间或阶段';
  const saveGap=subtitleButton('保存本批缺口',async()=>{
   await api('/api/local/slot-finish',{run_id:run.id,missing:input.value,reviewer:aiReviewer()});
   if(aiRun()?.id===run.id)await aiHistory(run.id);
  });
  label.append(input,saveGap);$('ai-batch-note').append(label);
 }
}
function suggestedReviewFact(candidate){
 const tidy=text=>(text||'').trim().replace(/[，,。；;！!]+$/,'');
 for(const text of [candidate.classification_description,candidate.machine_description]){
  const line=tidy((text||'').split(/[\n。！？]/).find(s=>/[\u4e00-\u9fff]/.test(s)&&!/(?:^\s*[\[{]|[\\/]|待补|待核对|^\s*见.*表)/.test(s))||'');
  if(line&&line.length<=160&&visibleFact(line))return line;
 }
 const tags=candidate.tags||[],labels=(localTree?.labels||[]).filter(t=>tags.includes(t.id)&&!t.group);
 const name=dim=>labels.find(t=>t.dimension===dim&&!/其他|看不清|分不清|未知/.test(t.name))?.name;
 const action=name('主动作'),space=name('空间');
 if(action&&!/类$/.test(action))return (space?'在'+space+'里，':'')+'画面中可见'+action;
 if(tags.includes('V02'))return '画面中有人在交流';
 if(tags.includes('V01'))return '画面中有人面向镜头';
 if(tags.includes('V05'))return '画面里有人在批刮施工';
 if(space)return '画面拍到的是'+space;
 const picture=name('画面类型');
 return picture&&!/[／/→]/.test(picture)?'画面中可见'+picture:'';
}
function slotCard(card,run,c,stale){
 const saved=run.review.records[c.slot];
 if(saved)card.append(el('p',saved.sentence,'hint'));
 for(const w of c.warnings_to_review||[])card.append(el('p','旧错核对 · '+w.sentence,'local-warning'));
 if(stale||run.review.group)return;
 card.dataset.slot=c.slot;
 const draft=reviewDraft(run),form=el('div');
 const reject=subtitleButton('不合适',()=>choose('不合适')),accept=subtitleButton('采用',()=>choose('采用'));
 reject.dataset.reject='';reject.dataset.verdict='不合适';accept.dataset.verdict='采用';
 card.append(accept,reject,form);
 function choose(verdict){
  if(savingReview)return;
  const previous=draft[c.slot];
  if(previous?.verdict===verdict){
   delete draft[c.slot];render();return;
  }
  draft[c.slot]={slot:c.slot,verdict,code:verdict==='采用'?'动作发生了':'',
   anchor:previous?.anchor||run.payload.need||run.payload.text,fact:previous?.fact||saved?.fact||suggestedReviewFact(c),checked:false};
  if(draft[c.slot].anchor==='见原句')draft[c.slot].anchor=run.payload.text;
  render();
 }
 function render(){
  form.replaceChildren();
  const entry=draft[c.slot];
  const status=card.querySelector('[data-saved-status]');
  if(status)status.textContent=entry?'待保存 · '+entry.verdict:status.dataset.savedStatus;
  for(const b of card.querySelectorAll('button[data-verdict]'))b.setAttribute('aria-pressed',String(entry?.verdict===b.dataset.verdict));
  if(!entry){updateReviewFooter(run);return;}
  if(entry.verdict==='不合适'){
   const other=el('details');other.append(el('summary','先不拿来比这句文案'));
   const reasons=el('div');reasons.className='rank-reasons';form.append(reasons);
   for(const code of [...matchReasons,...excludedReasons]){
    const labels={'横屏或清晰度不够':'模糊或画幅不符','自带字幕、贴纸、水印、界面、二维码、品牌字、手写编号':'字幕、贴纸或水印'};
    const button=subtitleButton(labels[code]||code,()=>{if(entry.code!==code)entry.checked=false;entry.code=code;render();});
    button.setAttribute('aria-pressed',String(entry.code===code));
    (matchReasons.includes(code)?reasons:other).append(button);
    if(entry.code===code&&!matchReasons.includes(code))other.open=true;
   }
   form.append(other);
  }
  if(entry.code){
   const fields=el('div');fields.dataset.reviewFacts='';
   if(entry.verdict==='采用'){
    const transition=el('input');transition.type='checkbox';transition.checked=entry.code==='过渡采用';
    const label=el('label','仅用作过渡');label.prepend(transition);fields.append(label);
    transition.onchange=()=>{entry.code=transition.checked?'过渡采用':'动作发生了';entry.checked=false;render();};
   }
   const need=run.payload.need==='见原句'?'':(run.payload.need||'').trim();
   const target=need?'「'+need+'」':'这句文案';
   const meaning={'动作发生了':'可用来表现'+target,'过渡采用':'这里用作过渡镜头','动作没发生':'没看到'+target+'要求的动作',
    '阶段不对':'所处阶段与'+target+'不符','动作做反了':'动作方向与'+target+'相反'};
   if(entry.editing||!entry.fact){
    entry.editing=true;
    const fact=el('textarea');fact.value=entry.fact;
    const label=el('label','按实际画面改一句');label.append(fact);fields.append(label);
    addReviewDictation(fields,fact);
    const confirm=subtitleButton('对',()=>{entry.checked=true;entry.editing=false;render();});
    confirm.disabled=!visibleFact(fact.value);fields.append(confirm);
    fact.oninput=()=>{entry.fact=fact.value;entry.checked=visibleFact(fact.value);confirm.disabled=!entry.checked;updateReviewFooter(run);};
   }else{
    const observed=entry.fact.replace(/[。！？]+$/,'');
    fields.append(el('p',observed+'，'+(meaning[entry.code]||'本次原因是「'+entry.code+'」')+'。','review-suggestion'));
    const yes=subtitleButton('对',()=>{entry.checked=true;render();});
    yes.setAttribute('aria-pressed',String(!!entry.checked));
    fields.append(yes,subtitleButton('不对，修改',()=>{entry.checked=false;entry.editing=true;render();form.querySelector('textarea')?.focus();}));
   }
   if(entry.verdict==='采用'&&entry.code!=='过渡采用'){
    const anchor=el('input');anchor.value=entry.anchor;
    const l=el('label','对上的词');l.append(anchor);fields.append(l);
    anchor.oninput=()=>{entry.anchor=anchor.value;updateReviewFooter(run);};
   }
   form.append(fields);
  }
  updateReviewFooter(run);
 }
 render();
}
const matchReasons=['动作没发生','阶段不对','动作做反了'];
const excludedReasons=['同条重复','没看连续画面','晃动、失焦、拖影','横屏或清晰度不够','自带字幕、贴纸、水印、界面、二维码、品牌字、手写编号'];
let activeReviewId='',draftEntries={},gapText='',savingReview=false;
function reviewDraft(run){
 if(activeReviewId!==run.id){activeReviewId=run.id;draftEntries={};gapText='';}
 return draftEntries;
}
function visibleFact(value){
 const text=(value||'').trim().replace(/[\s，。！？,.!?]/g,'');
 return text.length>=2&&!/^(看着|看起来|就是|感觉|画面|素材|很|太|不对劲|不对|不好看|不合适|不符合|说不清|差不多|不知道|不清楚|不好|没看清|了)+$/.test(text);
}
function updateReviewFooter(run){
 const footer=$('review-footer');if(!footer||activeReviewId!==run.id)return;
 const entries=Object.values(draftEntries),records={...run.review.records,...draftEntries};
 const oldGap=$('local-group-missing');if(oldGap)oldGap.parentElement.hidden=entries.length>0;
 const ordered=run.result.items.map(c=>records[c.slot]);
 const chosen=ordered.filter(r=>r?.verdict==='采用');
 const allRejected=ordered.length>0&&ordered.every(r=>r?.verdict==='不合适'&&(r.code||r.codes?.length));
 for(const f of $('ai-cards').querySelectorAll('[data-review-facts]'))f.hidden=!!allRejected;
 footer.hidden=!entries.length;footer.replaceChildren();if(footer.hidden)return;
 let message,valid;
 if(allRejected){
  const label=el('label','这批还缺哪种能看见的动作'),gap=el('textarea');
  gap.id='review-gap';gap.value=gapText;label.append(gap);footer.append(label);
  gap.oninput=()=>{gapText=gap.value;save.disabled=savingReview||!visibleFact(gapText);};
  message='只记下缺口，这批候选都不合适。';valid=visibleFact(gapText);
 }else{
  const need=(run.payload.need||'').trim();
  const losses=ordered.filter(r=>r?.verdict==='不合适'&&(r.codes||[r.code]).some(code=>matchReasons.includes(code))&&!(r.codes||[]).some(code=>excludedReasons.includes(code)));
  if(!need||need==='见原句')message='先不进入排序，画面要求仍为空或是「见原句」。';
  else if(chosen.length>1)message='保存评价时只能采用一条。再点一次多选的「采用」即可取消。';
  else if(chosen.length&&(chosen[0].code==='过渡采用'||chosen[0].codes?.includes('过渡采用')))message='先不进入排序，这条镜头只用作过渡。';
  else if(!chosen.length)message='先不进入排序，还没有明确采用的镜头。';
  else if(!losses.length)message='先不进入排序，还没有明确不合适且可比较的镜头。';
  else message='会进入下次排序，'+losses.map(r=>chosen[0].slot+' 排在 '+r.slot+' 前面，因为 '+r.slot+' '+(r.codes||[r.code]).filter(code=>matchReasons.includes(code)).join('、')).join('。')+'。';
  valid=chosen.length<=1&&entries.every(e=>e.code&&e.checked&&visibleFact(e.fact)&&e.anchor.trim()&&(run.payload.text.includes(e.anchor)||need.includes(e.anchor)));
 }
 const hint=el('p',message);hint.id='review-purpose';hint.setAttribute('aria-live','polite');footer.append(hint);
 const save=subtitleButton('确认并保存',async()=>{
  if(savingReview)return;aiAssert(run);
  const reviewer=aiReviewer();
  savingReview=true;save.disabled=true;
  try{
   const previous=Object.values(run.review.records).map(r=>r.id).sort();
   if(run.review.group)previous.push(run.review.group.id);
   const reviews=entries.map(({slot,verdict,code,fact,anchor})=>({slot,verdict,code,fact,anchor}));
   const result=await api('/api/local/slot-batch',{run_id:run.id,reviewer,previous,reviews,missing:gapText});
   if(result.warning)notice(result.warning,true);
   if(activeReviewId===run.id){draftEntries={};gapText='';}
   await aiHistory(run.id);
  }finally{savingReview=false;if(aiRun()?.id===run.id)updateReviewFooter(run);}
 });
 save.disabled=!valid||savingReview;footer.append(save);
}
