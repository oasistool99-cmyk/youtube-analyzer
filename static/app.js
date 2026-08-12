'use strict';

// 모델이 생성한 텍스트는 전부 textContent로만 넣습니다.
// (이전 버전은 innerHTML로 리포트를 렌더링해 자막 → 모델 → DOM 경로로
//  스크립트가 주입될 수 있었습니다.)

const $ = (id) => document.getElementById(id);

const el = {
  modeSection: $('modeSection'),
  smartBtn: $('smartBtn'),
  fastBtn: $('fastBtn'),
  modeHint: $('modeHint'),
  inputCard: $('inputCard'),
  urlInput: $('urlInput'),
  analyzeBtn: $('analyzeBtn'),
  loadingCard: $('loadingCard'),
  progressBar: $('progressBar'),
  loadingMsg: $('loadingMsg'),
  cancelBtn: $('cancelBtn'),
  errorCard: $('errorCard'),
  errorMsg: $('errorMsg'),
  errorDismiss: $('errorDismiss'),
  resultSection: $('resultSection'),
  videoInfoCard: $('videoInfoCard'),
  videoThumb: $('videoThumb'),
  videoTitle: $('videoTitle'),
  videoAuthor: $('videoAuthor'),
  videoDuration: $('videoDuration'),
  statsGrid: $('statsGrid'),
  statCues: $('statCues'),
  statFrames: $('statFrames'),
  statCost: $('statCost'),
  costNote: $('costNote'),
  imageCard: $('imageCard'),
  imageBadge: $('imageBadge'),
  imageList: $('imageList'),
  reportCard: $('reportCard'),
  reportBadge: $('reportBadge'),
  reportContent: $('reportContent'),
  resetBtn: $('resetBtn'),
};

const HINTS = {
  smart: '자막 분석 + 핵심 장면 자동 캡처 + 화면 분석 (1~3분 소요)',
  fast: '자막만 분석 (30초~1분 소요, 더 저렴)',
};

let mode = 'smart';
let controller = null;

function setMode(next) {
  mode = next;
  el.smartBtn.classList.toggle('on', next === 'smart');
  el.fastBtn.classList.toggle('on', next === 'fast');
  el.modeHint.textContent = HINTS[next];
}

function show(node) { node.hidden = false; }
function hide(node) { node.hidden = true; }

function showError(message) {
  el.errorMsg.textContent = '⚠️ ' + message;
  show(el.errorCard);
  show(el.inputCard);
  show(el.modeSection);
}

function setProgress(percent, message) {
  el.progressBar.style.width = Math.max(0, Math.min(100, percent)) + '%';
  el.loadingMsg.textContent = message;
}

function startLoading() {
  hide(el.errorCard);
  hide(el.resultSection);
  hide(el.inputCard);
  hide(el.modeSection);
  setProgress(0, '요청을 보내는 중...');
  show(el.loadingCard);
  el.analyzeBtn.disabled = true;
}

function stopLoading() {
  hide(el.loadingCard);
  el.analyzeBtn.disabled = false;
}

function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m + '분 ' + s + '초';
}

// --- 렌더링 (전부 textContent) -------------------------------------------

function heading(text) {
  const node = document.createElement('h3');
  node.textContent = text;
  return node;
}

function paragraph(text, className) {
  const node = document.createElement('p');
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

function bulletList(items) {
  const list = document.createElement('ul');
  items.forEach((item) => {
    const li = document.createElement('li');
    li.textContent = item;
    list.appendChild(li);
  });
  return list;
}

function keywordRow(keywords) {
  const row = document.createElement('div');
  row.className = 'keyword-row';
  keywords.forEach((keyword) => {
    const chip = document.createElement('span');
    chip.className = 'keyword';
    chip.textContent = keyword;
    row.appendChild(chip);
  });
  return row;
}

function renderReport(report) {
  const root = el.reportContent;
  root.replaceChildren();
  if (!report) return;

  if (report.headline) root.appendChild(heading('📌 ' + report.headline));
  if (report.topic) root.appendChild(paragraph(report.topic));

  if (report.summary_points && report.summary_points.length) {
    root.appendChild(heading('📝 내용 요약'));
    root.appendChild(bulletList(report.summary_points));
  }
  if (report.visual_notes && report.visual_notes.length) {
    root.appendChild(heading('🖼️ 주요 화면 설명'));
    root.appendChild(bulletList(report.visual_notes));
  }
  if (report.keywords && report.keywords.length) {
    root.appendChild(heading('💡 핵심 키워드'));
    root.appendChild(keywordRow(report.keywords));
  }
  if (report.takeaway) {
    root.appendChild(heading('🎯 한 줄 결론'));
    root.appendChild(paragraph(report.takeaway, 'takeaway'));
  }
}

function renderImages(items) {
  el.imageList.replaceChildren();
  items.forEach((item) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'img-item';

    const head = document.createElement('div');
    head.className = 'img-head';
    const ts = document.createElement('span');
    ts.className = 'img-ts';
    ts.textContent = item.timestamp;
    const reason = document.createElement('span');
    reason.className = 'img-reason';
    reason.textContent = item.reason || '';
    head.append(ts, reason);

    const desc = document.createElement('p');
    desc.className = 'img-desc';
    desc.textContent = item.description || '';

    wrapper.append(head, desc);
    el.imageList.appendChild(wrapper);
  });
}

