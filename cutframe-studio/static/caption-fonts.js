'use strict';

// 字体文件只分发开源的思源黑体。缺少微软雅黑的服务器接收整句字幕图。
const captionFonts = (() => {
  const member = typeof memberFetch === 'function';
  const localFaces = new Set();
  const sourceReady = new Set();
  let capability = null;
  let failed = '';
  let lastPreview = '';
  let bitmap;

  function selection() {
    return {family: $('subtitle-font').value, weight: $('subtitle-weight').value};
  }
  function assetMode(family, weight) {
    if (!member) return 'server';
    if (!capability || !capability.available) return '';
    if (capability.fonts?.[family]?.[weight]) return 'server';
    if (family === 'yahei' && localFaces.has(weight)) return 'browser';
    return '';
  }
  function reason() {
    const {family, weight} = selection();
    if (failed) return failed;
    if (member && !capability) return '正在检测导出字体';
    if (member && !capability.available) return capability.reasons.join('，');
    if (assetMode(family, weight)) return '';
    return family === 'yahei' ? '此设备和服务器均缺少所选微软雅黑。可在第三步选思源黑体，或换用装有微软雅黑的浏览器。' : '服务器缺少所选思源黑体文件';
  }
  async function init() {
    const faces = [['regular','Microsoft YaHei','微软雅黑'],['bold','Microsoft YaHei Bold','微软雅黑 Bold']];
    const tasks = faces.map(async ([weight,en,cn]) => {
      try {
        const face = new FontFace('Jingxu YaHei', 'local("'+en+'"), local("'+cn+'")', {weight: weight==='bold'?'700':'400'});
        await face.load();
        document.fonts.add(face);
        localFaces.add(weight);
      } catch { /* 用户设备可能未安装此字体。 */ }
    });
    if (member) tasks.push(api('/api/workflow/render-capability').then(info => { capability=info; }).catch(() => { failed='云端字体检测失败，请刷新重试'; }));
    await Promise.all(tasks);
    wfRefresh();
  }
  function strip(text, width, height, size, weight) {
    const canvas = document.createElement('canvas');
    canvas.width=width;
    canvas.height=Math.min(height,Math.ceil(size*1.5+8));
    const ctx=canvas.getContext('2d');
    ctx.font=(weight==='bold'?'700':'400')+' '+size+'px "Jingxu YaHei"';
    ctx.textAlign='center';
    ctx.textBaseline='middle';
    ctx.lineJoin='round';
    ctx.lineWidth=4;
    ctx.strokeStyle='#101010';
    ctx.fillStyle='white';
    const y=canvas.height-size*0.625-1;
    ctx.strokeText(text,width/2,y);
    ctx.fillText(text,width/2,y);
    return canvas;
  }
  function preview(label, w, h, size, bottom) {
    const {family,weight}=selection();
    label.style.fontFamily=family==='source-han'?'"Jingxu Source Han"':'"Jingxu YaHei","Microsoft YaHei",sans-serif';
    label.style.fontWeight=weight==='bold'?'700':'400';
    let message=reason();
    const client=assetMode(family,weight)==='browser';
    if (!message && client) message='微软雅黑由当前浏览器绘制整句字幕，云端合成。';
    if (family==='source-han' && !sourceReady.has(weight)) {
      if (!message) message='正在加载思源黑体预览';
      const key='load-'+weight;
      if (!sourceReady.has(key)) {
        sourceReady.add(key);
        document.fonts.load((weight==='bold'?'700':'400')+' 24px "Jingxu Source Han"','字幕')
          .then(faces=>{ if(faces.length)sourceReady.add(weight); }).catch(()=>{}).finally(()=>wfRefresh());
      } else if (document.fonts.status==='loaded' && !sourceReady.has(weight)) message='思源黑体预览尚未载入，请检查网络并刷新';
    }
    if (!message && member && family==='yahei' && !localFaces.has(weight)) message='当前设备缺少微软雅黑，预览字形可能有差异。';
    const example=$('subtitle-font-example');
    example.style.fontFamily=label.style.fontFamily;
    example.style.fontWeight=label.style.fontWeight;
    const sample=label.textContent || wf.cues[0]?.text || '我们免费上门量房';
    if (example.textContent!==sample) example.textContent=sample;
    const title=(family==='yahei'?'微软雅黑':'思源黑体')+' · '+(weight==='bold'?'粗体':'常规');
    const status=title+(message?'。'+message:'');
    if($('subtitle-font-note').textContent!==message) $('subtitle-font-note').textContent=message;
    if($('render-font-note').textContent!==status) $('render-font-note').textContent=status;
    label.style.visibility=client?'hidden':'visible';
    if (bitmap) bitmap.hidden=!client;
    if (!client) { lastPreview=''; return; }
    const key=JSON.stringify([label.textContent,w,h,size,bottom,weight]);
    if (key===lastPreview) return;
    lastPreview=key;
    const next=strip(label.textContent,w,h,size,weight);
    next.className='wf-caption-art';
    next.style.bottom=bottom/h*100+'%';
    next.setAttribute('aria-hidden','true');
    if (bitmap) bitmap.replaceWith(next); else label.after(next);
    bitmap=next;
  }
  function renderPayload(project, cues) {
    const {family,weight}=selection();
    const error=reason();
    if(error) throw Error(error);
    if(assetMode(family,weight)!=='browser') return project;
    const [w,h]=project.settings.canvas.split('x').map(Number);
    const art=Object.create(null);
    for (const cue of cues) {
      const line=cue.text.trim().replace(/[，。！？、；：,.!?;:]+$/,'');
      if (!Object.hasOwn(art,line)) art[line]=strip(line,w,h,project.settings.font_size,weight).toDataURL('image/png').split(',')[1];
    }
    return {...project,caption_art:art};
  }
  return {init,preview,reason,renderPayload};
})();
