// autocut editor — interfaccia locale (nessuna build: ES modules nel browser).
// Tutti i tempi interni sono ms sull'asse della camera (come in timeline.json).

const $ = (sel, el = document) => el.querySelector(sel);
const video = $("#video");
const PAD = 12; // px a sinistra dello 0 nella timeline
const FPS_STEP = 1000 / 30;

const S = {
  data: null,
  tl: null,
  words: [],
  wordById: new Map(),
  chunks: [],
  eff: [],
  decisions: [],
  groups: [],
  axisStart: 0,
  axisEnd: 0,
  mode: "edited",
  pps: 20,
  fitPps: 20,
  selected: null,
  filter: "all",
  leftTab: "media",
  rightTab: "ai",
  wave: null,
  stopAt: null,
  aiKind: "video",
  aiFrame: null,
  aiStatus: null,
  suggestions: null,
  suggestAt: null,
  suggesting: false,
  pollTimer: null,
  brand: null,
  brandKey: null,
  look: null,
  lookKey: "null",
  phrases: [],
  thumbW: 40,
  lastChunk: -1,
  lastWord: -1,
  dragging: false,
};

// --- util --------------------------------------------------------------------

function clock(ms, cents = true) {
  const neg = ms < 0;
  ms = Math.abs(ms);
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const c = Math.floor((ms % 1000) / 10);
  const base = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return (neg ? "-" : "") + (cents ? `${base}.${String(c).padStart(2, "0")}` : base);
}
const secs = (ms) => `${(ms / 1000).toFixed(2).replace(".", ",")} s`;
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast on" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 2200);
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* vuoto */ }
    throw new Error(msg);
  }
  return res.json();
}

async function mutate(path, body, okMsg) {
  const st = $("#save-state");
  st.textContent = "Salvo…";
  st.classList.add("busy");
  try {
    apply(await api(path, body));
    st.textContent = "Salvato";
    if (okMsg) toast(okMsg);
  } catch (e) {
    st.textContent = "Errore";
    toast(e.message, true);
  } finally {
    st.classList.remove("busy");
  }
}

// --- tempo e riproduzione ----------------------------------------------------

const nowMs = () => S.axisStart + video.currentTime * 1000;

function seekMs(ms) {
  ms = Math.max(S.axisStart, Math.min(S.axisEnd, ms));
  video.currentTime = (ms - S.axisStart) / 1000;
  updateClock(ms);
}

function rangeIndexAt(ms) {
  const e = S.eff;
  let lo = 0, hi = e.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (ms < e[mid].start_ms) hi = mid - 1;
    else if (ms >= e[mid].end_ms) lo = mid + 1;
    else return mid;
  }
  return -1;
}

function editedAt(ms) {
  let t = 0;
  for (const r of S.eff) {
    if (r.end_ms <= ms) { if (r.state === "keep") t += r.end_ms - r.start_ms; }
    else { if (r.state === "keep" && ms > r.start_ms) t += ms - r.start_ms; break; }
  }
  return t;
}

function keptTotal() {
  return S.eff.reduce((a, r) => a + (r.state === "keep" ? r.end_ms - r.start_ms : 0), 0);
}

function togglePlay() {
  if (video.paused) {
    S.stopAt = null;
    if (nowMs() >= S.axisEnd - 30) seekMs(S.axisStart);
    video.play();
  } else video.pause();
}

function playWindow(start, end) {
  S.stopAt = end;
  seekMs(start);
  video.play();
}

function tick() {
  const cur = nowMs();
  if (!video.paused) {
    if (S.mode === "edited") {
      let i = rangeIndexAt(cur);
      if (i >= 0 && S.eff[i].state === "remove") {
        while (i + 1 < S.eff.length && S.eff[i + 1].state === "remove") i++;
        const end = S.eff[i].end_ms;
        if (end >= S.axisEnd - 5) video.pause();
        else seekMs(end + 1);
      }
    }
    if (S.stopAt !== null && cur >= S.stopAt) { video.pause(); S.stopAt = null; }
    followPlayhead(cur);
  }
  updatePlayhead(cur);
  updateClock(cur);
  updateCaption(cur);
  updateLowerThird(cur);
  updateLook(cur);
  updatePopups(cur);
  requestAnimationFrame(tick);
}

// --- brand pack ----------------------------------------------------------------

// Parole che non diventano mai la parola chiave evidenziata.
const STOPWORDS = new Set(
  ("il lo la i gli le un uno una di a da in con su per tra fra e ed o ma che chi cui non è era sono " +
   "ho hai ha abbiamo avete hanno mi ti si ci vi ne del dello della dei degli delle al allo alla ai " +
   "agli alle dal dalla dai nel nello nella nei nelle sul sulla sui questo questa questi quello quella " +
   "io tu lui lei noi voi loro mio mia miei tuo tua suo sua come cosa più anche poi già qui lì così " +
   "molto tutto tutti fare fatto essere stato sempre quando dove perché proprio ancora allora quindi " +
   "vuole voglio vuoi volete vogliono posso puoi può possiamo devo deve dobbiamo dire detto faccio " +
   "fanno vado andare provare proverò sapete sapere vedere guardare mettere prendere stesso stessa " +
   "abbastanza veramente davvero praticamente semplicemente comunque insomma diciamo conseguenza " +
   "eh ok the and a of to is it you").split(" "),
);

function emphasisIndex(words) {
  let best = -1, score = 0;
  words.forEach((w, i) => {
    const clean = w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
    if (!clean || STOPWORDS.has(clean)) return;
    const s = /\p{N}/u.test(clean) ? 100 : clean.length;
    if (s > score) { score = s; best = i; }
  });
  // meglio nessuna evidenziazione che una parola debole: numeri sempre, altrimenti >= 6 lettere
  return score >= 6 ? best : -1;
}

function styleFor(brand) {
  if (!brand) return null;
  return S.portrait ? brand.captions.vertical : brand.captions.horizontal;
}

function captionHTML(chunk) {
  const style = styleFor(S.brand);
  if ((!style && !S.look) || chunk.event) return esc(chunk.text);
  const words = chunk.text.split(/\s+/);
  let idx, block;
  if (S.look) {
    const e = S.look.captions.emphasis;
    idx = e ? emphasisIndex(words) : -1;
    block = Boolean(e && e.layout === "line");
  } else {
    idx = style.emphasis && style.emphasis.rule !== "none" ? emphasisIndex(words) : -1;
    block = style.emphasis && style.emphasis.scale >= 1.4;
  }
  return words.map((w, i) => i === idx
    ? `<span class="emph${block ? " block" : ""}">${esc(w)}</span>`
    : esc(w)).join(" ");
}

function fontStack(brand, key, fallback) {
  const f = brand?.fonts?.[key];
  return f ? `"${f.family}", ${fallback}` : fallback;
}

