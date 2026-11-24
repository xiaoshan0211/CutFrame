const vm=require('vm'),fs=require('fs'),assert=require('assert'),{webcrypto}=require('crypto');
const code=fs.readFileSync(__dirname+'/static/uuid-compat.js','utf8');
const ctx={crypto:{getRandomValues:a=>webcrypto.getRandomValues(a)}};vm.createContext(ctx);vm.runInContext(code,ctx);
const ids=Array.from({length:10000},()=>ctx.crypto.randomUUID());assert.equal(new Set(ids).size,ids.length);assert(ids.every(id=>/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id)));
const native=()=> 'native';const c={crypto:{randomUUID:native}};vm.createContext(c);vm.runInContext(code,c);assert.strictEqual(c.crypto.randomUUID,native);
vm.runInContext(fs.readFileSync(__dirname+'/static/subtitle-board-core.js','utf8'),ctx);
const result=vm.runInContext('SubtitleBoardCore.sync([], [{text:"第一句",start:0,end:1},{text:"第二句",start:1,end:2}],0,()=>crypto.randomUUID())',ctx);
assert.equal(result.tasks.length,2);assert.notEqual(result.tasks[0].id,result.tasks[1].id);
console.log('无randomUUID环境建立字幕任务成功；10000个UUID格式/唯一性通过；原生API保留');
