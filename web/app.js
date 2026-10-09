/* Voice TTS - streaming player, voice sheet, and app-not-a-page behaviour. */

const $ = (id) => document.getElementById(id);
const els = {
  status: $('status'), statusText: $('statusText'),
  text: $('text'), count: $('count'),
  voiceBtn: $('voiceBtn'), voiceName: $('voiceName'), voiceList: $('voiceList'),
  sheet: $('sheet'), scrim: $('scrim'), speed: $('speed'),
  playBtn: $('playBtn'), playIcon: $('playIcon'), playLabel: $('playLabel'),
  saveBtn: $('saveBtn'), timecode: $('timecode'), meter: $('meter'),
  pron: $('pron'),
};

const REGIONS = ['Bắc', 'Trung', 'Nam'];
const PRIME_SECONDS = 0.3;   // head start so a slow chunk never starves playback
const METER_BARS = 40;

let voices = [];
let voice = null;
let speaking = false;
let abort = null;
let speed = 1;
// "normal": the engine reads the text as typed. "special": the backend respells
// the words it gets wrong first (POST, AP, Board, ESP32).
let pronunciation = 'normal';
// Every start and every stop bumps this. A read carries the value it started
// with and checks it before touching the UI, so a read the user has already
// stopped can no longer report into the one that replaced it.
let run = 0;

/* ---- This is an app: no page behaviour leaks through ------------------- */