function applyBrand(brand) {
  S.brand = brand;
  S.brandKey = brand?.id ?? "";
  const frame = $("#frame");
  // font da Google Fonts (o locali in futuro)
  let link = $("#brand-fonts");
  if (brand?.google_fonts_url) {
    if (!link) {
      link = document.createElement("link");
      link.id = "brand-fonts";
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    link.href = brand.google_fonts_url;
  } else if (link) link.remove();

  frame.classList.toggle("branded", Boolean(brand));
  const cap = $("#caption");
  cap.className = "caption" + ($("#btn-cc").classList.contains("on") ? "" : " off");
  const style = styleFor(brand);
  if (brand && style) {
    const pal = brand.palette;
    const caseMap = { sentence: "none", upper: "uppercase", lower: "lowercase" };
    const vars = {
      "--cap-font": fontStack(brand, style.font, "system-ui, sans-serif"),
      "--cap-weight": String(style.weight),
      "--cap-color": pal[style.color] ?? "#fff",
      "--cap-case": caseMap[style.case] ?? "none",
      "--cap-bottom": `${style.bottom_pct}%`,
      "--emph-font": fontStack(brand, style.emphasis?.font ?? style.font, "Georgia, serif"),
      "--emph-style": style.emphasis?.italic ? "italic" : "normal",
      "--emph-weight": String(style.emphasis?.weight ?? style.weight),
      "--emph-color": pal[style.emphasis?.color ?? style.color] ?? "#fff",
      "--emph-scale": String(style.emphasis?.scale ?? 1),
      "--lt-name-font": fontStack(brand, brand.lower_third?.name_font ?? "sans", "system-ui, sans-serif"),
      "--lt-role-font": fontStack(brand, brand.lower_third?.role_font ?? "sans", "system-ui, sans-serif"),
      "--lt-accent": pal.accent,
      "--lt-role-color": pal.muted,
      "--lt-radius": `${Math.round(brand.graphics.card_radius_px / 2)}px`,
      "--lt-bg": brand.graphics.glass ? `${pal.surface}b3` : pal.surface,
      "--lt-border": `${pal.accent}55`,
      "--lt-glow": brand.graphics.glow === "none" ? "none" : `0 0 24px ${pal[brand.graphics.glow] ?? pal.accent}55`,
    };
    Object.entries(vars).forEach(([k, v]) => frame.style.setProperty(k, v));
    cap.classList.add(`shadow-${style.shadow}`);
  }
  const lt = $("#lower-third");
  lt.querySelector(".lt-name").textContent = brand?.lower_third?.name ?? "";
  lt.querySelector(".lt-role").textContent = brand?.lower_third?.role ?? "";

  const limits = style
    ? { words: style.max_words, chars: style.max_chars }
    : CHUNK_LIMITS[S.portrait ? "portrait" : "landscape"];
  S.chunks = buildChunks(S.words, limits);
  S.lastChunk = -1;
  fitFrame();
  renderTextTrack();
}

// --- preset di stile (look brand × stile, risolto dal server) --------------------------

// Inizio di ogni frase (dopo . ? ! o una pausa lunga): lì cambia il punch-in "phrase_alternate".
function phraseStarts(words) {
  const out = [];
  let prev = null;
  for (const w of words) {
    if (w.kind !== "word") continue;
    if (!prev || /[.?!]$/.test(prev.text) || w.start_ms - prev.end_ms > 700) out.push(w.start_ms);
    prev = w;
  }
  return out;
}

// Righe dell'hook con il ruolo (come render/preview.py: hook_lines): kicker, big, sub.
function hookLines(text) {
  const raw = String(text).split(/\||\n/).map((x) => x.trim()).filter(Boolean);
  const marked = raw.findIndex((x) => x.length > 2 && x.startsWith("*") && x.endsWith("*"));
  const big = marked >= 0 ? marked : raw.length === 1 ? 0 : 1;
  return raw.map((x, i) => ({
    text: i === big ? x.replace(/^\*|\*$/g, "").trim() : x,
    role: i === big ? "big" : i < big ? "kicker" : "sub",
  }));
}

function applyLook(look) {
  S.look = look;
  const frame = $("#frame");
  let link = $("#style-fonts");
  if (look?.fonts_url) {
    if (!link) {
      link = document.createElement("link");
      link.id = "style-fonts";
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    link.href = look.fonts_url;
  } else if (link) link.remove();
  frame.classList.toggle("styled", Boolean(look));
  frame.classList.toggle("stroked", Boolean(look && look.captions.stroke_px > 0));
  frame.classList.toggle("punch-smooth", Boolean(look && look.pacing.punch_in.ease_ms > 0));
  video.style.filter = look ? look.grade.css_filter : "";
  video.style.transform = "";
  const v = look?.grade.vignette ?? 0;
  $("#vignette").style.background = v > 0
    ? `radial-gradient(ellipse at 50% 42%, transparent 48%, rgba(0,0,0,${(0.85 * v).toFixed(2)}) 100%)` : "";
  if (look) {
    const c = look.captions;
    const caseMap = { sentence: "none", upper: "uppercase", lower: "lowercase" };
    const vars = {
      "--cap-font": `"${c.font}", system-ui, sans-serif`,
      "--cap-weight": String(c.weight),
      "--cap-case": caseMap[c.case] ?? "none",
      "--cap-bottom": `${c.bottom_pct}%`,
    };
    if (c.emphasis) {
      Object.assign(vars, {
        "--emph-font": c.emphasis.font ? `"${c.emphasis.font}", Georgia, serif` : vars["--cap-font"],
        "--emph-style": c.emphasis.italic ? "italic" : "normal",
        "--emph-weight": String(c.emphasis.weight ?? c.weight),
        "--emph-color": c.emphasis.color,
        "--emph-scale": String(c.emphasis.scale),
      });
    }
    if (look.hook) {
      const h = look.hook;
      Object.assign(vars, {
        "--hook-font": `"${h.font}", system-ui, sans-serif`,
        "--hook-big-font": `"${h.big_font}", system-ui, sans-serif`,
        "--hook-weight": String(h.weight),
        "--hook-big-weight": String(h.big_weight),
        "--hook-kicker": String(h.kicker_ratio),
        "--hook-sub": String(h.sub_ratio),
        "--hook-stroke-color": h.stroke_color,
        "--hook-big-stroke-color": h.big_stroke_color,
        "--hook-case": h.case === "upper" ? "uppercase" : "none",
      });
    }
    Object.entries(vars).forEach(([k, val]) => frame.style.setProperty(k, val));
    S.chunks = buildChunks(S.words, { words: c.max_words, chars: c.max_chars });
  }
  const hook = $("#hook");
  hook.innerHTML = look?.hook ? hookLines(S.data?.hook ?? "").map((l) =>
    `<span class="line ${l.role}" style="color:${look.hook.colors[l.role]}">${esc(l.text)}</span>`).join("") : "";
  S.phrases = phraseStarts(S.words);
  S.lastChunk = -1;
  fitFrame();
  renderTextTrack();
}

function updateLook(cur) {
  const look = S.look;
  if (!look) return;
  const pi = look.pacing.punch_in;
  let scale = 1;
  if (pi.enabled) {
    let i = -1;
    if (pi.mode === "cut_alternate") {
      // zoom secco a ogni taglio: conta i tratti tenuti prima di adesso
      for (const r of S.eff) { if (r.start_ms > cur) break; if (r.state === "keep") i++; }
    } else {
      for (let k = 0; k < S.phrases.length && S.phrases[k] <= cur; k++) i = k;
    }
    scale = i % 2 === 1 ? pi.scale : 1;
  }
  const tf = scale === 1 ? "" : `scale(${scale})`;
  if (video.style.transform !== tf) video.style.transform = tf;
  const hook = $("#hook");
  const t = S.mode === "edited" ? editedAt(cur) : cur - S.axisStart;
  const hooking = Boolean(look.hook && hook.innerHTML && t < look.hook.duration_ms);
  hook.classList.toggle("on", hooking);
  $("#frame").classList.toggle("hooking", hooking); // l'hook è la copertina: niente sottotitoli
}

function renderStyleSelect() {
  const sel = $("#style-select");
  const opts = [`<option value="">Nessuno</option>`]
    .concat((S.data.styles ?? []).map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`));
  sel.innerHTML = opts.join("");
  sel.value = S.look?.style ?? "";
}

function updateLowerThird(cur) {
  const lt = S.brand?.lower_third;
  const el = $("#lower-third");
  if (!lt || !lt.enabled) { el.classList.remove("on"); return; }
  const t = S.mode === "edited" ? editedAt(cur) : cur - S.axisStart;
  el.classList.toggle("on", t >= lt.show_ms[0] && t <= lt.show_ms[1]);
}

function renderBrandSelect() {
  const sel = $("#brand-select");
  const opts = [`<option value="">Nessuno</option>`]
    .concat(S.data.brands.map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`));
  sel.innerHTML = opts.join("");
  sel.value = S.brandKey ?? "";
}

function updateClock(cur) {
  const edited = S.mode === "edited";
  $("#tc-now").textContent = clock(edited ? editedAt(cur) : cur - S.axisStart);
  $("#tc-total").textContent = clock(edited ? keptTotal() : S.axisEnd - S.axisStart);
  $("#tc-mode").textContent = edited ? "montato" : "raw";
  const i = rangeIndexAt(cur);
  $("#cut-flag").classList.toggle("on", video.paused && i >= 0 && S.eff[i].state === "remove");
}

function updateCaption(cur) {
  let idx = -1;
  for (let i = 0; i < S.chunks.length; i++) {
    const c = S.chunks[i];
    if (cur >= c.start && cur < c.end + 250) { idx = i; break; }
    if (c.start > cur) break;
  }
  if (idx !== S.lastChunk) {
    S.lastChunk = idx;
    const capEl = $("#caption");
    capEl.innerHTML = idx >= 0 ? captionHTML(S.chunks[idx]) : "";
    if (S.look) {
      const colors = S.look.captions.colors;
      capEl.style.color = idx >= 0 ? colors[idx % colors.length] : "";
      const anim = S.look.captions.animation;
      capEl.classList.remove("anim-pop", "anim-blur_in");
      if (idx >= 0 && anim !== "none") { void capEl.offsetWidth; capEl.classList.add(`anim-${anim}`); }
    } else capEl.style.color = "";
    document.querySelectorAll(".chunk.now").forEach((n) => n.classList.remove("now"));
    if (idx >= 0) document.querySelector(`.chunk[data-i="${idx}"]`)?.classList.add("now");
  }
  if (S.leftTab === "subs") {
    let w = -1;
    for (let i = 0; i < S.words.length; i++) {
      if (cur >= S.words[i].start_ms && cur < S.words[i].end_ms + 120) { w = i; break; }
      if (S.words[i].start_ms > cur) break;
    }
    if (w !== S.lastWord) {
      document.querySelectorAll(".transcript .w.now").forEach((n) => n.classList.remove("now"));
      if (w >= 0) document.querySelector(`.transcript .w[data-i="${w}"]`)?.classList.add("now");
      S.lastWord = w;
    }
  }
}

// --- dati ----------------------------------------------------------------------

// Verticale: frasi brevi (max 4 parole / 24 caratteri) per stare in 2 righe dentro l'area
// sicura. Orizzontale: fino a 8 parole / 42 caratteri (standard sottotitoli su 2 righe).
const CHUNK_LIMITS = { portrait: { words: 4, chars: 24 }, landscape: { words: 8, chars: 42 } };

function buildChunks(words, limits) {
  const out = [];
  let cur = null;
  for (const w of words) {
    const gapBreak = cur && w.start_ms - cur.end > 350;
    const full = cur && (cur.n >= limits.words || cur.text.length + 1 + w.text.length > limits.chars);
    const punct = cur && /[.?!,]$/.test(cur.last) && cur.n >= 2;
    if (!cur || gapBreak || full || punct || w.kind === "audio_event" || cur.event) {
      cur = { start: w.start_ms, end: w.end_ms, text: w.text, n: 1, last: w.text, event: w.kind === "audio_event" };
      out.push(cur);
    } else {
      cur.end = w.end_ms;
      cur.text += " " + w.text;
      cur.n += 1;
      cur.last = w.text;
    }
  }
  return out;
}

function isCut(ms) {
  const i = rangeIndexAt(ms);
  return i >= 0 && S.eff[i].state === "remove";
}

function apply(data) {
  const first = S.data === null;
  S.data = data;
  S.tl = data.timeline;
  S.eff = data.effective;
  S.decisions = data.decisions;
  S.groups = data.groups;
  if (first) {
    S.words = S.tl.words;
    S.words.forEach((w) => S.wordById.set(w.id, w));
    const v = S.tl.sources.camera.video;
    S.portrait = v.display_height >= v.display_width;
    S.chunks = buildChunks(S.words, CHUNK_LIMITS[S.portrait ? "portrait" : "landscape"]);
    S.axisStart = data.media.offset_ms;
    S.axisEnd = data.media.offset_ms + data.media.duration_ms;
    S.thumbW = Math.max(28, Math.round(52 * (v.display_width / v.display_height)));
  }
  const lookKey = JSON.stringify([data.style ?? null, data.hook ?? null]);
  if ((data.brand?.id ?? "") !== S.brandKey || lookKey !== S.lookKey) {
    applyBrand(data.brand);
    applyLook(data.style ?? null);
    S.lookKey = lookKey;
  } else S.brand = data.brand;
  renderBrandSelect();
  renderStyleSelect();
  $("#project-title").textContent = data.project;
  $("#player-name").textContent = S.tl.sources.camera.file_name;
  $("#btn-undo-top").disabled = !data.summary.can_undo;
  $("#tl-undo").disabled = !data.summary.can_undo;
  const todo = S.decisions.filter((d) => !d.reviewed).length;
  $("#ai-count").textContent = todo ? String(todo) : "";
  const popTodo = (data.popups ?? []).filter((p) => p.status === "proposed").length;
  $("#pop-count").textContent = popTodo ? String(popTodo) : "";
  $("#popup-layer").dataset.key = "";
  renderStats();
  renderRanges();
  renderTextTrack();
  renderLeft();
  const typing = ["boost-prompt", "pop-prompt"].includes(document.activeElement?.id);
  if (!typing) renderRight();
  updateToggle();
  managePolling();
}

// Finché una richiesta AI è in lavorazione, aggiorna lo stato ogni 4 s.
function managePolling() {
  const running = (S.data?.ai_requests ?? []).some((r) => r.status === "running")
    || S.data?.popup_job?.status === "running";
  if (running && !S.pollTimer) {
    S.pollTimer = setInterval(async () => {
      try { apply(await api("/api/project")); } catch { /* riprova al prossimo giro */ }
    }, 4000);
  } else if (!running && S.pollTimer) {
    clearInterval(S.pollTimer);
    S.pollTimer = null;
  }
}

async function loadAiStatus(refresh = false) {
  try {
    S.aiStatus = await api(`/api/ai-status${refresh ? "?refresh=true" : ""}`);
  } catch (e) {
    S.aiStatus = { claude: false, higgsfield: "error", server: "higgsfield", error: e.message };
  }
  if (S.rightTab === "boost") renderRight();
}

// --- timeline --------------------------------------------------------------------

const xOf = (ms) => PAD + ((ms - S.axisStart) / 1000) * S.pps;
const msOf = (x) => S.axisStart + ((x - PAD) / S.pps) * 1000;

function contentWidth() {
  return Math.ceil(((S.axisEnd - S.axisStart) / 1000) * S.pps) + PAD * 2;
}

function renderTimeline() {
  const w = contentWidth();
  $("#tl-content").style.width = `${w}px`;
  $("#filmstrip").style.width = `${w - PAD * 2}px`;
  $("#filmstrip").style.left = `${PAD}px`;
  renderRuler();
  renderTextTrack();
  renderFilmstrip();
  renderWave();
  renderRanges();
  updatePlayhead(nowMs());
}

function renderRuler() {
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find((s) => s * S.pps >= 70) ?? 600;
  const dur = (S.axisEnd - S.axisStart) / 1000;
  const parts = [];
  const minor = step / 5;
  for (let t = 0; t <= dur + 1e-6; t += minor) {
    const major = Math.abs(t / step - Math.round(t / step)) < 1e-6;
    const x = PAD + t * S.pps;
    parts.push(`<div class="tick${major ? " major" : ""}" style="left:${x}px"></div>`);
    if (major) parts.push(`<div class="tick-label" style="left:${x}px">${clock(S.axisStart + t * 1000 - S.axisStart, step < 1)}</div>`);
  }
  $("#ruler").innerHTML = parts.join("");
}

function renderTextTrack() {
  if (!S.chunks.length) return;
  const parts = S.chunks.map((c, i) => {
    const left = xOf(c.start);
    const width = Math.max(4, xOf(c.end) - left - 1);
    const mid = (c.start + c.end) / 2;
    const cls = ["chunk", c.event ? "event" : "", isCut(mid) ? "cut" : "", i === S.lastChunk ? "now" : ""].join(" ");
    return `<div class="${cls}" data-i="${i}" style="left:${left}px;width:${width}px" title="${esc(c.text)}">${width > 22 ? esc(c.text) : ""}</div>`;
  });
  $("#track-text").innerHTML = parts.join("");
}

function renderFilmstrip() {
  const strip = $("#filmstrip");
  const scroll = $("#tl-scroll");
  const m = S.data.media;
  if (!m.thumb_count) return;
  const from = Math.max(0, scroll.scrollLeft - PAD - scroll.clientWidth);
  const to = scroll.scrollLeft + scroll.clientWidth * 2;
  const total = contentWidth() - PAD * 2;
  const first = Math.floor(from / S.thumbW);
  const last = Math.min(Math.ceil(total / S.thumbW), Math.ceil(to / S.thumbW));
  const parts = [];
  for (let j = first; j < last; j++) {
    const x = j * S.thumbW;
    const tRel = ((x + S.thumbW / 2) / S.pps) * 1000;
    const idx = Math.min(m.thumb_count, Math.floor(tRel / m.thumb_interval_ms) + 1);
    parts.push(`<img src="/media/thumbs/${idx}.jpg" style="left:${x}px;width:${S.thumbW}px" alt="">`);
  }
  strip.innerHTML = parts.join("");
}

function renderWave() {
  const cv = $("#wave");
  const w = contentWidth() - PAD * 2;
  const pxW = Math.min(w, 30000);
  cv.style.left = `${PAD}px`;
  cv.style.width = `${w}px`;
  cv.width = pxW;
  cv.height = 44;
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (!S.wave) return;
  const peaks = S.wave.peaks;
  const bucket = S.wave.bucket_ms;
  const msPerPx = (S.axisEnd - S.axisStart) / pxW;
  ctx.fillStyle = "#33c7c2";
  for (let x = 0; x < pxW; x++) {
    const a = Math.floor((x * msPerPx) / bucket);
    const b = Math.max(a + 1, Math.floor(((x + 1) * msPerPx) / bucket));
    let p = 0;
    for (let k = a; k < b && k < peaks.length; k++) p = Math.max(p, peaks[k]);
    const h = Math.max(1, (p / 100) * (cv.height - 4));
    ctx.fillRect(x, (cv.height - h) / 2, 1, h);
  }
}

function decisionForRange(r) {
  if (r.origin === "take") {
    const g = S.groups.find((g) => g.takes.some((t) => t.id === r.source_id));
    return g ? g.id : null;
  }
  return S.decisions.some((d) => d.id === r.source_id) ? r.source_id : null;
}

function renderRanges() {
  if (!S.data) return;
  const file = S.tl.sources.camera.file_name;
  const parts = S.eff.map((r, i) => {
    const left = xOf(r.start_ms);
    const width = Math.max(2, xOf(r.end_ms) - left);
    const dur = r.end_ms - r.start_ms;
    const dec = decisionForRange(r);
    const sel = dec && dec === S.selected ? " sel" : "";
    if (r.state === "keep") {
      const restored = r.origin === "override";
      const cls = restored ? "rng restored" : "rng keep";
      const lbl = restored
        ? (width > 50 ? `<span class="lbl">↺ tenuta</span>` : "")
        : (width > 70 ? `<span class="lbl">${esc(file)} · ${clock(dur)}</span>` : "");
      return `<div class="${cls}${sel}" data-r="${i}" data-dec="${dec ?? ""}" style="left:${left}px;width:${width}px">${lbl}</div>`;
    }
    const extra = r.origin === "override" ? " override" : r.origin === "take" ? " take" : "";
    const lbl = width > 40 ? `<span class="lbl">✂ ${(dur / 1000).toFixed(1)}s</span>` : "";
    return `<div class="rng remove${extra}${sel}" data-r="${i}" data-dec="${dec ?? ""}" style="left:${left}px;width:${width}px" title="Parte tolta: ${secs(dur)}">${lbl}</div>`;
  });
  $("#ranges").innerHTML = parts.join("");
}

function updatePlayhead(cur) {
  $("#playhead").style.transform = `translateX(${xOf(cur)}px)`;
}

function followPlayhead(cur) {
  const sc = $("#tl-scroll");
  const x = xOf(cur);
  if (x < sc.scrollLeft + 40 || x > sc.scrollLeft + sc.clientWidth - 80) {
    sc.scrollLeft = Math.max(0, x - sc.clientWidth * 0.3);
  }
}

function renderStats() {
  const s = S.data.summary;
  const removed = s.raw_ms - s.kept_ms;
  $("#tl-stats").innerHTML =
    `raw <b>${clock(s.raw_ms)}</b> → montato <b>${clock(s.kept_ms)}</b> · tolti ${secs(removed)} ` +
    `(${Math.round((100 * removed) / Math.max(1, s.raw_ms))}%)`;
}

// zoom: slider logaritmico tra "adatta" e 400 px/s
function setZoomFromSlider() {
  const v = Number($("#zoom").value) / 1000;
  const min = S.fitPps, max = Math.max(400, S.fitPps * 2);
  zoomTo(min * Math.pow(max / min, v));
}
function sliderFromPps() {
  const min = S.fitPps, max = Math.max(400, S.fitPps * 2);
  $("#zoom").value = String(Math.round((1000 * Math.log(S.pps / min)) / Math.log(max / min)));
}
function zoomTo(pps, anchorMs = nowMs()) {
  const sc = $("#tl-scroll");
  const anchorX = xOf(anchorMs) - sc.scrollLeft;
  S.pps = Math.max(S.fitPps, Math.min(Math.max(400, S.fitPps * 2), pps));
  renderTimeline();
  sc.scrollLeft = Math.max(0, xOf(anchorMs) - anchorX);
  sliderFromPps();
  renderFilmstrip();
}
function fitZoom() {
  const sc = $("#tl-scroll");
  S.fitPps = Math.max(1, (sc.clientWidth - PAD * 2 - 8) / ((S.axisEnd - S.axisStart) / 1000));
  S.pps = S.fitPps;
  renderTimeline();
  sc.scrollLeft = 0;
  sliderFromPps();
}

// --- selezione e decisioni --------------------------------------------------

function select(id, { seek = true, scrollCard = true } = {}) {
  S.selected = id;
  const d = S.decisions.find((x) => x.id === id);
  if (d && seek) seekMs(d.start_ms);
  renderRanges();
  updateToggle();
  if (S.rightTab !== "ai") setRightTab("ai");
  else renderRight();
  if (scrollCard) document.querySelector(`.card[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
}

function updateToggle() {
  const btn = $("#tl-toggle");
  const d = S.decisions.find((x) => x.id === S.selected);
  btn.disabled = !d;
  $("#tl-toggle-label").textContent = !d ? "Togli / Ripristina" : d.effective === "remove" ? "Ripristina" : "Togli";
}

const flip = (id) => mutate("/api/decision", { id, action: "flip" });
const accept = (id) => mutate("/api/decision", { id, action: "accept" }, "Proposta approvata");
const reset = (id) => mutate("/api/decision", { id, action: "reset" }, "Tornato alla proposta");
const undo = () => mutate("/api/undo", {}, "Annullato");

function gapWords(id) {
  const m = /^gap:(.+?)-(.+)$/.exec(id);
  if (!m) return [null, null];
  return [S.wordById.get(m[1]) ?? null, S.wordById.get(m[2]) ?? null];
}

function commentFor(d) {
  if (d.type === "speech") {
    return d.effective === "remove"
      ? "Tratto di parlato che hai deciso di togliere."
      : "Tratto di parlato.";
  }
  const [a, b] = gapWords(d.id);
  const gap = d.data?.gap_ms ?? d.end_ms - d.start_ms;
  const removed = d.end_ms - d.start_ms;
  const margin = d.data?.margin_ms ?? 150;
  const dead = (d.data?.dead_events ?? []).map((e) => `[${e.tag}]`);
  let text;
  if (!a && !b) text = `Nel tratto non c'è parlato: tolgo tutto (${secs(removed)}).`;
  else if (!a) text = `Silenzio di ${secs(gap)} prima della prima parola «${esc(b.text)}». Tolgo ${secs(removed)} e lascio ${margin} ms prima della voce.`;
  else if (!b) text = `Silenzio di ${secs(gap)} dopo l'ultima parola «${esc(a.text)}». Tolgo ${secs(removed)} lasciando ${margin} ms di coda.`;
  else text = `Pausa di ${secs(gap)} tra «${esc(a.text)}» e «${esc(b.text)}». Tolgo ${secs(removed)} e lascio ${margin} ms per lato, così le parole restano intere.`;
  if (dead.length) text += ` Dentro c'è ${dead.join(", ")}: lo considero tempo morto.`;
  return text;
}

// --- pannello destro ---------------------------------------------------------

const ICON_CUT = `<svg viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/></svg>`;
const ICON_KEEP = `<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>`;
const ICON_PLAY = `<svg viewBox="0 0 24 24"><path d="m7 4 13 8-13 8z"/></svg>`;
const ICON_OK = `<svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg>`;

function setRightTab(tab) {
  S.rightTab = tab;
  document.querySelectorAll("#right-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.rtab === tab));
  if (tab === "boost") {
    captureFrame();
    if (!S.aiStatus) loadAiStatus();
  }
  renderRight();
}

function renderRight() {
  if (!S.data) return;
  const body = $("#right-body");
  if (S.rightTab === "ai") body.innerHTML = renderAiTab();
  else if (S.rightTab === "popups") body.innerHTML = renderPopupsTab();
  else if (S.rightTab === "boost") body.innerHTML = renderBoostTab();
  else body.innerHTML = renderDetailsTab();
}

function renderAiTab() {
  const s = S.data.summary;
  const total = S.decisions.length;
  const done = S.decisions.filter((d) => d.reviewed).length;
  const changed = S.decisions.filter((d) => d.overridden).length;
  const pct = total ? Math.round((100 * done) / total) : 100;
  const removed = s.raw_ms - s.kept_ms;
  let list = S.decisions;
  if (S.filter === "todo") list = list.filter((d) => !d.reviewed);
  if (S.filter === "changed") list = list.filter((d) => d.overridden);

  const cards = list.map((d) => {
    const isRemove = d.effective === "remove";
    const badges = [];
    if (d.overridden) badges.push(`<span class="badge kept">${isRemove ? "Tolta da te" : "Tenuta da te"}</span>`);
    else badges.push(`<span class="badge cut">Proposta: togli</span>`);
    if (d.reviewed && !d.overridden) badges.push(`<span class="badge ok">✓ Approvata</span>`);
    const actions = d.overridden
      ? `<button class="act" data-act="reset" data-id="${esc(d.id)}">${ICON_KEEP}Torna alla proposta</button>`
      : `<button class="act yes" data-act="accept" data-id="${esc(d.id)}">${ICON_OK}Approva</button>
         <button class="act no" data-act="flip" data-id="${esc(d.id)}">${ICON_KEEP}Rifiuta, tieni</button>`;
    return `
      <div class="card${d.id === S.selected ? " sel" : ""}${d.reviewed ? " done" : ""}" data-id="${esc(d.id)}">
        <div class="card-head">
          <span class="card-icon${isRemove ? "" : " kept"}">${isRemove ? ICON_CUT : ICON_KEEP}</span>
          <span class="card-title">${esc(d.label)}</span>
          <span class="badge">${secs(d.end_ms - d.start_ms)}</span>
          <span class="card-time">${clock(d.start_ms - S.axisStart)} → ${clock(d.end_ms - S.axisStart)}</span>
        </div>
        <div class="comment">
          <span class="ai-dot">AI</span>
          <div>${commentFor(d)}<div class="why">${esc(d.reason)}</div></div>
        </div>
        <div class="card-actions">
          ${badges.join("")}
          <span style="flex:1"></span>
          <button class="act" data-act="listen" data-id="${esc(d.id)}" title="Ascolta 2 s prima e dopo">${ICON_PLAY}Ascolta</button>
          ${actions}
        </div>
      </div>`;
  });

  const orphans = S.data.orphans.map((o) => `
      <div class="card"><div class="card-head"><span class="card-icon kept">${ICON_KEEP}</span>
      <span class="card-title">Scelta orfana</span><span class="card-time">${esc(o.target.id)}</span></div>
      <div class="comment"><span class="ai-dot">!</span><div>Questa tua scelta non corrisponde più a una proposta
      (es. hai cambiato la soglia): non viene applicata.<div class="why">${esc(o.snapshot?.reason ?? "")}</div></div></div></div>`).join("");

  const groups = S.groups.length
    ? S.groups.map(renderGroup).join("")
    : `<div class="info">Le <b>ripetizioni</b> (stessa frase detta più volte, false partenze) arrivano con il
       prossimo passo del motore. Qui vedrai le prese di ogni gruppo con la proposta e potrai scegliere quale tenere.</div>`;

  return `
    <div class="summary">
      <div class="big">${clock(s.raw_ms)}<span class="arrow">→</span>${clock(s.kept_ms)}</div>
      <div class="sub">tolti ${secs(removed)} (${Math.round((100 * removed) / Math.max(1, s.raw_ms))}%) · profilo
        ${esc(S.tl.settings.profile)}, soglia ${S.tl.settings.pauses.threshold_ms} ms, margine ${S.tl.settings.pauses.margin_ms} ms</div>
      <div class="progress"><div style="width:${pct}%"></div></div>
      <div class="row"><span class="sub">${done}/${total} rivedute · ${changed} cambiate da te</span>
        ${done < total ? `<button class="act primary" data-act="accept-all">${ICON_OK}Approva le restanti</button>` : ""}</div>
    </div>
    <div class="filters">
      <button data-filter="all" class="${S.filter === "all" ? "on" : ""}">Tutte ${total}</button>
      <button data-filter="todo" class="${S.filter === "todo" ? "on" : ""}">Da rivedere ${total - done}</button>
      <button data-filter="changed" class="${S.filter === "changed" ? "on" : ""}">Cambiate ${changed}</button>
    </div>
    ${orphans}
    ${cards.join("") || `<div class="placeholder">Niente qui.</div>`}
    <div class="section-title" style="margin-top:16px">Ripetizioni</div>
    ${groups}
    <div class="history"><span>Cronologia: ${S.data.summary.history} modifiche</span>
      <button class="act" data-act="undo" ${S.data.summary.can_undo ? "" : "disabled"}>Annulla ultima</button></div>`;
}

function renderGroup(g) {
  const takes = g.takes.map((t) => `
    <label class="req" style="grid-template-columns:20px 1fr;cursor:pointer">
      <input type="radio" name="g-${esc(g.id)}" data-group="${esc(g.id)}" value="${esc(t.id)}" ${g.chosen === t.id ? "checked" : ""}>
      <div><div class="p">${esc(t.text)}</div><div class="m">${clock(t.start_ms - S.axisStart)} · ${t.status === "complete" ? "completa" : "falsa partenza"} · somiglianza ${Math.round(t.similarity_to_compared * 100)}%</div></div>
    </label>`).join("");
  return `<div class="card" data-id="${esc(g.id)}"><div class="card-head"><span class="card-title">Ripetizione</span>
    <span class="card-time">${g.takes.length} prese</span></div>
    <div class="comment"><span class="ai-dot">AI</span><div>${esc(g.proposal?.reason ?? g.reason ?? "")}</div></div>${takes}</div>`;
}

// --- pop-up ----------------------------------------------------------------------------

const POP_KIND = { image: "Immagine", emoji: "Emoji", text: "Testo" };
const POP_ORIGIN = { auto: "automatico", ai: "Claude", user: "tu" };
const POP_STATUS = { proposed: "Proposto", approved: "✓ Approvato", rejected: "Rifiutato" };
const POP_PLACE = { side: "di lato", above: "sopra il testo", pair: "coppia ai lati", center: "grande al centro",
  top: "in alto", behind: "dietro di te" };
const POP_SIZE = { small: "piccolo", medium: "medio", large: "grande" };

function popupThumb(p) {
  if (p.image_url) return `<img class="pop-thumb" src="${esc(p.image_url)}" alt="">`;
  if (p.kind === "emoji") return `<span class="pop-thumb emoji">${esc(p.emoji)}</span>`;
  if (p.kind === "image") return `<span class="pop-thumb wait" title="immagine da generare">🖼</span>`;
  return `<span class="pop-thumb text">Aa</span>`;
}

function renderPopupsTab() {
  const items = S.data.popups ?? [];
  const styleName = S.look?.style_name ?? "nessuno stile (logica premium)";
  const job = S.data.popup_job ?? {};
  const busyText = S.popBusy || (job.status === "running"
    ? `Claude sta proponendo da solo i pop-up per lo stile ${S.look?.style_name ?? ""}: pochi e solo nei punti giusti…` : "");
  const busy = busyText
    ? `<div class="ideas-box"><div class="spinner-row"><span class="spinner"></span>${esc(busyText)}</div></div>` : "";
  const note = S.popMessage ?? (job.status === "done" || job.status === "error" ? job.message : null);
  const msg = note ? `<div class="comment"><span class="ai-dot">AI</span><div>${esc(note)}</div></div>` : "";
  const list = items.map((p) => {
    const toGen = p.kind === "image" && !p.image_url;
    const genState = p.image_status === "running" ? "Generazione in corso…" : p.image_status === "error" ? "Errore nella generazione" : "";
    return `
      <div class="card pop${p.status === "rejected" ? " rejected" : ""}" data-pop="${esc(p.id)}">
        <div class="card-head">
          ${popupThumb(p)}
          <span class="card-title">${esc(p.title || p.emoji || POP_KIND[p.kind])}</span>
          <span class="badge">${esc(POP_KIND[p.kind])} · ${esc(POP_PLACE[p.placement])} · ${esc(POP_SIZE[p.size])}</span>
          <span class="card-time">${clock(p.at_ms - S.axisStart)} · ${secs(p.duration_ms)}</span>
        </div>
        <div class="comment"><span class="ai-dot">${p.origin === "user" ? "Tu" : "AI"}</span>
          <div>${esc(p.reason || "—")}<div class="why">da ${esc(POP_ORIGIN[p.origin])}${p.image_prompt && toGen ? ` · prompt: ${esc(p.image_prompt)}` : ""}${genState ? ` · ${genState}` : ""}</div></div></div>
        <div class="card-actions">
          <span class="badge${p.status === "approved" ? " ok" : ""}">${POP_STATUS[p.status]}</span>
          <button class="act${p.sound ? " on" : ""}" data-act="pop-sound" data-id="${esc(p.id)}" title="Suono quando compare">${p.sound ? "🔊" : "🔇"}</button>
          <span style="flex:1"></span>
          <button class="act" data-act="pop-go" data-id="${esc(p.id)}">${ICON_PLAY}Vai</button>
          ${toGen && p.image_prompt && p.image_status !== "running"
            ? `<button class="act ai" data-act="pop-gen" data-id="${esc(p.id)}" title="Usa crediti Higgsfield">✦ Genera</button>` : ""}
          ${p.status === "proposed"
            ? `<button class="act yes" data-act="pop-approve" data-id="${esc(p.id)}">${ICON_OK}Approva</button>
               <button class="act no" data-act="pop-reject" data-id="${esc(p.id)}">Rifiuta</button>`
            : `<button class="act" data-act="pop-reset" data-id="${esc(p.id)}">${ICON_KEEP}Rimetti proposta</button>`}
          <button class="act no" data-act="pop-delete" data-id="${esc(p.id)}" title="Elimina">✕</button>
        </div>
      </div>`;
  }).join("");
  return `
    <div class="summary">
      <div class="sub">Stile: <b>${esc(styleName)}</b>. Claude li propone da solo quando scegli lo stile, con
        parsimonia; tu tieni solo quelli giusti. Compaiono quando dici la parola; il suono solo su quelli con 🔊.</div>
      <div class="row" style="margin-top:8px">
        <button class="act primary" data-act="pop-suggest" ${busyText ? "disabled" : ""}>✦ Analizza di nuovo il parlato</button>
      </div>
    </div>
    <div class="boost-box">
      <textarea id="pop-prompt" rows="3" placeholder="Chiedi a Claude, es. «qui metti un'emoji 💸 invece dell'immagine», «togli il pop-up a 0:41», «aggiungine uno quando dico Italia»"></textarea>
      <div class="row"><span class="sub">Riferito al punto ${clock(nowMs() - S.axisStart)}</span>
        <button class="act ai" data-act="pop-chat" ${S.popBusy ? "disabled" : ""}>Invia</button></div>
    </div>
    ${busy}${msg}
    <div class="section-title" style="margin-top:12px">Pop-up (${items.length})</div>
    ${list || `<div class="placeholder">Nessun pop-up: premi «Analizza il parlato» o chiedi a Claude.</div>`}`;
}

async function popupAi(path, body, busyText) {
  video.pause();
  S.popBusy = busyText;
  S.popMessage = null;
  renderRight();
  try {
    const res = await api(path, body);
    apply(res);
    S.popMessage = res.popup_message ?? null;
  } catch (err) {
    toast(err.message, true);
  } finally {
    S.popBusy = null;
    renderRight();
  }
}

// Pop-up nell'anteprima: compaiono sopra il video come nel render (vetro o sticker).
function updatePopups(cur) {
  const layer = $("#popup-layer");
  const items = (S.data?.popups ?? []).filter((p) => p.status !== "rejected"
    && cur >= p.at_ms && cur < p.at_ms + p.duration_ms && !(p.kind === "image" && !p.image_url));
  const key = items.map((p) => p.id).join(",");
  if (layer.dataset.key === key) return;
  layer.dataset.key = key;
  const kind = S.look?.cards.kind ?? "liquid_glass";
  layer.innerHTML = items.map((p) => `
    <div class="pop-el ${kind === "sticker" ? "sticker" : "glass"} at-${p.placement} sz-${p.size} sd-${p.side} k-${p.image_url ? "image" : p.kind}"
      ${p.placement === "behind" ? 'title="nel render passa dietro di te"' : ""}>
      ${p.image_url ? `<img src="${esc(p.image_url)}" alt="">`
        : p.emoji ? (p.placement === "pair"
          ? [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(p.emoji)].map((g) => g.segment).filter((g) => g.trim())
              .map((g, i) => `<div class="em pair-${i}">${esc(g)}</div>`).join("")
          : `<div class="em">${esc(p.emoji)}</div>`) : ""}
      ${p.title && p.placement !== "pair" ? `<div class="t">${esc(p.title)}</div>` : ""}
    </div>`).join("");
}

const IDEAS = [
  "B-roll ultra realistico che illustra quello che dico qui",
  "Sfondo cinematografico dietro di me, stessa luce",
  "Titolo animato 3D con la parola chiave",
  "Transizione cinematografica verso la scena successiva",
];

const KIND_NAME = { video: "Video AI", image: "Immagine", graphic: "Grafica" };
const STATUS_NAME = {
  queued: "In coda",
  running: "In lavorazione…",
  done: "Pronto",
  error: "Errore",
  interrupted: "Interrotta",
};

function renderAiStatus() {
  const st = S.aiStatus;
  if (!st) return `<div class="ai-status wait"><span class="dot"></span>Controllo il collegamento con Claude e Higgsfield…</div>`;
  if (!st.claude) {
    return `<div class="ai-status bad"><span class="dot"></span><div><b>Claude Code non trovato.</b>
      Serve il comando <code>claude</code> nel PATH per suggerire e generare.</div></div>`;
  }
  if (st.higgsfield === "connected") {
    const credits = st.credits != null ? ` · ${st.credits} crediti${st.plan ? ` (${esc(st.plan)})` : ""}` : "";
    return `<div class="ai-status ok"><span class="dot"></span>Claude + Higgsfield collegati${credits}
      <button class="link" data-act="recheck">ricontrolla</button></div>`;
  }
  const fix = {
    missing: ["la CLI non è installata", "npm i -g @higgsfield/cli"],
    needs_auth: ["serve l'accesso", "higgsfield auth login"],
    no_workspace: ["manca il workspace", "higgsfield workspace list   →   higgsfield workspace set <id>"],
  }[st.higgsfield] ?? ["non risponde", "higgsfield account status"];
  return `<div class="ai-status warn"><span class="dot"></span><div><b>Higgsfield: ${fix[0]}.</b>
    I suggerimenti funzionano già; per generare, in un terminale: <code>${esc(fix[1])}</code>
    <button class="link" data-act="recheck">ricontrolla</button></div></div>`;
}

function renderSuggestions() {
  if (S.suggesting) {
    return `<div class="ideas-box"><div class="spinner-row"><span class="spinner"></span>Claude sta guardando il frame e
      ascoltando cosa dici in quel punto…</div></div>`;
  }
  if (!S.suggestions) return "";
  return `<div class="ideas-box"><div class="section-title">Idee di Claude per ${clock(S.suggestAt - S.axisStart)}</div>
    ${S.suggestions.map((s, i) => `
      <div class="idea">
        <div class="idea-head"><span class="badge">${esc(KIND_NAME[s.kind] ?? s.kind)}</span><b>${esc(s.title)}</b></div>
        <div class="idea-why">${esc(s.why)}</div>
        <div class="idea-prompt">${esc(s.prompt)}</div>
        <div class="card-actions"><span style="flex:1"></span>
          <button class="act" data-act="use-idea" data-i="${i}">Modifica</button>
          <button class="act ai" data-act="gen-idea" data-i="${i}">✦ Genera</button></div>
      </div>`).join("")}</div>`;
}

function renderRequest(r) {
  const local = r.result?.local ?? [];
  const preview = local.length
    ? local.map((u) => /\.(mp4|webm|mov)$/i.test(u)
        ? `<video src="${esc(u)}" controls muted loop playsinline class="result"></video>`
        : `<a href="${esc(u)}" target="_blank"><img src="${esc(u)}" class="result" alt=""></a>`).join("")
    : "";
  const retry = ["error", "interrupted", "queued"].includes(r.status)
    ? `<button class="link" data-act="retry-ai" data-id="${esc(r.id)}">${r.status === "queued" ? "esegui" : "riprova"}</button>` : "";
  return `
    <div class="req ${esc(r.status)}"><img src="${esc(r.frame)}" alt="">
      <div><div class="p">${esc(r.prompt)}</div>
        <div class="m"><span class="status ${esc(r.status)}">${r.status === "running" ? '<span class="spinner sm"></span>' : ""}${esc(STATUS_NAME[r.status] ?? r.status)}</span>
          ${esc(KIND_NAME[r.kind] ?? r.kind)} · al frame ${clock(r.time_ms - S.axisStart)} ${retry}</div>
        ${r.note ? `<div class="m">${esc(r.note)}</div>` : ""}
        ${r.result?.model ? `<div class="m">modello: ${esc(r.result.model)}</div>` : ""}
      </div>
      ${preview ? `<div class="result-box">${preview}</div>` : ""}
    </div>`;
}

function renderBoostTab() {
  const cur = nowMs();
  const reqs = S.data.ai_requests.slice().reverse().map(renderRequest).join("");
  const canGenerate = S.aiStatus?.claude && S.aiStatus?.higgsfield === "connected";
  return `
    <div class="boost-hero">
      <h3><span class="spark">✦</span> Potenzia con Higgsfield</h3>
      <p>Claude guarda il frame, ascolta cosa dici in quel punto e ti propone video, immagini o grafiche AI.
         Quando invii, esegue subito la generazione con Higgsfield.</p>
    </div>
    ${renderAiStatus()}
    <div class="frame-pick">
      <img id="boost-frame" src="${S.aiFrame ?? ""}" alt="Frame corrente">
      <div><div class="card-title">Frame a ${clock(cur - S.axisStart)}</div>
        <div class="sub" style="color:var(--muted);font-size:12px">Sposta la testina per cambiare frame.</div>
        <div class="card-actions" style="margin-top:8px">
          <button class="act" data-act="refresh-frame">Usa il frame corrente</button>
          <button class="act ai" data-act="suggest" ${S.suggesting || !S.aiStatus?.claude ? "disabled" : ""}>✦ Suggerisci</button>
        </div></div>
    </div>
    ${renderSuggestions()}
    <div class="kinds">
      <button data-kind="video" class="${S.aiKind === "video" ? "on" : ""}">Video AI</button>
      <button data-kind="image" class="${S.aiKind === "image" ? "on" : ""}">Immagine</button>
      <button data-kind="graphic" class="${S.aiKind === "graphic" ? "on" : ""}">Grafica</button>
    </div>
    <textarea id="boost-prompt" placeholder="Es. qui dico che voglio andare in Thailandia: mostra una spiaggia al tramonto, ripresa da drone, ultra realistica, 3 secondi"></textarea>
    <div class="ideas">${IDEAS.map((i) => `<button data-idea="${esc(i)}">${esc(i)}</button>`).join("")}</div>
    <button class="act ai" data-act="send-ai" style="width:100%;justify-content:center;height:34px">
      ✦ ${canGenerate ? "Invia a Claude + Higgsfield" : "Metti in coda (Higgsfield non ancora collegato)"}</button>
    <div class="section-title" style="margin-top:16px">Richieste</div>
    ${reqs || `<div class="placeholder">Nessuna richiesta ancora.</div>`}`;
}

function renderDetailsTab() {
  const c = S.tl.sources.camera;
  const sc = S.tl.sources.screen;
  const st = S.tl.settings;
  return `
    <div class="section-title">Camera</div>
    <div class="kv">
      <span class="k">File</span><code>${esc(c.file_name)}</code>
      <span class="k">Video</span><span>${c.video.display_width}×${c.video.display_height} ${c.video.orientation}, ${c.video.fps} fps ${c.video.fps_mode}, ${esc(c.video.codec)}</span>
      <span class="k">Audio</span><span>${c.audio ? `${esc(c.audio.codec)} ${c.audio.channels} ch, ${c.audio.sample_rate} Hz` : "—"}</span>
      <span class="k">Riconosciuta da</span><span>${S.tl.detection.camera.signals.map((s) => `<span class="tag mute">${esc(s)}</span>`).join(" ")}</span>
    </div>
    <div class="section-title">Schermo</div>
    <div class="kv"><span class="k">File</span><span>${sc ? `<code>${esc(sc.file_name)}</code>` : "nessuno"}</span>
      <span class="k">Sync</span><span>${esc(S.tl.sync.status)}</span></div>
    <div class="section-title">Impostazioni</div>
    <div class="kv">
      <span class="k">Profilo</span><span>${esc(st.profile)} (${esc(st.profile_source)})</span>
      <span class="k">Pause</span><span>soglia ${st.pauses.threshold_ms} ms, margine ${st.pauses.margin_ms} ms</span>
      <span class="k">Trascrizione</span><span>${esc(st.transcription.model)}, ${esc(st.transcription.language)}</span>
      <span class="k">Parole</span><span>${S.words.length}</span>
    </div>
    <div class="section-title">Scorciatoie</div>
    <div class="kv">
      <span class="k"><kbd>Spazio</kbd></span><span>play / pausa</span>
      <span class="k"><kbd>←</kbd> <kbd>→</kbd></span><span>un frame (con <kbd>Maiusc</kbd> 1 s)</span>
      <span class="k"><kbd>Canc</kbd></span><span>togli / ripristina la parte selezionata</span>
      <span class="k"><kbd>Ctrl</kbd>+<kbd>Z</kbd></span><span>annulla</span>
      <span class="k"><kbd>M</kbd></span><span>montato / raw</span>
      <span class="k"><kbd>+</kbd> <kbd>-</kbd></span><span>zoom timeline</span>
    </div>`;
}

function captureFrame() {
  try {
    const cv = document.createElement("canvas");
    const h = 240;
    cv.height = h;
    cv.width = Math.round((h * video.videoWidth) / Math.max(1, video.videoHeight)) || 135;
    cv.getContext("2d").drawImage(video, 0, 0, cv.width, cv.height);
    S.aiFrame = cv.toDataURL("image/jpeg", 0.8);
  } catch { S.aiFrame = null; }
}

// --- pannello sinistro ---------------------------------------------------------

const TOOL_TABS = [
  ["media", "File multimediali", `<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/></svg>`],
  ["brand", "Brand", `<svg viewBox="0 0 24 24"><path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="m3 13 9 5 9-5"/><path d="m3 17.5 9 4.5 9-4.5"/></svg>`],
  ["audio", "Audio", `<svg viewBox="0 0 24 24"><path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/></svg>`],
  ["text", "Testo", `<svg viewBox="0 0 24 24"><path d="M4 7V5h16v2M12 5v14M9 19h6"/></svg>`],
  ["stickers", "Sticker", `<svg viewBox="0 0 24 24"><path d="M15 3H6a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3h7l8-8V6a3 3 0 0 0-3-3h-3z"/><path d="M13 21v-5a3 3 0 0 1 3-3h5"/></svg>`],
  ["effects", "Effetti", `<svg viewBox="0 0 24 24"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/></svg>`],
  ["transitions", "Transizioni", `<svg viewBox="0 0 24 24"><path d="M4 4h7v16H4zM13 4l7 8-7 8"/></svg>`],
  ["subs", "Sottotitoli", `<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 13h4M13 13h4M7 16h10"/></svg>`],
  ["filters", "Filtri", `<svg viewBox="0 0 24 24"><circle cx="9" cy="10" r="5"/><circle cx="15" cy="10" r="5"/><circle cx="12" cy="15" r="5"/></svg>`],
];

function renderToolTabs() {
  $("#tool-tabs").innerHTML = TOOL_TABS.map(([id, label, icon]) =>
    `<button class="tool-tab${S.leftTab === id ? " on" : ""}" data-ltab="${id}">${icon}<span>${label}</span></button>`).join("");
}

function renderLeft() {
  renderToolTabs();
  const box = $("#left-content");
  if (S.leftTab === "media") box.innerHTML = renderMedia();
  else if (S.leftTab === "brand") box.innerHTML = renderBrandPanel();
  else if (S.leftTab === "subs") box.innerHTML = renderTranscript();
  else {
    const label = TOOL_TABS.find((t) => t[0] === S.leftTab)?.[1] ?? "";
    box.innerHTML = `<div class="placeholder">${TOOL_TABS.find((t) => t[0] === S.leftTab)?.[2] ?? ""}
      <b>${esc(label)}</b><br>Arriva con la fase grafica (stili, effetti, Remotion e Higgsfield).</div>`;
  }
  S.lastWord = -1;
}

function renderMedia() {
  const c = S.tl.sources.camera;
  const sc = S.tl.sources.screen;
  const thumb = S.data.media.thumb_count ? `/media/thumbs/1.jpg` : "";
  const card = (src, role, tags) => `
    <div class="media-card">
      <div class="thumb" style="background-image:url('${thumb}')"><span class="dur">${clock(src.duration_ms, false)}</span></div>
      <div><div class="name">${esc(src.file_name)}</div>
        <div class="meta">${src.video.display_width}×${src.video.display_height} · ${src.video.fps} fps</div>
        ${tags}</div>
    </div>`;
  const ignored = S.tl.detection.ignored.length
    ? `<div class="section-title" style="margin-top:14px">Ignorati</div>${S.tl.detection.ignored.map((i) => `<div class="meta" style="color:var(--muted);font-size:12px">${esc(i)}</div>`).join("")}`
    : "";
  return `
    <div class="btn-row"><button class="btn" disabled title="Si importa con: autocut ingest">＋ Importa</button></div>
    <div class="section-title">Nel progetto</div>
    ${card(c, "camera", `<span class="tag">Camera</span><span class="tag">audio di riferimento</span>`)}
    ${sc ? card(sc, "screen", `<span class="tag">Schermo</span><span class="tag mute">audio muto</span>`) : ""}
    ${ignored}
    <div class="info" style="margin-top:14px">I file raw restano dove sono e non vengono mai modificati:
      l'editor usa una copia di anteprima leggera in <code>projects/${esc(S.data.project)}/work/</code>.</div>`;
}

function renderBrandPanel() {
  const list = S.data.brands.map((b) => `
    <div class="brand-card${b.id === S.brandKey ? " on" : ""}" data-brand="${esc(b.id)}">
      <div class="bname">${esc(b.name)}</div>
      ${b.id === S.brandKey ? `<div class="bdesc">${esc(S.brand?.description ?? "")}</div>` : ""}
    </div>`).join("");
  const none = `<div class="brand-card${!S.brandKey ? " on" : ""}" data-brand="">
      <div class="bname">Nessuno</div><div class="bdesc">Anteprima base, senza stile.</div></div>`;
  const b = S.brand;
  if (!b) {
    return `<div class="section-title">Brand pack</div>${list}${none}
      <div class="info">I brand pack sono in <code>brands/&lt;id&gt;/brand.json</code>: palette, font,
      sottotitoli, lower third, grafiche, transizioni e sound. Scegline uno per applicarlo al video.</div>`;
  }
  const style = styleFor(b);
  const swatches = Object.entries(b.palette).map(([k, v]) =>
    `<div class="swatch" style="background:${esc(v)}" title="${esc(k)} ${esc(v)}"><span>${esc(k.replace("_", " "))}</span></div>`).join("");
  const fonts = Object.entries(b.fonts).map(([k, f]) => `
    <div class="font-row"><span class="sample" style="font-family:'${esc(f.family)}';${f.italic ? "font-style:italic;" : ""}font-weight:${f.weights.at(-1)}">${esc(f.family)}</span>
      <span class="fmeta">${esc(k)} · ${esc(f.source)}${f.license ? ` · ${esc(f.license)}` : ""}</span></div>`).join("");
  const sampleWords = ["Quanti", "clienti", "hai", "chiuso?"];
  const sample = sampleWords.map((w, i) => i === 1
    ? `<span style="font-family:${esc(fontStack(b, style.emphasis?.font ?? style.font, "serif"))};font-style:${style.emphasis?.italic ? "italic" : "normal"};color:${esc(b.palette[style.emphasis?.color ?? "highlight"])};font-size:${style.emphasis?.scale ?? 1}em;display:block">${w}</span>`
    : w).join(" ");
  const transitions = b.transitions.presets.map((t) =>
    `<span class="tag mute" title="${t.sound ? `suono: ${esc(t.sound)}` : "senza suono"}">${esc(t.label)}${t.duration_frames ? ` · ${t.duration_frames}f` : ""}</span>`).join("");
  const levels = Object.entries(b.sound.levels_db).map(([k, v]) => `<span class="tag mute">${esc(k)} ${v} dB</span>`).join("");
  const refs = b.reference_images.slice(0, 16).map((u) => `<img src="${esc(u)}" loading="lazy" alt="">`).join("");
  return `
    <div class="section-title">Brand pack</div>${list}${none}
    <div class="section-title" style="margin-top:14px">Palette</div><div class="swatches" style="margin-bottom:18px">${swatches}</div>
    <div class="section-title">Font</div>${fonts}
    <div class="section-title" style="margin-top:14px">Sottotitoli (${S.portrait ? "verticale" : "orizzontale"})</div>
    <div class="cap-sample" style="font-family:${esc(fontStack(b, style.font, "sans-serif"))};font-weight:${style.weight};color:${esc(b.palette[style.color])};font-size:18px">${sample}</div>
    <div class="chips" style="margin-bottom:12px"><span class="tag mute">max ${style.max_words} parole</span>
      <span class="tag mute">${style.size_pct}% del lato</span><span class="tag mute">a ${style.bottom_pct}% dal fondo</span>
      <span class="tag mute">parola chiave: numeri o la più lunga</span></div>
    ${b.lower_third ? `<div class="section-title">Lower third</div><div class="meta" style="margin-bottom:12px">${esc(b.lower_third.name)} — ${esc(b.lower_third.role)} · ${(b.lower_third.show_ms[0] / 1000).toFixed(1)}–${(b.lower_third.show_ms[1] / 1000).toFixed(1)} s</div>` : ""}
    <div class="section-title">Transizioni</div><div class="chips" style="margin-bottom:12px">${transitions}</div>
    <div class="section-title">Sound</div><div class="chips" style="margin-bottom:6px">${levels}</div>
    <div class="meta" style="color:var(--muted);font-size:12px;margin-bottom:12px">Regole: skill <code>${esc(b.sound.skill ?? "—")}</code>,
      libreria <code>${esc(b.sound.library)}</code>${b.sound.music_under_graphics ? "" : " · niente musica sotto le grafiche"}.</div>
    <div class="section-title">Stile grafico</div><div class="meta" style="color:var(--muted);font-size:12px;margin-bottom:10px">${esc(b.graphics.style)}</div>
    ${refs ? `<div class="refs">${refs}</div>` : ""}`;
}

function renderTranscript() {
  const out = [];
  let prevEnd = null;
  S.words.forEach((w, i) => {
    if (prevEnd !== null) {
      const d = S.decisions.find((x) => x.type === "dead_pause" && x.start_ms >= prevEnd - 200 && x.end_ms <= w.start_ms + 200);
      if (d) out.push(`<span class="gap${d.effective === "keep" ? " kept" : ""}" data-dec="${esc(d.id)}" title="${esc(d.reason)}">✂ ${(d.end_ms - d.start_ms) / 1000 >= 1 ? ((d.end_ms - d.start_ms) / 1000).toFixed(1) : ((d.end_ms - d.start_ms) / 1000).toFixed(2)}s</span>`);
    }
    const mid = (w.start_ms + w.end_ms) / 2;
    const cls = ["w", w.kind === "audio_event" ? "event" : "", isCut(mid) ? "cut" : ""].join(" ");
    out.push(`<span class="${cls}" data-i="${i}" data-t="${w.start_ms}">${esc(w.text)}</span>`);
    prevEnd = w.end_ms;
  });
  return `<div class="section-title">Trascrizione · clicca una parola per andarci</div><div class="transcript">${out.join(" ")}</div>`;
}

// --- eventi --------------------------------------------------------------------

function setMode(mode) {
  S.mode = mode;
  document.querySelectorAll("#mode-toggle button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
}

function fitFrame() {
  const stage = $("#stage");
  const v = S.tl?.sources.camera.video;
  if (!v) return;
  const ar = v.display_width / v.display_height;
  const W = stage.clientWidth - 24, H = stage.clientHeight - 24;
  let w = W, h = W / ar;
  if (h > H) { h = H; w = H * ar; }
  const frame = $("#frame");
  Object.assign(frame.style, { width: `${Math.floor(w)}px`, height: `${Math.floor(h)}px` });
  frame.classList.toggle("portrait", S.portrait);
  frame.classList.toggle("landscape", !S.portrait);
  // senza brand: ~54 px su 1080 di larghezza in verticale; ~49 px su 1080 di altezza in orizzontale
  const style = styleFor(S.brand);
  const pct = S.look ? S.look.captions.size_pct / 100 : style ? style.size_pct / 100 : S.portrait ? 0.05 : 0.045;
  const cap = S.portrait ? w * pct : h * pct;
  frame.style.setProperty("--cap-size", `${cap.toFixed(1)}px`);
  // valori dei preset pensati su 1080 px di larghezza (o altezza in orizzontale)
  const unit = (S.portrait ? w : h) / 1080;
  if (S.look) {
    frame.style.setProperty("--cap-stroke", `${(S.look.captions.stroke_px * unit * 2).toFixed(1)}px`);
    if (S.look.hook) {
      frame.style.setProperty("--hook-size", `${((S.portrait ? w : h) * S.look.hook.size_pct / 100).toFixed(1)}px`);
      frame.style.setProperty("--hook-stroke", `${(S.look.hook.stroke_px * unit * 2).toFixed(1)}px`);
      frame.style.setProperty("--hook-top", `${S.look.hook.center_pct}%`);
    }
  }
  frame.style.setProperty("--lt-size", `${(S.portrait ? w * 0.034 : h * 0.03).toFixed(1)}px`);
}

function jumpCut(dir) {
  const cur = nowMs();
  const cuts = S.eff.filter((r) => r.state === "remove");
  const target = dir > 0
    ? cuts.find((r) => r.start_ms > cur + 50)
    : cuts.slice().reverse().find((r) => r.start_ms < cur - 50);
  if (target) {
    seekMs(target.start_ms);
    const dec = decisionForRange(target);
    if (dec) select(dec, { seek: false });
  }
}

function seekFromEvent(ev) {
  const rect = $("#tl-content").getBoundingClientRect();
  seekMs(msOf(ev.clientX - rect.left));
}

function wireEvents() {
  $("#btn-play").addEventListener("click", togglePlay);
  video.addEventListener("play", () => $("#btn-play").classList.add("playing"));
  video.addEventListener("pause", () => $("#btn-play").classList.remove("playing"));
  $("#btn-prev").addEventListener("click", () => jumpCut(-1));
  $("#btn-next").addEventListener("click", () => jumpCut(1));
  $("#btn-cc").addEventListener("click", (e) => {
    e.currentTarget.classList.toggle("on");
    $("#caption").classList.toggle("off");
  });
  $("#btn-safe").addEventListener("click", (e) => {
    e.currentTarget.classList.toggle("on");
    $("#safe-zone").classList.toggle("on");
  });
  $("#btn-full").addEventListener("click", () => $("#frame").requestFullscreen?.());
  $("#mode-toggle").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (b) setMode(b.dataset.mode);
  });
  $("#btn-undo-top").addEventListener("click", undo);
  $("#tl-undo").addEventListener("click", undo);
  $("#tl-toggle").addEventListener("click", () => S.selected && flip(S.selected));

  $("#zoom").addEventListener("input", setZoomFromSlider);
  $("#zoom-in").addEventListener("click", () => zoomTo(S.pps * 1.5));
  $("#zoom-out").addEventListener("click", () => zoomTo(S.pps / 1.5));
  $("#zoom-fit").addEventListener("click", fitZoom);

  const scroll = $("#tl-scroll");
  let raf = 0;
  scroll.addEventListener("scroll", () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(renderFilmstrip);
  });
  scroll.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const rect = $("#tl-content").getBoundingClientRect();
      zoomTo(S.pps * (e.deltaY < 0 ? 1.15 : 1 / 1.15), msOf(e.clientX - rect.left));
    } else if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      scroll.scrollLeft += e.deltaY;
      e.preventDefault();
    }
  }, { passive: false });

  const content = $("#tl-content");
  content.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    const rng = e.target.closest(".rng[data-dec]");
    const chunk = e.target.closest(".chunk");
    if (rng && rng.dataset.dec) {
      select(rng.dataset.dec, { seek: false });
    } else if (chunk) {
      const c = S.chunks[Number(chunk.dataset.i)];
      seekMs(c.start);
      return;
    }
    S.dragging = true;
    seekFromEvent(e);
  });
  window.addEventListener("mousemove", (e) => { if (S.dragging) seekFromEvent(e); });
  window.addEventListener("mouseup", () => (S.dragging = false));

  $("#right-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-rtab]");
    if (b) setRightTab(b.dataset.rtab);
  });
  $("#right-body").addEventListener("click", onRightClick);
  $("#right-body").addEventListener("change", (e) => {
    const r = e.target.closest("input[data-group]");
    if (r) mutate("/api/group", { id: r.dataset.group, take_id: r.value }, "Presa scelta");
  });

  $("#tool-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-ltab]");
    if (b) { S.leftTab = b.dataset.ltab; renderLeft(); }
  });
  $("#brand-select").addEventListener("change", (e) =>
    mutate("/api/brand", { id: e.target.value || null }, e.target.value ? "Brand applicato" : "Brand rimosso"));
  $("#style-select").addEventListener("change", (e) =>
    mutate("/api/style", { id: e.target.value || null }, e.target.value ? "Stile applicato" : "Stile rimosso"));
  $("#left-content").addEventListener("click", (e) => {
    const card = e.target.closest(".brand-card[data-brand]");
    if (card) {
      const id = card.dataset.brand || null;
      if ((id ?? "") !== S.brandKey) mutate("/api/brand", { id }, id ? "Brand applicato" : "Brand rimosso");
      return;
    }
    const w = e.target.closest(".w[data-t]");
    if (w) { seekMs(Number(w.dataset.t)); return; }
    const g = e.target.closest(".gap[data-dec]");
    if (g) select(g.dataset.dec);
  });

  window.addEventListener("resize", () => { fitFrame(); fitZoom(); });
  window.addEventListener("keydown", onKey);
}

