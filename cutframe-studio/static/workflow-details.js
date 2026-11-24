'use strict';

// 只整理展示文本。原有的审核表单、选片按钮和播放器继续使用各自的事件绑定。
function workflowDisclosure(title) {
  const box = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = title;
  box.append(summary);
  return box;
}

function workflowSubtitleWarnings(warnings) {
  const state = document.getElementById('wf-subtitle-state');
  const notes = Array.from(new Set((warnings || []).filter(Boolean)));
  state.replaceChildren();
  if (!notes.length) {
    state.textContent = '字幕已生成';
    return;
  }
  const details = workflowDisclosure('字幕核对提示（' + notes.length + '）');
  const list = document.createElement('ul');
  for (const note of notes) {
    const row = document.createElement('li');
    row.textContent = note;
    list.append(row);
  }
  details.append(list);
  state.append(details);
}

function workflowCompactCard(card) {
  const heading = card.querySelector(':scope > strong');
  const match = heading?.textContent.match(/^([A-E])\((.+)\)$/);
  if (!match) return;
  const details = workflowDisclosure('素材详情');
  const id = document.createElement('p');
  id.textContent = '素材编号 · ' + match[2];
  heading.textContent = match[1];
  const meta = [];
  for (let item = heading.nextElementSibling; item; item = item.nextElementSibling) {
    if (!item.matches('p,strong') || item.hasAttribute('data-saved-status')) break;
    if (!item.matches('.local-warning,[role="alert"],[data-thumb-warning]')) meta.push(item);
  }
  details.append(...meta, id);
  heading.after(details);
}

function workflowCompactSelection() {
  const view = document.getElementById('local-viewpoint');
  const settings = document.getElementById('ai-status')?.closest('details');
  if (!view || !settings || view.closest('details[data-view-details]')) return;
  const details = workflowDisclosure('观点与画面依据');
  details.dataset.viewDetails = '';
  view.before(details);
  details.append(view);
  for (const id of ['ai-next-help', 'ai-count', 'rank-progress']) {
    const element = document.getElementById(id);
    if (element) settings.append(element);
  }
}

function workflowFoldNote(element, title) {
  if (!element) return;
  const details = workflowDisclosure(title);
  element.before(details);
  details.append(element);
}

function workflowCompactLayout() {
  const editor = document.getElementById('compose');
  if (!editor) return;
  for (const selector of ['.section-head .eyebrow', '.section-head h1 + .small', '.wf-preview h2 + .small']) {
    const note = editor.querySelector(selector);
    if (note) note.hidden = true;
  }
  const historyLabel = document.querySelector('#exports .eyebrow');
  if (historyLabel) historyLabel.hidden = true;
  for (const [id, general] of [
    ['wf-preview-status', /^(工程已载入。点击播放预览|正在预览当前工程；字幕设置即时生效。|先打开工程，或在第一步输入文案。)$/],
    ['wf-render-state', /^按顺序完成检查后，渲染第一版。$/],
  ]) {
    const state = document.getElementById(id);
    if (state) {
      const update = () => { state.hidden = general.test(state.textContent); };
      new MutationObserver(update).observe(state, {childList:true, subtree:true, characterData:true});
      update();
    }
  }
  const staticNote = step => document.querySelector('#wf-panel-' + step + ' > div > p.hint:not([id])');
  const first = staticNote(1);
  if (first) first.hidden = true;
  workflowFoldNote(staticNote(2), '配音说明');
  workflowFoldNote(document.querySelector('#tts-speed-panel > p.small:not([id])'), '语速说明');
  workflowFoldNote(staticNote(3), '字幕生成说明');
  workflowFoldNote(document.querySelector('#wf-style + .small'), '字幕样式说明');
  workflowFoldNote(staticNote(5), '配乐说明');
  const checklist = document.getElementById('wf-checklist');
  if (checklist) {
    const box = workflowDisclosure('成片检查');
    checklist.before(box);
    box.append(checklist);
    let previous;
    const sync = () => {
      const pending = checklist.querySelectorAll('.wf-pending').length;
      box.firstElementChild.textContent = pending ? '成片检查 · ' + pending + ' 项待处理' : '成片检查已通过';
      if (previous !== Boolean(pending)) box.open = Boolean(pending);
      previous = Boolean(pending);
    };
    new MutationObserver(sync).observe(checklist, {childList:true});
    sync();
  }
  workflowCompactSelection();
  for (const card of editor.querySelectorAll('#ai-cards > article')) workflowCompactCard(card);
}
