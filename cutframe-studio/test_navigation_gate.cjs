const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const dir=process.argv[2]||__dirname+'/static';
const source=fs.readFileSync(dir+'/subtitle-board.js','utf8');
const workflow=fs.readFileSync(dir+'/workflow.js','utf8');
function element(){return {children:[],append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},before(){},setAttribute(){},scrollIntoView(){},focus(){}};}
const nodes={},context={projectId:'p',imports:{voice:'v',subtitle:'s'},el:element,$:id=>nodes[id]??=element(),root:{querySelector:element},wf:{step:4,resources:{subtitle:{meta:{voice_id:'v'}}}},board:{enabled:true,tasks:[{}],confirmed:null},shots:[{}],subtitleButton:(text,fn)=>({text,onclick:fn}),wfRefresh(){},wfStep(n){context.wf.step=n},notice(){}};
let shotIssues=[];
context.sbIssues=()=>[...(!context.imports.voice?['请先采用或导入配音']:[]),context.wfSubtitleIssue(),...shotIssues].filter(Boolean);
vm.createContext(context);
vm.runInContext(workflow.slice(workflow.indexOf('function wfSubtitleIssue(){'),workflow.indexOf('function wfRefresh(){')),context);
vm.runInContext(source.slice(source.indexOf('const sbGatePanel=')),context);
function go(expected){context.wf.step=4;context.wfStep(5);assert.equal(context.wf.step,expected);}
go(5);
assert.equal(context.board.confirmed,null);
context.wf.dirtySubtitle=true;go(4);assert.equal(context.sbNavigationIssues()[0].step,3);
context.wf.dirtySubtitle=false;delete context.imports.voice;go(4);assert.equal(context.sbNavigationIssues()[0].step,2);
context.imports.voice='new';go(4);assert.match(context.wfSubtitleIssue(),/旧配音/);
context.imports.voice='v';shotIssues=['第2条待选镜头'];go(4);
shotIssues=[];go(5);context.wfStep(6);assert.equal(context.wf.step,6);
for(const id of ['sb-confirm','wf-confirm-subtitles','wf-confirm-voice']){
 for(const file of [source,workflow,fs.readFileSync(dir+'/storyboard.js','utf8')])assert.ok(!file.includes("'"+id+"'")&&!file.includes('id="'+id+'"'));
}
console.log('旧工程无确认标志可到配乐与导出；缺配音、旧配音字幕、未保存字幕或缺镜头时准确提示。');