async function onRightClick(e) {
  const filter = e.target.closest("[data-filter]");
  if (filter) { S.filter = filter.dataset.filter; renderRight(); return; }
  const kind = e.target.closest("[data-kind]");
  if (kind) {
    S.aiKind = kind.dataset.kind;
    const prompt = $("#boost-prompt")?.value ?? "";
    renderRight();
    $("#boost-prompt").value = prompt;
    return;
  }
  const idea = e.target.closest("[data-idea]");
  if (idea) { const ta = $("#boost-prompt"); ta.value = idea.dataset.idea; ta.focus(); return; }

  const btn = e.target.closest("[data-act]");
  if (btn) {
    e.stopPropagation();
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    if (act === "accept") accept(id);
    else if (act === "flip") flip(id);
    else if (act === "reset") reset(id);
    else if (act === "undo") undo();
    else if (act === "listen") {
      const d = S.decisions.find((x) => x.id === id);
      select(id, { seek: false, scrollCard: false });
      playWindow(d.start_ms - 2000, d.end_ms + 2000);
    } else if (act === "accept-all") {
      const ids = S.decisions.filter((d) => !d.reviewed && !d.overridden).map((d) => d.id);
      mutate("/api/reviewed", { ids, value: true }, `${ids.length} proposte approvate`);
    } else if (act === "refresh-frame") {
      captureFrame();
      renderRight();
    } else if (act === "send-ai") {
      const prompt = $("#boost-prompt").value.trim();
      if (!prompt) { toast("Scrivi cosa vuoi generare", true); return; }
      video.pause();
      await sendAi(prompt, S.aiKind, Math.round(nowMs()));
      $("#boost-prompt").value = "";
    } else if (act === "suggest") {
      video.pause();
      captureFrame();
      S.suggesting = true;
      S.suggestions = null;
      S.suggestAt = Math.round(nowMs());
      renderRight();
      try {
        const res = await api("/api/ai-suggest", { time_ms: S.suggestAt });
        S.suggestions = res.suggestions;
      } catch (err) {
        toast(`Suggerimenti non disponibili: ${err.message}`, true);
      } finally {
        S.suggesting = false;
        renderRight();
      }
    } else if (act === "use-idea") {
      const s = S.suggestions[Number(btn.dataset.i)];
      S.aiKind = s.kind;
      renderRight();
      const ta = $("#boost-prompt");
      ta.value = s.prompt;
      ta.focus();
    } else if (act === "gen-idea") {
      const s = S.suggestions[Number(btn.dataset.i)];
      await sendAi(s.prompt, s.kind, S.suggestAt);
    } else if (act === "pop-suggest") {
      await popupAi("/api/popups/suggest", {}, "Claude sta leggendo tutto il parlato e sceglie dove servono pop-up…");
    } else if (act === "pop-chat") {
      const prompt = $("#pop-prompt").value.trim();
      if (!prompt) { toast("Scrivi cosa vuoi cambiare", true); return; }
      await popupAi("/api/popups/chat", { prompt, time_ms: Math.round(nowMs()) }, "Claude sta modificando i pop-up…");
    } else if (act?.startsWith("pop-")) {
      const p = (S.data.popups ?? []).find((x) => x.id === id);
      if (!p) return;
      if (act === "pop-go") { seekMs(p.at_ms - 300); return; }
      if (act === "pop-gen") {
        if (!confirm("Generare l'immagine con Higgsfield? Usa crediti (circa 2 per un'immagine).")) return;
        await mutate("/api/popups/generate", { id }, "Immagine in generazione");
        return;
      }
      const map = { "pop-approve": "approve", "pop-reject": "reject", "pop-reset": "reset", "pop-delete": "delete" };
      if (act === "pop-sound") await mutate("/api/popups/item", { id, action: "update", fields: { sound: !p.sound } });
      else if (map[act]) await mutate("/api/popups/item", { id, action: map[act] });
    } else if (act === "retry-ai") {
      await mutate("/api/ai-requests/run", { id }, "Richiesta rimandata a Claude");
    } else if (act === "recheck") {
      S.aiStatus = null;
      renderRight();
      loadAiStatus(true);
    }
    return;
  }
  const card = e.target.closest(".card[data-id]");
  if (card && S.decisions.some((d) => d.id === card.dataset.id)) select(card.dataset.id, { scrollCard: false });
}

