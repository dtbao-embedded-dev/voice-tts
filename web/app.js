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
  card: $('card'), openBtn: $('openBtn'), fileInput: $('fileInput'), reader: $('reader'),
  lexBtn: $('lexBtn'), lexSheet: $('lexSheet'), lexForm: $('lexForm'), lexWord: $('lexWord'),
  lexSay: $('lexSay'), lexCase: $('lexCase'), lexTry: $('lexTry'), lexError: $('lexError'),
  lexList: $('lexList'), histBtn: $('histBtn'), histSheet: $('histSheet'),
  histList: $('histList'), histClear: $('histClear'),
};

const REGIONS = ['Bắc', 'Trung', 'Nam'];
const PRIME_SECONDS = 0.3;   // head start so a slow chunk never starves playback
const METER_BARS = 40;

let voices = [];
let defaultVoice = null;
// The model is loaded and the limit known: until then nothing may be opened,
// since the field's maxLength - what a file is cut to - is not set yet.
let ready = false;
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
    // Ctrl+O is still "open", only ours: a text file, not a page.
    if (c && k.toLowerCase() === 'o' && !els.openBtn.disabled) els.fileInput.click();
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

/* ---- Sheets: 1:1 drag, rubber-band, momentum projection ----------------- */

// One state per sheet; one sheet open at a time, over one shared scrim.
const sheetOf = (el) => ({ el, open: false, y: 0, cancel: () => {}, height: 0 });
let activeSheet = null;

function setSheetY(st, y) {
  st.y = y;
  st.el.style.transform = `translateY(${y}px)`;
  const p = st.height ? 1 - y / st.height : 0;
  els.scrim.style.opacity = String(Math.max(0, Math.min(1, p)) * 0.45);
}

function openSheet(st) {
  if (st.open) return;
  if (activeSheet) closeSheet(activeSheet);
  activeSheet = st;
  st.open = true;
  st.el.hidden = false;
  els.scrim.hidden = false;
  st.height = st.el.offsetHeight;
  setSheetY(st, st.height);
  st.cancel();
  // A sheet arrives with a little momentum of its own.
  st.cancel = spring(st.height, 0, (y) => setSheetY(st, y), { damping: 0.8, response: 0.3 });
}

function closeSheet(st = activeSheet, velocity = 0) {
  if (!st || !st.open) return;
  st.open = false;
  if (activeSheet === st) activeSheet = null;
  st.cancel();
  // Its list may have filled in since it opened: leave by its height now.
  st.height = st.el.offsetHeight;
  // It leaves along the path it came in on.
  st.cancel = spring(st.y, st.height, (y, done) => {
    setSheetY(st, y);
    if (done) {
      st.el.hidden = true;
      if (!activeSheet) els.scrim.hidden = true;
    }
  }, { damping: 1.0, response: 0.3, velocity });
}

function project(velocity, decel = 0.998) {
  return (velocity / 1000) * decel / (1 - decel);
}