function renderResult(data) {
  const info = data.video_info || {};
  if (info.title || info.thumbnail) {
    show(el.videoInfoCard);
    if (info.thumbnail) {
      el.videoThumb.src = info.thumbnail;
      el.videoThumb.alt = info.title ? info.title + ' 썸네일' : '';
      el.videoThumb.hidden = false;
    } else {
      el.videoThumb.hidden = true;
    }
    el.videoTitle.textContent = info.title || '분석 완료';
    el.videoAuthor.textContent = info.author || '';
    el.videoDuration.textContent = formatDuration(info.duration);
  }

  const stats = data.stats || {};
  show(el.statsGrid);
  el.statCues.textContent = (stats.subtitle_cues || 0) + '개';
  el.statFrames.textContent = (stats.frames_captured || 0) + '장';
  el.statCost.textContent = '₩' + (stats.estimated_cost_krw || 0).toLocaleString('ko-KR');

  const noteParts = [];
  if (stats.model) noteParts.push(stats.model);
  if (stats.input_tokens != null) {
    noteParts.push(
      '입력 ' + stats.input_tokens.toLocaleString('ko-KR') +
      ' / 출력 ' + (stats.output_tokens || 0).toLocaleString('ko-KR') + ' 토큰'
    );
  }
  if (stats.estimated_cost_usd != null) noteParts.push('$' + stats.estimated_cost_usd);
  if (data.cached) noteParts.push('캐시된 결과 (추가 비용 없음)');
  if (noteParts.length) {
    el.costNote.textContent = noteParts.join(' · ') + ' — 환율에 따른 근사치';
    show(el.costNote);
  }

  const images = data.image_analyses || [];
  if (images.length) {
    show(el.imageCard);
    el.imageBadge.textContent = '🖼️ 자동 캡처 + 화면 분석 (' + images.length + '장)';
    renderImages(images);
  } else {
    hide(el.imageCard);
  }

  show(el.reportCard);
  el.reportBadge.textContent =
    '✨ ' + (mode === 'smart' ? '스마트' : '빠른') + ' 분석 완료';
  renderReport(data.report);

  show(el.resultSection);
  el.resultSection.scrollIntoView({ behavior: 'smooth' });
}

// --- SSE 소비 -------------------------------------------------------------

function handleEvent(event) {
  if (event.type === 'progress') {
    setProgress(event.percent, event.message);
  } else if (event.type === 'result') {
    stopLoading();
    renderResult(event.data);
  } else if (event.type === 'error') {
    stopLoading();
    showError(event.message);
  }
}

// EventSource 대신 fetch를 쓰는 이유: HTTP 상태 코드(400/429/503)를 읽어
// 정확한 오류 메시지를 보여줄 수 있고, 취소도 가능합니다.
async function analyze() {
  const url = el.urlInput.value.trim();
  if (!url) {
    showError('YouTube 링크를 입력해 주세요.');
    return;
  }

  startLoading();
  controller = new AbortController();

  let response;
  try {
    response = await fetch(
      '/api/analyze/stream?url=' + encodeURIComponent(url) + '&mode=' + mode,
      { headers: { Accept: 'text/event-stream' }, signal: controller.signal }
    );
  } catch (err) {
    stopLoading();
    if (err.name !== 'AbortError') showError('서버에 연결할 수 없습니다.');
    return;
  }

  if (!response.ok) {
    stopLoading();
    let message = 'HTTP ' + response.status;
    try {
      const body = await response.json();
      if (body && body.error) message = body.error;
    } catch (_) { /* 본문이 JSON이 아니면 상태 코드를 그대로 보여줍니다. */ }
    showError(message);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of raw.split('\n')) {
          if (!line.startsWith('data:')) continue;
          try {
            handleEvent(JSON.parse(line.slice(5).trim()));
          } catch (_) { /* 잘린 이벤트는 무시 */ }
        }
      }
    }
  } catch (err) {
    stopLoading();
    if (err.name !== 'AbortError') showError('분석 중 연결이 끊어졌습니다.');
    return;
  }

  // 서버가 result 없이 스트림을 닫은 경우.
  if (!el.loadingCard.hidden) {
    stopLoading();
    showError('분석이 완료되지 않았습니다. 다시 시도해 주세요.');
  }
}

function reset() {
  if (controller) controller.abort();
  el.urlInput.value = '';
  hide(el.resultSection);
  hide(el.errorCard);
  hide(el.imageCard);
  hide(el.videoInfoCard);
  hide(el.costNote);
  stopLoading();
  show(el.inputCard);
  show(el.modeSection);
  el.urlInput.focus();
}

el.smartBtn.addEventListener('click', () => setMode('smart'));
el.fastBtn.addEventListener('click', () => setMode('fast'));
el.analyzeBtn.addEventListener('click', analyze);
el.urlInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') analyze();
});
el.cancelBtn.addEventListener('click', () => {
  if (controller) controller.abort();
  stopLoading();
  show(el.inputCard);
  show(el.modeSection);
});
el.errorDismiss.addEventListener('click', () => hide(el.errorCard));
el.resetBtn.addEventListener('click', reset);

setMode('smart');
