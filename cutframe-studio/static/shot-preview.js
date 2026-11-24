'use strict';
// 双缓冲预览：下一镜头先定位并解码，准备好后才替换可见画面。
class ShotPreview {
  constructor(frame,video){
    this.frame=frame;this.active=video;this.serial=0;
    const other=video.cloneNode(false);other.id='wf-video-next';other.removeAttribute('src');
    other.style.visibility='hidden';other.muted=true;frame.insertBefore(other,video.nextSibling);
    this.videos=[video,other];this.entries=new Map();this.activeKey=null;
  }
  cancel(){this.serial++;this.videos.forEach(v=>v.pause());}
  reset(){
    this.cancel();
    for(const video of this.videos){
      this.entries.get(video)?.cancel?.();
      video.removeAttribute('src');video.load();
      video.style.visibility='hidden';
    }
    this.entries.clear();this.activeKey=null;
    this.frame.dataset.previewState='empty';
  }
  prepare(video,url,target){
    const key=url+'@'+target.toFixed(3),prior=this.entries.get(video);
    if(prior&&!prior.failed&&(prior.key===key||(prior.ready&&prior.url===url&&Math.abs(prior.target-target)<.06)))return prior.promise;
    if(prior?.cancel)prior.cancel();
    const entry={key,url,target,ready:false};this.entries.set(video,entry);
    entry.promise=new Promise((resolve,reject)=>{
      let finished=false,frameId=null;
      const cleanup=()=>{clearTimeout(timer);for(const ev of ['loadedmetadata','loadeddata','seeked','error'])video.removeEventListener(ev,handler);if(frameId!==null&&video.cancelVideoFrameCallback)video.cancelVideoFrameCallback(frameId);entry.cancel=null;};
      const fail=message=>{if(finished)return;finished=true;entry.failed=true;cleanup();reject(Error(message));};
      const done=()=>{if(finished)return;finished=true;entry.ready=true;cleanup();resolve(video);};
      const decoded=(_,meta)=>{frameId=null;if(finished)return;if(!video.seeking&&Math.abs(meta.mediaTime-target)<.09){done();return;}frameId=video.requestVideoFrameCallback(decoded);};
      const handler=event=>{
        if(event.type==='error'){fail('镜头无法解码，请生成当前镜头兼容预览');return;}
        if(event.type==='loadedmetadata'){video.currentTime=target;}
        if(video.readyState>=2&&!video.seeking&&Math.abs(video.currentTime-target)<.06){
          // 部分编码在暂停定位后不再次触发视频帧回调；seeked+当前帧可用后等两次绘制即可交接。
          if(typeof requestAnimationFrame==='function')requestAnimationFrame(()=>requestAnimationFrame(done));else done();
        }
      };
      const timer=setTimeout(()=>fail('镜头加载超时，已保留上一画面；请重试或生成兼容预览'),15000);
      entry.cancel=()=>fail('预览定位已更新');
      for(const ev of ['loadedmetadata','loadeddata','seeked','error'])video.addEventListener(ev,handler);
      video.pause();video.muted=true;video.preload='auto';
      if(video.requestVideoFrameCallback)frameId=video.requestVideoFrameCallback(decoded);
      video.src=url;video.load();
    });
    // 预取失败暂不打扰用户；到达该镜头时由 show 显示具体错误。
    entry.promise.catch(()=>{});return entry.promise;
  }
  async show(key,url,target,next,force=false){
    const serial=this.serial;
    if(this.activeKey!==key||force){
      const nextVideo=this.videos.find(v=>v!==this.active),cached=this.entries.get(nextVideo);
      this.frame.dataset.previewState=cached?.ready?'ready':'buffering';
      try{await this.prepare(nextVideo,url,target);}catch(e){if(serial!==this.serial)return null;throw e;}
      if(serial!==this.serial)return null;
      const previous=this.active;previous.pause();nextVideo.style.visibility='visible';previous.style.visibility='hidden';
      this.active=nextVideo;this.activeKey=key;this.frame.dataset.previewState='ready';
    }
    if(next){const spare=this.videos.find(v=>v!==this.active);this.prepare(spare,next.url,next.start).catch(()=>{});}
    return this.active;
  }
}
