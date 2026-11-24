// 验证尚未解码时保留旧画面，以及取消定位后不会被旧请求切回。
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const ShotPreview=vm.runInNewContext(fs.readFileSync(__dirname+'/static/shot-preview.js','utf8')+';ShotPreview',{setTimeout,clearTimeout,Error});
class Video extends EventTarget{
 constructor(){super();this.style={};this.readyState=0;this.currentTime=0;this.loads=0;}
 cloneNode(){return new Video();}removeAttribute(k){delete this[k];}pause(){}
 load(){this.loads++;this.readyState=0;}
 finish(){this.dispatchEvent(new Event('loadedmetadata'));this.readyState=4;this.dispatchEvent(new Event('loadeddata'));}
}
function player(){return new ShotPreview({dataset:{},insertBefore(){}},new Video());}
test('下一镜头未解码时旧画面保持可见',async()=>{
 const p=player(),old=p.active,back=p.videos[1],result=p.show('一','/一.mp4',2,null);
 assert.notEqual(old.style.visibility,'hidden');assert.equal(back.style.visibility,'hidden');
 back.finish();await result;assert.equal(p.active,back);assert.equal(back.style.visibility,'visible');assert.equal(old.style.visibility,'hidden');
});
test('预取镜头在切点附近复用，不重载视频地址',async()=>{
 const p=player(),first=p.show('一','/一.mp4',2,{url:'/二.mp4',start:2});p.videos[1].finish();await first;
 const back=p.videos[0];back.finish();const loads=back.loads;
 await p.show('二','/二.mp4',2.02,null);assert.equal(back.loads,loads);assert.equal(p.active,back);
});
test('用户取消定位后，晚完成的解码不得切换画面',async()=>{
 const p=player(),old=p.active,result=p.show('一','/一.mp4',2,null);p.cancel();p.videos[1].finish();
 assert.equal(await result,null);assert.equal(p.active,old);assert.equal(p.videos[1].style.visibility,'hidden');
});
test('暂停定位不触发帧回调时仍可凭已解码帧完成准备',async()=>{
 const p=player(),back=p.videos[1];back.requestVideoFrameCallback=()=>1;back.cancelVideoFrameCallback=()=>{};
 const result=p.show('一','/一.mp4',2,null);back.finish();await result;assert.equal(p.active,back);
});
test('切换工程时释放两个播放器，迟到的预取不能重新显示上一条素材',async()=>{
 const p=player(),pending=p.show('旧片','/old.mp4',1,null);
 p.reset();
 assert.equal(await pending,null);
 assert.equal(p.entries.size,0);assert.equal(p.activeKey,null);
 assert.ok(p.videos.every(v=>!v.src&&v.style.visibility==='hidden'));
 const next=p.show('新片','/new.mp4',0,null);
 p.videos.find(v=>v.src==='/new.mp4').finish();
 assert.equal((await next).src,'/new.mp4');
});
