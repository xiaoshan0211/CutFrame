'use strict';
// 单条成片的六步工程。
const wf={step:1,cues:[],resources:{},confirmed_voice:null,confirmed_subtitle:null,no_music:false,dirtySubtitle:false,films:[],time:0,playing:false,shotIndex:-1,proxy:{},loading:false};
let wfProjectIdentity=null;
const titles=['工程与文案','配音与试听','字幕与样式','选片与分镜','配乐与混音','检查与成片'];
const root=document.querySelector('#compose .composition');
const old=document.createElement('div');while(root.firstChild)old.append(root.firstChild);
root.innerHTML=`<div class="section-head"><div><span class="eyebrow">LOCAL PRODUCTION WORKFLOW</span><h1>一步一步，完成你的影片</h1><p class="small">文案 → 配音 → 字幕 → 分镜 → 配乐 → 成片。原视频留本地；GPT选片仅发送抽帧与文案。</p></div></div><div id="wf-steps" class="wf-steps"></div><div class="wf-layout"><section class="wf-editor"><div id="wf-panels"></div><div class="wf-navigation"><button id="wf-prev">上一步</button><span id="wf-step-hint"></span><button id="wf-next" class="primary">下一步</button></div><p id="wf-draft" class="small"></p><div class="button-row"><button id="wf-restore">恢复本机草稿</button><button id="wf-discard">清除本机草稿</button></div></section><aside class="wf-preview"><h2>制作预览</h2><p class="small">即时查看字幕位置、分镜和声音；最终编码效果以导出成片为准。</p><div id="wf-frame"><video id="wf-video" playsinline preload="metadata"></video><span id="wf-caption"></span></div><audio id="wf-voice" preload="metadata"></audio><audio id="wf-music" preload="metadata"></audio><input id="wf-seek" type="range" min="0" max="1" value="0" step=".01" aria-label="成片预览时间"><div class="button-row"><button id="wf-play">播放预览</button><button id="wf-proxy">生成当前镜头兼容预览</button></div><p id="wf-time" class="small">0.00 秒</p><p id="wf-preview-status" class="hint">先打开工程，或在第一步输入文案。</p></aside></div>`;
const shotPreview=new ShotPreview($('wf-frame'),$('wf-video'));
const panels=titles.map((title,i)=>{const p=el('section',undefined,'wf-panel');p.id='wf-panel-'+(i+1);p.append(el('h2',`${i+1}. ${title}`));$('wf-panels').append(p);const b=el('button',`${i+1} ${title}`);b.id='wf-step-'+(i+1);b.onclick=()=>wfStep(i+1);$('wf-steps').append(b);return p;});
function move(id,step,label=false){const n=old.querySelector('#'+id);if(n)panels[step-1].append(label?n.closest('label'):n);}
function markup(step,html){const d=el('div');d.innerHTML=html;panels[step-1].append(d);}
markup(1,'<label>本工程选片素材来源<select id="wf-material-scope"><option value="all">本地素材 · 全部原片库</option></select></label>');
markup(1,`<details id="cloud-import"><summary>从云端导入素材</summary>
<p class="small">选网盘同步目录中的文件或文件夹。导入完成后，原片保存在镜序电脑，断网也能打开。</p>
<div class="button-row"><button type="button" id="cloud-pick-files">选择视频文件</button><button type="button" id="cloud-pick-folder">选择文件夹</button></div>
<input type="file" id="cloud-files" accept=".mp4,.mov,.mkv,.avi,.wmv,.m4v,.mts,.m2ts,.webm" multiple hidden><input type="file" id="cloud-folder" webkitdirectory multiple hidden>
<label>团队云端或阿里云 OSS 原片下载链接（每行一个）<textarea id="cloud-urls" placeholder="https://存储桶.oss-地域.aliyuncs.com/视频.mp4"></textarea></label>
<button id="cloud-fetch" type="button">从存储桶导入</button><p id="cloud-result" role="status"></p><ul id="cloud-errors"></ul></details>`);
markup(1,`<section id="cloud-library" hidden><h3>已保存在本机的云端素材</h3>
<label>找原片<input id="cloud-query" type="search" placeholder="文件名或目录名"></label>
<p id="cloud-count" role="status"></p><div id="cloud-list" class="button-row"></div>
<div class="button-row"><button id="cloud-prev" type="button">上一页</button><button id="cloud-next" type="button">下一页</button></div>
<p id="cloud-playing" aria-live="polite"></p><video id="cloud-player" controls playsinline preload="none" hidden></video>
<button id="cloud-proxy" type="button" hidden>生成本机兼容预览</button><div id="cloud-segments"></div></section>`);
move('project-name',1,true);move('project-list',1,true);move('load-project',1);move('save-project',1);markup(1,'<button id="wf-new">新建空白工程</button><button id="wf-copy">另存为新工程</button>');move('tts-text',1,true);
markup(1,'<p class="hint">先填写工程名与完整文案。修改文案后，可按新稿更新配音和字幕。</p>');
markup(2,'<p class="hint">使用已选定的松弛男 G 版音色。先生成并完整试听，再点击“用作本工程配音”。也可导入现成音频。</p>');
for(const id of ['tts-generate','tts-status','tts-player','tts-speed-panel','tts-use'])move(id,2);move('tts-history',2,true);move('voice',2,true);move('voice-info',2);move('voice-offset',2,true);
markup(2,'<audio id="wf-current-voice" controls preload="metadata"></audio><p id="wf-voice-state" class="small"></p>');
markup(3,'<p class="hint">从当前配音生成时间戳，字幕文字沿用原稿。识别差异会提示，请逐句试听核对；修改后保存字幕。</p><button id="wf-generate-subtitles">按当前配音生成字幕</button><div id="wf-subtitle-state" role="status"></div>');move('subtitle',3,true);move('subtitle-info',3);
markup(3,'<div class="wf-table-wrap"><table class="wf-table"><thead><tr><th>入点 / 秒</th><th>出点 / 秒</th><th>单行字幕</th><th>操作</th></tr></thead><tbody id="wf-cues"></tbody></table></div><button id="wf-add-cue">增加字幕页</button><button id="wf-save-subtitles">保存字幕修改</button>');
markup(3,'<label>字幕字体<select id="subtitle-font"><option value="yahei">微软雅黑</option><option value="source-han">思源黑体</option></select></label><label>字幕字重<select id="subtitle-weight"><option value="regular">常规</option><option value="bold">粗体</option></select></label><p id="subtitle-font-example" aria-label="字体预览"></p><p id="subtitle-font-note" class="small" role="status"></p>');
for(const id of ['font-size','subtitle-bottom','subtitle-offset'])move(id,3,true);
markup(3,'<p id="wf-font-status" class="small" role="status"></p>');
markup(3,'<button id="wf-style">恢复已验收第四版样式</button><p class="small">全片统一字号、单行、无尾标点；距底边默认 360 像素。字号自由调整，不自动缩小。</p>');
move('film-duration',4);move('shots',4);
for(const id of ['canvas','fps','fit','source-audio'])move(id,6,true);
panels[0].append($('wf-draft'),$('wf-restore').parentElement);
markup(5,'<button id="wf-list-music">浏览本地 BGM 目录</button><select id="wf-music-list" aria-label="音乐候选"><option value="">先浏览音乐目录</option></select><audio id="wf-music-audition" controls preload="none"></audio><button id="wf-use-music">采用选中音乐</button>');move('music',5,true);move('music-info',5);
for(const id of ['music-start','music-volume'])move(id,5,true);
markup(5,'<label>片尾淡出 / 秒<input id="music-fade" type="number" min="0" max="10" step=".1" value="1.5"></label><button id="wf-no-music">本片不使用背景音乐</button><p class="hint">右侧播放可试听配音和配乐的组合。音乐不自动循环；长度不足时导出会提示。</p>');
markup(6,'<div id="wf-checklist"></div><p id="render-font-note" class="small" role="status"></p><p id="wf-render-state" class="hint"></p>');move('render-film',6);move('film-result',6);markup(6,'<h2>本工程成片版本</h2><div id="wf-versions"></div>');
$('font-size').value=72;$('subtitle-bottom').value=360;
const baseProject=project;
project=function(){const p=baseProject();p.settings.subtitle_font=$('subtitle-font').value;p.settings.subtitle_weight=$('subtitle-weight').value;p.settings.music_fade=Number($('music-fade').value);p.workflow={script:$('tts-text').value,step:wf.step,confirmed_voice:wf.confirmed_voice,confirmed_subtitle:wf.confirmed_subtitle,no_music:wf.no_music};return p;};
function wfStep(n){wfPause();wf.step=n;panels.forEach((p,i)=>p.hidden=i!==n-1);titles.forEach((_,i)=>$('wf-step-'+(i+1)).classList.toggle('selected',i===n-1));$('wf-prev').disabled=n===1;$('wf-next').disabled=n===6;$('wf-step-hint').textContent=`第 ${n} / 6 步`;wfRefresh();}
action('wf-prev',()=>wfStep(Math.max(1,wf.step-1)));action('wf-next',()=>wfStep(Math.min(6,wf.step+1)));
function fingerprint(p){if(!p)return '';const stable=v=>Array.isArray(v)?v.map(stable):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,stable(v[k])])):v;return JSON.stringify(stable({shots:p.shots,imports:p.imports,settings:{subtitle_font:'yahei',subtitle_weight:'regular',...p.settings,music_fade:p.settings.music_fade||0}}));}
function wfSubtitleIssue(){
 if(wf.dirtySubtitle)return '请保存字幕修改';
 if(!imports.subtitle)return '请生成或导入字幕';
 const voice=wf.resources.subtitle?.meta?.voice_id;
 if(voice&&voice!==imports.voice)return '字幕对应旧配音，请按当前配音重新生成字幕';
 return '';
}
function wfRefresh(){
 const voice=wf.resources.voice,sub=wf.resources.subtitle;
 $('wf-voice-state').textContent=imports.voice?'已用作本工程配音':'请选择工程配音';
 const subtitleIssue=wfSubtitleIssue();
 $('wf-save-subtitles').disabled=!wf.dirtySubtitle;
 const checks=[[$('project-name').value.trim()&&$('tts-text').value.trim(),'填写工程名和文案'],[imports.voice,'采用或导入工程配音'],[!subtitleIssue,subtitleIssue||'字幕已保存'],[shots.length>0,'加入并排列镜头'],[imports.music||wf.no_music,'选择音乐，或明确不使用音乐']];
 $('wf-checklist').replaceChildren(...checks.map(([ok,t])=>el('p',(ok?'✓ ':'○ ')+t,ok?'wf-ok':'wf-pending')));
 const states=[checks[0][0]?'已填写':'待填写',checks[1][0]?'已采用':'待采用',checks[2][0]?'已保存':wf.dirtySubtitle?'待保存':'待生成',shots.length?shots.length+'个镜头':'待选片',checks[4][0]?'已选择':'待选择',wf.films.length?'已有成片':'待导出'];titles.forEach((title,i)=>{$('wf-step-'+(i+1)).textContent=(i+1)+' '+title+' · '+states[i];});const last=wf.films[0];$('wf-render-state').textContent=last?(fingerprint(last.project)===fingerprint(project())?'当前配置已有成片，可在下方播放。':'当前配置与已有成片不同，需要重新渲染；旧版本保留。'):'按顺序完成检查后，渲染第一版。';
 $('render-film').disabled=checks.some(([ok])=>!ok)||!!jobId||!!captionFonts.reason();
 if(voice)$('voice-info').textContent=voice.name+' · '+voice.meta.duration.toFixed(2)+' 秒';
 if(sub)$('subtitle-info').textContent=sub.name+' · '+wf.cues.length+' 页'+(wf.dirtySubtitle?' · 修改未保存':'');
 wfCaption();
}
async function wfResources(){
 for(const kind of ['voice','subtitle','music']){if(!imports[kind]){delete wf.resources[kind];continue;}if(wf.resources[kind]?.id===imports[kind])continue;wf.resources[kind]=await api('/api/workflow/resources/'+imports[kind]);if(kind==='subtitle'){wf.cues=structuredClone(wf.resources[kind].meta.cues);wf.dirtySubtitle=false;wfCues();}if(kind==='voice'){$('wf-current-voice').src=wf.resources[kind].url;$('wf-voice').src=wf.resources[kind].url;}if(kind==='music'){$('wf-music').src=wf.resources[kind].url;$('music-info').textContent=wf.resources[kind].name;}}
 if(!imports.voice){$('wf-current-voice').removeAttribute('src');$('wf-voice').removeAttribute('src');}if(!imports.music)$('wf-music').removeAttribute('src');wfRefresh();
}
function wfCues(){
 $('wf-cues').replaceChildren();wf.cues.forEach((c,i)=>{const tr=el('tr');for(const key of ['start','end','text']){const td=el('td'),input=el('input');input.type=key==='text'?'text':'number';input.value=c[key];input.setAttribute('aria-label',`字幕 ${i+1} ${key}`);if(key!=='text'){input.step='.01';input.min=0;}if(key==='text')input.onkeydown=e=>{if(e.key==='Backspace'&&!e.isComposing&&input.selectionStart===0&&input.selectionEnd===0){e.preventDefault();wfMergeCue(i);return;}if(e.key==='Enter'&&!e.isComposing){e.preventDefault();wfSplitCue(i,input).catch(err=>notice(err.message,true));}};input.oninput=()=>{c[key]=key==='text'?input.value:Number(input.value);wf.dirtySubtitle=true;wf.confirmed_subtitle=null;wfChanged();};td.append(input);tr.append(td);}const td=el('td'),play=el('button','定位'),del=el('button','删除');play.onclick=()=>wfSeek(c.start+Number($('subtitle-offset').value)).catch(e=>notice(e.message,true));del.onclick=()=>{wf.cues.splice(i,1);wf.dirtySubtitle=true;wf.confirmed_subtitle=null;wfCues();wfChanged();};td.append(play,del);tr.append(td);$('wf-cues').append(tr);});
}
async function wfSplitCue(index,input){
 if(wf.splitting)throw Error('正在定位分割时间，请稍候');
 if(input.selectionStart!==input.selectionEnd)throw Error('请先取消文字选中，把光标放到要分割的位置');
 const cue=structuredClone(wf.cues[index]),voice=imports.voice,sub=imports.subtitle;
 const position=Array.from(input.value.slice(0,input.selectionStart)).length;
 wf.splitting=true;
 try{
  const result=await api('/api/workflow/subtitles/split',{voice_id:voice,subtitle_id:sub,cue,position});
  if(imports.voice!==voice||imports.subtitle!==sub||JSON.stringify(wf.cues[index])!==JSON.stringify(cue))throw Error('字幕或配音已变化，请重新分割');
  wf.cues.splice(index,1,...result.cues);wf.dirtySubtitle=true;wf.confirmed_subtitle=null;wfCues();wfChanged();
  notice(result.estimated?'已自动拆成两条：词内切点为声学估计，请联播确认后再保存。':'已按配音词边界拆成两条；请试听分割点，再保存字幕修改。');
 }finally{wf.splitting=false;}
}
function wfMergeCue(index){
 if(wf.splitting){notice('正在分割，请稍候',true);return;}
 if(index===0)return;
 const previous=wf.cues[index-1],current=wf.cues[index];
 if(current.start<previous.start||current.end<=previous.end){notice('两条字幕时间重叠或顺序异常，请先核对',true);return;}
 const pos=previous.text.length;
 wf.cues.splice(index-1,2,{start:previous.start,end:current.end,text:previous.text+current.text});
 wf.dirtySubtitle=true;wf.confirmed_subtitle=null;wfCues();wfChanged();
 const input=$('wf-cues').querySelectorAll('tr')[index-1]?.querySelector('input[type=text]');if(input){input.focus();input.setSelectionRange(pos,pos);}
 notice('已合并到上一句，保留首句入点和末句出点；请试听后保存。');
}
const initialSelectionDraft=localStorage.getItem('cutframe-workflow-draft');
let restoringSelection=!!initialSelectionDraft;
function wfSaveDraft(){
 clearTimeout(wf.draftTimer);wf.draftTimer=null;
 if(wf.loading||restoringSelection)return;
 localStorage.setItem('cutframe-workflow-draft',JSON.stringify({project:project(),identity:wfProjectIdentity,cues:wf.cues,dirtySubtitle:wf.dirtySubtitle,time:new Date().toLocaleString()}));
 $('wf-draft').textContent='本机草稿已自动保存。';
}
function wfChanged(){
 if(wf.loading||restoringSelection)return;
 wfRefresh();clearTimeout(wf.draftTimer);
 wf.draftTimer=setTimeout(()=>{try{wfSaveDraft();}catch(e){notice('草稿保存失败：'+e.message,true);}},500);
}
window.addEventListener('pagehide',()=>{if(wf.draftTimer)wfSaveDraft();});
window.addEventListener('DOMContentLoaded',async()=>{
 try{
  const d=JSON.parse(initialSelectionDraft);
  if(d?.project&&(d.project.id||d.project.workflow?.script||d.project.imports?.voice||d.project.workflow?.storyboard?.tasks?.length)){
   await wfOpen(d.project);
   if(d.identity?.id===projectId)wfProjectIdentity=d.identity;
   if(d.dirtySubtitle){wf.cues=d.cues;wf.dirtySubtitle=true;wfCues();}
   wfRefresh();
  }
 }catch(e){notice('恢复选片草稿失败：'+e.message,true);}
 finally{restoringSelection=false;}
});
root.addEventListener('input',e=>{if(e.target.id==='tts-text'){wf.confirmed_voice=null;wf.confirmed_subtitle=null;}wfChanged();});
root.addEventListener('change',()=>{wfPause();wfChanged();});
action('wf-add-cue',()=>{const start=wf.cues.at(-1)?.end||0;wf.cues.push({start,end:start+1,text:''});wf.dirtySubtitle=true;wf.confirmed_subtitle=null;wfCues();wfChanged();});
action('wf-save-subtitles',async()=>{const current=wf.resources,voice=imports.voice,snapshot=JSON.stringify(wf.cues);
 const r=await api('/api/workflow/subtitles/save',{cues:wf.cues,voice_id:voice});
 if(current!==wf.resources||voice!==imports.voice)return;
 if(snapshot!==JSON.stringify(wf.cues))throw Error('保存期间字幕又有修改，请保存最新字幕');
 imports.subtitle=r.id;wf.confirmed_subtitle=null;await wfResources();wfChanged();notice('字幕已另存，原版本保留。');});