addEventListener('contextmenu', (e) => e.preventDefault());
addEventListener('dragstart', (e) => e.preventDefault());
addEventListener('wheel', (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
addEventListener('keydown', (e) => {
  const k = e.key;
  const c = e.ctrlKey || e.metaKey;
  const reload = k === 'F5' || (c && k.toLowerCase() === 'r');
  const browserish = c && ['f', 'g', 'p', 'o', 's', 'u', 'j', 'h', 'd', '+', '-', '=', '0']
    .includes(k.toLowerCase());
  if (reload || browserish || k === 'F3' || k === 'F7' || k === 'F11' || k === 'F12') {
    e.preventDefault();
    e.stopPropagation();
  }
}, true);

/* ---- Spring: critically damped by default, interruptible, velocity-aware */

function spring(from, to, onFrame, { damping = 1.0, response = 0.4, velocity = 0 } = {}) {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced) { onFrame(to, true); return () => {}; }

  const w = (2 * Math.PI) / response;
  let x = from - to, v = velocity, raf = 0, last = performance.now();
  const step = (now) => {
    const dt = Math.min((now - last) / 1000, 1 / 30);
    last = now;
    // Semi-implicit Euler; stable at the step sizes rAF gives us.
    v += (-2 * damping * w * v - w * w * x) * dt;
    x += v * dt;
    const done = Math.abs(x) < 0.3 && Math.abs(v) < 2;
    onFrame(done ? to : to + x, done);
    if (!done) raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  return () => cancelAnimationFrame(raf);
}

/* ---- Voice sheet: 1:1 drag, rubber-band, momentum projection ----------- */

const sheetState = { open: false, y: 0, cancel: () => {}, height: 0 };

function setSheetY(y) {
  sheetState.y = y;
  els.sheet.style.transform = `translateY(${y}px)`;
  const p = sheetState.height ? 1 - y / sheetState.height : 0;
  els.scrim.style.opacity = String(Math.max(0, Math.min(1, p)) * 0.45);
}

function openSheet() {
  if (sheetState.open) return;
  sheetState.open = true;
  els.sheet.hidden = false;
  els.scrim.hidden = false;
  sheetState.height = els.sheet.offsetHeight;
  setSheetY(sheetState.height);
  sheetState.cancel();
  // A sheet arrives with a little momentum of its own.
  sheetState.cancel = spring(sheetState.height, 0, setSheetY, { damping: 0.8, response: 0.3 });
}

function closeSheet(velocity = 0) {
  if (!sheetState.open) return;
  sheetState.open = false;
  sheetState.cancel();
  // It leaves along the path it came in on.
  sheetState.cancel = spring(sheetState.y, sheetState.height, (y, done) => {
    setSheetY(y);
    if (done) { els.sheet.hidden = true; els.scrim.hidden = true; }
  }, { damping: 1.0, response: 0.3, velocity });
}

function project(velocity, decel = 0.998) {
  return (velocity / 1000) * decel / (1 - decel);
}

function rubberband(overshoot, dimension, constant = 0.55) {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

els.sheet.addEventListener('pointerdown', (e) => {
  if (e.target.closest('.voice-item, .sheet__list')) return; // let the list scroll
  els.sheet.setPointerCapture(e.pointerId);
  sheetState.cancel();
  const grabY = e.clientY, grabAt = sheetState.y;
  const history = [];

  const move = (ev) => {
    const raw = grabAt + (ev.clientY - grabY);
    // Past the top there is nothing more: resist instead of stopping dead.
    const y = raw < 0 ? -rubberband(-raw, sheetState.height) : raw;
    setSheetY(y);
    history.push([performance.now(), ev.clientY]);
    if (history.length > 5) history.shift();
  };
  const up = () => {
    els.sheet.removeEventListener('pointermove', move);
    els.sheet.removeEventListener('pointerup', up);
    els.sheet.removeEventListener('pointercancel', up);
    const [t0, y0] = history[0] || [performance.now(), grabY];
    const [t1, y1] = history[history.length - 1] || [performance.now() + 1, grabY];
    const v = t1 > t0 ? ((y1 - y0) / (t1 - t0)) * 1000 : 0;
    // Decide from where the flick is heading, not from where the finger stopped.
    if (sheetState.y + project(v) > sheetState.height * 0.4) {
      sheetState.open = true; closeSheet(v);
    } else {
      sheetState.cancel();
      sheetState.cancel = spring(sheetState.y, 0, setSheetY, { damping: 0.8, response: 0.3, velocity: v });
    }
  };
  els.sheet.addEventListener('pointermove', move);
  els.sheet.addEventListener('pointerup', up);
  els.sheet.addEventListener('pointercancel', up);
});

els.scrim.addEventListener('pointerdown', () => closeSheet());
els.voiceBtn.addEventListener('click', openSheet);
addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSheet(); });

/* ---- Voices ------------------------------------------------------------ */

function pickVoice(name) {
  voice = name;
  els.voiceName.textContent = name;
  for (const el of els.voiceList.querySelectorAll('.voice-item')) {
    el.setAttribute('aria-selected', String(el.dataset.name === name));
  }
}

function renderVoices() {
  const groups = new Map();
  for (const v of voices) {
    const key = REGIONS.includes(v.region) ? v.region : 'Khác';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(v);
  }
  const order = [...REGIONS, 'Khác'].filter((r) => groups.has(r));
  els.voiceList.replaceChildren();
  for (const region of order) {
    const h = document.createElement('div');
    h.className = 'voice-group';
    h.textContent = region === 'Khác' ? 'Khác' : `Miền ${region}`;
    els.voiceList.append(h);
    for (const v of groups.get(region)) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'voice-item';
      b.dataset.name = v.name;
      const title = document.createElement('span');
      title.className = 'voice-item__name';
      title.textContent = v.featured ? `★ ${v.name}` : v.name;
      const sub = document.createElement('span');
      sub.className = 'voice-item__sub';
      sub.textContent = v.description;
      b.append(title, sub);
      b.addEventListener('click', () => { pickVoice(v.name); closeSheet(); });
      els.voiceList.append(b);
    }
  }
}

/* ---- Reading speed ----------------------------------------------------- */

// The backend stretches the time and leaves the pitch alone, so this only has
// to travel with the request - what arrives is already at the chosen speed.
els.speed.addEventListener('click', (e) => {
  const opt = e.target.closest('.speed__opt');
  if (!opt) return;
  speed = Number(opt.dataset.speed);
  for (const o of els.speed.children) o.setAttribute('aria-pressed', String(o === opt));
});

els.pron.addEventListener('click', (e) => {
  const opt = e.target.closest('.speed__opt');
  if (!opt) return;
  pronunciation = opt.dataset.pron;
  for (const o of els.pron.children) o.setAttribute('aria-pressed', String(o === opt));
});