async function sendAi(prompt, kind, timeMs) {
  const live = S.aiStatus?.claude && S.aiStatus?.higgsfield === "connected";
  await mutate(
    "/api/ai-requests",
    { time_ms: timeMs, prompt, kind, run: Boolean(live) },
    live ? "Inviata: Claude sta generando con Higgsfield" : "In coda: collega Higgsfield per generarla",
  );
}

function onKey(e) {
  if (e.target.closest("input, textarea")) return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  else if (e.key === "ArrowRight") { e.preventDefault(); video.pause(); seekMs(nowMs() + (e.shiftKey ? 1000 : FPS_STEP)); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); video.pause(); seekMs(nowMs() - (e.shiftKey ? 1000 : FPS_STEP)); }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
  else if (e.key === "Delete" || e.key === "Backspace") { if (S.selected) { e.preventDefault(); flip(S.selected); } }
  else if (e.key.toLowerCase() === "m") setMode(S.mode === "edited" ? "raw" : "edited");
  else if (e.key === "+" || e.key === "=") zoomTo(S.pps * 1.5);
  else if (e.key === "-") zoomTo(S.pps / 1.5);
}

// --- avvio ---------------------------------------------------------------------

async function init() {
  try {
    const data = await api("/api/project");
    apply(data);
    video.src = data.media.video_url;
    S.wave = await (await fetch(data.media.waveform_url)).json();
    wireEvents();
    fitFrame();
    fitZoom();
    $("#loading").classList.add("off");
    requestAnimationFrame(tick);
  } catch (e) {
    $("#loading").textContent = `Errore nel caricare il progetto: ${e.message}`;
  }
}

init();