action('wf-generate-subtitles',async()=>{if(jobId)throw Error('请等待当前任务完成');if(!imports.voice)throw Error('先采用配音');$('wf-generate-subtitles').disabled=true;try{const r=await api('/api/workflow/subtitles/generate',{voice_id:imports.voice,text:$('tts-text').value});$('wf-subtitle-state').textContent='正在本地生成…';const j=await watch(r.job_id,async result=>{imports.subtitle=result.id;wf.confirmed_subtitle=null;await wfResources();typeof workflowSubtitleWarnings==='function'?workflowSubtitleWarnings(result.warnings):$('wf-subtitle-state').textContent=result.warnings.join('；')||'字幕已生成并保存';wfChanged();});if(j.status!=='done')$('wf-subtitle-state').textContent=j.message;}finally{$('wf-generate-subtitles').disabled=false;}});
action('wf-style',()=>{$('subtitle-font').value='yahei';$('subtitle-weight').value='regular';$('font-size').value=72;$('subtitle-bottom').value=360;wfChanged();});
const baseRenderShots=renderShots;renderShots=function(){baseRenderShots();let offset=0;document.querySelectorAll('#shots .shot').forEach((card,i)=>{const s=shots[i],at=Number.isFinite(s.timeline_start)?s.timeline_start:offset;offset=at+s.end-s.start;card.append(el('p',`${at.toFixed(2)}–${offset.toFixed(2)} 秒 · `+wf.cues.filter(c=>c.end+Number($('subtitle-offset').value)>at&&c.start+Number($('subtitle-offset').value)<offset).map(c=>c.text).join(' / '),'small'));const b=el('button','预览这个镜头');b.onclick=()=>wfSeek(at).catch(e=>notice(e.message,true));card.append(b);});wfChanged();};
for(const id of ['tts-use','voice','subtitle','music']){const n=$(id),event=id==='tts-use'?'onclick':'onchange',fn=n[event];n[event]=async(...args)=>{const current=wf.resources,previous=imports.voice;await fn(...args);if(current!==wf.resources)return;if((id==='tts-use'||id==='voice')&&previous!==imports.voice){if(previous)delete imports.subtitle;wfPause();shotPreview.reset();wf.time=0;wf.shotIndex=-1;wf.confirmed_voice=null;wf.confirmed_subtitle=null;if(!imports.subtitle){wf.cues=[];wf.dirtySubtitle=false;wfCues();$('subtitle-info').textContent='配音已变化，请按当前配音重新生成字幕';}}if(id==='subtitle')wf.confirmed_subtitle=null;if(id==='music'&&imports.music)wf.no_music=false;await wfResources();wfChanged();};}
action('wf-list-music',async()=>{const d=await api('/api/workflow/music');$('wf-music-list').replaceChildren(el('option','选择试听音乐'));$('wf-music-list').firstChild.value='';for(const item of d.items){const o=el('option',item.name);o.value=item.id;$('wf-music-list').append(o);}});
$('wf-music-list').onchange=()=>{const id=$('wf-music-list').value;$('wf-music-audition').pause();if(id)$('wf-music-audition').src='/api/workflow/music/'+id;};
action('wf-use-music',async()=>{if(!$('wf-music-list').value)throw Error('请先选一首音乐');const r=await api('/api/workflow/music/use',{id:$('wf-music-list').value});imports.music=r.id;wf.no_music=false;await wfResources();wfChanged();});
action('wf-no-music',async()=>{delete imports.music;wf.no_music=true;$('music-info').textContent='本片不使用背景音乐';await wfResources();wfChanged();});
async function wfOpen(d){if(jobId)throw Error('请等待当前制作任务完成后再切换工程');clearTimeout(wf.draftTimer);wfClearProjectPreview();
 wfProjectIdentity=d.id?{id:d.id,name:d.name,script:d.workflow?.script}:null;
 $('film-result').replaceChildren();wf.loading=true;wfPause();try{projectId=d.id||null;$('project-name').value=d.name||'';shots.splice(0,shots.length,...(d.shots||[]));Object.keys(imports).forEach(k=>delete imports[k]);Object.assign(imports,d.imports||{});wf.resources={};wf.cues=[];wf.dirtySubtitle=false;wfCues();const map={canvas:'canvas',fps:'fps',fit:'fit',source_audio:'source-audio',voice_offset:'voice-offset',music_start:'music-start',music_volume:'music-volume',music_fade:'music-fade',subtitle_offset:'subtitle-offset',subtitle_font:'subtitle-font',subtitle_weight:'subtitle-weight',font_size:'font-size',subtitle_bottom:'subtitle-bottom'};const settings={canvas:'1080x1920',fps:30,fit:'contain',source_audio:'mute',voice_offset:0,music_start:0,music_volume:.12,music_fade:d.id?0:1.5,subtitle_offset:0,subtitle_font:'yahei',subtitle_weight:'regular',font_size:72,subtitle_bottom:360,...d.settings};for(const [key,id]of Object.entries(map))$(id).value=key==='music_volume'?settings[key]*100:settings[key];wf.confirmed_voice=d.workflow?.confirmed_voice||null;wf.confirmed_subtitle=d.workflow?.confirmed_subtitle||null;wf.no_music=d.workflow?.no_music||false;await wfResources();$('tts-text').value=d.workflow?.script||wf.resources.voice?.meta.tts?.text||'';renderShots();await wfVersions();wf.shotIndex=-1;await wfSeek(0);wfStep(d.workflow?.step||1);$('wf-draft').textContent='工程已打开；修改会自动保存为本机草稿。';$('wf-preview-status').textContent='工程已载入。点击播放预览，或定位某一句字幕、某个镜头。';}finally{wf.loading=false;}}
