/* Voice TTS - streaming player, voice sheet, and app-not-a-page behaviour. */

const $ = (id) => document.getElementById(id);
const els = {
  status: $('status'), statusText: $('statusText'),
  text: $('text'), count: $('count'),
  voiceBtn: $('voiceBtn'), voiceName: $('voiceName'), voiceList: $('voiceList'),
  sheet: $('sheet'), scrim: $('scrim'), speed: $('speed'),
  playBtn: $('playBtn'), playIcon: $('playIcon'), playLabel: $('playLabel'),
  saveBtn: $('saveBtn'), timecode: $('timecode'), meter: $('meter'),
  pron: $('pron'), stopBtn: $('stopBtn'), seek: $('seek'), format: $('format'),
};

const REGIONS = ['Bắc', 'Trung', 'Nam'];
const PRIME_SECONDS = 0.3;   // head start so a slow chunk never starves playback
const METER_BARS = 40;

let voices = [];
let voice = null;
let abort = null;
let speed = 1;
// "normal": the engine reads the text as typed. "special": the backend respells
// the words it gets wrong first (POST, AP, Board, ESP32).
let pronunciation = 'normal';
// What "Lưu" writes: a WAV built here, or an MP3/OGG the backend encodes.
let saveFormat = 'wav';
// Every start and every stop bumps this. A read carries the value it started
// with and checks it before touching the UI, so a read the user has already
// stopped can no longer report into the one that replaced it.
let run = 0;

/* ---- Preferences: what the user chose survives a reload and a restart -- */

// Per viewer, in this browser (the desktop window keeps a profile of its own).
// Storage can be missing or refuse - a private window, cleared site data - so
// every access is guarded and the app works the same without it.
const PREFS_KEY = 'voice-tts:prefs';
const DRAFT_KEY = 'voice-tts:draft';

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {}; } catch { return {}; }
}

function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ voice, speed, pronunciation, saveFormat }));
  } catch { /* nothing to keep it in */ }
}

let draftTimer = 0;
function saveDraft() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    try {
      if (els.text.value) localStorage.setItem(DRAFT_KEY, els.text.value);
      else localStorage.removeItem(DRAFT_KEY);
    } catch { /* nothing to keep it in */ }
  }, 500);
}

function loadDraft() {
  try { return localStorage.getItem(DRAFT_KEY) || ''; } catch { return ''; }
}

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

