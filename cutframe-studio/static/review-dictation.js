'use strict';

// 三张卡片共用一个麦克风，每次录音只绑定发起它的事实框。
let cancelActiveReviewDictation = null;

function addReviewDictation(form, fact) {
 const controls = el('div', undefined, 'review-dictation');
 const button = el('button', '语音输入'), cancel = el('button', '取消录音');
 const status = el('span', '', 'small');
 button.type = cancel.type = 'button';
 cancel.hidden = true;
 status.setAttribute('role', 'status');
 controls.append(button, cancel, status);
 form.append(controls);
 let session = null;

 button.onclick = async () => {
  if (session) {
   if (session.recorder?.state === 'recording') session.stop();
   return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
   status.textContent = '此页面无法录音，请用本机浏览器打开 127.0.0.1 的工作台，并允许使用麦克风。';
   return;
  }
  cancelActiveReviewDictation?.();
  const take = {stream:null, recorder:null, timer:null, request:new AbortController()};
  session = take;
  const chunks = [];
  const active = () => session === take && fact.isConnected && fact.getClientRects().length > 0;
  const releaseMic = () => take.stream?.getTracks().forEach(track => track.stop());
  function end(message) {
   if (session !== take) return;
   session = null;
   cancelActiveReviewDictation = null;
   clearTimeout(take.timer);
   observer.disconnect();
   window.removeEventListener('pagehide', discard);
   document.removeEventListener('visibilitychange', checkVisibility);
   take.request.abort();
   if (take.recorder?.state === 'recording') take.recorder.stop();
   releaseMic();
   button.textContent = '语音输入';
   cancel.hidden = true;
   button.disabled = false;
   status.textContent = message;
  }
  function discard() { end('已取消语音输入。'); }
  function checkVisibility() { if (document.hidden || !active()) discard(); }
  const observer = new MutationObserver(checkVisibility);
  observer.observe(document.body, {subtree:true, childList:true, attributes:true, attributeFilter:['hidden','class']});
  window.addEventListener('pagehide', discard);
  document.addEventListener('visibilitychange', checkVisibility);
  cancelActiveReviewDictation = discard;
  cancel.onclick = discard;
  cancel.hidden = false;
  cancel.textContent = '取消';
  button.disabled = true;
  status.textContent = '正在请求麦克风权限…';
  try {
   const stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true}, video:false});
   if (!active()) { stream.getTracks().forEach(track => track.stop()); discard(); return; }
   take.stream = stream;
   const mimeType = ['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(t => MediaRecorder.isTypeSupported(t));
   if (!mimeType) { end('当前浏览器没有可用的录音格式，请用本机 Edge 或 Chrome 录音。'); return; }
   const recorder = new MediaRecorder(stream, {mimeType, audioBitsPerSecond:64000});
   take.recorder = recorder;
   take.stop = () => {
    if (recorder.state !== 'recording') return;
    button.disabled = true;
    recorder.stop();
    releaseMic();
   };
   recorder.ondataavailable = e => { if (session === take && e.data.size) chunks.push(e.data); };
   recorder.onerror = () => end('录音中断，请检查麦克风后重试。');
   recorder.onstop = async () => {
    releaseMic();
    if (!active()) { discard(); return; }
    clearTimeout(take.timer);
    button.disabled = true;
    status.textContent = '正在本机识别…';
    try {
     const audio = new Blob(chunks, {type:recorder.mimeType});
     const response = await fetch('/api/local/review-dictation', {
      method:'POST', headers:{'X-Local-Token':token,'Content-Type':audio.type},
      body:audio, signal:take.request.signal
     });
     const result = await response.json();
     if (!response.ok || !result.text) throw Error(result.error || '语音识别未完成，请重试。');
     if (!active()) { discard(); return; }
     fact.setRangeText(result.text, fact.value.length, fact.value.length, 'end');
     fact.dispatchEvent(new Event('input', {bubbles:true}));
     if (controls.contains(document.activeElement)) fact.focus({preventScroll:true});
     end('已填入，可修改。');
    } catch (err) { end(err.message || '语音识别未完成，请重试。'); }
   };
   stream.getAudioTracks()[0].addEventListener('ended', () => end('麦克风已断开，请重新录音。'), {once:true});
   recorder.start();
   document.getElementById('sb-player')?.pause();
   button.textContent = '结束并转文字';
   button.disabled = false;
   status.textContent = '正在录音，最长 1 分钟。';
   take.timer = setTimeout(take.stop, 59000);
  } catch (err) {
   const reason = {NotAllowedError:'麦克风权限未开启，请允许此页面使用麦克风后重试。',
    NotFoundError:'没有找到麦克风，请连接设备后重试。',
    NotReadableError:'麦克风暂时不可用，请检查设备占用。'};
   end(reason[err.name] || '无法开始录音，请检查麦克风后重试。');
  }
 };
}