/* ---- Meter ------------------------------------------------------------- */

const bars = Array.from({ length: METER_BARS }, () => {
  const b = document.createElement('b');
  els.meter.append(b);
  return b;
});

function drawMeter(analyser) {
  const data = new Uint8Array(analyser.frequencyBinCount);
  const tick = () => {
    if (!speaking) {
      bars.forEach((b) => { b.style.height = '2px'; });
      return;
    }
    analyser.getByteFrequencyData(data);
    // Speech lives below ~6 kHz; spreading 24 kHz of bins over the bars would
    // leave most of them permanently flat.
    const used = Math.max(METER_BARS, Math.floor(data.length / 4));
    const per = Math.floor(used / METER_BARS) || 1;
    bars.forEach((b, i) => {
      let sum = 0;
      for (let j = 0; j < per; j++) sum += data[i * per + j];
      b.style.height = `${2 + (sum / per / 255) * 32}px`;
    });
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ---- Streaming playback ------------------------------------------------ */

let ctx = null, gain = null, analyser = null;
let sources = [];
let recorded = [];
let recordedRate = 48000;

function audio() {
  if (!ctx) {
    ctx = new AudioContext({ sampleRate: 48000 });
    gain = ctx.createGain();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    gain.connect(analyser);
    analyser.connect(ctx.destination);
  }
  return ctx;
}

function setSpeaking(on) {
  speaking = on;
  els.playLabel.textContent = on ? 'Dừng' : 'Đọc';
  els.playIcon.innerHTML = on
    ? '<rect x="4" y="4" width="8" height="8" rx="1.6" fill="currentColor"/>'
    : '<path d="M4 2.8v10.4l9-5.2z" fill="currentColor"/>';
  els.text.readOnly = on;
  // The speed is baked into the request, so it is fixed for the whole read.
  for (const o of els.speed.children) o.disabled = on;
  for (const o of els.pron.children) o.disabled = on;
  els.meter.dataset.live = on ? '1' : '0';
  if (on) drawMeter(analyser);
}

function stop() {
  run++;
  if (abort) abort.abort();
  for (const s of sources) { try { s.stop(); } catch { /* already finished */ } }
  sources = [];
  setSpeaking(false);
  setStatus('ready', 'Sẵn sàng');
}

async function speak() {
  const text = els.text.value.trim();
  if (!text) { els.text.focus(); return; }

  const myRun = ++run;
  const ac = audio();
  await ac.resume();
  abort = new AbortController();
  recorded = [];
  sources = [];
  els.saveBtn.disabled = true;
  setSpeaking(true);
  setStatus('speaking', 'Đang đọc…');

  let res;
  try {
    res = await fetch('/api/tts/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, speed, pronunciation }),
      signal: abort.signal,
    });
  } catch {
    if (myRun !== run) return;   // aborted by Dừng, not a failure to report
    setSpeaking(false);
    setStatus('error', 'Không gọi được backend');
    return;
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    if (myRun !== run) return;
    setSpeaking(false);
    setStatus('error', detail.detail || `Lỗi ${res.status}`);
    return;
  }

  recordedRate = Number(res.headers.get('X-Sample-Rate')) || 48000;
  const reader = res.body.getReader();
  let tail = new Uint8Array(0);
  let cursor = 0;   // where the next chunk starts on the audio clock
  let total = 0;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      const joined = new Uint8Array(tail.length + value.length);
      joined.set(tail); joined.set(value, tail.length);
      const usable = joined.length - (joined.length % 4);
      tail = joined.slice(usable);
      if (!usable) continue;

      // Copy into a fresh buffer: Float32Array needs a 4-byte-aligned offset.
      const samples = new Float32Array(joined.buffer.slice(0, usable));
      // The tape is kept as Int16. At the 20 000-character limit this is 20+
      // minutes of audio; float32 would hold twice as much of it in memory
      // and the WAV is 16-bit either way.
      const pcm = new Int16Array(samples.length);
      for (let i = 0; i < samples.length; i++) {
        pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 32767;
      }
      recorded.push(pcm);
      total += samples.length;

      const buf = ac.createBuffer(1, samples.length, recordedRate);
      buf.copyToChannel(samples, 0);
      const src = ac.createBufferSource();
      src.buffer = buf;
      src.connect(gain);
      cursor = Math.max(cursor, ac.currentTime + PRIME_SECONDS);
      src.start(cursor);
      cursor += buf.duration;
      sources.push(src);

      els.timecode.textContent = fmt(total / recordedRate);
    }
  } catch (err) {
    if (myRun === run && err.name !== 'AbortError') setStatus('error', 'Luồng âm thanh bị ngắt');
  }

  if (myRun !== run) return;   // stopped or superseded: this read owns nothing now

  if (!total) {
    setSpeaking(false);
    setStatus('error', 'Không nhận được âm thanh');
    return;
  }

  els.saveBtn.disabled = false;
  // Generation is done, but audio is still queued: stay "đang đọc" until the
  // last scheduled buffer has actually played.
  const remaining = Math.max(0, (cursor - ac.currentTime) * 1000);
  setTimeout(() => {
    if (myRun !== run) return;
    setSpeaking(false);
    setStatus('ready', 'Sẵn sàng');
  }, remaining);
}

