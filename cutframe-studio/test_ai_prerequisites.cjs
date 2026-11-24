const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=file=>fs.readFileSync(path.join(__dirname,'static',file),'utf8');
const file=source('subtitle-board.js'),ctx={board:{confirmed:null},projectId:null,imports:{},sbSignature:()=>1,sbIssues:()=>[]};
vm.createContext(ctx);vm.runInContext(file.slice(file.indexOf('function sbNavigationIssues'),file.indexOf('function sbNavigationRefresh')),ctx);
assert.deepEqual([...ctx.sbNavigationIssues()].map(i=>i.step),[3,1,4]);
assert.match(file,/去填写并保存工程/);assert.match(file,/去保存字幕/);
console.log('缺工程或字幕仍可从底部直接定位处理');