action('load-project',async()=>{if(!$('project-list').value)throw Error('请选择工程');await wfOpen(await api('/api/projects/'+$('project-list').value));});
action('wf-new',async()=>{wfChanged();clearTimeout(wf.draftTimer);localStorage.setItem('cutframe-workflow-draft',JSON.stringify({project:project(),cues:wf.cues,dirtySubtitle:wf.dirtySubtitle}));await wfOpen({});notice('已新建；上一份未归档内容仍可通过恢复本机草稿找回。');});
action('wf-restore',async()=>{const raw=localStorage.getItem('cutframe-workflow-draft');if(!raw)throw Error('没有本机草稿');const d=JSON.parse(raw);await wfOpen(d.project);if(d.dirtySubtitle){wf.cues=d.cues;wf.dirtySubtitle=true;wfCues();}wfRefresh();});
action('wf-discard',()=>{clearTimeout(wf.draftTimer);localStorage.removeItem('cutframe-workflow-draft');$('wf-draft').textContent='已清除本机草稿，已保存工程不受影响。';});
action('save-project',async()=>{if(!$('project-name').value.trim()){wfStep(1);$('project-name').focus();throw Error('请先填写城市工程名，再保存工程；配音、字幕和本机草稿均保留。');}if(wf.dirtySubtitle)throw Error('请先保存字幕修改');const payload=project();const d=await api('/api/projects',payload);projectId=d.id;wfProjectIdentity={id:d.id,name:payload.name,script:payload.workflow.script};await loadProjects();$('project-list').value=d.id;wfChanged();notice('工程已保存，文案和步骤一同保留。');});
async function wfVersions(){const id=projectId,ctx=wf.resources;const films=id?(await api('/api/workflow/films/'+id)).items:[];if(id!==projectId||ctx!==wf.resources)return;wf.films=films;$('wf-versions').replaceChildren();for(const f of wf.films){const b=el('button','播放 v'+f.result.version+' · '+f.result.duration.toFixed(2)+' 秒');b.onclick=()=>{wfPause();$('film-result').replaceChildren(el('p',f.result.path,'small'));const v=el('video');v.controls=true;v.src=f.result.url;$('film-result').append(v);};$('wf-versions').append(b);}if(!wf.films.length)$('wf-versions').append(el('p','尚无成片版本','small'));wfRefresh();}
action('render-film',async()=>{if(wf.dirtySubtitle)throw Error('请先保存字幕');wfPause();$('render-film').disabled=true;try{const d=await api('/api/render',captionFonts.renderPayload(project(),wf.cues));projectId=d.project_id;await watch(d.job_id,async r=>{await wfVersions();$('film-result').replaceChildren(el('p',r.path,'small'));const v=el('video');v.controls=true;v.src=r.url;$('film-result').append(v);notice('新成片已生成，请完整播放验收。');});}finally{wfRefresh();}});
function wfClearProjectPreview(){
 shotPreview.reset();wf.time=0;wf.shotIndex=-1;wf.failedVisual=null;wf.proxy={};wf.playRange=null;
 wf.films=[];$('wf-versions').replaceChildren();$('wf-caption').textContent='';
 selectTts('');$('tts-history').value='';$('tts-status').textContent='';
 for(const id of ['tts-player','wf-current-voice','wf-voice','wf-music','wf-music-audition']){
  const player=$(id);player.pause();player.removeAttribute('src');player.load();
 }
 for(const kind of ['voice','subtitle','music'])$(kind+'-info').textContent='未导入';
}
function wfDifferentVideo(){
 if(!projectId||(!shots.length&&!imports.voice))return false;
 const name=$('project-name').value.trim(),script=$('tts-text').value.trim();
 const film=wf.films?.find(f=>f.project?.id===projectId)?.project;
 const changed=old=>old?.name&&old?.script&&old.name.trim()!==name&&old.script.trim()!==script;
 return Boolean(name&&script&&(changed(wfProjectIdentity)||changed(film&&{name:film.name,script:film.workflow?.script})));
}
// 改工程名并写了新文案，下一次保存或进入制作时沿用样式、启用独立时间线。
let wfOpeningNewVideo=false;
root.addEventListener('click',async event=>{
 const button=event.target.closest('button');
 if(!button||!(/^(wf-step-[1-6]|wf-next|save-project|wf-save-all|tts-generate|wf-play)$/.test(button.id)))return;
 if(!wfOpeningNewVideo&&!wfDifferentVideo())return;
 event.preventDefault();event.stopImmediatePropagation();
 if(wfOpeningNewVideo)return;
 wfOpeningNewVideo=true;
 try{
  const p=project(),settings={};
  for(const k of ['canvas','fps','fit','subtitle_font','subtitle_weight','font_size','subtitle_bottom'])settings[k]=p.settings[k];
  await wfOpen({name:p.name,settings,workflow:{script:p.workflow.script,step:wf.step,material_scope:p.workflow.material_scope}});
  wfOpeningNewVideo=false;wfChanged();button.click();
 }catch(e){notice(e.message,true);}finally{wfOpeningNewVideo=false;}
},true);
function wfAudition(){
 return wf.step===2&&ttsSelection?.id&&ttsSelection.id!==imports.voice?ttsSelection:null;
}
function wfBoardVoiceChanged(){
 if(typeof board==='undefined'||board.mode!=='subtitle'||!board.context)return false;
 if(wf.boardContext!==board.context){
  wf.boardContext=board.context;
  try{wf.boardVoice=JSON.parse(board.context)?.voice;}catch{wf.boardVoice=null;}
 }
 return Boolean(wf.boardVoice&&wf.boardVoice!==imports.voice);
}
function wfDuration(){return Math.max(wfBoardVoiceChanged()?0:shots.reduce((n,s)=>n+s.end-s.start,0),wf.resources.voice?.meta.duration+Number($('voice-offset').value)||0,1);}
function wfCaption(){
 const audition=wfAudition(),empty=!shots.length||!!audition||wfBoardVoiceChanged();
 const frame=$('wf-frame'),caption=$('wf-caption'),play=$('wf-play'),seek=$('wf-seek');
 const [w,h]=$('canvas').value.split('x').map(Number);
 const size=Math.max(.1,Number($('font-size').value)||.1),bottom=Number($('subtitle-bottom').value);
 for(const video of shotPreview.videos){
  video.style.display=empty?'none':'';
  video.style.objectFit=$('fit').value==='cover'?'cover':'contain';
 }
 $('wf-proxy').disabled=empty;
 frame.style.aspectRatio=w+'/'+h;caption.style.fontSize=size*frame.clientWidth/w+'px';
 caption.style.bottom=bottom/h*100+'%';
 const cueTime=wf.time-Number($('subtitle-offset').value);
 const cue=audition?null:wf.cues.find(c=>cueTime>=c.start&&cueTime<c.end);
 caption.textContent=cue?.text.replace(/[，。！？、；：,.!?;:]+$/,'')||'';
 $('wf-font-status').textContent=`全片统一字号：${size}。不自动缩小；长句超出画面时可在文字中按回车拆分字幕。`;
 captionFonts.preview(caption,w,h,size,bottom);
 const player=$('tts-player'),time=audition?player.currentTime:wf.time,duration=audition?audition.duration:wfDuration();
 $('wf-time').textContent=`${time.toFixed(2)} / ${duration.toFixed(2)} 秒`;seek.max=duration;seek.value=time;
 if(audition){
  wf.wasAudition=true;
  play.disabled=!player.getAttribute('src');
  play.textContent=player.paused?'播放试听配音':'暂停试听配音';
  $('wf-preview-status').textContent='正在试听 '+audition.name+'，采用后可按这条配音生成字幕。';return;
 }
 play.disabled=false;play.textContent=wf.playing?'暂停预览':'播放预览';
 if(empty&&imports.voice)$('wf-preview-status').textContent=wfBoardVoiceChanged()?'当前配音已更换，请按新字幕核对镜头。':'当前工程尚未选入镜头，可先播放配音与已生成的字幕。';
 else if(wf.wasAudition)$('wf-preview-status').textContent='正在预览当前工程。';
 wf.wasAudition=false;
}
let wfPlaybackSerial=0;
function wfPause(){
 ++wfPlaybackSerial;
 if(wf.step===4&&typeof sbPlayingFilm!=='undefined'&&sbPlayingFilm)$('sb-player').pause();
 shotPreview.cancel();wf.playing=false;cancelAnimationFrame(wf.raf);
 root.querySelectorAll('audio,video:not(#sb-player)').forEach(v=>v.pause());
 $('wf-play').textContent='播放预览';
}

