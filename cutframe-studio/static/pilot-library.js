/* 仅显示可用表收录的原片及其已核秒段。 */
const reviewedShelf = (() => {
 const key='__reviewed__', root=$('root'), type=el('select');
 const controls=el('div');
 type.setAttribute('aria-label','筛选画面类型');
 function option(value,name){const o=el('option',name);o.value=value;return o;}
 controls.append(type);$('search').before(controls);
 let catalog, chosen='';
 function mount(){
   if(!root.querySelector('option[value="__reviewed__"]')){
     root.append(option(key,'已筛选的竖屏片段'));
   }
   controls.hidden=root.value!==key;
 }
 async function pick(r){
   chosen=r.id;
   await select({id:r.id});$('start').value=r.start;$('end').value=r.end;$('player').currentTime=r.start;updateRange();
 }
 async function render(){
   catalog??=api('/static/baba-reviewed/items.json').catch(e=>{catalog=null;throw e;});
   const items=(await catalog).filter(r=>r.portrait===true && r.image===false);if(root.value!==key)return;
   if(!type.options.length){type.append(option('','全部画面类型'));for(const [c,n] of new Map(items.map(r=>[r.type,r.label])))type.append(option(c,c+' · '+n));}
   const q=$('search').value.trim().toLowerCase();
   const matches=items.filter(r=>(!type.value||r.type===type.value)&&(r.rel+' '+r.label+' '+r.type).toLowerCase().includes(q));
   total=matches.length;const pages=Math.max(1,Math.ceil(total/60));page=Math.min(page,pages);
   $('inventory').textContent='当前 '+total+' 个竖屏视频片段';
   $('page').textContent=page+' / '+pages;$('prev').disabled=page<=1;$('next').disabled=page>=pages;$('assets').replaceChildren();
   for(const r of matches.slice((page-1)*60,page*60)){const b=el('button',undefined,'asset'+(chosen===r.id?' selected':''));
     b.append(el('span',r.type+' · '+r.label),el('strong',r.rel.split('/').pop()),el('small',r.start+'–'+r.end+' 秒'));
     b.onclick=()=>pick(r).catch(e=>notice(e.message,true));$('assets').append(b);}
 }
 type.onchange=()=>{page=1;render().catch(e=>notice(e.message,true));};
 return {mount,render,refresh:()=>{catalog=null;return render();},active:()=>root.value===key};
})();

