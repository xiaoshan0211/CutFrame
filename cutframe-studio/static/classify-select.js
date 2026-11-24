'use strict';

const byId = id => document.getElementById(id);
const token = document.querySelector('meta[name="local-token"]').content;
async function api(url, body) {
  const options = body === undefined ? {} : {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Local-Token': token},
    body: JSON.stringify(body)
  };
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.error || data.message || '请求失败（' + response.status + '）');
  return data;
}

function status(id, text, error = false) {
  byId(id).textContent = text;
  byId(id).classList.toggle('error', error);
}

function element(tag, text, className) {
  const item = document.createElement(tag);
  item.textContent = text;
  if (className) item.className = className;
  return item;
}

function detailsList(pairs) {
  const list = document.createDocumentFragment();
  for (const [name, value] of pairs) {
    if (value) list.append(element('dt', name), element('dd', String(value)));
  }
  return list;
}

function listen(id, event, statusId, callback) {
  byId(id).addEventListener(event, async e => {
    if (event === 'submit') e.preventDefault();
    try { await callback(e); }
    catch (error) { status(statusId, error.message, true); }
  });
}

function switchPane(pane) {
  for (const name of ['class', 'pick']) {
    const active = name === pane;
    byId(name + '-pane').hidden = !active;
    byId(name + '-tab').setAttribute('aria-pressed', String(active));
    byId(name + '-tab').classList.toggle('active', active);
  }
  byId(pane === 'class' ? 'pick-video' : 'source-video').pause();
}
byId('class-tab').onclick = () => switchPane('class');
byId('pick-tab').onclick = () => switchPane('pick');

const sourceVideo = byId('source-video');
let page = 1, listRequest = 0, assetRequest = 0, currentAsset = null, sourceStop = null;

async function listAssets(pageNumber) {
  const request = ++listRequest;
  const query = new URLSearchParams({
    page: pageNumber, root: byId('library').value, q: byId('asset-query-text').value.trim()
  });
  const result = await api('/api/assets?' + query);
  if (request !== listRequest) return;
  page = result.page;
  const pages = Math.ceil(result.total / 60);
  byId('asset-page').textContent = pages ? page + ' / ' + pages : '';
  byId('asset-prev').disabled = page <= 1;
  byId('asset-next').disabled = page >= pages;
  status('asset-status', result.total ? '找到 ' + result.total + ' 条原片' : '未找到匹配的原片。');
  byId('asset-list').replaceChildren(...result.items.map(asset => {
    const button = element('button', '', 'asset');
    button.dataset.id = asset.id;
    button.setAttribute('aria-pressed', String(asset.id === currentAsset?.id));
    button.append(element('strong', asset.name), element('small', asset.rel));
    button.onclick = () => openAsset(asset.id).catch(e => status('source-status', e.message, true));
    return button;
  }));
}

async function openAsset(assetId) {
  const request = ++assetRequest;
  currentAsset = null;
  sourceStop = null;
  const reviewer = byId('reviewer').value;
  byId('confirm-form').reset();
  byId('reviewer').value = reviewer;
  byId('class-fields').disabled = true;
  byId('class-note').required = false;
  byId('source-proxy').hidden = true;
  byId('source-proxy').disabled = false;
  sourceVideo.pause();
  sourceVideo.removeAttribute('src');
  sourceVideo.load();
  byId('asset-name').textContent = '正在读取原片…';
  byId('asset-path').textContent = '';
  status('source-status', '');
  status('class-status', '');
  for (const item of byId('asset-list').children) item.setAttribute('aria-pressed', String(item.dataset.id === assetId));
  const result = await api('/api/assets/' + encodeURIComponent(assetId));
  if (request !== assetRequest) return;
  currentAsset = {...result.asset, duration: result.meta.duration};
  byId('asset-name').textContent = currentAsset.name;
  byId('asset-path').textContent = currentAsset.source_path;
  byId('start-sec').value = 0;
  byId('end-sec').value = Math.min(5, currentAsset.duration).toFixed(3);
  for (const id of ['start-sec', 'end-sec']) byId(id).max = currentAsset.duration.toFixed(3);
  byId('class-fields').disabled = false;
  sourceVideo.src = '/media/' + encodeURIComponent(assetId);
}