function wfSyncAudio(position=false){
 const fade=Number($('music-fade').value);
 for(const kind of ['voice','music']){
  if(!imports[kind])continue;
  const music=kind==='music',a=$('wf-'+kind);
  const start=music?wf.time+Number($('music-start').value):wf.time-Number($('voice-offset').value);
  const factor=music&&fade>0?Math.min(1,Math.max(0,(wfDuration()-wf.time)/fade)):1;
  a.volume=music?Math.max(0,Math.min(1,Number($('music-volume').value)/100*factor)):1;
  if(start<0){if(!a.paused)a.pause();continue;}
  if(position)a.currentTime=Math.min(start,Number.isFinite(a.duration)?a.duration:start);
  if(!wf.playing||!a.paused||start>=a.duration)continue;
  if(!position)a.currentTime=start;
  const serial=wfPlaybackSerial;
  a.play().catch(e=>{
   if(serial!==wfPlaybackSerial||e.name==='AbortError')return;
   wfPause();$('wf-preview-status').textContent=music?'配乐播放失败，请重新播放。':'配音播放失败，请重新播放。';
  });
 }
}

async function wfSeek(t){
 wf.playRange=null;wfPause();wf.time=Math.max(0,Math.min(t,wfDuration()));
 wfSyncAudio(true);wfCaption();await wfVisual(true);
}