/* 分轮画面类型库：保留原库切换；未审预测不冒充人工标签。 */
(() => {
 const key='__pilot__';let round='',selected=null,tree=[],lastTypes={},blind=false;
 const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const errorsOnly=node('input');errorsOnly.type='checkbox';errorsOnly.checked=true;errorsOnly.id='pilot-errors-only';const errorsLabel=node('label');errorsLabel.append(errorsOnly,document.createTextNode('只看与旧审核不一致'));
 const controls=node('div');controls.id='pilot-controls';controls.hidden=true;
 const rounds=node('select');rounds.id='pilot-round';rounds.setAttribute('aria-label','试标轮次');const types=node('select');types.id='pilot-type';types.setAttribute('aria-label','画面类型');
 const blindLabel=node('label');const blindInput=node('input');blindInput.type='checkbox';blindInput.id='pilot-blind';blindLabel.append(blindInput,document.createTextNode('盲审：隐藏模型分类'));controls.append(rounds,types,errorsLabel,blindLabel);$('search').before(controls);
 let showFrame=false;const toggle=node('button','切换原片 / 四帧拼图');toggle.type='button';toggle.hidden=true;document.querySelector('.preview-tools').append(toggle);
 const panel=node('section');panel.id='pilot-review';panel.hidden=true;const title=node('h2');const image=node('img');image.alt='本次片段的四帧拼图';image.id='pilot-frame';const status=node('p');const label=node('select');label.id='pilot-code';label.setAttribute('aria-label','人工判定画面类型');const reviewer=node('input');reviewer.id='pilot-reviewer';reviewer.placeholder='实际审核人（必填）';reviewer.setAttribute('aria-label','实际审核人');const save=node('button','确认分类并用于本机选片');save.type='button';panel.append(title,status,label,reviewer,save);document.querySelector('.preview-tools').after(panel);document.querySelector('.player-wrap').append(image);image.hidden=true;toggle.onclick=()=>{showFrame=!showFrame;image.hidden=!showFrame;$('player').hidden=showFrame;if(showFrame)$('player').pause();};
 async function labels(){const data=await api('/api/local/labels');tree=data.labels.filter(t=>t.dimension==='画面类型'&&!t.group&&t.enabled);label.replaceChildren();const empty=node('option','请选择画面类型');empty.value='';label.append(empty);for(const t of tree){const o=node('option',`${t.id} · ${t.name}`);o.value=t.id==='B1U01'?'看不清':t.id;label.append(o);}}
 function drawTypes(){const before=types.value;types.replaceChildren();const all=node('option','全部画面类型');all.value='';types.append(all);for(const t of tree){const code=t.id==='B1U01'?'看不清':t.id;const o=node('option',`${t.id} ${t.name}（${lastTypes[code]||0}）`);o.value=code;types.append(o);}types.value=blind?'':before;types.disabled=blind;}
 function mount(){if(!$('root').querySelector(`option[value="${key}"]`)){const option=node('option','试标素材 · 按画面类型');option.value=key;$('root').prepend(option);$('root').value=key;page=1;}controls.hidden=$('root').value!==key;panel.hidden=$('root').value!==key||!selected;toggle.hidden=panel.hidden;if($('root').value!==key){image.hidden=true;$('player').hidden=false;}}
 async function render(){mount();if(!tree.length)await labels();if(!round){const data=await api('/api/pilot/rounds');rounds.replaceChildren();for(const r of data.items){const o=node('option',`${r.name} · ${r.count}段`);o.value=r.id;rounds.append(o);}const requested=new URLSearchParams(location.search).get('round');if(requested&&[...rounds.options].some(o=>o.value===requested))rounds.value=requested;round=rounds.value;}
  const data=await api(`/api/pilot/items?round=${encodeURIComponent(round)}&code=${encodeURIComponent(blind?'':types.value)}&q=${encodeURIComponent($('search').value)}&page=${page}&mismatches=${errorsOnly.checked&&!blind?'1':'0'}`);lastTypes=data.types;errorsOnly.disabled=!data.has_baseline||blind;drawTypes();total=data.total;$('inventory').textContent=`试标 ${data.round_total} 段 · 已审核 ${data.reviewed} 段 · 旧审核差异 ${data.mismatches} 段 · 当前 ${total} 段${blind?' · 盲审模式':' · 未审分类是模型预测'}`;$('page').textContent=`${page} / ${Math.max(1,Math.ceil(total/60))}`;$('prev').disabled=page<=1;$('next').disabled=page*60>=total;$('assets').replaceChildren();
  if(!data.round_total)$('assets').append(node('p','本轮尚未导入完成的预测。2,000段是后续上限，当前先复验50段。'));
  for(const item of data.items){const b=node('button');b.className='asset';const codeName=tree.find(t=>t.id===item.code||t.name===item.code)?.name||item.code;b.append(node('span',blind?'待盲审':`${item.code} · ${codeName}`),node('strong',item.name),node('small',`${item.start.toFixed(3)}–${item.end.toFixed(3)}秒 · ${item.review?'人工已核':'模型预测未审'}`),node('small',item.sample_id));b.onclick=()=>pick(item).catch(e=>notice(e.message,true));$('assets').append(b);}}
 async function pick(item){selected=item;panel.hidden=false;toggle.hidden=false;showFrame=false;image.hidden=true;$('player').hidden=false;title.textContent=`${item.sample_id} · ${item.name}`;image.src='/api/pilot/frame/'+encodeURIComponent(item.id);status.textContent=`${!blind&&item.old_review_code?'旧审核 '+item.old_review_code+'，本轮模型 '+item.predicted_code+'（旧答案仅作对照，本轮需重新看）。':''}限定秒段 ${item.start.toFixed(3)}–${item.end.toFixed(3)}；${item.review?'已有人审核':'尚未人工审核'}。仅确认你实际看过的这几秒。`;label.value=blind?'':item.code;
  try{await select({id:item.asset_id});$('start').value=item.start;$('end').value=item.end;$('player').currentTime=item.start;updateRange();}catch(e){notice('原视频暂不可读，可先看现有拼图；当前不能保证能选入成片。'+e.message,true);current=null;meta=null;showFrame=true;image.hidden=false;$('player').hidden=true;}
  $('filename').scrollIntoView({block:'nearest'});}
 save.onclick=async()=>{try{if(!selected)throw Error('请先选择片段');if(!label.value)throw Error('请选择画面类型');await api('/api/pilot/review/'+encodeURIComponent(selected.id),{code:label.value,reviewer:reviewer.value,blind});notice('该秒段的人工分类已保存，可供标签库本机选片使用。');await render();}catch(e){notice(e.message,true);}};
 errorsOnly.onchange=()=>{page=1;render().catch(e=>notice(e.message,true));};rounds.onchange=()=>{round=rounds.value;selected=null;panel.hidden=true;page=1;render().catch(e=>notice(e.message,true));};types.onchange=()=>{page=1;render().catch(e=>notice(e.message,true));};blindInput.onchange=()=>{blind=blindInput.checked;selected=null;panel.hidden=true;toggle.hidden=true;image.hidden=true;showFrame=false;$('player').hidden=false;page=1;render().catch(e=>notice(e.message,true));};
 window.PilotLibrary={refresh:()=>reviewedShelf.active()?reviewedShelf.refresh():render(),mount:()=>{mount();reviewedShelf.mount();mount();},load:()=>reviewedShelf.active()?reviewedShelf.render():render(),isActive:()=>reviewedShelf.active()||$('root').value===key};
 if($('root').options.length){mount();load().catch(e=>notice(e.message,true));}
})();