function pickVoice(name, remember = true) {
  voice = name;
  if (remember) savePrefs();
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
// Both setters ignore a value no button offers, so a stale or hand-edited
// preference falls back to the default instead of reaching the backend.
function setSpeed(value) {
  const opt = [...els.speed.children].find((o) => Number(o.dataset.speed) === Number(value));
  if (!opt) return;
  speed = Number(opt.dataset.speed);
  for (const o of els.speed.children) o.setAttribute('aria-pressed', String(o === opt));
}

function setPronunciation(value) {
  const opt = [...els.pron.children].find((o) => o.dataset.pron === value);
  if (!opt) return;
  pronunciation = opt.dataset.pron;
  for (const o of els.pron.children) o.setAttribute('aria-pressed', String(o === opt));
}

function setFormat(value) {
  const opt = [...els.format.children].find((o) => o.dataset.format === value);
  if (!opt) return;
  saveFormat = opt.dataset.format;
  for (const o of els.format.children) o.setAttribute('aria-pressed', String(o === opt));
  els.saveBtn.textContent = `Lưu ${saveFormat.toUpperCase()}`;
}

els.format.addEventListener('click', (e) => {
  const opt = e.target.closest('.speed__opt');
  if (!opt) return;
  setFormat(opt.dataset.format);
  savePrefs();
});

els.speed.addEventListener('click', (e) => {
  const opt = e.target.closest('.speed__opt');
  if (!opt) return;
  setSpeed(opt.dataset.speed);
  savePrefs();
});

els.pron.addEventListener('click', (e) => {
  const opt = e.target.closest('.speed__opt');
  if (!opt) return;
  setPronunciation(opt.dataset.pron);
  savePrefs();
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
    if (!player.playing) {
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

/* ---- Tape: the reading, kept so it plays again without the backend ------ */

let ctx = null, gain = null, analyser = null;

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

// The tape is kept as Int16. At the 20 000-character limit this is 20+ minutes
// of audio; float32 would hold twice as much of it in memory and the WAV is
// 16-bit either way. `starts[i]` is where `chunks[i]` begins, in samples.
const tape = { key: '', rate: 48000, chunks: [], starts: [], length: 0, complete: false };
// True while the backend is still sending this tape.
let synthesizing = false;

// What a reading depends on. The tape answers for this key only: change the
// text, the voice, the speed or the pronunciation and the next press reads anew.
function readingKey() {
  return JSON.stringify([els.text.value.trim(), voice, speed, pronunciation]);
}

// A tape that can be played: it matches what is on screen, and it is either
// whole or still arriving. One stopped half-way is kept for saving only.
function tapeValid() {
  return tape.length > 0 && tape.key === readingKey() && (tape.complete || synthesizing);
}

function resetTape(key, rate = 48000) {
  Object.assign(tape, { key, rate, chunks: [], starts: [], length: 0, complete: false });
}

function appendTape(pcm) {
  tape.starts.push(tape.length);
  tape.chunks.push(pcm);
  tape.length += pcm.length;
}

// `n` samples from `from`, as the float32 an AudioBuffer takes.
function tapeSlice(from, n) {
  const out = new Float32Array(Math.max(0, Math.min(n, tape.length - from)));
  let lo = 0, hi = tape.starts.length - 1;
  while (lo < hi) {   // the chunk holding `from`
    const mid = (lo + hi + 1) >> 1;
    if (tape.starts[mid] <= from) lo = mid; else hi = mid - 1;
  }
  for (let i = lo, off = from - tape.starts[lo], w = 0; w < out.length; i++, off = 0) {
    const chunk = tape.chunks[i];
    const take = Math.min(chunk.length - off, out.length - w);
    for (let k = 0; k < take; k++) out[w + k] = chunk[off + k] / 32767;
    w += take;
  }
  return out;
}

/* ---- Player: schedules the tape a little ahead of the audio clock ------- */

const SLICE = 48000;        // one second per AudioBuffer
const AHEAD_SECONDS = 2;    // how far ahead of the clock the tape is scheduled

// `sched` is what is queued on the audio clock: [{src, at, from, to}], sample
// ranges of the tape. `base` is the position before the first entry, `next`
// the first sample not yet queued, `cursor` where on the clock it would go.
const player = { playing: false, pos: 0, base: 0, next: 0, cursor: 0, sched: [], timer: 0 };

// Where playback is on the tape, in samples.
function position() {
  if (!player.playing) return player.pos;
  const t = ctx.currentTime;
  let p = player.base;
  for (const s of player.sched) {
    if (t < s.at) return s.from;   // waiting out the head start, or an underrun
    const end = s.at + (s.to - s.from) / tape.rate;
    if (t < end) return s.from + Math.floor((t - s.at) * tape.rate);
    p = s.to;
  }
  return p;
}

function stopSources() {
  for (const s of player.sched) { try { s.src.stop(); } catch { /* already finished */ } }
  player.sched = [];
}

function pump() {
  if (!player.playing) return;
  const t = ctx.currentTime;
  // Forget what has played, keeping the last entry: position() reads from it.
  while (player.sched.length > 1 && player.sched[0].at
         + (player.sched[0].to - player.sched[0].from) / tape.rate < t - 0.5) {
    player.base = player.sched.shift().to;
  }
  while (player.next < tape.length && player.cursor - t < AHEAD_SECONDS) {
    const data = tapeSlice(player.next, SLICE);
    const buf = ctx.createBuffer(1, data.length, tape.rate);
    buf.copyToChannel(data, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(gain);
    // Fell behind (the start, or the backend was slower than real time): leave
    // a head start so the next slow chunk does not starve playback. A whole
    // tape is all there already and needs none.
    const at = player.cursor >= t ? player.cursor
      : t + (tape.complete ? 0.03 : PRIME_SECONDS);
    src.start(at);
    player.sched.push({ src, at, from: player.next, to: player.next + data.length });
    player.cursor = at + buf.duration;
    player.next += data.length;
  }
  if (!synthesizing && player.next >= tape.length && t >= player.cursor) finished();
}

function play(from) {
  stopSources();
  Object.assign(player, { playing: true, pos: from, base: from, next: from, cursor: 0 });
  clearInterval(player.timer);
  player.timer = setInterval(pump, 200);
  pump();
  if (player.playing) {   // an empty rest of the tape finishes at once
    setStatus('speaking', 'Đang đọc…');
    render();
    tick();
  }
}

function pause() {
  player.pos = position();
  stopSources();
  player.playing = false;
  clearInterval(player.timer);
  setStatus('ready', synthesizing ? 'Tạm dừng · vẫn đang tạo phần sau' : 'Tạm dừng');
  render();
}

// The end of the tape: back to the start, ready to play it again.
function finished() {
  stopSources();
  Object.assign(player, { playing: false, pos: 0 });
  clearInterval(player.timer);
  setStatus('ready', 'Sẵn sàng');
  render();
}

function seek(to) {
  to = Math.max(0, Math.min(Math.floor(to), tape.length));
  if (player.playing) play(to);
  else { player.pos = to; render(); }
}

/* ---- Reading: the backend fills the tape, the player plays it ----------- */

// Stop everything: the request, and the playback. What was read stays on the
// tape for saving; a tape cut short is not offered for replay.
function stop() {
  run++;
  if (abort) abort.abort();
  synthesizing = false;
  if (!tape.complete) tape.key = '';
  stopSources();
  Object.assign(player, { playing: false, pos: 0 });
  clearInterval(player.timer);
  setStatus('ready', 'Sẵn sàng');
  render();
}

async function read() {
  const text = els.text.value.trim();
  if (!text) { els.text.focus(); return; }

  stop();
  const myRun = run;
  const ac = audio();
  await ac.resume();
  abort = new AbortController();
  resetTape(readingKey());
  synthesizing = true;
  play(0);

  // A failure before any audio leaves nothing to keep.
  const fail = (message) => {
    synthesizing = false;
    tape.key = '';
    stopSources();
    Object.assign(player, { playing: false, pos: 0 });
    clearInterval(player.timer);
    setStatus('error', message);
    render();
  };

  let res;
  try {
    res = await fetch('/api/tts/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, speed, pronunciation }),
      signal: abort.signal,
    });
  } catch {
    if (myRun === run) fail('Không gọi được backend');   // else: aborted by Dừng
    return;
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    if (myRun === run) fail(detail.detail || `Lỗi ${res.status}`);
    return;
  }

  tape.rate = Number(res.headers.get('X-Sample-Rate')) || 48000;
  const reader = res.body.getReader();
  let tail = new Uint8Array(0);
  let broken = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (myRun !== run) return;

      const joined = new Uint8Array(tail.length + value.length);
      joined.set(tail); joined.set(value, tail.length);
      const usable = joined.length - (joined.length % 4);
      tail = joined.slice(usable);
      if (!usable) continue;

      // Copy into a fresh buffer: Float32Array needs a 4-byte-aligned offset.
      const samples = new Float32Array(joined.buffer.slice(0, usable));
      const pcm = new Int16Array(samples.length);
      for (let i = 0; i < samples.length; i++) {
        pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 32767;
      }
      appendTape(pcm);
      pump();
      render();
    }
  } catch (err) {
    broken = err.name !== 'AbortError';
  }

  if (myRun !== run) return;   // stopped or superseded: this read owns nothing now
  synthesizing = false;
  if (!tape.length) { fail('Không nhận được âm thanh'); return; }
  if (broken) {
    // Keep what arrived for saving; it is not the whole text, so no replay.
    tape.key = '';
    setStatus('error', 'Luồng âm thanh bị ngắt');
  } else {
    tape.complete = true;
  }
  pump();   // the end of the tape may be what finishes playback
  render();
}

function fmt(seconds) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/* ---- Controls ------------------------------------------------------------ */

const PLAY_ICON = '<path d="M4 2.8v10.4l9-5.2z" fill="currentColor"/>';
const PAUSE_ICON = '<rect x="3.5" y="3" width="3" height="10" rx="1" fill="currentColor"/>'
  + '<rect x="9.5" y="3" width="3" height="10" rx="1" fill="currentColor"/>';

let seeking = false;   // the user is dragging the bar: the clock must not fight it

function renderTime() {
  const total = tape.length / tape.rate;
  const at = seeking ? Number(els.seek.value) * total : position() / tape.rate;
  els.timecode.textContent = tape.length ? `${fmt(at)} / ${fmt(total)}` : '0:00';
  if (!seeking) els.seek.value = tape.length ? String(position() / tape.length) : '0';
  els.seek.style.setProperty('--fill-to', `${Number(els.seek.value) * 100}%`);
}

function render() {
  const valid = tapeValid();
  const busy = synthesizing || player.playing;
  let label = 'Đọc';
  if (player.playing) label = 'Tạm dừng';
  else if (valid) label = player.pos > 0 ? 'Tiếp tục' : 'Phát lại';
  els.playLabel.textContent = label;
  els.playIcon.innerHTML = player.playing ? PAUSE_ICON : PLAY_ICON;
  els.stopBtn.disabled = !(busy || player.pos > 0);
  els.seek.disabled = !valid;
  els.saveBtn.disabled = tape.length === 0;
  // What a reading depends on is fixed while it is being made or heard.
  els.text.readOnly = busy;
  els.voiceBtn.disabled = busy;
  for (const o of els.speed.children) o.disabled = busy;
  for (const o of els.pron.children) o.disabled = busy;
  const live = player.playing ? '1' : '0';
  if (els.meter.dataset.live !== live) {
    els.meter.dataset.live = live;
    if (player.playing) drawMeter(analyser);
  }
  renderTime();
}

// The time display follows the clock while something plays.
function tick() {
  if (!player.playing) return;
  renderTime();
  requestAnimationFrame(tick);
}

// The one button: read, pause, carry on, or play again.
function primary() {
  if (player.playing) pause();
  else if (tapeValid()) play(player.pos >= tape.length ? 0 : player.pos);
  else read();
}

els.seek.addEventListener('input', () => { seeking = true; renderTime(); });
els.seek.addEventListener('change', () => {
  seeking = false;
  seek(Number(els.seek.value) * tape.length);
});

/* ---- Saving: WAV built here, MP3/OGG encoded by the backend ------------ */

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

function download(blob, ext) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `voice-tts-${Date.now()}.${ext}`;
  a.click();
  // The save dialog is native, so the page never hears how it ended; say what
  // was handed over rather than claiming a file exists.
  setStatus(player.playing ? 'speaking' : 'ready',
    `Đã gửi file ${ext.toUpperCase()} sang hộp thoại lưu`);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// The tape as a file: WAV right here; MP3 and OGG from the backend, which gets
// the 16-bit samples it would have produced anyway - no second synthesis.
async function saveTape(chunks, rate, fmt) {
  // The samples already carry the speed they were read at, so this is a plain
  // 48 kHz file - no sample-rate trickery for a player to refuse.
  if (fmt === 'wav') { download(toWav(chunks, rate), 'wav'); return; }
  els.saveBtn.disabled = true;
  setStatus('loading', `Đang mã hoá ${fmt.toUpperCase()}…`);
  try {
    const res = await fetch(`/api/encode?format=${fmt}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: new Blob(chunks),   // Int16Array views: little-endian on every platform we run on
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      setStatus('error', detail.detail || `Lỗi ${res.status}`);
      return;
    }
    download(await res.blob(), fmt);
  } catch {
    setStatus('error', 'Không gọi được backend');
  } finally {
    render();
  }
}

els.saveBtn.addEventListener('click', () => {
  if (tape.length) saveTape(tape.chunks, tape.rate, saveFormat);
});

/* ---- Wiring ------------------------------------------------------------ */

function setStatus(state, text) {
  els.status.dataset.state = state;
  els.statusText.textContent = text;
}

els.playBtn.addEventListener('click', primary);
els.stopBtn.addEventListener('click', stop);

function renderCount() {
  // The limit arrives with /api/voices; until then report the length alone
  // rather than the browser's "no limit" sentinel.
  const max = els.text.maxLength;
  els.count.textContent = max > 0 ? `${els.text.value.length} / ${max}` : `${els.text.value.length}`;
}

els.text.addEventListener('input', () => { renderCount(); saveDraft(); render(); });

// Ctrl+Enter is the commit gesture: read, pause, carry on. Escape stops.
addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !els.playBtn.disabled) {
    e.preventDefault();
    primary();
  }
  if (e.key === 'Escape' && !sheetState.open && !els.stopBtn.disabled) stop();
});

async function boot() {
  const prefs = loadPrefs();
  setSpeed(prefs.speed);
  setPronunciation(prefs.pronunciation);
  setFormat(prefs.saveFormat);
  els.text.value = loadDraft();
  renderCount();
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
  // A voice the server no longer lists - an SDK upgrade renamed it, or this is
  // another server - falls back to the default rather than failing the read.
  const known = voices.some((v) => v.name === prefs.voice);
  pickVoice(known ? prefs.voice : info.default, false);
  els.playBtn.disabled = false;
  render();
  setStatus('ready', 'Sẵn sàng');
  els.text.focus();
}

boot();