async function wfVisual(seek=false){
 if(wfBoardVoiceChanged())return;
 const serial=wfPlaybackSerial,single=wf.step===4&&typeof sbPlayback!=='undefined';
 if(single&&!sbPlayingFilm)return;
 const preview=single?sbPlayback:shotPreview;
 const plan=typeof subtitlePlaybackPlan==='function'?subtitlePlaybackPlan():{shots,errors:[],gaps:[]},visualShots=plan.shots;
 let at=0,index=-1;
 for(let i=0;i<visualShots.length;i++){
  const shot=visualShots[i];
  if(Number.isFinite(shot.timeline_start))at=shot.timeline_start;
  if(wf.time>=at&&wf.time<at+shot.end-shot.start){index=i;break;}
  at+=shot.end-shot.start;
 }
 if(index<0){
  preview.active.pause();wf.shotIndex=-1;
  if(typeof board!=='undefined'&&board.mode==='subtitle'&&wf.step>=4){
   wfPause();$('wf-preview-status').textContent=plan.gaps.find(g=>wf.time>=g.start&&wf.time<g.end)?.error||'此时段还没有可播放镜头，请完成对应字幕选片。';
  }
  return;
 }
 const s=visualShots[index],next=visualShots[index+1],end=at+s.end-s.start;
 wf.shotIndex=index;
 if(seek)wf.failedVisual=null;
 if(wf.playing&&wf.failedVisual===index)return;
 try{
  const url=wf.proxy[s.asset_id]||'/media/'+s.asset_id;
  const upcoming=next?{url:wf.proxy[next.asset_id]||'/media/'+next.asset_id,start:next.start}:null;
  if(serial!==wfPlaybackSerial||wf.time>=end)return;
  const key=index+':'+url,target=s.start+wf.time-at;
  const v=await preview.show(key,url,target,upcoming,seek);
  if(!v||serial!==wfPlaybackSerial||wf.time>=end)return;
  v.muted=$('source-audio').value==='mute';v.style.objectFit=$('fit').value==='cover'?'cover':'contain';
  if(wf.playing){
   // 解码可能晚于切点。只定位画面，配音始终沿原音频播放。
   const now=s.start+wf.time-at;
   if(!v.seeking&&Math.abs(v.currentTime-now)>.18)v.currentTime=now;
   if(v.paused)await v.play();
  }
 }catch(e){
  if(serial!==wfPlaybackSerial||wf.time>=end)return;
  wf.failedVisual=index;preview.active.pause();
  $('wf-preview-status').textContent=e.message;
 }
}