function rubberband(overshoot, dimension, constant = 0.55) {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

function draggable(st) {
  st.el.addEventListener('pointerdown', (e) => {
    // Lists scroll and controls take their own presses; the rest drags.
    if (e.target.closest('.sheet__list, button, input, label')) return;
    st.el.setPointerCapture(e.pointerId);
    st.cancel();
    st.height = st.el.offsetHeight;
    const grabY = e.clientY, grabAt = st.y;
    const history = [];

    const move = (ev) => {
      const raw = grabAt + (ev.clientY - grabY);
      // Past the top there is nothing more: resist instead of stopping dead.
      const y = raw < 0 ? -rubberband(-raw, st.height) : raw;
      setSheetY(st, y);
      history.push([performance.now(), ev.clientY]);
      if (history.length > 5) history.shift();
    };
    const up = () => {
      st.el.removeEventListener('pointermove', move);
      st.el.removeEventListener('pointerup', up);
      st.el.removeEventListener('pointercancel', up);
      const [t0, y0] = history[0] || [performance.now(), grabY];
      const [t1, y1] = history[history.length - 1] || [performance.now() + 1, grabY];
      const v = t1 > t0 ? ((y1 - y0) / (t1 - t0)) * 1000 : 0;
      // Decide from where the flick is heading, not from where the finger stopped.
      if (st.y + project(v) > st.height * 0.4) {
        closeSheet(st, v);
      } else {
        st.cancel();
        st.cancel = spring(st.y, 0, (y) => setSheetY(st, y),
          { damping: 0.8, response: 0.3, velocity: v });
      }
    };
    st.el.addEventListener('pointermove', move);
    st.el.addEventListener('pointerup', up);
    st.el.addEventListener('pointercancel', up);
  });
}

const voiceSheet = sheetOf(els.sheet);
const lexSheet = sheetOf(els.lexSheet);
const histSheet = sheetOf(els.histSheet);
draggable(voiceSheet);
draggable(lexSheet);
draggable(histSheet);

els.scrim.addEventListener('pointerdown', () => closeSheet());
els.voiceBtn.addEventListener('click', () => openSheet(voiceSheet));

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
      b.addEventListener('click', () => { pickVoice(v.name); closeSheet(voiceSheet); });
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
// `sentences` are the text's, `segments` [{i, start, end}] where each one read
// so far sits on the tape - from the sentence the reading started at. `source`,
// `voice`, `speed` and `pronunciation` are what it was read with, for the
// history; `saved` once it is there.
const tape = { key: '', rate: 48000, chunks: [], starts: [], length: 0, complete: false,
  sentences: [], segments: [], first: 0, saved: false };
// True while the backend is still sending this tape.
let synthesizing = false;

// What a reading depends on. The tape answers for this key only: change the
// text, the voice, the speed or the pronunciation and the next press reads anew.
function readingKey() {
  const lex = pronunciation === 'special' ? lexVersion : 0;
  return JSON.stringify([els.text.value.trim(), voice, speed, pronunciation, lex]);
}

// A tape that can be played: it matches what is on screen, and it is either
// whole or still arriving. One stopped half-way is kept for saving only.
function tapeValid() {
  return tape.length > 0 && tape.key === readingKey() && (tape.complete || synthesizing);
}

function resetTape(key, rate = 48000) {
  Object.assign(tape, { key, rate, chunks: [], starts: [], length: 0, complete: false,
    sentences: [], segments: [], first: 0, saved: false });
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
  if (synthesizing) remember();   // cut short, but what was heard is kept
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

// One sentence through the backend onto the tape. Answers null when it all
// arrived, or why it did not: an error message, or "aborted" once stopped.
async function streamSentence(sentence, seg, myRun) {
  let res;
  try {
    res = await fetch('/api/tts/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: sentence, voice, speed, pronunciation }),
      signal: abort.signal,
    });
  } catch {
    return myRun === run ? 'Không gọi được backend' : 'aborted';
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    return myRun === run ? (detail.detail || `Lỗi ${res.status}`) : 'aborted';
  }

  tape.rate = Number(res.headers.get('X-Sample-Rate')) || 48000;
  const reader = res.body.getReader();
  let tail = new Uint8Array(0);
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (myRun !== run) return 'aborted';

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
      seg.end = tape.length;
      pump();
      render();
    }
  } catch (err) {
    if (myRun !== run || err.name === 'AbortError') return 'aborted';
    return 'Luồng âm thanh bị ngắt';
  }
  return myRun === run ? null : 'aborted';
}

// Read the text from sentence `from` on, one request per sentence: each
// sentence's place on the tape is then known exactly, which is what the
// highlight and click-to-seek go by. Playback starts with the first sentence
// while the rest are still being made.
async function read(from = 0) {
  const sentences = VoiceText.splitSentences(els.text.value);
  if (!sentences.length) { els.text.focus(); return; }

  stop();
  const myRun = run;
  await audio().resume();
  abort = new AbortController();
  resetTape(readingKey());
  Object.assign(tape, { sentences, first: Math.min(from, sentences.length - 1),
    source: els.text.value, voice, speed, pronunciation });
  synthesizing = true;
  buildReader();
  play(0);

  let failure = null;
  for (let i = tape.first; i < sentences.length; i++) {
    const seg = { i, start: tape.length, end: tape.length };
    tape.segments.push(seg);
    failure = await streamSentence(sentences[i].text, seg, myRun);
    if (failure === 'aborted') return;   // stopped or superseded: owns nothing now
    if (seg.end === seg.start) tape.segments.pop();   // nothing came back for it
    if (failure) break;
    render();
  }

  synthesizing = false;
  if (!tape.length) {
    // A failure before any audio leaves nothing to keep.
    tape.key = '';
    stopSources();
    Object.assign(player, { playing: false, pos: 0 });
    clearInterval(player.timer);
    setStatus('error', failure || 'Không nhận được âm thanh');
    render();
    return;
  }
  if (failure) {
    // Keep what arrived for saving; it is not the whole text, so no replay.
    tape.key = '';
    setStatus('error', failure);
  } else {
    tape.complete = true;
  }
  remember();
  pump();   // the end of the tape may be what finishes playback
  render();
}

