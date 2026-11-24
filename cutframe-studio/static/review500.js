'use strict';
const {cards:allCards,rid,token,scores:initialScores}=JSON.parse(document.getElementById('review-data').textContent);
const newOnly=rid==='8' && new URLSearchParams(location.search).get('batch')==='new';
const cards=newOnly ? allCards.filter(card=>card[3].startsWith('T10B-')) : allCards;
function reviewedCount(){return cards.filter(card=>scores[card[3]]).length}
let scores=initialScores,n=0,busy=false;
const [s,h,v,t,p,m,prev,next,yes,no]=['s','h','v','t','p','m','prev','next','yes','no'].map(id=>document.getElementById(id));
const reviewStatus=document.createElement('p');document.body.append(reviewStatus);
if(['8','9','10'].includes(rid)){
  const maybe=document.createElement('button');
  maybe.textContent='勉强';
  no.after(maybe);
  maybe.onclick=()=>{if(!busy)save({[cards[n][3]]:'勉强'}).catch(()=>reviewStatus.textContent='保存失败，请重试')};
}
async function save(values){busy=true;yes.disabled=no.disabled=prev.disabled=next.disabled=s.disabled=true;try{
const res=await fetch('/api/review500/'+rid,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(values)});if(!res.ok)throw Error();scores=await res.json();reviewStatus.textContent='已保存到项目 · '+reviewedCount()+'/'+cards.length;
}finally{busy=false;yes.disabled=no.disabled=s.disabled=false;draw()}}
function draw(){const [i,j,line,url,type,path,a,b]=cards[n];s.value=i;h.textContent=line+' · 候选 '+j;v.src='/review500/'+rid+'/media/'+url;t.textContent=type;p.textContent=path+' ｜ '+a+'–'+b+' 秒';m.textContent=scores[url]||'待看';prev.disabled=!n;next.disabled=n===cards.length-1}
for(const c of cards.filter((item,index)=>cards.findIndex(other=>other[0]===item[0])===index))s.add(new Option(c[0]+' '+c[2],c[0]));
s.onchange=()=>{n=cards.findIndex(c=>c[0]==s.value);draw()};prev.onclick=()=>{n--;draw()};next.onclick=()=>{n++;draw()};
for(const btn of [yes,no])btn.onclick=()=>save({[cards[n][3]]:btn.textContent}).catch(()=>reviewStatus.textContent='保存失败，请刷新后重试');
draw();reviewStatus.textContent='项目已保存 '+reviewedCount()+'/'+cards.length;
if(location.hash.length>1){const old=JSON.parse(decodeURIComponent(location.hash.slice(1)));for(const k of Object.keys(scores))delete old[k];save(old).then(()=>history.replaceState(null,'',location.pathname)).catch(()=>reviewStatus.textContent='同步失败，请刷新重试')}
