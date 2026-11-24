const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),test=require('node:test');
const source=fs.readFileSync(__dirname+'/static/workflow.js','utf8');
const rules=source.slice(source.indexOf('function wfDifferentVideo()'),source.indexOf('function wfCaption()'));
function fixture(){
 const fields={'project-name':'小山1武汉','tts-text':'旧文案','voice-offset':0};
 const ctx={wf:{step:2,films:[],resources:{voice:{meta:{duration:23.02}}}},projectId:'old',shots:[{start:0,end:27.14}],
  board:{mode:'subtitle',context:JSON.stringify({voice:'oldVoice'})},imports:{voice:'oldVoice'},
  ttsSelection:{id:'newVoice',duration:23.02},wfProjectIdentity:{name:'小山1武汉',script:'旧文案'},
  $:k=>({value:fields[k]}),root:{addEventListener(_,fn){ctx.click=fn;}},wfChanged(){},notice(e){throw Error(e);}};
 vm.createContext(ctx);vm.runInContext(rules,ctx);return {ctx,fields};
}
test('改名或修订原稿可延续原工程；同时填写新片名和新文案，保存使用独立空时间线',async()=>{
 const {ctx,fields}=fixture();
 fields['project-name']='小山2武汉';assert.equal(ctx.wfDifferentVideo(),false);
 fields['tts-text']='新文案';assert.equal(ctx.wfDifferentVideo(),true);
 let opened,replayed=0;ctx.project=()=>({id:'old',name:'小山2武汉',shots:ctx.shots,imports:ctx.imports,
 settings:{canvas:'1080x1920',voice_offset:7},workflow:{script:'新文案',material_scope:'all'}});
 ctx.wfOpen=async p=>{opened=p;ctx.projectId=null;};
 const button={id:'save-project',click(){replayed++;}};
 await ctx.click({target:{closest:()=>button},preventDefault(){},stopImmediatePropagation(){}});
 assert.equal(opened.id,undefined);assert.equal(opened.shots,undefined);assert.equal(opened.imports,undefined);
 assert.equal(opened.name,'小山2武汉');assert.equal(opened.workflow.script,'新文案');assert.equal(opened.settings.voice_offset,undefined);assert.equal(replayed,1);
});
test('待采用的配音仅在试听步骤供右侧预览，采用后旧配音的镜头不再决定总时长',()=>{
 const {ctx}=fixture();assert.equal(ctx.wfAudition().duration,23.02);
 ctx.wf.step=3;assert.equal(ctx.wfAudition(),null);ctx.wf.step=2;ctx.imports.voice='newVoice';
 assert.equal(ctx.wfAudition(),null);assert.equal(ctx.wfBoardVoiceChanged(),true);
 assert.equal(ctx.wfDuration(),23.02);
});