/* ---- Reader: the text while it is read, the current sentence lit -------- */

// The sentence playing now: the segment holding `pos`, or -1.
function sentenceAt(pos) {
  for (const s of tape.segments) if (pos >= s.start && pos < s.end) return s.i;
  return -1;
}

function buildReader() {
  const src = els.text.value;
  els.reader.replaceChildren();
  let at = 0;
  tape.sentences.forEach((s, i) => {
    if (s.start > at) els.reader.append(src.slice(at, s.start));
    const span = document.createElement('span');
    span.className = 'sent';
    span.dataset.i = String(i);
    span.textContent = s.text;
    els.reader.append(span);
    at = s.end;
  });
  if (at < src.length) els.reader.append(src.slice(at));
  els.reader.scrollTop = els.text.scrollTop;
  litSentence = -2;
}

let litSentence = -2;   // what the reader shows lit; -2: nothing drawn yet

// Shown while a reading is under way or paused; sentences already on the tape
// look ready, the rest are still being made.
function renderReader() {
  const show = tapeValid() && (synthesizing || player.playing || player.pos > 0);
  els.reader.hidden = !show;
  els.text.hidden = show;
  if (!show) return;
  const ready = new Set(tape.segments.map((s) => s.i));
  for (const span of els.reader.children) {
    span.classList.toggle('sent--ready', ready.has(Number(span.dataset.i)));
  }
}

