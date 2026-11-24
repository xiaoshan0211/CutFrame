const assert=require('assert'),core=require('./static/subtitle-board-core.js');
const a={text:'文案',voice:'v',subtitle:'old',cues:[{start:0,end:2,text:'文案'}],fps:'30',voiceOffset:'0',subtitleOffset:'0'};
const same=b=>core.sameContext(JSON.stringify(a),JSON.stringify(b));
assert(same({...a,subtitle:'new'}));
for(const change of [{voice:'other'},{text:'改文案'},{fps:25},{voiceOffset:1},{subtitleOffset:1},{cues:[{start:0,end:2.1,text:'文案'}]},{cues:[{start:0,end:2,text:'新文案'}]}])assert(!same({...a,...change}));
assert(!core.sameContext('',JSON.stringify(a)));
console.log('字幕同内容另存保留上下文；真实文案、时间、配音与设置变更仍失效：通过');
