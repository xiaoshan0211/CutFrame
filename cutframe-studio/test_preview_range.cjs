const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const test=require('node:test');
const source=fs.readFileSync(__dirname+'/static/workflow.js','utf8');
const playback=source.slice(source.indexOf('let wfPlaybackSerial='),source.indexOf("$('wf-seek').oninput"));
function preview(end){
 let play,tick,complete,shows=0;
 const voice={paused:true,position:0,seeks:0,pauses:0,duration:27.14,
  get currentTime(){return this.position;},set currentTime(t){this.seeks++;this.position=t;},
  async play(){this.paused=false;},pause(){this.paused=true;this.pauses++;}};
 const video={paused:true,currentTime:0,style:{},pause(){this.paused=true;},async play(){this.paused=false;}};
 const wf={time:0,step:6,playing:false,shotIndex:-1,proxy:{},playRange:end?{start:0,end}:null};
 const parts=[{asset_id:'a',start:0,end:1},{asset_id:'b',start:0,end:26.14}];
 const nodes={'wf-voice':voice,'voice-offset':{value:0},'music-fade':{value:0},'wf-play':{},'wf-preview-status':{},
  fit:{value:'contain'},'source-audio':{value:'mute'}};
 const ctx={wf,imports:{voice:'原配音'},shots:parts,$:id=>nodes[id],performance:{now:()=>0},action:(_,fn)=>play=fn,
  wfAudition:()=>null,wfBoardVoiceChanged:()=>false,wfResources:async()=>{},wfDuration:()=>27.14,wfCaption:()=>{},cancelAnimationFrame:()=>{},
  root:{querySelectorAll:()=>[voice]},requestAnimationFrame:fn=>{tick=fn;return 1;},
  shotPreview:{active:video,cancel(){},async show(key,url,t,next,seek){
   shows++;if(!seek&&key.startsWith('1:'))await new Promise(resolve=>{complete=resolve;});
   return video;
  }}};
 vm.runInNewContext(playback,ctx);
 return {wf,voice,play:()=>play(),advance:async t=>{voice.position=t;await tick();},
  finish:()=>complete(),shows:()=>shows};
}
test('四个字幕范围在配音抵达边界后立即止播并定位回末帧',async()=>{
 for(const end of [.78,1.84,5.2,6.9]){
  const p=preview(end);await p.play();await p.advance(end+.03);
  assert.equal(p.wf.playing,false);assert.equal(p.wf.playRange,null);assert.equal(p.wf.time,end-.000001);
  assert.equal(p.voice.currentTime,p.wf.time);
 }
});
test('等待下一个镜头期间配音持续前进，切镜不会暂停、回拨或越过限定播放终点',async()=>{
 const p=preview(3);await p.play();await p.advance(.3);await p.advance(1.1);
 const seeks=p.voice.seeks;await p.advance(2.7);
 assert.equal(p.wf.time,2.7);assert.equal(p.shows(),2);assert.equal(p.voice.seeks,seeks);assert.equal(p.voice.pauses,0);
 await p.advance(3.1);assert.equal(p.wf.time,3-.000001);assert.equal(p.voice.paused,true);
 p.finish();await Promise.resolve();assert.equal(p.voice.paused,true);
});
