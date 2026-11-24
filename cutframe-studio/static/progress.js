'use strict';
let plan, revision = '';
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const done = tasks => tasks.filter(t => t.status === '已完成').length;
const ratio = tasks => tasks.length ? Math.round(done(tasks) / tasks.length * 100) : 0;
const bar = tasks => `<progress max="${tasks.length || 1}" value="${done(tasks)}" aria-label="完成 ${done(tasks)} / ${tasks.length}"></progress>`;
function render() {
  const phaseMap = Object.fromEntries(plan.phases.map(p => [p.id,p]));
  const groups = ['当前','后期'].map(scope => plan.tasks.filter(t => phaseMap[t.phase].scope === scope));
  $('metrics').innerHTML = groups.map((tasks,i) => `<div class="metric">${i ? '后期路线 · 尚未启动' : '当前范围 · 精裁与单条验证'}<strong>${ratio(tasks)}% <small>${done(tasks)} / ${tasks.length} 项完成</small></strong>${bar(tasks)}<small>${tasks.filter(t=>t.status==='待验收').length} 项待验收 · ${tasks.filter(t=>t.status==='等待输入').length} 项等待输入</small></div>`).join('') + `<div class="metric">整个方案任务覆盖<strong>${plan.tasks.length} <small>项已登记</small></strong><p>${done(plan.tasks)} 已完成 · ${plan.tasks.filter(t=>t.status==='进行中').length} 进行中</p><small>完整长期路线不折算成工时完成率</small></div>`;
  $('flow').innerHTML = plan.phases.map(p => { const tasks=plan.tasks.filter(t=>t.phase===p.id); return `<button type="button" data-phase="${p.id}">${p.id} · ${esc(p.title)}<span>${p.scope} · ${done(tasks)}/${tasks.length} 完成</span>${bar(tasks)}</button>`; }).join('');
  const selected=$('phase').value;
  $('phase').innerHTML='<option value="">全部阶段</option>'+plan.phases.map(p=>`<option value="${p.id}">${p.id} · ${esc(p.title)}</option>`).join('');
  $('phase').value=selected;
  $('history').innerHTML = [...plan.history].reverse().map(h=>`<li><strong>${esc(h.task)} · ${esc(h.change)}</strong><br><span class="muted">${esc(h.time)}</span>${h.evidence ? '<br>'+esc(h.evidence) : ''}</li>`).join('');
  filter();
}
function filter() {
  if(!plan) return;
  const q=$('query').value.trim().toLowerCase();
  const tasks=plan.tasks.filter(t=>(!$('scope').value || plan.phases.find(p=>p.id===t.phase).scope===$('scope').value)&&(!$('status').value||t.status===$('status').value)&&(!$('phase').value||t.phase===$('phase').value)&&(!q||[t.id,t.title,t.evidence,t.next].join(' ').toLowerCase().includes(q)));
  $('count').textContent=`显示 ${tasks.length} / ${plan.tasks.length} 项；当前筛选内 ${done(tasks)} 项完成。`;
  $('tasks').innerHTML=tasks.map(t=>`<tr><td>${esc(t.id)}<small>${esc(plan.phases.find(p=>p.id===t.phase).title)}</small></td><td>${esc(t.title)}</td><td><span class="badge ${t.status==='已完成'?'done':t.status==='进行中'?'active':['等待输入','待验收'].includes(t.status)?'wait':''}">${esc(t.status)}</span></td><td><p>${esc(t.evidence)}</p><p><b>下一步 / 标准：</b>${esc(t.next)}</p><small>${esc(t.owner)} · 核对/更新 ${esc(t.updated)}</small></td></tr>`).join('') || '<tr><td colspan="4">没有匹配任务</td></tr>';
}
async function refresh() {
  try {
    const response=await fetch('/static/progress.json',{cache:'no-store'});
    if(!response.ok) throw Error(response.status);
    const data=await response.json();
    if(revision!==JSON.stringify(data)){plan=data;revision=JSON.stringify(data);render();}
    $('sync').textContent=`台账 v${data.version} · 更新 ${data.updated} · 每10秒同步`;
  } catch(error) { $('sync').textContent='同步失败，显示上次数据；请检查本地服务。'; }
}
['scope','status','phase','query'].forEach(id=>$(id).addEventListener('input',filter));
$('reset').addEventListener('click',()=>{['scope','status','phase','query'].forEach(id=>$(id).value='');filter();});
$('flow').addEventListener('click',e=>{const button=e.target.closest('button[data-phase]');if(button){$('phase').value=button.dataset.phase;$('scope').value='';$('status').value='';$('query').value='';filter();$('count').scrollIntoView({behavior:'smooth'});}});
refresh();setInterval(refresh,10000);