// 限定播放的结束和字幕更新都跟随配音，不等待某个镜头下载或解码。
async function wfFinishRange(){
 const range=wf.playRange;if(!range)return;
 wfPause();wf.playRange=null;wf.time=Math.max(range.start,range.end-.000001);
 const serial=wfPlaybackSerial;
 wfSyncAudio(true);wfCaption();await wfVisual(true);
 if(serial!==wfPlaybackSerial)return;
 $('wf-preview-status').textContent='联播已结束，保留末尾画面与字幕；可再次点击联播重播。';
}
action('wf-play',async()=>{
 if(wfAudition()){
  const player=$('tts-player');
  if(player.paused){wfPause();if(player.ended)player.currentTime=0;await player.play();}
  else player.pause();
  wfCaption();return;
 }
 if(wf.playing){wfPause();return;}
 const serial=++wfPlaybackSerial;
 await wfResources();if(serial!==wfPlaybackSerial)return;
 if(wf.time>=wfDuration()-.02)wf.time=0;
 wf.playing=true;wf.failedVisual=null;wf.clock=performance.now()-wf.time*1000;
 wfSyncAudio(true);
 $('wf-play').textContent='暂停预览';$('wf-preview-status').textContent='正在按工程配音原速播放，字幕和镜头跟随配音。';
 let drawing=false;
 const tick=async()=>{
  if(serial!==wfPlaybackSerial||!wf.playing)return;
  const voice=$('wf-voice'),offset=Number($('voice-offset').value);
  if(imports.voice&&!voice.paused&&wf.time>=offset){
   wf.time=voice.currentTime+offset;wf.clock=performance.now()-wf.time*1000;
  }else wf.time=(performance.now()-wf.clock)/1000;
  if(wf.playRange&&wf.time>=wf.playRange.end){await wfFinishRange();return;}
  if(wf.time>=wfDuration()){wf.time=wfDuration();wfPause();wfCaption();return;}
  wfSyncAudio();wfCaption();
  if(!drawing){
   drawing=true;wfVisual().finally(()=>{drawing=false;});
  }
  if(serial===wfPlaybackSerial)wf.raf=requestAnimationFrame(tick);
 };
 wf.raf=requestAnimationFrame(tick);
});
$('wf-seek').oninput=()=>{
 const t=Number($('wf-seek').value);
 if(wfAudition()){$('tts-player').currentTime=t;wfCaption();return;}
 wfSeek(t).catch(e=>notice(e.message,true));
};
for(const ev of ['loadedmetadata','timeupdate','play','pause','ended'])$('tts-player').addEventListener(ev,()=>{if(wfAudition())wfCaption();});
action('wf-proxy',async()=>{const s=shots[wf.shotIndex];if(!s)throw Error('请先定位到一个镜头');wfPause();const r=await api('/api/proxy/'+s.asset_id,{});const use=async d=>{wf.proxy[s.asset_id]=d.url;wf.shotIndex=-1;await wfSeek(wf.time);};if(r.url)await use(r);else await watch(r.job_id,use);});
new ResizeObserver(()=>wfCaption()).observe($('wf-frame'));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{wfPause();if(b.dataset.view==='compose')wfCaption();}));
captionFonts.init().catch(e=>notice(e.message,true));wfStep(1);if(localStorage.getItem('cutframe-workflow-draft'))$('wf-draft').textContent='检测到本机草稿，可点击“恢复本机草稿”继续。';

action('wf-copy',async()=>{if(wf.dirtySubtitle)throw Error('请先保存字幕修改');const p=project();delete p.id;const d=await api('/api/projects',p);projectId=d.id;await loadProjects();$('project-list').value=d.id;await wfVersions();wfChanged();notice('已另存为新工程，原工程保留。');});

const saveAll=el('button','保存当前工程');saveAll.id='wf-save-all';saveAll.onclick=()=>$('save-project').onclick();document.querySelector('.wf-navigation').after(saveAll);
const originalSelectTts=selectTts;selectTts=function(id){const text=$('tts-text').value;if(wf.playing)wfPause();
 originalSelectTts(id);$('tts-text').value=text;wfCaption();
};


