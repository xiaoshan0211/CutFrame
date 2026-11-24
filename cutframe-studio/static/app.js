'use strict';
// 局域网 HTTP 不提供 randomUUID；getRandomValues 仍可生成安全随机字节。
(function(root){
 const crypto=root.crypto;
 if(typeof crypto?.randomUUID==='function')return;
 if(typeof crypto?.getRandomValues!=='function')return;
 crypto.randomUUID=function(){
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const h=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
 };
})(globalThis);

const $=id=>document.getElementById(id), token=document.querySelector('meta[name="local-token"]').content;
let jobId=null,projectId=null;
const shots=[], imports={};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function notice(msg,error=false){$('notice').textContent=msg;$('notice').className=error?'error':'';$('notice').style.display='block';clearTimeout(notice.timer);notice.timer=setTimeout(()=>$('notice').style.display='none',error?16000:7000);}
async function api(url,body){const opts=body===undefined?{}:{method:'POST',headers:{'X-Local-Token':token},body:body instanceof FormData?body:JSON.stringify(body)};if(body!==undefined&&!(body instanceof FormData))opts.headers['Content-Type']='application/json';if((url.startsWith('/api/local/')||url.startsWith('/api/ai/'))&&typeof materialScope!=='undefined'){opts.headers??={};opts.headers['X-Material-Scope']=materialScope;}const r=await fetch(url,opts);const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
function action(id,fn){$(id).onclick=async()=>{try{await fn();}catch(e){notice(e.message,true);}};}
async function watch(jid,callback){jobId=jid;$('job-panel').hidden=false;while(jobId===jid){const j=await api('/api/jobs/'+jid);if(jobId!==jid)return;$('job-title').textContent=j.kind;$('job-message').textContent=j.message;$('progress').value=j.progress;if(['done','failed','cancelled','interrupted'].includes(j.status)){jobId=null;$('cancel-job').hidden=true;if(j.status==='done'){$('job-panel').hidden=true;notice('任务完成');if(callback)await callback(j.result);}else notice(j.message,true);return j;} $('cancel-job').hidden=false;await new Promise(r=>setTimeout(r,1000));}}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.view,.tab').forEach(n=>n.classList.remove('active'));$(b.dataset.view).classList.add('active');b.classList.add('active');if(b.dataset.view==='exports')loadExports().catch(e=>notice(e.message,true));if(b.dataset.view==='compose')loadProjects().catch(e=>notice(e.message,true));});
action('cancel-job',async()=>{if(jobId)await api('/api/jobs/'+jobId+'/cancel',{});});
function renderShots(){$('shots').replaceChildren();shots.forEach((s,i)=>{const card=el('div',undefined,'shot'),head=el('div',undefined,'shot-name');head.append(el('strong',`${String(i+1).padStart(2,'0')}  ${s.name}`));const buttons=el('div',undefined,'shot-actions');for(const [label,fn]of [['↑',()=>{if(i>0)[shots[i-1],shots[i]]=[shots[i],shots[i-1]];}],['↓',()=>{if(i<shots.length-1)[shots[i+1],shots[i]]=[shots[i],shots[i+1]];}],['×',()=>shots.splice(i,1)]]){const b=el('button',label);b.onclick=()=>{fn();renderShots();};buttons.append(b);}head.append(buttons);card.append(head);const times=el('div',undefined,'shot-times');for(const [key,label]of [['start','入点 / 秒'],['end','出点 / 秒']]){const l=el('label',label),input=el('input');input.type='number';input.step='.001';input.min='0';input.value=s[key];input.onchange=()=>{s[key]=Number(input.value);updateFilmDuration();};l.append(input);times.append(l);}card.append(times);$('shots').append(card);});updateFilmDuration();}
function updateFilmDuration(){$('film-duration').textContent=shots.reduce((n,s)=>n+s.end-s.start,0).toFixed(3)+' 秒';}
for(const kind of ['voice','music','subtitle'])$(kind).onchange=async()=>{try{const file=$(kind).files[0];if(!file)return;const form=new FormData();form.append('kind',kind);form.append('file',file);const r=await api('/api/imports',form);imports[kind]=r.id;$(kind+'-info').textContent=r.name+(r.meta?.duration?' · '+r.meta.duration.toFixed(2)+' 秒':'');}catch(e){notice(e.message,true);}};
function project(){return {id:projectId,name:$('project-name').value,shots,imports,settings:{canvas:$('canvas').value,fps:Number($('fps').value),fit:$('fit').value,source_audio:$('source-audio').value,voice_offset:Number($('voice-offset').value),music_start:Number($('music-start').value),music_volume:Number($('music-volume').value)/100,subtitle_offset:Number($('subtitle-offset').value),font_size:Number($('font-size').value),subtitle_bottom:Number($('subtitle-bottom').value)}};}
async function loadProjects(){const d=await api('/api/projects');$('project-list').replaceChildren(el('option','选择工程'));$('project-list').firstChild.value='';for(const p of d.items){const o=el('option',p.name);o.value=p.id;$('project-list').append(o);}}
action('save-project',async()=>{const d=await api('/api/projects',project());projectId=d.id;await loadProjects();$('project-list').value=d.id;notice('工程已保存到本地');});
action('load-project',async()=>{const id=$('project-list').value;if(!id)throw Error('请选择工程');const d=await api('/api/projects/'+id);projectId=d.id;$('project-name').value=d.name;shots.splice(0,shots.length,...d.shots);Object.keys(imports).forEach(k=>delete imports[k]);Object.assign(imports,d.imports);const map={canvas:'canvas',fps:'fps',fit:'fit',source_audio:'source-audio',voice_offset:'voice-offset',music_start:'music-start',music_volume:'music-volume',subtitle_offset:'subtitle-offset',font_size:'font-size',subtitle_bottom:'subtitle-bottom'};for(const [k,id]of Object.entries(map))if(d.settings[k]!==undefined)$(id).value=k==='music_volume'?d.settings[k]*100:d.settings[k];for(const k of ['voice','subtitle','music'])$(k+'-info').textContent=d.import_names?.[k]||'未导入';renderShots();notice('工程已恢复');});
action('render-film',async()=>{if(!shots.length)throw Error('请先添加镜头');const d=await api('/api/render',project());projectId=d.project_id;await watch(d.job_id,result=>{const box=$('film-result');box.replaceChildren(el('h2','完整成片验证'),el('p',result.path,'small'));const v=el('video');v.controls=true;v.src=result.url;box.append(v);box.scrollIntoView({behavior:'smooth'});});});
async function loadExports(){
  const d=await api('/api/clips');$('export-list').replaceChildren();
  for(const c of d.items){
    const m=JSON.parse(c.data),card=el('div',undefined,'export-card');
    card.append(el('strong',c.path),el('p',`${m.mode==='copy'?'无损切割':'精确转码'} · ${m.requested_start}–${m.requested_end} 秒 · ${m.category||'未分类'}`,'small'));
    const details=el('details');details.append(el('summary','查看来源与导出信息'));
    const fields=[['标签',(m.tags||[]).join('、')||'未填写'],['用途 / 对应文案',m.purpose||'未填写'],['来源素材库',({xiaoq:'拍摄 · 小区',baba:'扒扒 · 分类素材',chengdu:'参考成片 · 成都',suzhou:'参考成片 · 苏州'})[m.root_alias]||m.root_alias],['源文件相对路径',m.relative_path],['请求入出点',`${m.requested_start}–${m.requested_end} 秒`],['输出时长',`${m.output_meta?.duration??'未知'} 秒`],['切点核验状态',m.actual_source_boundaries?JSON.stringify(m.actual_source_boundaries):'未逐帧核验；请求时间不等于已验证的实际源帧边界'],['片段编号',m.clip_id],['来源素材编号',m.asset_id],['源文件大小',`${m.source_size} 字节`],['导出时间',m.created?new Date(m.created).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+'（北京时间）':'未记录'],['发布状态',m.publication_status==='published'?'已发布':m.publication_status]];
    for(const [label,value] of fields){const row=el('p');row.append(el('b',label+'：'),document.createTextNode(String(value??'未记录')));details.append(row);}
    card.append(details);$('export-list').append(card);
  }
  if(!d.items.length)$('export-list').append(el('p','尚无导出记录','small'));
}
loadProjects().catch(e=>notice(e.message,true));
api('/api/state').then(s=>{
 const active=s.jobs.find(j=>['queued','running'].includes(j.status));
 if(active)return watch(active.id);
}).catch(e=>notice(e.message,true));

let ttsSelection=null;
const ttsItems=new Map();
const speedPanel=document.createElement('div');speedPanel.id='tts-speed-panel';speedPanel.innerHTML='<label>配音语速（倍）<input id="tts-speed" type="number" min="0.5" max="2" step="0.05" value="1"></label><button id="tts-speed-apply">生成此语速试听</button><p class="small">0.5—2.0倍，默认1倍。生成后试听，再用作工程配音；字幕须按新音频重新生成，分镜须重新核对。原版保留。</p>';$('tts-player').after(speedPanel);
function ttsSpeedDirty(){return ttsSelection&&Math.abs(Number($('tts-speed').value)-(ttsSelection.speed||1))>.000001;}
$('tts-speed').oninput=()=>{$('tts-use').disabled=!ttsSelection||ttsSpeedDirty()||!$('tts-speed').checkValidity();if(ttsSpeedDirty())$('tts-status').textContent='语速尚未应用，播放器仍是上一版本；请点击“生成此语速试听”。';};
action('tts-speed-apply',async()=>{if(jobId)throw Error('请等待当前任务完成');if(!ttsSelection)throw Error('请先生成或选择配音');if(!$('tts-speed').checkValidity())throw Error('语速范围为0.5—2.0倍');const speed=Number($('tts-speed').value);$('tts-speed-apply').disabled=true;try{const r=await api('/api/tts/speed',{voice_id:ttsSelection.id,speed});const j=await watch(r.job_id,async result=>{await loadTts(result.id);});if(j.status!=='done')throw Error(j.message||'变速失败');}finally{$('tts-speed-apply').disabled=false;}});

async function loadTts(selected){
 const data=await api('/api/tts');ttsItems.clear();$('tts-history').replaceChildren(el('option','选择试听记录'));$('tts-history').firstChild.value='';
 for(const item of data.items){ttsItems.set(item.id,item);const o=el('option',item.name+' · '+item.duration.toFixed(2)+' 秒');o.value=item.id;$('tts-history').append(o);}
 if(selected&&ttsItems.has(selected)){$('tts-history').value=selected;selectTts(selected);}
}
function selectTts(id){ttsSelection=ttsItems.get(id)||null;$('tts-use').disabled=!ttsSelection;$('tts-player').pause();if(ttsSelection){$('tts-speed').value=ttsSelection.speed||1;$('tts-player').playbackRate=1;$('tts-player').src=ttsSelection.url;$('tts-player').hidden=false;$('tts-text').value=ttsSelection.text;$('tts-status').textContent='请完整试听，确认后用作本工程配音。';}else{$('tts-player').removeAttribute('src');$('tts-player').hidden=true;}}
$('tts-history').onchange=()=>selectTts($('tts-history').value);
action('tts-generate',async()=>{
 if(jobId)throw Error('请先等待当前任务结束');
 $('tts-generate').disabled=true;$('tts-status').textContent='准备生成…';
 try{const result=await api('/api/tts',{text:$('tts-text').value,name:$('project-name').value||'武汉翻新'});const job=await watch(result.job_id,async r=>{await loadTts(r.id);});if(job.status!=='done')$('tts-status').textContent=job.message;}
 catch(e){$('tts-status').textContent=e.message;throw e;}finally{$('tts-generate').disabled=false;}
});
action('tts-use',()=>{if(!ttsSelection)throw Error('请先选择配音');if(ttsSpeedDirty()||!$('tts-speed').checkValidity())throw Error('请先生成当前语速的试听版本');const changed=imports.voice!==ttsSelection.id;imports.voice=ttsSelection.id;if(changed)delete imports.subtitle;$('voice-info').textContent=ttsSelection.name+' · '+ttsSelection.duration.toFixed(2)+' 秒';$('tts-status').textContent='已用作本工程配音，请保存工程。';notice('已采用试听音频，成片使用同一语速。请按新配音生成字幕并核对分镜');});
loadTts().catch(e=>notice(e.message,true));