function range() {
  const start = byId('start-sec').valueAsNumber, end = byId('end-sec').valueAsNumber;
  if (!currentAsset || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start ||
      end > Number(currentAsset.duration.toFixed(3))) throw Error('请在原片时长内填写起止秒，止秒须大于起秒。');
  return {start, end};
}

function changedRange() {
  byId('watched').checked = false;
  sourceStop = null;
  status('class-status', '');
}
for (const [mark, input] of [['set-start', 'start-sec'], ['set-end', 'end-sec']]) {
  byId(input).oninput = changedRange;
  byId(mark).onclick = () => { byId(input).value = sourceVideo.currentTime.toFixed(3); changedRange(); };
}
listen('play-segment', 'click', 'source-status', async () => {
  const {start, end} = range();
  sourceStop = end;
  sourceVideo.currentTime = start;
  await sourceVideo.play();
});
sourceVideo.ontimeupdate = () => {
  if (sourceStop !== null && sourceVideo.currentTime >= sourceStop) {
    sourceVideo.pause();
    sourceStop = null;
  }
};
sourceVideo.onerror = () => {
  if (!currentAsset || !sourceVideo.hasAttribute('src')) return;
  status('source-status', '原片预览失败，请检查共享盘连接，或使用兼容预览。', true);
  byId('source-proxy').hidden = false;
};
listen('source-proxy', 'click', 'source-status', async () => {
  const asset = currentAsset;
  if (!asset) return;
  byId('source-proxy').disabled = true;
  try {
    let result = await api('/api/proxy/' + encodeURIComponent(asset.id), {});
    while (!result.url && currentAsset === asset) {
      status('source-status', '正在生成兼容预览…');
      const job = await api('/api/jobs/' + encodeURIComponent(result.job_id));
      if (job.status === 'done') { result = job.result; break; }
      if (['failed', 'cancelled', 'interrupted'].includes(job.status)) throw Error(job.message || '兼容预览失败');
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
    if (currentAsset !== asset) return;
    sourceVideo.src = result.url;
    byId('source-proxy').hidden = true;
    status('source-status', '已切换至兼容预览。');
  } finally { byId('source-proxy').disabled = false; }
});
listen('asset-query', 'submit', 'asset-status', () => listAssets(1));
listen('library', 'change', 'asset-status', () => listAssets(1));
listen('asset-prev', 'click', 'asset-status', () => listAssets(page - 1));
listen('asset-next', 'click', 'asset-status', () => listAssets(page + 1));
byId('picture-type').onchange = () => { byId('class-note').required = byId('picture-type').value === 'V22'; };
listen('confirm-form', 'submit', 'class-status', async () => {
  const payload = {asset_id: currentAsset.id, ...range(), type_id: byId('picture-type').value,
    reviewer: byId('reviewer').value.trim(), watched: byId('watched').checked,
    stage: byId('stage').value, evidence: byId('evidence').value.trim(), note: byId('class-note').value.trim()};
  byId('confirm').disabled = true;
  try {
    await api('/api/classification/confirm', payload);
    if (currentAsset?.id === payload.asset_id) status('class-status', '已写入标注库 · 人工确认 · ' +
      payload.start + '–' + payload.end + ' 秒 · ' + payload.reviewer);
  } finally { byId('confirm').disabled = false; }
});

async function initClassification() {
  const [{roots}, {items}] = await Promise.all([api('/api/state'), api('/api/classification/types')]);
  for (const [key, root] of Object.entries(roots)) {
    if (root.role === 'raw') byId('library').add(new Option(root.label, key));
  }
  if (!byId('library').value) throw Error('当前没有已配置的原片素材库。');
  for (const item of items) byId('picture-type').add(new Option(item.id + ' ' + item.name, item.id));
  await listAssets(1);
}
initClassification().catch(error => status('asset-status', error.message, true));

let catalogue = {purposes: [], types: []};
let searchVersion = 0, activeQuery = null, items = [], history = [], candidateIndex = 0;
let clipPreview = false;
const pickVideo = byId('pick-video');
// 未保存的输入只在当前查询内保留，切换候选时不会串用别条的理由。
const drafts = new Map();

function clearResults() {
  searchVersion++;
  activeQuery = null;
  items = [];
  history = [];
  drafts.clear();
  pickVideo.pause();
  pickVideo.removeAttribute('src');
  pickVideo.load();
  byId('candidates').hidden = true;
  byId('history-panel').hidden = true;
  status('pick-status', '填写或调整条件后，点击「从 500 条总表找候选」。');
}

function choosePurpose() {
  clearResults();
  const name = byId('purpose').value;
  const rule = catalogue.purposes.find(entry => entry.name === name);
  const guidance = byId('guidance');
  guidance.replaceChildren();
  byId('type-picker').hidden = !name;
  if (!name) return;
  if (rule) {
    const list = element('dl', '');
    list.append(detailsList([['对应性质', rule.nature], ['先找的画面类型', rule.lookup],
      ['实看核对', rule.check], ['不能当主画面', rule.avoid]]));
    guidance.append(list);
  }
  const suggested = new Set(rule?.types || []);
  byId('recommended-types').replaceChildren();
  byId('other-types').replaceChildren();
  for (const type of catalogue.types) {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = type.code;
    checkbox.checked = suggested.has(type.code);
    checkbox.disabled = name !== '新增观点' && !checkbox.checked;
    const label = element('label', '', 'check');
    label.append(checkbox, document.createTextNode(type.code + ' ' + type.name + '（' + type.count + '）'));
    byId(checkbox.checked ? 'recommended-types' : 'other-types').append(label);
  }
  byId('type-picker').querySelector('details').open = !suggested.size;
}

function renderHistory() {
  byId('history-panel').hidden = false;
  const target = byId('history');
  target.replaceChildren();
  if (!history.length) {
    target.append(element('p', '还没有相同或相似原句的评分。', 'small'));
    return;
  }
  for (const entry of history) {
    const article = element('article', '', 'history-row');
    article.append(element('strong', (entry.relation || '同一句') + ' · ' + entry.sentence + (entry.segments ? ' · 整组评分 · ' : ' · ') + entry.rating));
    for (const shot of entry.segments || [entry]) {
      article.append(element('p', (shot.type || '') + ' ' + shot.path + ' ｜ ' + shot.start + '–' + shot.end + ' 秒', 'small'));
    }
    article.append(element('p', '评分理由：' + (entry.reason || '未填写')));
    if (entry.note) article.append(element('p', '原记录备注：' + entry.note, 'small'));
    target.append(article);
  }
}

function existingScore(item) {
  return history.find(row => row.sentence === activeQuery.sentence && row.path === item.path &&
    Number(row.start) === Number(item.start) && Number(row.end) === Number(item.end));
}

function rememberDraft() {
  const item = items[candidateIndex];
  if (item) drafts.set(item.id, {rating: byId('rating').value, reason: byId('reason').value, action: byId('action').value});
}

function showCandidate(index) {
  candidateIndex = index;
  const item = items[index];
  byId('candidate').selectedIndex = index;
  byId('candidate-prev').disabled = index === 0;
  byId('candidate-next').disabled = index + 1 === items.length;
  byId('candidate-info').replaceChildren(detailsList([
    ['画面类型', item.type + ' ' + item.type_name], ['原片路径', item.path], ['原片秒段', item.start + '–' + item.end + ' 秒'],
    ['依据来源', item.source], ['画面依据', item.evidence]
  ]));
  const saved = existingScore(item);
  const values = drafts.get(item.id) || saved || {};
  byId('reason').value = values.reason || '';
  byId('rating').value = values.rating || '';
  byId('action').value = values.action || '';
  status('rating-status', saved ? '已存评分 · ' + saved.rating : '');
  pickVideo.pause();
  clipPreview = false;
  status('pick-media-status', '');
  pickVideo.src = item.media_url + '#t=' + item.start + ',' + item.end;
}

function selectCandidate(index) {
  rememberDraft();
  showCandidate(index);
}
byId('candidate-prev').onclick = () => selectCandidate(candidateIndex - 1);
byId('candidate-next').onclick = () => selectCandidate(candidateIndex + 1);
byId('candidate').onchange = () => selectCandidate(byId('candidate').selectedIndex);

pickVideo.onerror = () => {
  const item = items[candidateIndex];
  if (!item || !pickVideo.hasAttribute('src')) return;
  if (!clipPreview && item.media_preview_url) {
    clipPreview = true;
    status('pick-media-status', '正在读取所选秒段的兼容预览…');
    pickVideo.src = item.media_preview_url;
    return;
  }
  status('pick-media-status', '候选预览读取失败，请检查共享盘连接后重新选择该原片。', true);
};
pickVideo.onloadedmetadata = () => {
  const item = items[candidateIndex];
  if (!item) return;
  if (clipPreview) status('pick-media-status', '兼容预览仅含总表标记的秒段。');
  else pickVideo.currentTime = Number(item.start);
};
pickVideo.onplay = () => {
  const item = items[candidateIndex];
  if (item && !clipPreview && (pickVideo.currentTime < item.start || pickVideo.currentTime >= item.end - 0.02)) {
    pickVideo.currentTime = Number(item.start);
  }
};
pickVideo.ontimeupdate = () => {
  const item = items[candidateIndex];
  if (item && !clipPreview && !pickVideo.paused && pickVideo.currentTime >= item.end) pickVideo.pause();
};

listen('search-form', 'submit', 'pick-status', async () => {
  clearResults();
  const version = searchVersion;
  const fields = {
    sentence: byId('sentence').value.trim(), purpose: byId('purpose').value, polarity: byId('polarity').value,
    intent: byId('intent').value.trim(), types: [...byId('type-picker').querySelectorAll('input:checked')].map(input => input.value)
  };
  if (!fields.types.length) throw Error('请选择至少一个要查找的画面类型。');
  byId('search').disabled = true;
  status('pick-status', '正在查总表和已有评分…');
  try {
    const result = await api('/api/viewpoint-selection/search', fields);
    if (version !== searchVersion) return;
    activeQuery = fields;
    items = result.items;
    byId('more-six').hidden = items.length >= result.total;
    history = result.history;
    renderHistory();
    status('pick-status', fields.sentence + ' · ' + items.length + ' 个候选');
    if (items.length) {
      byId('candidate').replaceChildren(...items.map((item, i) =>
        new Option((i + 1) + ' / ' + items.length + ' · ' + item.type + ' ' + item.path.split(/[\\/]/).pop(), item.id)));
      byId('candidates').hidden = false;
      showCandidate(0);
    }
  } finally { byId('search').disabled = false; }
});
listen('more-six', 'click', 'pick-status', async () => {
  const query = activeQuery;
  if (!query) return;
  const button = byId('more-six');
  button.disabled = true;
  try {
    const offset = items.length;
    const result = await api('/api/viewpoint-selection/search', {...query, offset});
    if (query !== activeQuery) return;
    for (const item of result.items) {
      items.push(item);
      byId('candidate').add(new Option(items.length + ' · ' + item.type + ' ' + item.path.split(/[\\/]/).pop(), item.id));
    }
    if (items.length > offset) selectCandidate(offset);
    button.hidden = items.length >= result.total;
    status('pick-status', '已列出 ' + items.length + ' / ' + result.total + ' 个候选');
  } finally { button.disabled = false; }
});
listen('rating-form', 'submit', 'rating-status', async () => {
  const query = activeQuery;
  const item = items[candidateIndex];
  const rating = byId('rating').value, reason = byId('reason').value.trim(), action = byId('action').value.trim();
  if (!reason) throw Error('请写下这段画面合适或不合适的具体理由。');
  byId('save-rating').disabled = true;
  try {
    await api('/api/viewpoint-selection/rating', {...query, id: item.id, rating, reason, action});
    if (query !== activeQuery) return;
    const entry = existingScore(item);
    if (entry) Object.assign(entry, {rating, reason, action});
    else history.unshift({...item, sentence: query.sentence, rating, reason, action});
    renderHistory();
    if (items[candidateIndex] === item) status('rating-status', '已保存 · ' + rating);
  } finally { byId('save-rating').disabled = false; }
});
byId('purpose').onchange = choosePurpose;
for (const id of ['sentence', 'intent']) byId(id).oninput = clearResults;
for (const id of ['polarity', 'type-picker']) byId(id).onchange = clearResults;

async function initSelection() {
  catalogue = await api('/api/viewpoint-selection/options');
  for (const entry of catalogue.purposes) byId('purpose').add(new Option(entry.name, entry.name));
  if (!catalogue.purposes.some(entry => entry.name === '新增观点')) byId('purpose').add(new Option('新增观点', '新增观点'));
}
initSelection().catch(error => status('pick-status', error.message, true));
