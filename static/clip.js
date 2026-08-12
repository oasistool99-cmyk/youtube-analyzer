'use strict';

const urlInput = document.getElementById('url');
const startInput = document.getElementById('start');
const endInput = document.getElementById('end');
const button = document.getElementById('clipBtn');
const status = document.getElementById('status');

function setStatus(text, color) {
  status.textContent = text;
  status.style.color = color || '#aaa';
}

async function clipVideo() {
  const url = urlInput.value.trim();
  const start = startInput.value.trim();
  const end = endInput.value.trim();

  if (!url || !start || !end) {
    setStatus('모든 항목을 입력해 주세요.', '#ff6b7a');
    return;
  }

  button.disabled = true;
  button.textContent = '⏳ 처리 중...';
  setStatus('영상을 내려받고 자르는 중입니다. 1~3분 걸릴 수 있어요.');

  let objectUrl = null;
  try {
    const response = await fetch('/api/clip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, start, end }),
    });

    if (!response.ok) {
      let message = 'HTTP ' + response.status;
      try {
        const body = await response.json();
        if (body && body.error) message = body.error;
      } catch (_) { /* JSON이 아니면 상태 코드를 그대로 */ }
      throw new Error(message);
    }

    const blob = await response.blob();
    objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download =
      'clip_' + start.replace(/:/g, '') + '_' + end.replace(/:/g, '') + '.mp4';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setStatus('✅ 다운로드 완료! 다운로드 폴더를 확인하세요.', '#7ddba0');
  } catch (err) {
    setStatus('❌ ' + err.message, '#ff6b7a');
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    button.disabled = false;
    button.textContent = '🎬 자르고 내려받기';
  }
}

button.addEventListener('click', clipVideo);
[urlInput, startInput, endInput].forEach((input) => {
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') clipVideo();
  });
});