// Every frame while playing: light the sentence being heard.
function renderLit() {
  if (els.reader.hidden) return;
  const now = sentenceAt(position());
  if (now === litSentence) return;
  litSentence = now;
  for (const span of els.reader.querySelectorAll('.sent--now')) span.classList.remove('sent--now');
  const span = els.reader.querySelector(`.sent[data-i="${now}"]`);
  if (span) {
    span.classList.add('sent--now');
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    span.scrollIntoView({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' });
  }
}

// A sentence clicked: play from it if it is on the tape, else read from it.
els.reader.addEventListener('click', (e) => {
  const span = e.target.closest('.sent');
  if (!span) return;
  const i = Number(span.dataset.i);
  const seg = tape.segments.find((s) => s.i === i);
  if (seg) {
    if (player.playing) seek(seg.start);
    else play(seg.start);
  } else {
    read(i);
  }
});

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
  renderLit();
}

function render() {
  const valid = tapeValid();
  const busy = synthesizing || player.playing;
  let label = 'Đọc';
  if (player.playing) label = 'Tạm dừng';
  else if (valid && player.pos > 0) label = 'Tiếp tục';
  else if (valid && tape.first === 0) label = 'Phát lại';
  els.playLabel.textContent = label;
  els.playIcon.innerHTML = player.playing ? PAUSE_ICON : PLAY_ICON;
  els.stopBtn.disabled = !(busy || player.pos > 0);
  els.seek.disabled = !valid;
  els.saveBtn.disabled = tape.length === 0;
  // What a reading depends on is fixed while it is being made or heard.
  els.text.readOnly = busy;
  els.openBtn.disabled = busy || !ready;
  els.voiceBtn.disabled = busy;
  for (const o of els.speed.children) o.disabled = busy;
  for (const o of els.pron.children) o.disabled = busy;
  const live = player.playing ? '1' : '0';
  if (els.meter.dataset.live !== live) {
    els.meter.dataset.live = live;
    if (player.playing) drawMeter(analyser);
  }
  renderReader();
  renderTime();
}

// The time display follows the clock while something plays.
function tick() {
  if (!player.playing) return;
  renderTime();
  requestAnimationFrame(tick);
}

// The one button: read, pause, carry on, or play again. A tape that starts
// part-way (a sentence was clicked) is played again only from where it stands;
// from its start, the whole text is read.
function primary() {
  if (player.playing) pause();
  else if (tapeValid() && (player.pos > 0 || tape.first === 0)) {
    play(player.pos >= tape.length ? 0 : player.pos);
  } else read();
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

/* ---- Lexicon: the words the special pronunciation respells ------------- */

// The server's list (one per server: on a LAN server everyone with the token
// shares it). `lexVersion` goes into the reading key, so a changed list makes
// a special-pronunciation reading read anew instead of replaying the old tape.
let lexicon = { builtin: [], user: [] };
let lexVersion = 0;

function lexError(message) {
  els.lexError.textContent = message;
  els.lexError.hidden = !message;
}

const detailOf = (body, res) =>
  (typeof body.detail === 'string' ? body.detail : `Lỗi ${res.status}`);

async function loadLexicon() {
  try {
    const res = await fetch('/api/lexicon');
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { lexError(detailOf(body, res)); return; }
    lexicon = body;
    lexError('');
  } catch {
    lexError('Không gọi được backend');
  }
  renderLexicon();
}

async function storeLexicon(user) {
  try {
    const res = await fetch('/api/lexicon', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { lexError(detailOf(body, res)); return false; }
    lexicon = body;
  } catch {
    lexError('Không gọi được backend');
    return false;
  }
  lexError('');
  lexVersion++;
  renderLexicon();
  render();
  return true;
}

// "Nghe thử": how the engine says a spelling, in a throwaway player of its own.
let tryAudio = null;
async function tryWord(say) {
  if (!say.trim()) return;
  try {
    const res = await fetch('/api/tts/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: say, voice, speed, pronunciation: 'normal', format: 'wav' }),
    });
    if (!res.ok) { lexError(detailOf(await res.json().catch(() => ({})), res)); return; }
    const url = URL.createObjectURL(await res.blob());
    if (tryAudio) tryAudio.pause();
    tryAudio = new Audio(url);
    tryAudio.onended = () => URL.revokeObjectURL(url);
    await tryAudio.play();
  } catch {
    lexError('Không gọi được backend');
  }
}

const sameWord = (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase();

function lexRow(entry, mine, overridden) {
  const row = document.createElement('div');
  row.className = 'lex-item' + (overridden ? ' lex-item--overridden' : '');
  const word = document.createElement('span');
  word.className = 'lex-item__word';
  word.textContent = entry.word;
  if (entry.matchCase) {
    const badge = document.createElement('span');
    badge.className = 'lex-item__case';
    badge.textContent = 'Aa';
    badge.title = 'Chỉ đúng chữ hoa/thường này';
    word.append(badge);
  }
  const say = document.createElement('span');
  say.className = 'lex-item__say';
  say.textContent = entry.say;
  const listen = document.createElement('button');
  listen.type = 'button';
  listen.className = 'link';
  listen.textContent = 'Nghe';
  listen.addEventListener('click', () => tryWord(entry.say));
  row.append(word, say, listen);
  if (mine) {
    // A press on the word puts it in the form, to change how it is read.
    word.addEventListener('click', () => {
      els.lexWord.value = entry.word;
      els.lexSay.value = entry.say;
      els.lexCase.checked = entry.matchCase;
      els.lexSay.focus();
    });
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'link link--danger';
    del.textContent = 'Xoá';
    del.addEventListener('click', () =>
      storeLexicon(lexicon.user.filter((e) => !sameWord(e.word, entry.word))));
    row.append(del);
  }
  return row;
}

function renderLexicon() {
  const list = els.lexList;
  list.replaceChildren();
  const group = (title) => {
    const h = document.createElement('div');
    h.className = 'voice-group';
    h.textContent = title;
    list.append(h);
  };
  group(`Của bạn · ${lexicon.user.length}`);
  if (!lexicon.user.length) {
    const empty = document.createElement('p');
    empty.className = 'lex-empty';
    empty.textContent = 'Chưa có từ nào. Thêm ở trên, ví dụ MQTT → em kiu ti ti.';
    list.append(empty);
  }
  for (const e of lexicon.user) list.append(lexRow(e, true, false));
  group('Có sẵn');
  for (const e of lexicon.builtin) {
    list.append(lexRow(e, false, lexicon.user.some((u) => sameWord(u.word, e.word))));
  }
}

els.lexForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const entry = { word: els.lexWord.value.trim(), say: els.lexSay.value.trim(),
    matchCase: els.lexCase.checked };
  if (!entry.word || !entry.say) return;
  // The same word again changes how it is read rather than adding a twin.
  const user = [...lexicon.user.filter((u) => !sameWord(u.word, entry.word)), entry];
  if (await storeLexicon(user)) {
    els.lexForm.reset();
    els.lexWord.focus();
  }
});
els.lexTry.addEventListener('click', () => tryWord(els.lexSay.value));
els.lexBtn.addEventListener('click', () => { openSheet(lexSheet); loadLexicon(); });

/* ---- History: the last readings, kept in this browser ------------------- */

// IndexedDB, per viewer like the preferences: the desktop window's profile, or
// each LAN browser's own. A reading is stored with its audio, so playing it
// back never asks the backend. Without storage (a private window, blocked site
// data) history is simply off.
const HISTORY_MAX = 20;
const HISTORY_MIN_SECONDS = 1;   // a reading stopped sooner is not worth a row
let dbOpening = null;

function historyDb() {
  if (!dbOpening) {
    dbOpening = new Promise((resolve, reject) => {
      const req = indexedDB.open('voice-tts', 1);
      req.onupgradeneeded = () => {
        req.result.createObjectStore('readings', { keyPath: 'id', autoIncrement: true });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }).catch(() => null);
  }
  return dbOpening;
}

// Run `fn(store)` in one transaction; resolves with what `fn` returned once
// the transaction commits, or `fallback` if there is no storage or it fails.
async function historyTx(mode, fn, fallback) {
  const db = await historyDb();
  if (!db) return fallback;
  return new Promise((resolve) => {
    let result = fallback;
    try {
      const t = db.transaction('readings', mode);
      const req = fn(t.objectStore('readings'));
      if (req) req.onsuccess = () => { result = req.result; };
      t.oncomplete = () => resolve(result);
      t.onerror = t.onabort = () => resolve(fallback);
    } catch {
      resolve(fallback);
    }
  });
}

// Newest first, without the audio: the list needs only what it shows.
function historyList() {
  return historyDb().then((db) => new Promise((resolve) => {
    if (!db) { resolve([]); return; }
    const out = [];
    try {
      const req = db.transaction('readings').objectStore('readings').openCursor(null, 'prev');
      req.onsuccess = () => {
        const cursor = req.result;
        if (!cursor) { resolve(out); return; }
        const { audio: _, ...meta } = cursor.value;
        out.push(meta);
        cursor.continue();
      };
      req.onerror = () => resolve(out);
    } catch {
      resolve(out);
    }
  }));
}

async function historyAdd(record) {
  await historyTx('readwrite', (s) => s.add(record));
  // Keys grow with time, so the oldest are the smallest.
  const keys = await historyTx('readonly', (s) => s.getAllKeys(), []);
  const extra = keys.slice(0, Math.max(0, keys.length - HISTORY_MAX));
  if (extra.length) await historyTx('readwrite', (s) => { for (const k of extra) s.delete(k); });
}

const historyGet = (id) => historyTx('readonly', (s) => s.get(id), null);
const historyDelete = (id) => historyTx('readwrite', (s) => s.delete(id));
const historyClear = () => historyTx('readwrite', (s) => s.clear());

// Keep the tape that just ended - once, and never one that came from here.
function remember() {
  if (tape.saved || !tape.length || tape.length < tape.rate * HISTORY_MIN_SECONDS) return;
  tape.saved = true;
  historyAdd({
    at: Date.now(),
    text: tape.source,
    voice: tape.voice,
    speed: tape.speed,
    pronunciation: tape.pronunciation,
    rate: tape.rate,
    length: tape.length,
    complete: tape.complete,
    first: tape.first,
    sentences: tape.sentences,
    segments: tape.segments.map(({ i, start, end }) => ({ i, start, end })),
    audio: new Blob(tape.chunks),
  }).then(() => { if (histSheet.open) renderHistory(); });
}

// Put a stored reading back: its text and settings on screen, its audio on the
// tape, playing from the start - the backend is not asked.
async function loadHistory(id) {
  const rec = await historyGet(id);
  if (!rec) { renderHistory(); return; }
  stop();
  els.text.value = rec.text;
  setSpeed(rec.speed);
  setPronunciation(rec.pronunciation);
  pickVoice(rec.voice);
  savePrefs();
  renderCount();
  saveDraft();
  const pcm = new Int16Array(await rec.audio.arrayBuffer());
  resetTape(readingKey(), rec.rate);
  appendTape(pcm);
  // What it holds is all there is to it: playable as it is, kept as it was.
  Object.assign(tape, { complete: true, saved: true, first: rec.first, source: rec.text,
    sentences: rec.sentences, segments: rec.segments });
  buildReader();
  await audio().resume();
  play(0);
}

function fmtWhen(ms) {
  const d = new Date(ms);
  const two = (n) => String(n).padStart(2, '0');
  return `${two(d.getDate())}/${two(d.getMonth() + 1)} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

async function renderHistory() {
  const items = await historyList();
  const list = els.histList;
  list.replaceChildren();
  els.histClear.disabled = !items.length;
  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'lex-empty';
    empty.textContent = 'Chưa có lần đọc nào. Mỗi lần đọc xong được giữ ở đây, tối đa '
      + `${HISTORY_MAX} lần gần nhất.`;
    list.append(empty);
    return;
  }
  for (const rec of items) {
    const row = document.createElement('div');
    row.className = 'hist-item';
    row.tabIndex = 0;
    row.setAttribute('role', 'button');
    const snippet = document.createElement('span');
    snippet.className = 'hist-item__text';
    snippet.textContent = rec.text.trim().replace(/\s+/g, ' ');
    const meta = document.createElement('span');
    meta.className = 'hist-item__meta';
    const parts = [fmtWhen(rec.at), rec.voice, `${rec.speed}×`];
    if (rec.pronunciation === 'special') parts.push('Đặc biệt');
    parts.push(fmt(rec.length / rec.rate));
    if (!rec.complete || rec.first > 0) parts.push('một phần');
    meta.textContent = parts.join(' · ');
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'link link--danger';
    del.textContent = 'Xoá';
    del.addEventListener('click', async (e) => {
      e.stopPropagation();
      await historyDelete(rec.id);
      renderHistory();
    });
    const open = () => { closeSheet(histSheet); loadHistory(rec.id); };
    row.addEventListener('click', open);
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    row.append(snippet, meta, del);
    list.append(row);
  }
}

els.histBtn.addEventListener('click', () => { openSheet(histSheet); renderHistory(); });
els.histClear.addEventListener('click', async () => { await historyClear(); renderHistory(); });

/* ---- Opening a file: picked, Ctrl+O, or dropped on the window ---------- */

const MAX_FILE_BYTES = 4 * 1024 * 1024;   // far past 20 000 characters of text

async function openFile(file) {
  if (!file) return;
  if (!ready) return;
  if (els.text.readOnly) { setStatus('error', 'Dừng đọc trước khi mở file'); return; }
  if (file.size > MAX_FILE_BYTES) { setStatus('error', `${file.name} quá lớn để mở`); return; }
  let value;
  try {
    value = VoiceText.decodeFile(new Uint8Array(await file.arrayBuffer()), file.name);
  } catch (err) {
    setStatus('error', err.message || `Không đọc được ${file.name}`);
    return;
  }
  const max = els.text.maxLength > 0 ? els.text.maxLength : Infinity;
  const cut = value.length > max;
  els.text.value = cut ? value.slice(0, max) : value;
  renderCount();
  saveDraft();
  render();
  setStatus('ready', cut ? `Đã mở ${file.name} - chỉ giữ ${max} ký tự đầu`
    : `Đã mở ${file.name}`);
}

els.openBtn.addEventListener('click', () => els.fileInput.click());
els.fileInput.addEventListener('change', () => {
  openFile(els.fileInput.files[0]);
  els.fileInput.value = '';   // picking the same file again still opens it
});

// Without these, a file dropped anywhere makes the web view navigate to it.
const carriesFile = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
addEventListener('dragover', (e) => {
  if (!carriesFile(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = els.text.readOnly ? 'none' : 'copy';
  els.card.dataset.drop = '1';
});
addEventListener('dragleave', (e) => { if (!e.relatedTarget) els.card.dataset.drop = '0'; });
addEventListener('drop', (e) => {
  if (!carriesFile(e)) return;
  e.preventDefault();
  els.card.dataset.drop = '0';
  openFile(e.dataTransfer.files[0]);
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
  // Escape closes an open sheet first; only with none open does it stop.
  if (e.key === 'Escape') {
    if (activeSheet) closeSheet();
    else if (!els.stopBtn.disabled) stop();
  }
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
  // A draft kept from before may be longer than this server takes.
  if (els.text.value.length > info.maxChars) els.text.value = els.text.value.slice(0, info.maxChars);
  defaultVoice = info.default;
  ready = true;
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