function fmt(seconds) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/* ---- WAV export -------------------------------------------------------- */

function toWav(chunks, rate) {
  const n = chunks.reduce((a, c) => a + c.length, 0);
  const buf = new ArrayBuffer(44 + n * 2);
  const view = new DataView(buf);
  const ascii = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };

  ascii(0, 'RIFF'); view.setUint32(4, 36 + n * 2, true); ascii(8, 'WAVE');
  ascii(12, 'fmt '); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  ascii(36, 'data'); view.setUint32(40, n * 2, true);

  let off = 44;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++, off += 2) view.setInt16(off, chunk[i], true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

els.saveBtn.addEventListener('click', () => {
  if (!recorded.length) return;
  // The samples already carry the speed they were read at, so this is a plain
  // 48 kHz file - no sample-rate trickery for a player to refuse.
  const url = URL.createObjectURL(toWav(recorded, recordedRate));
  const a = document.createElement('a');
  a.href = url;
  a.download = `voice-tts-${Date.now()}.wav`;
  a.click();
  // The save dialog is native, so the page never hears how it ended; say what
  // was handed over rather than claiming a file exists.
  setStatus(speaking ? 'speaking' : 'ready', 'Đã gửi file WAV sang hộp thoại lưu');
  setTimeout(() => URL.revokeObjectURL(url), 5000);
});

/* ---- Wiring ------------------------------------------------------------ */

function setStatus(state, text) {
  els.status.dataset.state = state;
  els.statusText.textContent = text;
}

els.playBtn.addEventListener('click', () => (speaking ? stop() : speak()));

function renderCount() {
  // The limit arrives with /api/voices; until then report the length alone
  // rather than the browser's "no limit" sentinel.
  const max = els.text.maxLength;
  els.count.textContent = max > 0 ? `${els.text.value.length} / ${max}` : `${els.text.value.length}`;
}

els.text.addEventListener('input', renderCount);

// Ctrl+Enter is the commit gesture; Escape stops.
addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !els.playBtn.disabled) {
    e.preventDefault();
    speaking ? stop() : speak();
  }
  if (e.key === 'Escape' && speaking) stop();
});

async function boot() {
  setStatus('loading', 'Đang tải model…');
  for (;;) {
    let s;
    try {
      s = await (await fetch('/api/status')).json();
    } catch {
      await new Promise((r) => setTimeout(r, 1000));
      continue;
    }
    if (s.state === 'ready') break;
    if (s.state === 'error') { setStatus('error', 'Không tải được model'); return; }
    await new Promise((r) => setTimeout(r, 1000));
  }

  const info = await (await fetch('/api/voices')).json();
  // The backend owns the limit; the field and the counter follow it.
  els.text.maxLength = info.maxChars;
  renderCount();
  voices = info.voices;
  renderVoices();
  pickVoice(info.default);
  els.playBtn.disabled = false;
  setStatus('ready', 'Sẵn sàng');
  els.text.focus();
}

boot();
