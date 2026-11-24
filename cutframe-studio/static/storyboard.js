'use strict';
// 同页人工选片；所有工程数据仍通过既有本地工程服务保存。
let board={version:1,enabled:true,tasks:[],candidates:[],selected:null,confirmed:null,context:''};
let sbAsset=null,sbMeta=null,sbPage=1,sbTotal=0,sbClips=[],sbRoots={},sbRequest=0,sbStop=null,sbReplace=null;
const sbRoles=['话题开场','现场指认','改造项目清单','完工效果','咨询收尾'];
const sbPanel=$('wf-panel-4');
const sbUI=el('div');sbUI.id='sb-workbench';
sbUI.innerHTML=`<details id="sb-tools"><summary>全片检查</summary><button id="sb-play-all">全片联播</button><p id="sb-status"></p></details>
<div class="sb-columns"><section><h3>当前字幕</h3><div id="sb-tasks"></div><div id="sb-timeline"></div></section>
<section id="sb-middle"><details id="sb-file-search"><summary>按文件名找一条</summary><p class="small">已知原片名时，在对应素材库查找并预览。按字幕意思找镜头，请看上方 A、B、C。</p><label>素材来源<select id="sb-kind"><option value="raw">原始素材</option><option value="clips">已精裁素材记录</option></select></label><label>素材库<select id="sb-root"></select></label><label>素材编号、文件名或文件夹名<input id="sb-query" placeholder="例如 32951 或 小区场景" autocomplete="off"></label><div id="sb-clip-filters" hidden><label>主分类<input id="sb-category"></label><label>标签<input id="sb-tag"></label></div><button id="sb-search">查找素材</button><div id="sb-results"></div><button id="sb-prev">上一页</button><span id="sb-page"></span><button id="sb-next">下一页</button></details></section>
<section id="sb-source"><h3>当前片段</h3><p id="sb-current-caption"></p><video id="sb-player" controls playsinline preload="metadata"></video><p id="sb-source-name">请选择素材</p><p id="sb-source-info" class="small"></p>
<div class="form-grid"><label>片段开始／秒<input id="sb-in" type="number" min="0" step=".001" value="0"></label><label>片段结束／秒（自动）<input id="sb-out" readonly></label></div>
<input id="sb-position" type="range" min="0" step=".001" aria-label="移动片段开始位置"><button id="sb-mark-in">从播放位置开始</button><button id="sb-proxy" hidden>生成本地兼容预览</button>
<label>画面对应关系<select id="sb-match"><option value="direct">直接对应文案（默认）</option><option value="fallback">人物讲述／相关空镜替代</option></select></label>
<label id="sb-reason-label" hidden>替代画面理由<input id="sb-reason"></label><p id="sb-fixed-status" aria-live="polite"></p><button id="sb-adopt" disabled class="primary">选入当前字幕</button><button id="sb-cancel-replace" hidden>取消替换</button>
<details><summary>使用说明</summary><p>点候选的「看这一条」，选择画面对应关系，再点「选入当前字幕」。候选评价选填。</p></details></section></div>`;
sbPanel.append(sbUI);$('sb-timeline').append($('film-duration'),$('shots'));
function sbContext(){const current=JSON.stringify({text:$('tts-text').value,voice:imports.voice,subtitle:imports.subtitle,cues:wf.cues,voiceOffset:$('voice-offset').value,subtitleOffset:$('subtitle-offset').value,fps:$('fps').value});return typeof SubtitleBoardCore!=='undefined'&&SubtitleBoardCore.sameContext(board.context,current)?board.context:current;}
function sbDuration(){return (wf.resources.voice?.meta.duration||0)+Number($('voice-offset').value);}
function sbTask(){return board.tasks.find(t=>t.id===board.selected);}
function sbIssues(){const list=StoryboardCore.issues(board,shots,sbDuration(),Number($('fps').value));const clean=v=>v.replace(/[\s，。！？、；：,.!?;:]/g,'');if(clean(board.tasks.map(t=>t.text).join(''))!==clean($('tts-text').value))list.unshift('任务文案与工程原稿不一致，请核对拆分和顺序');if(!imports.voice)list.unshift('请先采用或导入配音');const sub=wfSubtitleIssue();if(sub)list.unshift(sub);if(board.context!==sbContext())list.unshift('文案、配音或字幕已变化：核对任务时间后点击重新核对');return list;}
function sbChanged(){board.confirmed=null;wfChanged();}
function sbStatus(){if(!$('sb-status'))return;if(!board.tasks.length){$('sb-status').textContent='第一步：点击“按当前文案建立任务草稿”，再逐段确认画面需求。当前没有采用任何镜头。';if(board.enabled)$('render-film').disabled=true;return;}const problems=board.enabled?sbIssues():['先建立画面任务；旧工程镜头仍保留，可随后关联'];$('sb-status').replaceChildren(el('span',problems.length?problems.slice(0,5).join('；'):'镜头已覆盖全片，可以进入配乐。'));if(board.enabled&&board.context!==sbContext()){const b=el('button','已核对任务时间与当前文案／配音');b.onclick=()=>{board.context=sbContext();sbChanged();};$('sb-status').append(b);}if(board.enabled&&problems.length)$('render-film').disabled=true;}
const sbProjectBase=project;project=function(){const p=sbProjectBase();p.workflow.storyboard=structuredClone(board);return p;};
const sbRefreshBase=wfRefresh;wfRefresh=function(){sbRefreshBase();sbStatus();};
const sbOpenBase=wfOpen;wfOpen=async function(d){board=d.workflow?.storyboard?structuredClone(d.workflow.storyboard):{version:1,enabled:!d.id,tasks:[],candidates:[],selected:null,confirmed:null,context:''};board.candidates??=[];sbRequest++;$('sb-results').replaceChildren();$('sb-file-search').open=false;sbClearSource();sbReplace=null;$('sb-player').pause();$('sb-player').removeAttribute('src');$('sb-source-name').textContent='从素材列表选择一个文件';$('sb-source-info').textContent='';$('sb-cancel-replace').hidden=true;await sbOpenBase(d);if(board.library){const l=board.library;for(const [id,k]of [['sb-kind','kind'],['sb-root','root'],['sb-query','q'],['sb-category','category'],['sb-tag','tag']])$(id).value=l[k]||'';if(!['raw','clips'].includes($('sb-kind').value))$('sb-kind').value='raw';sbPage=l.page||1;}sbTasks();sbStatus();};
const sbStepBase=wfStep;wfStep=function(n){sbStepBase(n);root.classList.toggle('sb-active',n===4);$('sb-player').pause();if(n===4){sbTasks();}};
function sbInput(label,value,fn,type='text'){const l=el('label',label),input=el(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.value=value;if(type==='number'){input.step='.001';input.min=0;}input.oninput=()=>{fn(type==='number'?Number(input.value):input.value);sbChanged();};l.append(input);return l;}
function sbTasks(){const box=$('sb-tasks');box.replaceChildren();board.tasks.forEach((t,i)=>{const c=el('article',undefined,'sb-task'+(t.id===board.selected?' selected':''));const select=el('button',`${i+1}. ${t.role} · ${t.start.toFixed(2)}–${t.end.toFixed(2)}秒`);select.onclick=()=>{sbClearSource();board.selected=t.id;sbTasks();wfChanged();};c.append(select);if(t.id===board.selected){c.append(sbInput('完整文案',t.text,v=>t.text=v,'textarea'),sbInput('需要看到什么（必填）',t.need,v=>t.need=v,'textarea'));const role=el('select');role.setAttribute('aria-label','结构角色');sbRoles.forEach(r=>{const o=el('option',r);role.append(o);});role.value=t.role;role.onchange=()=>{t.role=role.value;sbChanged();};c.append(role);const times=el('div',undefined,'form-grid');times.append(sbInput('成片入点',t.start,v=>t.start=v,'number'),sbInput('成片出点',t.end,v=>t.end=v,'number'));c.append(times);const missing=el('button',t.missing?'取消缺素材标记':'标记缺素材／待补拍');missing.onclick=()=>{t.missing=!t.missing;sbTasks();sbChanged();};c.append(missing);c.append(sbInput('补拍要求／备注',t.note||'',v=>t.note=v));if(i<board.tasks.length-1){const merge=el('button','与下一段合并');merge.onclick=()=>{const next=board.tasks[i+1];t.text+=next.text;t.end=next.end;t.need=[t.need,next.need].filter(Boolean).join('；');for(const s of shots)s.task_ids=[...new Set((s.task_ids||[]).map(id=>id===next.id?t.id:id))];board.candidates.forEach(x=>{if(x.task_id===next.id)x.task_id=t.id;});board.tasks.splice(i+1,1);renderShots();sbTasks();sbChanged();};c.append(merge);}const remove=el('button','移除此任务');remove.onclick=()=>{board.tasks.splice(i,1);board.selected=board.tasks[0]?.id||null;sbTasks();renderShots();sbChanged();};c.append(remove);}else c.append(el('p',t.text,'small'));if(t.missing)c.append(el('p','缺素材 · 不会自动用无关画面替代','wf-pending'));box.append(c);});}
async function sbInit(){
 const s=await api('/api/state');sbRoots=s.roots;
 const select=$('sb-root'),roots=Object.entries(s.roots).filter(([id,r])=>materialScope==='all'?r.origin!=='cloud':id===materialScope);
 select.replaceChildren();
 for(const [id,r] of roots){const o=el('option',r.label);o.value=id;select.append(o);}
 if(!roots.length){$('sb-results').textContent='当前素材库不可用';return;}
 const ids=roots.map(([id])=>id);
 select.value=ids.includes(board.library?.root)?board.library.root:ids.includes('xiaoq')?'xiaoq':ids[0];
 await sbSearch();
}
async function sbSearch(){const request=++sbRequest,kind=$('sb-kind').value;board.library={kind,root:$('sb-root').value,q:$('sb-query').value,category:$('sb-category').value,tag:$('sb-tag').value,page:sbPage};wfChanged();let items=[];const q=$('sb-query').value.trim();$('sb-clip-filters').hidden=kind!=='clips';if(kind==='raw'){const d=await api(`/api/assets?root=${encodeURIComponent($('sb-root').value)}&q=${encodeURIComponent(q)}&page=${sbPage}`);items=d.items;sbTotal=d.total;
 if(!items.length&&/^[0-9a-f]{32}$/i.test(q)){
  const response=await fetch('/api/assets/'+encodeURIComponent(q));
  if(response.ok){const {asset}=await response.json();if(asset.root===$('sb-root').value){items=[asset];sbTotal=1;}}
  else if(response.status!==404)throw Error('素材编号查询失败');
 }
 }else if(kind==='clips'){const d=await api('/api/clips');sbClips=d.items.map(c=>({...c,record:JSON.parse(c.data)}));const cat=$('sb-category').value.trim(),tag=$('sb-tag').value.trim();const rows=sbClips.filter(c=>(!cat||c.record.category===cat)&&(!tag||(c.record.tags||[]).some(t=>t.includes(tag)))&&(!q||JSON.stringify(c.record).includes(q))&&c.record.root_alias===$('sb-root').value);sbTotal=rows.length;items=rows.slice((sbPage-1)*60,sbPage*60).map(c=>({id:c.record.asset_id,name:c.record.relative_path.split(/[\\/]/).pop(),rel:c.record.relative_path,clip:c.record}));}
 if(request!==sbRequest)return;$('sb-results').replaceChildren();for(const a of items){const b=el('button',undefined,'sb-result');b.append(el('strong',a.name),el('small',a.rel||a.path||''));b.onclick=()=>sbSelect(a).catch(e=>notice(e.message,true));$('sb-results').append(b);}if(!items.length)$('sb-results').append(el('p',kind==='raw'?'当前库没有匹配的原片。可输入文件名中的数字或文件夹名；按字幕找素材请看上方 A、B、C。':'当前库没有匹配的精裁记录，请检查文件名、分类和标签。'));$('sb-page').textContent=`${sbPage} / ${Math.max(1,Math.ceil(sbTotal/60))} · ${sbTotal}条`;$('sb-prev').disabled=sbPage<=1;$('sb-next').disabled=sbPage*60>=sbTotal;}
$('sb-query').onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();$('sb-search').click();}};
action('sb-search',()=>{sbPage=1;return sbSearch();});action('sb-prev',()=>{sbPage--;return sbSearch();});action('sb-next',()=>{sbPage++;return sbSearch();});$('sb-kind').onchange=()=>{sbPage=1;sbSearch().catch(e=>notice(e.message,true));};$('sb-root').onchange=$('sb-kind').onchange;
$('sb-file-search').ontoggle=()=>{if($('sb-file-search').open)($('sb-root').options.length?sbSearch():sbInit()).catch(e=>notice(e.message,true));};
let sbSelectVersion=0;
function sbClearSource(){
 ++sbSelectVersion;wfPause();sbPlayingFilm=false;sbStop=null;sbAsset=null;sbMeta=null;
 const video=$('sb-player');video.onloadedmetadata=null;video.pause();video.removeAttribute('src');video.load();
 $('sb-source-name').textContent='请选择素材';$('sb-source-info').textContent='';$('sb-match').value='direct';$('sb-reason-label').hidden=true;
}

async function sbSelect(a){sbClearSource();const version=sbSelectVersion;sbFixedUpdate();$('sb-player').pause();sbAsset=null;sbMeta=null;sbStop=null;const d=await api('/api/assets/'+(a.asset_id||a.id));if(version!==sbSelectVersion)return;sbAsset=d.asset;sbMeta=d.meta;$('sb-source-name').textContent=sbAsset.name;$('sb-source-info').textContent=`${sbAsset.source_path||sbAsset.rel} · ${sbMeta.duration.toFixed(3)}秒 · ${sbMeta.codec}`;$('sb-player').src=wf.proxy[sbAsset.id]||'/media/'+sbAsset.id;const clip=a.clip;$('sb-in').value=clip?clip.requested_start:a.start||0;$('sb-out').value=clip?clip.requested_end:a.end||Math.min(sbMeta.duration,Math.max(1,(sbTask()?.end||3)-(sbTask()?.start||0)));$('sb-reason').value=a.reason||clip?.purpose||'';const player=$('sb-player');player.onloadedmetadata=()=>{if(version===sbSelectVersion){player.currentTime=Number($('sb-in').value);sbStop=a.end||Number($('sb-out').value);}};sbFixedUpdate();}
action('sb-proxy',async()=>{if(!sbAsset)throw Error('先打开素材');if(jobId)throw Error('请等待当前任务结束');const aid=sbAsset.id;const d=await api('/api/proxy/'+aid,{});const use=r=>{wf.proxy[aid]=r.url;if(sbAsset?.id===aid)$('sb-player').src=r.url;};if(d.url)use(d);else await watch(d.job_id,use);});
action('sb-cancel-replace',()=>{subtitleResetReplace();sbFixedUpdate();});
const sbRenderFilmBase=$('render-film').onclick;$('render-film').onclick=()=>{if(board.enabled){const issues=sbIssues();if(issues.length){notice(issues[0],true);return;}}return sbRenderFilmBase();};
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>$('sb-player').pause()));

