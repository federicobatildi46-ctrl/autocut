// autocut editor — interfaccia locale (nessuna build: ES modules nel browser).
// Tutti i tempi interni sono ms sull'asse della camera (come in timeline.json).

import { animCss, animState, wordState } from "/anim.js";

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
  // pannello Testo
  txScope: "all", // all = tutti i sottotitoli | scene = solo la frase corrente
  txSlot: "main", // main = font principale | emph = font della parola chiave
  txChunk: -1, // ultima frase mostrata (anche in pausa tra due frasi)
  txSel: false, // testo selezionato nell'anteprima (riquadro con le maniglie)
  txDrag: null,
  txLive: null, // posizione/rotazione/grandezza mentre trascini, prima di salvare
  txPanel: false, // pannello laterale aperto nello schermo intero
  viewerTab: "text", // text | stickers
  popSel: null, // sticker selezionato nell'anteprima
  stTab: "add", // pannello Sticker: add | edit | list (le schede non spostano la libreria)
  emoMap: new Map(), // emoji -> PNG stile iPhone (library/emoji)
  fxTab: "text", // pannello Effetti: text | stickers | trans
  coverArm: null, // formato in attesa di conferma (Genera costa crediti)
  coverThinking: false,
  hfLogin: false,
  sndSel: null, // suono selezionato (pannello Audio / traccia audio)
  sndDrag: null,
  piece: null, // pezzo selezionato nella traccia video (tagli a mano)
  imgQ: "", // pannello Immagini: richiesta, risultati, opzioni, lavori in corso
  imgRes: null,
  imgShown: "",
  imgBusy: false,
  imgErr: "",
  imgCut: true,
  imgQuality: "fast",
  imgTransp: false,
  imgFree: false,
  imgJobs: {},
  imgRedo: false,
  fxPoint: null, // giunta selezionata
  fxBusy: false,
  fxAll: false,
  fxAuto: {}, // stili per cui Claude ha già proposto in questa sessione
  transTf: "",
  emoCats: [],
  emoCat: 0,
  popLive: null, // sticker mentre lo trascini
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
    const data = await api(path, body);
    apply(data);
    st.textContent = "Salvato";
    if (okMsg) toast(okMsg);
    return data;
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
  ensureAudio();
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
  updateTransitionFx(cur);
  updateLook(cur);
  updatePopups(cur);
  updateCaptionFx(cur);
  updatePopupFx(cur);
  updateSounds(cur);
  updateVfxOverlay(cur);
  updateBroll(cur);
  updateMusic(cur);
  if (S.viewer) updateViewer(cur);
  updateCapSel();
  requestAnimationFrame(tick);
}

// --- visualizzatore a schermo intero -------------------------------------------
// Sposta il fotogramma (video + sottotitoli + hook + pop-up) in un livello che copre
// tutto lo schermo: verticale = telefono, orizzontale = 16:9. Stessa riproduzione.

// Inverso di editedAt: dal tempo del montato al tempo sull'asse camera.
function axisAtEdited(t) {
  let acc = 0;
  for (const r of S.eff) {
    if (r.state !== "keep") continue;
    const len = r.end_ms - r.start_ms;
    if (t <= acc + len) return r.start_ms + Math.max(0, t - acc);
    acc += len;
  }
  return S.axisEnd;
}

function openViewer() {
  if (S.viewer || !S.tl) return;
  S.viewer = true;
  const v = $("#viewer");
  v.hidden = false;
  v.classList.toggle("portrait", S.portrait);
  v.classList.toggle("landscape", !S.portrait);
  $("#viewer-stage").appendChild($("#frame"));
  S.vCutsKey = null;
  fitFrame();
  // schermo intero vero del browser; se non è permesso il livello copre comunque la finestra
  v.requestFullscreen?.().catch(() => {});
}

function closeViewer() {
  if (!S.viewer) return;
  S.viewer = false;
  S.vScrub = null;
  $("#stage").appendChild($("#frame"));
  $("#viewer").hidden = true;
  toggleViewerPanel(false);
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  fitFrame();
}

function viewerSpan() {
  return S.mode === "edited" ? keptTotal() : S.axisEnd - S.axisStart;
}

function viewerPos(cur) {
  return S.mode === "edited" ? editedAt(cur) : cur - S.axisStart;
}

// In Raw le parti tolte si vedono in rosso sulla barra; nel montato non esistono.
function renderViewerCuts() {
  const box = $("#v-cuts");
  S.vCutsKey = { eff: S.eff, mode: S.mode };
  if (S.mode === "edited") { box.innerHTML = ""; return; }
  const span = S.axisEnd - S.axisStart || 1;
  box.innerHTML = S.eff
    .filter((r) => r.state === "remove")
    .map((r) => `<i style="left:${((r.start_ms - S.axisStart) / span) * 100}%;width:${((r.end_ms - r.start_ms) / span) * 100}%"></i>`)
    .join("");
}

function updateViewer(cur) {
  if (!S.vCutsKey || S.vCutsKey.eff !== S.eff || S.vCutsKey.mode !== S.mode) renderViewerCuts();
  const span = viewerSpan();
  const pos = Math.min(span, Math.max(0, viewerPos(cur)));
  const pct = `${(span ? pos / span : 0) * 100}%`;
  $("#v-fill").style.width = pct;
  $("#v-knob").style.left = pct;
  $("#v-now").textContent = clock(pos);
  $("#v-total").textContent = clock(span);
  const mode = $("#v-mode");
  const label = S.mode === "edited" ? "Montato" : "Raw";
  if (mode.textContent !== label) mode.textContent = label;
  $("#v-cc").classList.toggle("on", !$("#caption").classList.contains("off"));
}

function seekFraction(ev) {
  const r = $("#v-seek").getBoundingClientRect();
  return Math.min(1, Math.max(0, (ev.clientX - r.left) / Math.max(1, r.width)));
}

function seekViewerTo(f) {
  const t = f * viewerSpan();
  seekMs(S.mode === "edited" ? axisAtEdited(t) : S.axisStart + t);
}

function wireViewer() {
  const seek = $("#v-seek");
  seek.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    seek.setPointerCapture(e.pointerId);
    S.vScrub = { wasPlaying: !video.paused };
    S.stopAt = null;
    video.pause();
    seek.classList.add("scrubbing");
    seekViewerTo(seekFraction(e));
  });
  seek.addEventListener("pointermove", (e) => {
    const f = seekFraction(e);
    const tip = $("#v-tip");
    tip.textContent = clock(f * viewerSpan());
    tip.style.left = `${f * 100}%`;
    if (S.vScrub) seekViewerTo(f);
  });
  const endScrub = () => {
    if (!S.vScrub) return;
    const resume = S.vScrub.wasPlaying;
    S.vScrub = null;
    seek.classList.remove("scrubbing");
    if (resume) video.play();
  };
  seek.addEventListener("pointerup", endScrub);
  seek.addEventListener("pointercancel", endScrub);

  $("#v-play").addEventListener("click", togglePlay);
  $("#v-close").addEventListener("click", closeViewer);
  $("#v-mode").addEventListener("click", () => setMode(S.mode === "edited" ? "raw" : "edited"));
  $("#v-cc").addEventListener("click", () => $("#btn-cc").click());
  // clic sul video = play/pausa, come sul telefono
  $("#viewer-stage").addEventListener("click", (e) => {
    if (e.target.closest(".viewer-bar, #caption, .cap-sel, .pop-el") || S.txClickGuard) return;
    togglePlay();
  });
  const side = (tab) => toggleViewerPanel(!(S.txPanel && S.viewerTab === tab), tab);
  $("#v-text").addEventListener("click", () => side("text"));
  $("#v-sticker").addEventListener("click", () => side("stickers"));
  $("#v-effects").addEventListener("click", () => side("effects"));
  $("#v-images").addEventListener("click", () => side("images"));
  $("#v-audio").addEventListener("click", () => side("audio"));
  $("#v-vfx").addEventListener("click", () => side("vfx"));
  $("#v-broll").addEventListener("click", () => side("broll"));
  video.addEventListener("play", () => $("#v-play").classList.add("playing"));
  video.addEventListener("pause", () => $("#v-play").classList.remove("playing"));
  // Esc in schermo intero lo chiude il browser: chiudiamo anche il livello
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && S.viewer) closeViewer();
    else if (S.viewer) fitFrame();
  });
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

function captionHTML(chunk, caps = S.look?.captions, text = chunk.text) {
  const style = styleFor(S.brand);
  if ((!style && !caps) || chunk.event) return esc(text);
  const words = text.split(/\s+/).filter(Boolean);
  let idx, block;
  if (caps) {
    const e = caps.emphasis;
    idx = e ? emphasisIndex(words) : -1;
    block = Boolean(e && e.layout === "line");
  } else {
    idx = style.emphasis && style.emphasis.rule !== "none" ? emphasisIndex(words) : -1;
    block = style.emphasis && style.emphasis.scale >= 1.4;
  }
  return words.map((w, i) => i === idx
    ? `<span class="emph cw${block ? " block" : ""}">${esc(w)}</span>`
    : `<span class="cw">${esc(w)}</span>`).join(" ");
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
  const tf = `${scale === 1 ? "" : `scale(${scale}) `}${S.transTf}`.trim();
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
  if (idx !== S.lastChunk || S.repaint) {
    const changed = idx !== S.lastChunk;
    S.repaint = false;
    S.lastChunk = idx;
    paintCaption(idx, changed);
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
      cur = { id: w.id, start: w.start_ms, end: w.end_ms, text: w.text, n: 1, last: w.text, event: w.kind === "audio_event", ws: [w.start_ms] };
      out.push(cur);
    } else {
      cur.ws.push(w.start_ms);
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
  loadTextFonts(data.text?.fonts_url);
  S.repaint = true; // ridisegna la frase con le scelte del pannello Testo (senza animazione)
  $("#project-title").textContent = data.project;
  $("#player-name").textContent = S.tl.sources.camera.file_name;
  $("#btn-undo-top").disabled = !data.summary.can_undo;
  $("#tl-undo").disabled = !data.summary.can_undo;
  $("#btn-redo-top").disabled = !data.summary.can_redo;
  $("#tl-redo").disabled = !data.summary.can_redo;
  if (S.sndSel && !soundItem(S.sndSel)) S.sndSel = null;
  applyVoiceGain();
  const todo = S.decisions.filter((d) => !d.reviewed).length;
  $("#ai-count").textContent = todo ? String(todo) : "";
  const popTodo = (data.popups ?? []).filter((p) => p.status === "proposed").length;
  $("#pop-count").textContent = popTodo ? String(popTodo) : "";
  $("#popup-layer").dataset.key = "";
  renderStats();
  renderRanges();
  renderTextTrack();
  renderAudioTrack();
  renderVfxTrack();
  renderBrollTrack();
  renderVersions();
  renderHeadMute();
  if (BR.sel && !brClip(BR.sel)) BR.sel = null;
  if (BR.selVo && !brVoice(BR.selVo)) BR.selVo = null;
  renderLeft();
  const typing = ["boost-prompt", "pop-prompt"].includes(document.activeElement?.id);
  if (!typing) renderRight();
  updateToggle();
  renderExport();
  managePolling();
}

// Finché una richiesta AI è in lavorazione, aggiorna lo stato ogni 4 s.
function managePolling() {
  const running = (S.data?.ai_requests ?? []).some((r) => r.status === "running")
    || S.data?.popup_job?.status === "running" || S.data?.covers?.job?.status === "running"
    || S.data?.export?.job?.status === "running"
    || (S.data?.vfx?.shots ?? []).some((s) => s.status === "running")
    || S.data?.import?.status === "running"
    || S.data?.music?.job?.status === "running";
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
  if (typeof renderAskSel === "function") renderAskSel(); // selezione di «Chiedi a Claude»
  $("#filmstrip").style.width = `${w - PAD * 2}px`;
  $("#filmstrip").style.left = `${PAD}px`;
  renderRuler();
  renderTextTrack();
  renderFilmstrip();
  renderWave();
  renderRanges();
  renderAudioTrack();
  renderVfxTrack();
  renderBrollTrack();
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
    const own = Boolean(S.data?.text?.scenes?.[c.id]);
    const open = S.leftTab === "text" && S.txScope === "scene" && i === S.txChunk;
    const cls = ["chunk", c.event ? "event" : "", isCut(mid) ? "cut" : "", i === S.lastChunk ? "now" : "", open ? "sel" : "", own ? "own" : ""].join(" ");
    const text = chunkText(c);
    return `<div class="${cls}" data-i="${i}" style="left:${left}px;width:${width}px" title="${esc(text)} · clic per modificarlo">${width > 22 ? esc(text) : ""}</div>`;
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
  const sel = pieceKey(S.piece);
  const parts = visiblePieces().map(({ i, start, end, keep, r }) => {
    const left = xOf(start);
    const width = Math.max(2, xOf(end) - left);
    const dur = end - start;
    const dec = decisionForRange(r);
    const key = `${start}-${end}`;
    const on = (dec && dec === S.selected) || key === sel ? " sel" : "";
    const data = `data-r="${i}" data-dec="${dec ?? ""}" data-piece="${key}"`;
    if (keep) {
      const restored = r.origin === "override";
      const cls = restored ? "rng restored" : "rng keep";
      const lbl = restored
        ? (width > 50 ? `<span class="lbl">↺ tenuta</span>` : "")
        : (width > 70 ? `<span class="lbl">${esc(file)} · ${clock(dur)}</span>` : "");
      return `<div class="${cls}${on}" ${data} style="left:${left}px;width:${width}px">${lbl}</div>`;
    }
    const extra = r.origin === "override" ? " override" : r.origin === "take" ? " take" : r.origin === "manual" ? " manual" : "";
    const lbl = width > 40 ? `<span class="lbl">✂ ${(dur / 1000).toFixed(1)}s</span>` : "";
    return `<div class="rng remove${extra}${on}" ${data} data-manual="${r.origin === "manual" ? 1 : ""}" style="left:${left}px;width:${width}px" title="${r.origin === "manual" ? "Tolto da te: clic e Ripristina per rimetterlo" : "Parte tolta"}: ${secs(dur)}">${lbl}</div>`;
  });
  const marks = (S.data.cuts?.splits ?? []).map((ms) =>
    `<button class="split-mark" data-split="${ms}" style="left:${xOf(ms)}px" title="Divisione a ${showTime(ms)}: clic per toglierla"></button>`);
  $("#ranges").innerHTML = parts.join("") + marks.join("");
  renderTransitionMarks();
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
  S.piece = null;
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
  btn.disabled = !d && !S.piece;
  $("#tl-toggle-label").textContent = S.piece ? (S.piece.manual ? "Ripristina" : "Togli")
    : !d ? "Togli / Ripristina" : d.effective === "remove" ? "Ripristina" : "Togli";
}

const flip = (id) => mutate("/api/decision", { id, action: "flip" });
const accept = (id) => mutate("/api/decision", { id, action: "accept" }, "Proposta approvata");
const reset = (id) => mutate("/api/decision", { id, action: "reset" }, "Tornato alla proposta");
const undo = () => mutate("/api/history/undo", {}, "Annullato");
const redo = () => mutate("/api/history/redo", {}, "Ripetuto");

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
// Emoji come immagini stile iPhone (se la libreria c'è), altrimenti come testo.
const SEG = new Intl.Segmenter(undefined, { granularity: "grapheme" });
const emoKey = (s) => s.replace(/\ufe0f/g, "");
function emojiParts(text) {
  return [...SEG.segment(String(text ?? ""))].map((g) => g.segment).filter((g) => g.trim());
}
function emojiHTML(text, cls = "emo") {
  return emojiParts(text).map((g) => {
    const img = S.emoMap.get(emoKey(g));
    return img ? `<img class="${cls}" src="/media/emoji/${img}" alt="${esc(g)}" draggable="false">` : esc(g);
  }).join("");
}

function popHTML(p, kind) {
  const free = p.placement === "free";
  const layer = p.placement === "behind" ? "person" : p.layer;
  const style = free ? ` style="left:${p.x_pct}%;top:${p.y_pct}%;rotate:${p.rotation}deg;scale:${p.scale}"`
    : p.scale !== 1 ? ` style="scale:${p.scale}"` : "";
  return `
    <div class="pop-el ${kind === "sticker" ? "sticker" : "glass"} at-${p.placement} sz-${p.size} sd-${p.side} k-${p.image_url ? "image" : p.kind} ly-${layer}${p.cutout ? " cutout" : ""}${p.id === S.justAdded ? " just-added" : ""}"
      data-id="${esc(p.id)}"${style}${layer === "person" ? ' title="nel render passa dietro di te"' : ""}>
      ${p.image_url ? `<img src="${esc(p.image_url)}" alt="" draggable="false">`
        : p.emoji ? (p.placement === "pair"
          ? emojiParts(p.emoji).map((g, i) => `<div class="em pair-${i}">${emojiHTML(g)}</div>`).join("")
          : `<div class="em">${emojiHTML(p.emoji)}</div>`) : ""}
      ${p.title && p.placement !== "pair" ? `<div class="t">${esc(p.title)}</div>` : ""}
    </div>`;
}

function updatePopups(cur) {
  const layer = $("#popup-layer");
  const items = (S.data?.popups ?? []).filter((p) => p.status !== "rejected"
    && cur >= p.at_ms && cur < p.at_ms + p.duration_ms && !(p.kind === "image" && !p.image_url));
  const key = items.map((p) => p.id).join(",");
  if (layer.dataset.key === key) return;
  layer.dataset.key = key;
  const kind = S.look?.cards.kind ?? "liquid_glass";
  layer.innerHTML = items.filter((p) => p.layer !== "over_text").map((p) => popHTML(p, kind)).join("");
  $("#popup-over").innerHTML = items.filter((p) => p.layer === "over_text").map((p) => popHTML(p, kind)).join("");
  if (S.popLive) paintPopLive();
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
  ["images", "Immagini", `<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/></svg>`],
  ["broll", "B-roll", `<svg viewBox="0 0 24 24"><rect x="3" y="7" width="13" height="10" rx="2"/><path d="m16 11 5-3v8l-5-3"/><path d="M6 4h7"/></svg>`],
  ["effects", "Effetti", `<svg viewBox="0 0 24 24"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/></svg>`],
  ["transitions", "Transizioni", `<svg viewBox="0 0 24 24"><path d="M4 4h7v16H4zM13 4l7 8-7 8"/></svg>`],
  ["subs", "Sottotitoli", `<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 13h4M13 13h4M7 16h10"/></svg>`],
  ["vfx", "Genera AI", `<svg viewBox="0 0 24 24"><path d="m12 3 1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>`],
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
  else if (["text", "stickers", "images", "broll", "effects", "audio", "transitions", "filters", "vfx"].includes(S.leftTab)) renderTextPanels();
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
    <div class="section-title">Importa un video raw</div>
    ${importHTML()}
    <div class="section-title" style="margin-top:14px">Nel progetto</div>
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
  const stage = S.viewer ? $("#viewer-stage") : $("#stage");
  const v = S.tl?.sources.camera.video;
  if (!v) return;
  const ar = v.display_width / v.display_height;
  const pad = S.viewer ? 48 : 24; // nel visualizzatore c'è la cornice del telefono
  const W = stage.clientWidth - pad, H = stage.clientHeight - pad;
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
    if (S.look.hook) {
      frame.style.setProperty("--hook-size", `${((S.portrait ? w : h) * S.look.hook.size_pct / 100).toFixed(1)}px`);
      frame.style.setProperty("--hook-stroke", `${(S.look.hook.stroke_px * unit * 2).toFixed(1)}px`);
      frame.style.setProperty("--hook-top", `${S.look.hook.center_pct}%`);
    }
  }
  frame.style.setProperty("--lt-size", `${(S.portrait ? w * 0.034 : h * 0.03).toFixed(1)}px`);
  S.repaint = true; // il bordo del testo dipende dalla grandezza del fotogramma
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
  $("#btn-full").addEventListener("click", openViewer);
  $("#stage").addEventListener("dblclick", (e) => { if (!e.target.closest("#caption, .cap-sel, .pop-el")) openViewer(); });
  wireTextPanel($("#left-content"));
  wireTextPanel($("#viewer-panel"));
  wireStickerPanel($("#left-content"));
  wireStickerPanel($("#viewer-panel"));
  wireEffectsPanel($("#left-content"));
  wireEffectsPanel($("#viewer-panel"));
  wireImagesPanel($("#left-content"));
  wireImagesPanel($("#viewer-panel"));
  wireVfxPanel($("#left-content"));
  wireVfxPanel($("#viewer-panel"));
  $("#track-vfx").addEventListener("click", (e) => {
    const b = e.target.closest("[data-vfxblk]");
    if (b) openVfx(b.dataset.vfxblk);
  });
  wireExport();
  wireFiltersPanel($("#left-content"));
  wireAudioPanel($("#left-content"));
  wireAudioPanel($("#viewer-panel"));
  wireMusicPanel($("#left-content"));
  wireMusicPanel($("#viewer-panel"));
  wireBrollPanel($("#left-content"));
  wireBrollPanel($("#viewer-panel"));
  wireBrollTracks();
  wireImport($("#left-content"));
  wireVersions();
  wireTimelineHeads();
  video.addEventListener("play", ensureAudio);
  video.addEventListener("pause", stopSounds);
  $("#tl-content").addEventListener("mousedown", (e) => {
    const m = e.target.closest("[data-fx-point]");
    if (m) { e.stopPropagation(); selectPoint(m.dataset.fxPoint); }
  }, true);
  wireCaptionDrag();
  wireViewer();
  $("#mode-toggle").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (b) setMode(b.dataset.mode);
  });
  $("#btn-undo-top").addEventListener("click", undo);
  $("#tl-undo").addEventListener("click", undo);
  $("#tl-redo").addEventListener("click", redo);
  $("#btn-redo-top").addEventListener("click", redo);
  $("#tl-split").addEventListener("click", splitHere);
  $("#tl-toggle").addEventListener("click", () => { if (S.piece) togglePiece(); else if (S.selected) flip(S.selected); });

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
    const snd = e.target.closest("[data-snd]");
    if (snd) {
      e.preventDefault();
      S.sndDrag = { id: snd.dataset.snd, x0: e.clientX, dx: 0 };
      selectSound(snd.dataset.snd);
      return;
    }
    const mark = e.target.closest("[data-split]");
    if (mark) { mutate("/api/cuts", { action: "unsplit", ms: Number(mark.dataset.split) }, "Divisione tolta"); return; }
    const rng = e.target.closest(".rng");
    const chunk = e.target.closest(".chunk");
    if (rng && rng.dataset.dec) {
      select(rng.dataset.dec, { seek: false });
    } else if (rng && rng.dataset.piece) {
      const [a, b] = rng.dataset.piece.split("-").map(Number);
      selectPiece(a, b, rng.dataset.manual === "1");
    } else if (chunk) {
      openCaptionEditor(Number(chunk.dataset.i));
      return;
    }
    S.dragging = true;
    seekFromEvent(e);
  });
  window.addEventListener("mousemove", (e) => {
    if (S.sndDrag) {
      const d = S.sndDrag;
      d.dx = e.clientX - d.x0;
      // il blocco può essere stato ridisegnato (selezione): lo si ritrova per id
      const el = document.querySelector(`#track-audio [data-snd="${CSS.escape(d.id)}"]`);
      if (el) el.style.translate = `${d.dx}px 0`;
      return;
    }
    if (S.dragging) seekFromEvent(e);
  });
  window.addEventListener("mouseup", () => {
    S.dragging = false;
    const d = S.sndDrag;
    S.sndDrag = null;
    if (d && Math.abs(d.dx) > 3) {
      saveAudio({ target: "sound", item: d.id, fields: { shift_ms: Math.round((d.dx / S.pps) * 1000) } }, "Suono spostato");
    }
  });

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
  if (e.target.closest?.("input, textarea, select")) return;
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); redo(); return; }
  if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); return; }
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveVersion(true); return; } // salva una versione
  if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); splitHere(); return; }
  if (e.key === "Escape" && (S.sndSel || S.piece)) { e.preventDefault(); S.sndSel = null; S.piece = null; renderAudioTrack(); renderRanges(); updateToggle(); renderTextPanels(); return; }
  if (S.sndSel && (e.key === "Delete" || e.key === "Backspace")) {
    e.preventDefault();
    const s = soundItem(S.sndSel);
    if (s) saveAudio(s.origin === "user" ? { target: "remove", item: s.id } : { target: "sound", item: s.id, fields: { muted: !s.own_muted } }, s.origin === "user" ? "Suono eliminato" : s.own_muted ? "Suono riattivato" : "Suono muto");
    return;
  }
  if (S.piece && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); togglePiece(); return; }
  if (e.key === "Escape" && (S.txSel || S.popSel)) { e.preventDefault(); S.txSel = false; S.popSel = null; renderTextPanels(); return; }
  if (S.popSel && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); deletePop(S.popSel); return; }
  if (e.key === "Escape" && S.viewer) { e.preventDefault(); closeViewer(); return; }
  if (e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey) { e.preventDefault(); S.viewer ? closeViewer() : openViewer(); return; }
  if (S.viewer && (e.key === "Delete" || e.key === "Backspace" || e.ctrlKey || e.metaKey)) return; // nel visualizzatore si guarda e basta
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  else if (e.key === "ArrowRight") { e.preventDefault(); video.pause(); seekMs(nowMs() + (e.shiftKey ? 1000 : FPS_STEP)); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); video.pause(); seekMs(nowMs() - (e.shiftKey ? 1000 : FPS_STEP)); }
  else if (e.key === "Delete" || e.key === "Backspace") { if (S.selected) { e.preventDefault(); flip(S.selected); } }
  else if (e.key.toLowerCase() === "m") setMode(S.mode === "edited" ? "raw" : "edited");
  else if (e.key === "+" || e.key === "=") zoomTo(S.pps * 1.5);
  else if (e.key === "-") zoomTo(S.pps / 1.5);
}

// --- testo personalizzato (pannello Testo) ---------------------------------------
// Le scelte stanno in text_style.json (per stile). Il server manda il look già con le
// scelte "per tutti"; per ogni frase manda in text.resolved i campi che la scena cambia.

const CASE_CSS = { sentence: "none", upper: "uppercase", lower: "lowercase" };
const TX_COLORS = ["#FFFFFF", "#000000", "#FFD60A", "#FFB800", "#FF7A00", "#FF3B30", "#FF2D78", "#FF66C4",
  "#B517FF", "#7B61FF", "#2F6BFF", "#00C2FF", "#1FD3CF", "#00E676", "#A3FF12", "#C9A86A"];
const TX_PRESETS = [
  ["stroke", "Contorno"], ["shadow", "Ombra"], ["hard", "Ombra netta"],
  ["glow", "Neon"], ["box", "Box"], ["plain", "Pulito"],
];

function chunkCaps(chunk) {
  if (!S.look) return null;
  const res = chunk ? S.data?.text?.resolved?.[chunk.id] : null;
  return res ? { ...S.look.captions, ...res } : S.look.captions;
}

function chunkText(chunk) {
  return S.data?.text?.scenes?.[chunk.id]?.text ?? chunk.text;
}

function presetOf(c) {
  if (c.effect === "glow" || c.effect === "box") return c.effect;
  if (c.stroke_px > 0) return "stroke";
  return { soft: "shadow", hard: "hard", none: "plain" }[c.shadow] ?? "plain";
}

function loadTextFonts(url) {
  let link = $("#text-fonts");
  if (!url) { link?.remove(); return; }
  if (!link) {
    link = document.createElement("link");
    link.id = "text-fonts";
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  if (link.getAttribute("href") !== url) link.href = url;
}

// Valori di posizione della frase mostrata (o quelli dal vivo mentre trascini).
function capValues() {
  if (S.txLive) return S.txLive;
  const c = chunkCaps(S.chunks[S.lastChunk] ?? S.chunks[S.txChunk]) ?? {};
  return { x_pct: c.x_pct ?? 0, y_pct: c.y_pct ?? 0, scale: c.scale ?? 1, rotation: c.rotation ?? 0 };
}

function paintTransform() {
  const capEl = $("#caption");
  if (!S.look) { capEl.style.translate = capEl.style.rotate = capEl.style.scale = ""; return; }
  const v = capValues();
  // cqw/cqh = % del fotogramma (container): resta giusto a qualsiasi grandezza del lettore
  capEl.style.translate = `calc(-50% + ${v.x_pct.toFixed(2)}cqw) ${v.y_pct.toFixed(2)}cqh`;
  capEl.style.rotate = `${v.rotation}deg`;
  capEl.style.scale = String(v.scale);
}

function paintCaption(idx, animate = false) {
  const capEl = $("#caption");
  const chunk = idx >= 0 ? S.chunks[idx] : null;
  if (!S.look) {
    capEl.innerHTML = chunk ? captionHTML(chunk) : "";
    capEl.style.color = "";
    return;
  }
  const c = chunkCaps(chunk);
  capEl.innerHTML = chunk ? `<span class="cap-in">${captionHTML(chunk, c, chunkText(chunk))}</span>` : "";
  const st = capEl.style;
  const frame = $("#frame");
  const unit = (S.portrait ? frame.clientWidth : frame.clientHeight) / 1080;
  st.fontFamily = `"${c.font}", system-ui, sans-serif`;
  st.fontWeight = String(c.weight);
  st.fontStyle = c.italic ? "italic" : "normal";
  st.textTransform = CASE_CSS[c.case] ?? "none";
  st.color = chunk ? c.colors[idx % c.colors.length] : "";
  st.setProperty("--cap-stroke", `${(c.stroke_px * unit * 2).toFixed(1)}px`);
  st.setProperty("--cap-stroke-color", c.stroke_color ?? "#000");
  st.setProperty("--fx-color", c.fx_color ?? "#000");
  const e = c.emphasis;
  if (e) {
    st.setProperty("--emph-font", e.font ? `"${e.font}", Georgia, serif` : st.fontFamily);
    st.setProperty("--emph-style", e.italic ? "italic" : "normal");
    st.setProperty("--emph-weight", String(e.weight ?? c.weight));
    st.setProperty("--emph-color", e.color);
    st.setProperty("--emph-scale", String(e.scale));
  }
  const fx = [`sh-${c.shadow}`, `fx-${c.effect ?? "none"}`, c.stroke_px > 0 ? "fx-stroke" : ""];
  capEl.className = ["caption", ...fx, $("#btn-cc").classList.contains("on") ? "" : "off"].filter(Boolean).join(" ");
  paintTransform();
  if (idx >= 0 && idx !== S.txChunk) {
    S.txChunk = idx;
    renderTextPanels();
  }
}

// --- pannello ---------------------------------------------------------------------

function textPanelHTML() {
  if (!S.look) {
    const btns = (S.data?.styles ?? []).map((s) =>
      `<button class="btn" data-tx-style="${esc(s.id)}">${esc(s.name)}</button>`).join("");
    return `<div class="placeholder"><svg viewBox="0 0 24 24"><path d="M4 7V5h16v2M12 5v14M9 19h6"/></svg>
      <b>Testo</b><br>Scegli prima uno stile: font, colori e stili del testo cambiano con il preset.</div>
      <div class="btn-row tx-styles">${btns}</div>`;
  }
  const T = S.data.text;
  if (!T) {
    // pagina nuova con un server avviato prima dell'aggiornamento
    return `<div class="placeholder"><b>Testo</b><br>L'editor in esecuzione è una versione vecchia.
      Chiudilo (Ctrl+C nel terminale) e rilancia <code>autocut editor ${esc(S.data.project)}</code>.</div>`;
  }
  const chunk = S.chunks[S.txChunk] ?? null;
  const scene = S.txScope === "scene" && chunk;
  const c = scene ? chunkCaps(chunk) : S.look.captions;
  const own = chunk && T.scenes[chunk.id];
  const slotFont = S.txSlot === "emph" ? c.emphasis?.font ?? c.font : c.font;
  const pre = presetOf(c);
  const sw = (field, current) => TX_COLORS.map((h) =>
    `<button class="sw${current && current.toUpperCase() === h ? " on" : ""}" style="background:${h}" data-tx-color="${field}" data-v="${h}" title="${h}"></button>`).join("")
    + `<label class="sw pick" title="Altro colore"><input type="color" data-tx-pick="${field}" value="${esc(current ?? "#ffffff")}"></label>`;
  const fonts = T.fonts.map((f) => `
    <button class="font-card${f.family === slotFont ? " on" : ""}" data-tx-font="${esc(f.family)}"
      style="font-family:'${esc(f.family)}';font-weight:${Math.max(...f.weights)}">
      <span class="fc-name">${esc(f.family)}</span><span class="fc-kind">${esc(f.kind)}</span></button>`).join("");
  const presets = TX_PRESETS.map(([id, label]) => `
    <button class="pre-card${pre === id ? " on" : ""}" data-tx-preset="${id}">
      <span class="pre-demo fx-${id}" style="font-family:'${esc(c.font)}'"><span class="cap-in">Testo</span></span>
      <span class="pre-label">${label}</span></button>`).join("");
  const sceneLabel = chunk ? `${clock(S.mode === "edited" ? editedAt(chunk.start) : chunk.start - S.axisStart, false)}` : "—";
  return `
    <div class="tx-head">
      <div class="seg-toggle tx-scope">
        <button data-tx-scope="all" class="${S.txScope === "all" ? "on" : ""}">Tutti i sottotitoli</button>
        <button data-tx-scope="scene" class="${S.txScope === "scene" ? "on" : ""}" ${chunk ? "" : "disabled"}>Solo questa scena ${sceneLabel}</button>
      </div>
      ${own ? `<div class="tx-own">Questa scena ha modifiche sue <button class="link" data-tx-act="reset-scene">Ripristina scena</button></div>` : ""}
    </div>
    <div class="section-title">Testo della scena</div>
    <textarea id="tx-text" class="tx-text" rows="2" ${chunk ? "" : "disabled"} data-scene="${esc(chunk?.id ?? "")}"
      placeholder="Porta la testina su una frase">${esc(chunk ? chunkText(chunk) : "")}</textarea>
    <div class="tx-hint">Invio per salvare · clicca il testo nel video per spostarlo, ruotarlo e ingrandirlo</div>

    <div class="section-title tx-row">Font
      <div class="seg-toggle small">
        <button data-tx-slot="main" class="${S.txSlot === "main" ? "on" : ""}">Testo</button>
        <button data-tx-slot="emph" class="${S.txSlot === "emph" ? "on" : ""}">Parola chiave</button>
      </div></div>
    <div class="font-grid">${fonts}</div>
    <div class="tx-hint">${S.txSlot === "emph" ? "La parola chiave (numeri o la parola più lunga) prende questo font: prova un serif con un testo sans." : `Font del ${esc(S.look.style_name)}. Cambia preset in alto per vedere gli altri.`}</div>

    <div class="section-title">Stile</div>
    <div class="pre-grid">${presets}</div>

    <div class="section-title">Formato</div>
    <div class="fmt-row">
      <button class="fmt${c.weight >= 700 ? " on" : ""}" data-tx-bold="${c.weight >= 700 ? "0" : "1"}" title="Grassetto"><b>B</b></button>
      <button class="fmt${c.italic ? " on" : ""}" data-tx-italic="${c.italic ? "0" : "1"}" title="Corsivo"><i>I</i></button>
      <span class="tl-sep"></span>
      <button class="fmt${c.case === "sentence" ? " on" : ""}" data-tx-case="sentence" title="Come scritto">Aa</button>
      <button class="fmt${c.case === "upper" ? " on" : ""}" data-tx-case="upper" title="Tutto maiuscolo">AA</button>
      <button class="fmt${c.case === "lower" ? " on" : ""}" data-tx-case="lower" title="Tutto minuscolo">aa</button>
    </div>

    <div class="section-title">Colore del testo</div><div class="swatch-row">${sw("color", c.colors[0])}</div>
    <div class="section-title">Colore della parola chiave</div><div class="swatch-row">${sw("emph_color", c.emphasis?.color)}</div>
    <div class="section-title">Colore di contorno, box o neon</div><div class="swatch-row">${sw("fx_color", c.fx_color)}</div>

    <div class="section-title">Grandezza <span class="tx-val" id="tx-scale-val">${Math.round(c.scale * 100)}%</span></div>
    <input type="range" class="tx-range" data-tx-range="scale" min="30" max="300" step="1" value="${Math.round(c.scale * 100)}">
    <div class="section-title">Rotazione <span class="tx-val" id="tx-rotation-val">${Math.round(c.rotation)}°</span></div>
    <input type="range" class="tx-range" data-tx-range="rotation" min="-180" max="180" step="1" value="${Math.round(c.rotation)}">
    <div class="btn-row tx-actions">
      <button class="btn" data-tx-act="center">Centra</button>
      <button class="btn" data-tx-act="reset-pos">Posizione originale</button>
      <button class="btn" data-tx-act="reset-all">Ripristina ${scene ? "scena" : "tutto"}</button>
    </div>`;
}

// Ridisegna i pannelli Testo visibili (a sinistra e nello schermo intero).
function renderTextPanels() {
  const boxes = [];
  if (["text", "stickers", "images", "broll", "effects", "audio", "transitions", "filters", "vfx"].includes(S.leftTab)) boxes.push([$("#left-content"), S.leftTab]);
  if (S.viewer && S.txPanel) boxes.push([$("#viewer-panel"), S.viewerTab]);
  for (const [box, tab] of boxes) {
    // non interrompere chi sta scrivendo o trascinando un cursore
    const active = document.activeElement;
    if (box.contains(active) && (["tx-text", "st-custom", "img-q", "vfx-text"].includes(active.id) || active.dataset?.q !== undefined)) continue;
    if (S.txSliding && box.contains(S.txSliding)) continue;
    const top = box.scrollTop;
    if (tab === "transitions") S.fxTab = "trans"; // la scheda Transizioni = giunte del pannello Effetti
    box.innerHTML = tab === "stickers" ? stickerPanelHTML() : tab === "effects" || tab === "transitions" ? effectsPanelHTML()
      : tab === "images" ? imagesPanelHTML() : tab === "broll" ? brollPanelHTML() : tab === "vfx" ? vfxPanelHTML() : tab === "audio" ? audioPanelHTML() : tab === "filters" ? filtersPanelHTML() : textPanelHTML();
    if (tab === "effects" || tab === "transitions") maybeAutoFx();
    box.scrollTop = top;
  }
}

// Pannello a destra nello schermo intero: Testo o Sticker (stesso tasto = chiude).
function toggleViewerPanel(on = !S.txPanel, tab = S.viewerTab) {
  S.txPanel = on;
  S.viewerTab = tab;
  $("#viewer").classList.toggle("with-panel", on);
  $("#viewer-panel").hidden = !on;
  $("#v-text")?.classList.toggle("on", on && tab === "text");
  $("#v-sticker")?.classList.toggle("on", on && tab === "stickers");
  $("#v-effects")?.classList.toggle("on", on && tab === "effects");
  $("#v-images")?.classList.toggle("on", on && tab === "images");
  $("#v-audio")?.classList.toggle("on", on && tab === "audio");
  $("#v-vfx")?.classList.toggle("on", on && tab === "vfx");
  $("#v-broll")?.classList.toggle("on", on && tab === "broll");
  if (on) renderTextPanels();
  if (S.viewer) fitFrame();
}

function txScene() {
  return S.txScope === "scene" ? S.chunks[S.txChunk]?.id ?? null : null;
}

async function saveText(fields, { scene = txScene(), reset = false } = {}) {
  await mutate("/api/text", { scene, fields, reset });
}

function wireTextPanel(box) {
  box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tx-style],[data-tx-scope],[data-tx-slot],[data-tx-font],[data-tx-preset],[data-tx-bold],[data-tx-italic],[data-tx-case],[data-tx-color],[data-tx-act]");
    if (!b || b.disabled) return;
    const d = b.dataset;
    if (d.txStyle) mutate("/api/style", { id: d.txStyle }, "Stile applicato");
    else if (d.txScope) { S.txScope = d.txScope; renderTextPanels(); }
    else if (d.txSlot) { S.txSlot = d.txSlot; renderTextPanels(); }
    else if (d.txFont) saveText(S.txSlot === "emph" ? { emph_font: d.txFont } : { font: d.txFont });
    else if (d.txPreset) saveText({ preset: d.txPreset });
    else if (d.txBold) saveText({ bold: d.txBold === "1" });
    else if (d.txItalic) saveText({ italic: d.txItalic === "1" });
    else if (d.txCase) saveText({ case: d.txCase });
    else if (d.txColor) saveText({ [d.txColor]: d.v });
    else if (d.txAct === "center") saveText({ x_pct: 0 });
    else if (d.txAct === "reset-pos") saveText({ x_pct: null, y_pct: null, scale: null, rotation: null });
    else if (d.txAct === "reset-all") saveText({}, { reset: true });
    else if (d.txAct === "reset-scene") saveText({}, { scene: S.chunks[S.txChunk]?.id, reset: true });
  });
  box.addEventListener("input", (e) => {
    const r = e.target.closest("[data-tx-range]");
    if (!r) return;
    S.txSliding = r;
    const k = r.dataset.txRange;
    const v = Number(r.value);
    S.txLive = { ...capValues(), [k]: k === "scale" ? v / 100 : v };
    box.querySelector(`#tx-${k}-val`).textContent = k === "scale" ? `${v}%` : `${v}°`;
    paintTransform();
  });
  box.addEventListener("change", async (e) => {
    const r = e.target.closest("[data-tx-range]");
    if (r) {
      const k = r.dataset.txRange;
      const v = Number(r.value);
      S.txSliding = null;
      await saveText({ [k]: k === "scale" ? v / 100 : v });
      S.txLive = null;
      return;
    }
    const pick = e.target.closest("[data-tx-pick]");
    if (pick) { saveText({ [pick.dataset.txPick]: pick.value.toUpperCase() }); return; }
    const ta = e.target.closest("#tx-text");
    if (ta && ta.dataset.scene) {
      const chunk = S.chunks.find((x) => x.id === ta.dataset.scene);
      const value = ta.value.replace(/\s+/g, " ").trim();
      if (!chunk || value === chunkText(chunk)) return;
      ta.blur();
      await saveText({ text: value === chunk.text ? null : value || null }, { scene: chunk.id });
    }
  });
  box.addEventListener("keydown", (e) => {
    if (e.target.id === "tx-text" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.target.blur(); }
  });
}

// --- testo e sticker nel video: seleziona, sposta, ruota, ingrandisci (come CapCut) ---

function selectCaption() {
  S.txSel = true;
  S.popSel = null;
  if (S.viewer) toggleViewerPanel(true, "text");
  else if (S.leftTab !== "text") { S.leftTab = "text"; renderLeft(); }
}

function selectPop(id, { open = true } = {}) {
  S.popSel = id;
  S.txSel = false;
  S.stTab = "edit";
  if (!open) return;
  const tab = isPhoto(popItem(id)) && (S.viewer ? S.viewerTab !== "stickers" || !S.txPanel : S.leftTab !== "stickers") ? "images" : "stickers";
  if (S.viewer) toggleViewerPanel(true, tab);
  else if (S.leftTab !== tab) { S.leftTab = tab; renderLeft(); }
  else renderTextPanels();
}

function capVisible() {
  const cap = $("#caption");
  return Boolean(S.look && cap.innerHTML && !cap.classList.contains("off") && !$("#frame").classList.contains("hooking"));
}

const popEl = (id) => (id ? document.querySelector(`.pop-el[data-id="${CSS.escape(id)}"]`) : null);
const popItem = (id) => (S.data?.popups ?? []).find((p) => p.id === id) ?? null;

// Centro (in % del fotogramma), grandezza e rotazione di uno sticker com'è adesso.
function popValues(id) {
  if (S.popLive?.id === id) return S.popLive;
  const p = popItem(id);
  if (p && p.placement === "free") return { id, x_pct: p.x_pct, y_pct: p.y_pct, scale: p.scale, rotation: p.rotation };
  const el = popEl(id);
  const fr = $("#frame").getBoundingClientRect();
  if (!el) return { id, x_pct: 50, y_pct: 40, scale: p?.scale ?? 1, rotation: 0 };
  const r = el.getBoundingClientRect();
  return {
    id,
    x_pct: ((r.left + r.width / 2 - fr.left) / fr.width) * 100,
    y_pct: ((r.top + r.height / 2 - fr.top) / fr.height) * 100,
    scale: p?.scale ?? 1,
    rotation: 0,
  };
}

// Mentre trascini: lo sticker diventa "libero" e segue il mouse (salvato al rilascio).
function paintPopLive() {
  const v = S.popLive;
  const el = v && popEl(v.id);
  if (!el) return;
  el.className = el.className.replace(/\bat-\w+/g, "").trim() + " at-free";
  Object.assign(el.style, { left: `${v.x_pct}%`, top: `${v.y_pct}%`, rotate: `${v.rotation}deg`, scale: String(v.scale) });
}

function placeSel(sel, cx, cy, w, h, rot) {
  sel.style.left = `${cx - w / 2}px`;
  sel.style.top = `${cy - h / 2}px`;
  sel.style.width = `${w}px`;
  sel.style.height = `${h}px`;
  sel.style.rotate = `${rot}deg`;
}

function updateCapSel() {
  const sel = $("#cap-sel");
  const on = S.txSel && capVisible();
  sel.classList.toggle("on", on);
  $("#cap-guide").classList.toggle("on", Boolean(S.txDrag?.snapX));
  if (on) {
    const cap = $("#caption");
    const frame = $("#frame");
    const v = capValues();
    placeSel(sel, cap.offsetLeft + (v.x_pct / 100) * frame.clientWidth,
      cap.offsetTop + cap.offsetHeight / 2 + (v.y_pct / 100) * frame.clientHeight,
      cap.offsetWidth * v.scale, cap.offsetHeight * v.scale, v.rotation);  // prettier-ignore
  }
  const psel = $("#pop-sel");
  const el = popEl(S.popSel);
  psel.classList.toggle("on", Boolean(el));
  if (!el) return;
  const fr = $("#frame").getBoundingClientRect();
  if (el.classList.contains("at-free")) {
    const v = popValues(S.popSel);
    placeSel(psel, (v.x_pct / 100) * fr.width, (v.y_pct / 100) * fr.height,
      el.offsetWidth * v.scale, el.offsetHeight * v.scale, v.rotation);  // prettier-ignore
  } else {
    const r = el.getBoundingClientRect();
    placeSel(psel, r.left + r.width / 2 - fr.left, r.top + r.height / 2 - fr.top, r.width, r.height, 0);
  }
}

function wireCaptionDrag() {
  const frame = $("#frame");
  frame.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const inPop = e.target.closest("#pop-sel") && S.popSel ? S.popSel : null;
    const inCap = !inPop && e.target.closest("#cap-sel") && S.txSel;
    const popHit = !inPop && !inCap ? e.target.closest(".pop-el[data-id]")?.dataset.id : null;
    const capHit = !inPop && !inCap && !popHit && e.target.closest("#caption") && capVisible();
    const pop = inPop || popHit;
    const cap = inCap || capHit;
    if (!pop && !cap) {
      if (S.txSel || S.popSel) { S.txSel = false; S.popSel = null; renderTextPanels(); }
      return;
    }
    if (cap && !S.look) return;
    e.preventDefault();
    e.stopPropagation();
    if (pop) { if (S.popSel !== pop) selectPop(pop); } else selectCaption();
    const handle = e.target.closest(".cap-sel .h, .cap-sel .rot");
    const box = $(pop ? "#pop-sel" : "#cap-sel").getBoundingClientRect();
    const fr = frame.getBoundingClientRect();
    const r = box.width ? box : (pop ? popEl(pop) : $("#caption")).getBoundingClientRect();
    S.txDrag = {
      target: pop ? "pop" : "cap", id: pop,
      mode: handle ? (handle.classList.contains("rot") ? "rotate" : "scale") : "move",
      x: e.clientX, y: e.clientY, fw: fr.width, fh: fr.height,
      cx: r.left + r.width / 2, cy: r.top + r.height / 2,
      start: pop ? { ...popValues(pop) } : { ...capValues() }, moved: false, snapX: false,
    };
    try { frame.setPointerCapture(e.pointerId); } catch { /* puntatore già rilasciato */ }
  });
  frame.addEventListener("pointermove", (e) => {
    const d = S.txDrag;
    if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 3) return;
    d.moved = true;
    const v = { ...d.start };
    if (d.mode === "move") {
      v.x_pct = d.start.x_pct + ((e.clientX - d.x) / d.fw) * 100;
      v.y_pct = d.start.y_pct + ((e.clientY - d.y) / d.fh) * 100;
      const center = d.target === "pop" ? 50 : 0; // sticker: posizione assoluta; testo: spostamento
      d.snapX = Math.abs(v.x_pct - center) < 1.5; // calamita sul centro
      if (d.snapX) v.x_pct = center;
      const [lo, hi, vlo, vhi] = d.target === "pop" ? [0, 100, 0, 100] : [-60, 60, -80, 80];
      v.x_pct = Math.max(lo, Math.min(hi, v.x_pct));
      v.y_pct = Math.max(vlo, Math.min(vhi, v.y_pct));
    } else if (d.mode === "scale") {
      const k = Math.hypot(e.clientX - d.cx, e.clientY - d.cy) / Math.max(1, Math.hypot(d.x - d.cx, d.y - d.cy));
      const [lo, hi] = d.target === "pop" ? [0.2, 5] : [0.3, 3];
      v.scale = Math.max(lo, Math.min(hi, d.start.scale * k));
    } else {
      const a0 = Math.atan2(d.y - d.cy, d.x - d.cx), a1 = Math.atan2(e.clientY - d.cy, e.clientX - d.cx);
      let r = d.start.rotation + ((a1 - a0) * 180) / Math.PI;
      r = ((r + 540) % 360) - 180;
      const near = Math.round(r / 90) * 90;
      if (Math.abs(r - near) < 4) r = near; // calamita su 0°/90°
      v.rotation = Math.max(-180, Math.min(180, r));
    }
    if (d.target === "pop") { S.popLive = v; paintPopLive(); }
    else { S.txLive = v; paintTransform(); }
  });
  const end = async () => {
    const d = S.txDrag;
    if (!d) return;
    S.txDrag = null;
    if (!d.moved) return;
    S.txClickGuard = true; // il clic che chiude il trascinamento non è play/pausa
    setTimeout(() => (S.txClickGuard = false), 0);
    const round = (x, n) => Math.round(x * n) / n;
    if (d.target === "pop") {
      const v = S.popLive;
      await savePop(d.id, { placement: "free", x_pct: round(v.x_pct, 10), y_pct: round(v.y_pct, 10),
        scale: round(v.scale, 100), rotation: round(v.rotation, 10) });  // prettier-ignore
      S.popLive = null;
      return;
    }
    const v = S.txLive;
    await saveText({ x_pct: round(v.x_pct, 10), y_pct: round(v.y_pct, 10), scale: round(v.scale, 100), rotation: round(v.rotation, 10) });
    S.txLive = null;
    paintTransform();
  };
  frame.addEventListener("pointerup", end);
  frame.addEventListener("pointercancel", end);
}

// --- pannello Sticker --------------------------------------------------------------

const EMO_CAT = {
  "Smileys & Emotion": ["Faccine", "😀"], "People & Body": ["Persone", "👋"], "Animals & Nature": ["Animali e natura", "🐻"],
  "Food & Drink": ["Cibo", "🍔"], "Travel & Places": ["Viaggi e luoghi", "🚗"], "Activities": ["Attività", "⚽"],
  "Objects": ["Oggetti", "💡"], "Symbols": ["Simboli", "❤️"], "Flags": ["Bandiere", "🏁"],
};

const LAYERS = [
  ["under_text", "Dietro al testo"],
  ["over_text", "Davanti al testo"],
  ["person", "Dietro la persona"],
];
const SIZES = [["small", "S"], ["medium", "M"], ["large", "L"]];

// Tempo come nell'orologio del lettore: sul montato o sul raw.
const showTime = (ms) => clock(S.mode === "edited" ? editedAt(ms) : ms - S.axisStart, false);

async function savePop(id, fields, msg) {
  await mutate("/api/popups/item", { id, action: "update", fields }, msg);
}

function popThumb(p) {
  if (p.image_url) return `<img class="st-thumb" src="${esc(p.image_url)}" alt="">`;
  if (p.kind === "emoji") return `<span class="st-thumb em">${emojiHTML(p.emoji)}</span>`;
  return `<span class="st-thumb txt">${esc(p.title)}</span>`;
}

function stickerEditHTML(sel, title = "Sticker selezionato") {
  const v = popValues(sel.id);
  const layer = sel.placement === "behind" ? "person" : sel.layer;
  return `
    <div class="st-sel">
      <div class="st-sel-head">${popThumb(sel)}<div><b>${title}</b>
        <div class="meta">a ${showTime(sel.at_ms)} · ${(sel.duration_ms / 1000).toFixed(1).replace(".", ",")} s${sel.status === "proposed" ? " · proposta di Claude" : ""}</div></div>
        <button class="icon-btn" data-st="close" title="Deseleziona">✕</button></div>
      <div class="section-title">Livello</div>
      <div class="seg-toggle st-layer">${LAYERS.map(([id, label]) =>
        `<button data-st-layer="${id}" class="${layer === id ? "on" : ""}">${label}</button>`).join("")}</div>
      ${layer === "person" ? `<div class="tx-hint">Nel render passa dietro di te (sagoma calcolata in locale). Nell'anteprima lo vedi trasparente.</div>` : ""}
      <div class="section-title" style="margin-top:12px">Grandezza <span class="tx-val" id="st-scale-val">${Math.round(v.scale * 100)}%</span></div>
      <div class="st-row"><input type="range" class="tx-range" data-st-range="scale" min="20" max="500" value="${Math.round(v.scale * 100)}">
        <div class="seg-toggle small">${SIZES.map(([id, l]) => `<button data-st-size="${id}" class="${sel.size === id ? "on" : ""}">${l}</button>`).join("")}</div></div>
      <div class="section-title">Rotazione <span class="tx-val" id="st-rotation-val">${Math.round(v.rotation)}°</span></div>
      <input type="range" class="tx-range" data-st-range="rotation" min="-180" max="180" value="${Math.round(v.rotation)}">
      <div class="section-title">Durata <span class="tx-val" id="st-duration-val">${(sel.duration_ms / 1000).toFixed(1).replace(".", ",")} s</span></div>
      <input type="range" class="tx-range" data-st-range="duration" min="4" max="100" value="${Math.round(sel.duration_ms / 100)}">
      <div class="btn-row tx-actions">
        <button class="btn" data-st="here" title="Fa partire lo sticker dove c'è la testina">Inizia qui</button>
        <button class="btn" data-st="center">Centra</button>
        <button class="btn${sel.sound ? " on" : ""}" data-st="sound">${sel.sound ? "🔊 Suono" : "🔇 Muto"}</button>
        ${sel.status === "proposed" ? `<button class="btn" data-st="approve">Approva</button>` : ""}
        <button class="btn danger" data-st="delete">Elimina</button>
      </div>
    </div>`;
}

function stickerPanelHTML() {
  if (!S.look) {
    const btns = (S.data?.styles ?? []).map((s) =>
      `<button class="btn" data-tx-style="${esc(s.id)}">${esc(s.name)}</button>`).join("");
    return `<div class="placeholder"><svg viewBox="0 0 24 24"><path d="M15 3H6a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3h7l8-8V6a3 3 0 0 0-3-3h-3z"/><path d="M13 21v-5a3 3 0 0 1 3-3h5"/></svg>
      <b>Sticker</b><br>Scegli prima uno stile: la libreria cambia tra Viral e Premium.</div>
      <div class="btn-row tx-styles">${btns}</div>`;
  }
  const lib = S.data.stickers ?? { emoji: [], text: [], images: [] };
  const items = (S.data.popups ?? []).filter((p) => p.status !== "rejected");
  const sel = popItem(S.popSel);
  const kindCls = S.look.cards.kind === "sticker" ? "sticker" : "glass";
  const selBox = sel ? stickerEditHTML(sel) : "";
  const emoBtn = (e) => `<button class="st-add em" data-st-add="emoji" data-v="${esc(e)}" title="Aggiungi">${emojiHTML(e)}</button>`;
  const emojis = lib.emoji.map(emoBtn).join("");
  const cat = S.emoCats[S.emoCat];
  const keyboard = S.emoCats.length ? `
    <div class="emo-tabs">${S.emoCats.map((c, i) =>
      `<button class="${i === S.emoCat ? "on" : ""}" data-st-cat="${i}" title="${esc(EMO_CAT[c.name]?.[0] ?? c.name)}">${emojiHTML(EMO_CAT[c.name]?.[1] ?? c.items[0].e)}</button>`).join("")}</div>
    <div class="st-grid em keyboard">${cat.items.map((i) => `<button class="st-add em" data-st-add="emoji" data-v="${esc(i.e)}"><img class="emo" src="/media/emoji/${i.img}" alt="" loading="lazy" draggable="false"></button>`).join("")}</div>` : "";
  const texts = lib.text.map((t) => `<button class="st-add txt ${kindCls}" data-st-add="text" data-v="${esc(t)}"><span>${esc(t)}</span></button>`).join("");
  const imgs = lib.images.map((im) => `<button class="st-add img" data-st-add="image" data-v="${esc(im.image)}"><img src="${esc(im.url)}" alt="" loading="lazy"></button>`).join("");
  const list = items.map((p) => `
    <button class="st-item${p.id === S.popSel ? " on" : ""}" data-st-pick="${esc(p.id)}">
      ${popThumb(p)}<span class="st-item-t">${showTime(p.at_ms)}
        <span class="meta">${p.placement === "behind" || p.layer === "person" ? "dietro di te" : p.layer === "over_text" ? "davanti al testo" : "dietro al testo"}${p.status === "proposed" ? " · proposta" : ""}</span></span>
    </button>`).join("");
  return `
    <div class="seg-toggle st-tabs">
      <button data-st-tab="add" class="${S.stTab === "add" ? "on" : ""}">Aggiungi</button>
      <button data-st-tab="edit" class="${S.stTab === "edit" ? "on" : ""}" ${sel ? "" : "disabled"}>Modifica${sel ? ` ${popThumb(sel)}` : ""}</button>
      <button data-st-tab="list" class="${S.stTab === "list" ? "on" : ""}">Nel video (${items.length})</button>
    </div>
    ${S.stTab === "edit" && sel ? selBox : S.stTab === "list" ? `
    <div class="st-list">${list || `<div class="tx-hint">Nessuno sticker per questo stile.</div>`}</div>` : `
    <div class="tx-hint" style="margin-top:0">Un clic aggiunge lo sticker dove c'è la testina (${esc(S.look.style_name)}). Per spostarlo, ruotarlo, ingrandirlo o metterlo davanti/dietro al testo clicca lo sticker nel video.</div>
    <div class="st-sub">Più usate</div>
    <div class="st-grid em">${emojis}</div>
    ${keyboard ? `<div class="st-sub">Tutte le emoji${cat ? ` · ${esc(EMO_CAT[cat.name]?.[0] ?? cat.name)}` : ""}</div>${keyboard}` : ""}
    <div class="st-sub">Scritte</div>
    <div class="st-grid txt">${texts}</div>
    ${imgs ? `<div class="section-title">Le tue immagini AI</div><div class="st-grid img">${imgs}</div>` : ""}
    <div class="st-custom"><input id="st-custom" maxlength="16" placeholder="Scrivi un testo o incolla un'emoji">
      <button class="btn" data-st="custom">Aggiungi</button></div>`}`;
}

// Posti liberi per un nuovo sticker (centro in % del fotogramma): prima in alto sopra la testa,
// poi ai lati, così non finisce sulla faccia né sopra un altro sticker dello stesso momento.
const SLOTS_V = [[50, 20], [24, 26], [76, 26], [26, 52], [74, 52], [50, 12], [30, 14], [70, 14]];
const SLOTS_H = [[50, 22], [20, 30], [80, 30], [22, 62], [78, 62], [50, 12]];

function freeSlot(atMs) {
  const busy = (S.data?.popups ?? []).filter((p) => p.status !== "rejected" && p.placement === "free"
    && p.at_ms < atMs + 2000 && atMs < p.at_ms + p.duration_ms);
  const slots = S.portrait ? SLOTS_V : SLOTS_H;
  const free = slots.find(([x, y]) => busy.every((p) => Math.hypot(p.x_pct - x, (p.y_pct - y) * 0.6) > 12));
  return free ?? slots[busy.length % slots.length];
}

async function addSticker(kind, value) {
  video.pause();
  const atMs = Math.round(nowMs());
  const [x, y] = freeSlot(atMs);
  // un po' più grande della taglia M: si vede bene anche nel lettore piccolo
  const body = { kind, at_ms: atMs, x_pct: x, y_pct: y, scale: kind === "emoji" ? 1.4 : 1 };
  if (kind === "emoji") body.emoji = value;
  else if (kind === "text") body.title = value;
  else body.image = value;
  const data = await mutate("/api/popups/add", body);
  if (!data?.added) return;
  S.popSel = data.added;
  S.justAdded = data.added;
  setTimeout(() => { if (S.justAdded === data.added) S.justAdded = null; $("#popup-layer").dataset.key = ""; }, 1400);
  $("#popup-layer").dataset.key = "";
  renderTextPanels();
  toast(`Sticker aggiunto a ${showTime(atMs)}: lo vedi selezionato nel video, trascinalo dove vuoi`);
}

const ONLY_EMOJI = /^(\p{Extended_Pictographic}|\p{Regional_Indicator}|‍|️|\p{Emoji_Modifier})+$/u;

function wireStickerPanel(box) {
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-st],[data-st-add],[data-st-pick],[data-st-layer],[data-st-size],[data-st-cat],[data-st-tab]");
    if (!b || b.disabled) return;
    const d = b.dataset;
    if (d.stTab) { S.stTab = d.stTab; renderTextPanels(); return; }
    if (d.stCat) { S.emoCat = Number(d.stCat); renderTextPanels(); return; }
    const sel = popItem(S.popSel);
    if (d.stAdd) { addSticker(d.stAdd, d.v); return; }
    if (d.stPick) {
      const p = popItem(d.stPick);
      video.pause();
      if (p) seekMs(p.at_ms + 120);
      selectPop(d.stPick);
      renderTextPanels();
      return;
    }
    if (d.st === "custom") {
      const v = box.querySelector("#st-custom").value.trim();
      if (!v) { toast("Scrivi un testo o incolla un'emoji", true); return; }
      addSticker(ONLY_EMOJI.test(v) ? "emoji" : "text", v);
      return;
    }
    if (d.st === "close") { S.popSel = null; S.stTab = "add"; renderTextPanels(); return; }
    if (!sel) return;
    if (d.stLayer) {
      const fields = { layer: d.stLayer };
      // "dietro la persona" automatico → diventa libero quando scegli un altro livello
      if (sel.placement === "behind" && d.stLayer !== "person") Object.assign(fields, { placement: "free", ...popValues(sel.id), id: undefined });
      delete fields.id;
      savePop(sel.id, fields);
    } else if (d.stSize) savePop(sel.id, { size: d.stSize });
    else if (d.st === "here") savePop(sel.id, { at_ms: Math.round(nowMs()) }, "Lo sticker parte qui");
    else if (d.st === "center") savePop(sel.id, { placement: "free", x_pct: 50, y_pct: popValues(sel.id).y_pct, rotation: 0 });
    else if (d.st === "sound") savePop(sel.id, { sound: !sel.sound });
    else if (d.st === "approve") mutate("/api/popups/item", { id: sel.id, action: "approve" });
    else if (d.st === "delete") deletePop(sel.id);
  });
  box.addEventListener("input", (e) => {
    const r = e.target.closest("[data-st-range]");
    if (!r || !S.popSel) return;
    S.txSliding = r;
    const k = r.dataset.stRange;
    const v = Number(r.value);
    const label = box.querySelector(`#st-${k}-val`);
    if (k === "duration") { label.textContent = `${(v / 10).toFixed(1).replace(".", ",")} s`; return; }
    S.popLive = { ...popValues(S.popSel), [k]: k === "scale" ? v / 100 : v };
    label.textContent = k === "scale" ? `${v}%` : `${v}°`;
    paintPopLive();
  });
  box.addEventListener("change", async (e) => {
    const r = e.target.closest("[data-st-range]");
    if (!r || !S.popSel) return;
    S.txSliding = null;
    const k = r.dataset.stRange;
    const v = Number(r.value);
    if (k === "duration") { await savePop(S.popSel, { duration_ms: v * 100 }); return; }
    const live = { ...popValues(S.popSel) };
    await savePop(S.popSel, { placement: "free", x_pct: Math.round(live.x_pct * 10) / 10, y_pct: Math.round(live.y_pct * 10) / 10,
      scale: Math.round(live.scale * 100) / 100, rotation: Math.round(live.rotation) });  // prettier-ignore
    S.popLive = null;
  });
  box.addEventListener("keydown", (e) => {
    if (e.target.id === "st-custom" && e.key === "Enter") { e.preventDefault(); box.querySelector('[data-st="custom"]').click(); }
  });
}

async function deletePop(id) {
  S.popSel = null;
  if (S.stTab === "edit") S.stTab = "add";
  await mutate("/api/popups/item", { id, action: "delete" }, "Sticker eliminato");
}

// --- filtri: il colore del video (sopra il look dello stile) ------------------------------

const FILTER_SLIDERS = [
  ["brightness", "Luminosità", 0.6, 1.4, 0.01, (v) => `${Math.round((v - 1) * 100)}%`],
  ["contrast", "Contrasto", 0.5, 1.6, 0.01, (v) => `${Math.round((v - 1) * 100)}%`],
  ["saturation", "Saturazione", 0, 2, 0.01, (v) => `${Math.round((v - 1) * 100)}%`],
  ["warmth", "Calore", 0, 0.4, 0.01, (v) => `${Math.round(v * 250)}`],
  ["hue", "Tinta", -40, 40, 1, (v) => `${Math.round(v)}°`],
  ["vignette", "Vignetta", 0, 1, 0.01, (v) => `${Math.round(v * 100)}%`],
];

function gradeCss(g) {
  const parts = [`contrast(${g.contrast})`, `saturate(${g.saturation})`, `brightness(${g.brightness})`];
  if (g.warmth) parts.push(`sepia(${g.warmth})`);
  if (g.hue) parts.push(`hue-rotate(${g.hue}deg)`);
  if (g.grayscale) parts.push(`grayscale(${g.grayscale})`);
  return parts.join(" ");
}

function filtersPanelHTML() {
  const f = S.data?.filters;
  if (!S.look || !f?.grade) {
    const btns = (S.data?.styles ?? []).map((s) => `<button class="btn" data-tx-style="${esc(s.id)}">${esc(s.name)}</button>`).join("");
    return `<div class="placeholder"><svg viewBox="0 0 24 24"><circle cx="9" cy="10" r="5"/><circle cx="15" cy="10" r="5"/><circle cx="12" cy="15" r="5"/></svg>
      <b>Filtri</b><br>Scegli prima uno stile: i filtri partono dal suo look del colore.</div><div class="btn-row tx-styles">${btns}</div>`;
  }
  const thumb = `/media/thumbs/${Math.max(1, Math.min(S.data.media.thumb_count, Math.floor((nowMs() - S.axisStart) / S.data.media.thumb_interval_ms) + 1))}.jpg`;
  const cards = f.presets.map((p) => {
    const g = { ...f.style_grade, ...p.values };
    return `<button class="flt-card${p.id === f.preset ? " on" : ""}" data-flt-preset="${p.id}">
      <img src="${thumb}" alt="" style="filter:${gradeCss(g)}"><span>${esc(p.label)}</span></button>`;
  }).join("");
  const g = f.grade;
  const sliders = FILTER_SLIDERS.map(([k, label, min, max, step, fmt]) => `
    <div class="section-title">${label} <span class="tx-val" id="flt-${k}-val">${fmt(g[k] ?? 0)}</span></div>
    <input type="range" class="tx-range" data-flt="${k}" min="${min}" max="${max}" step="${step}" value="${g[k] ?? 0}">`).join("");
  return `
    <div class="tx-hint" style="margin-top:0">Il colore del video per lo stile ${esc(S.look.style_name)}: vale nell'anteprima, nel render e nella copertina.</div>
    <div class="flt-grid">${cards}</div>
    ${sliders}
    <div class="btn-row tx-actions"><button class="btn" data-flt-act="reset">Torna al look dello stile</button></div>`;
}

function wireFiltersPanel(box) {
  box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-flt-preset],[data-flt-act]");
    if (!b || S.leftTab !== "filters") return;
    if (b.dataset.fltPreset) mutate("/api/filters", { preset: b.dataset.fltPreset }, "Filtro applicato");
    else if (b.dataset.fltAct === "reset") mutate("/api/filters", { reset: true }, "Look dello stile");
  });
  box.addEventListener("input", (e) => {
    const r = e.target.closest("[data-flt]");
    if (!r) return;
    S.txSliding = r;
    const k = r.dataset.flt;
    const v = Number(r.value);
    const fmt = FILTER_SLIDERS.find((s) => s[0] === k)[5];
    box.querySelector(`#flt-${k}-val`).textContent = fmt(v);
    const live = { ...S.data.filters.grade, [k]: v };
    video.style.filter = gradeCss(live); // anteprima dal vivo mentre trascini
    if (k === "vignette") $("#vignette").style.background = v > 0 ? `radial-gradient(ellipse at 50% 42%, transparent 48%, rgba(0,0,0,${(0.85 * v).toFixed(2)}) 100%)` : "";
  });
  box.addEventListener("change", async (e) => {
    const r = e.target.closest("[data-flt]");
    if (!r) return;
    S.txSliding = null;
    await mutate("/api/filters", { values: { [r.dataset.flt]: Number(r.value) } });
  });
}

// --- esporta: anteprima delle copertine (Shorts 9:16 e YouTube 16:9) ---------------------
// Claude propone frase e sfondo; Higgsfield genera solo quando premi Genera (costa crediti).

const COVER_PHASE = { render: "Creo la copertina…", queued: "In coda…", person: "Ti metto nella scena (Soul)…", cover: "Impagino la copertina in 4K…", download: "Scarico…", done: "Fatto" };
const COVER_LABEL = { "9:16": "Shorts · 9:16", "16:9": "YouTube · 16:9" };

function coverChosen(ratio) {
  const c = S.data?.covers;
  const list = c?.versions?.[ratio] ?? [];
  if (!list.length) return null;
  return list.find((v) => v.index === c.chosen?.[ratio]) ?? list[list.length - 1];
}

// «ME NE VADO IN» + «THAILANDIA» → «Me ne vado in Thailandia» (come un titolo YouTube)
function ytTitle(k) {
  const cap = (s) => s.toLowerCase().replace(/^./, (m) => m.toUpperCase());
  const kicker = k.kicker ? cap(k.kicker) : "";
  const title = k.title ? k.title.toLowerCase().replace(/(^|\s)\S/g, (m) => m.toUpperCase()) : "";
  return kicker && title ? `${kicker} ${title}` : cap(kicker || title);
}

function coverCard(ratio) {
  const c = S.data.covers;
  const list = c.versions[ratio] ?? [];
  const cur = coverChosen(ratio);
  const busy = c.job?.status === "running";
  const mine = busy && c.job.ratio === ratio;
  const img = cur ? `<img src="${esc(cur.url)}" alt="Copertina ${esc(COVER_LABEL[ratio])}">`
    : `<div class="cv-empty">${mine ? "" : "Nessuna copertina: premi Genera"}</div>`;
  const shell = ratio === "9:16"
    ? `<div class="cv-phone">${img}${mine ? `<div class="cv-busy"><i></i>${esc(COVER_PHASE[c.job.phase] ?? "…")}</div>` : ""}</div>`
    : `<div class="cv-yt"><div class="cv-yt-img">${img}<span class="cv-dur">${clock(S.data.summary.kept_ms, false)}</span>${mine ? `<div class="cv-busy"><i></i>${esc(COVER_PHASE[c.job.phase] ?? "…")}</div>` : ""}</div>
        <div class="cv-yt-meta"><span class="cv-avatar">${c.person.face_url ? `<img src="${esc(c.person.face_url)}" alt="">` : ""}</span>
          <div><b>${esc(ytTitle(c.concept) || "Titolo del video")}</b>
          <span>${esc(c.person.name || "Il tuo canale")} · in anteprima</span></div></div></div>`;
  const strip = list.length > 1 ? `<div class="cv-strip">${list.map((v) =>
    `<button class="${v.index === cur?.index ? "on" : ""}" data-cv-choose="${ratio}" data-i="${v.index}" title="Versione ${v.index + 1}"><img src="${esc(v.url)}" alt=""></button>`).join("")}</div>` : "";
  const tiny = cur ? `<div class="cv-tiny" title="Così si vede piccola nel feed"><img src="${esc(cur.url)}" alt=""><span>nel feed</span></div>` : "";
  const armed = S.coverArm === ratio;
  const free = c.mode === "viral";
  return `
    <div class="cv-card r${ratio.replace(":", "x")}">
      <div class="cv-head"><b>${COVER_LABEL[ratio]}</b>${list.length ? `<span class="meta">${list.length} version${list.length > 1 ? "i" : "e"}</span>` : ""}</div>
      ${shell}${strip}
      <div class="cv-actions">
        <button class="btn ${armed ? "danger" : "ai"}" data-cv-gen="${ratio}" ${busy || !c.ready ? "disabled" : ""}
          title="${!c.ready ? "Scegli prima uno stile" : free ? "Gratis, in locale" : S.aiStatus?.higgsfield !== "connected" ? "Prima ricollega Higgsfield" : ""}">
          ${free ? (cur ? "↻ Rifai copertina" : "✦ Crea copertina") : armed ? `Conferma · ${esc(c.cost_hint)}` : cur ? "↻ Rigenera" : "✦ Genera"}</button>
        ${cur ? `<a class="btn" href="${esc(cur.url)}" download="copertina-${ratio === "9:16" ? "shorts" : "youtube"}.png">⬇ Scarica</a>` : ""}
        ${tiny}
      </div>
    </div>`;
}

function exportHTML() {
  const c = S.data?.covers;
  if (!c) return `<div class="ex-box"><div class="placeholder">L'editor in esecuzione è una versione vecchia: chiudilo e rilancialo.</div></div>`;
  const k = c.concept;
  const err = c.job?.status === "error" ? `<div class="tx-hint err">Copertina non riuscita: ${esc(c.job.error)}</div>` : "";
  const notReady = !c.ready ? `<div class="cv-note"><span>Scegli uno stile per la copertina: <b>Premium</b> (Shorts + YouTube con Higgsfield) o <b>Viral</b> (verticale, fotogramma + frase d'esordio).</span>
      <span><button class="btn ai small" data-ex="premium">Premium</button> <button class="btn ai small" data-ex="viral">Viral</button></span></div>` : "";
  const st = S.aiStatus;
  const hf = !st ? `<span class="hf-dot wait"></span>Controllo Higgsfield…`
    : st.higgsfield === "connected" ? `<span class="hf-dot ok"></span>Higgsfield collegato${st.credits != null ? ` · ${Math.floor(st.credits)} crediti` : ""}`
    : `<span class="hf-dot bad"></span>Higgsfield ${st.higgsfield === "missing" ? "non installato" : "non collegato (sessione scaduta)"}
       ${st.higgsfield === "missing" ? "" : `<button class="btn small" data-ex="login" ${S.hfLogin ? "disabled" : ""}>${S.hfLogin ? "Aspetto il login nel browser…" : "Ricollega"}</button>`}`;
  const viral = c.mode === "viral";
  const SW = ["#FFB800", "#FF7A00", "#FF3B30", "#FF2D78", "#00E676", "#1FD3CF", "#2F6BFF", "#FFFFFF"];
  const accent = k.accent ?? c.accent_auto;
  const viralForm = `
          <div class="section-title">Di cosa parla il video</div>
          <textarea class="cv-in" rows="2" data-cv="topic" placeholder="es. voglio andare a vivere in Thailandia">${esc(k.topic)}</textarea>
          <button class="btn ai wide" data-ex="concept" ${S.coverThinking ? "disabled" : ""}>${S.coverThinking ? "Claude sta pensando…" : "✦ Proponi la frase d'esordio con Claude"}</button>
          <div class="section-title">Frase d'esordio</div>
          <input class="cv-in" data-cv="kicker" value="${esc(k.kicker)}" maxlength="40" placeholder="Riga piccola · es. A STO GIRO L'AVETE">
          <input class="cv-in big" data-cv="title" value="${esc(k.title)}" maxlength="28" placeholder="Riga grande · es. FATTA GROSSA">
          <input class="cv-in" data-cv="sub" value="${esc(k.sub)}" maxlength="40" placeholder="Riga piccolissima sotto · es. arrivo al locale">
          <div class="section-title">Emoji <span class="meta">(0-2, ai lati della prima riga)</span></div>
          <div class="cv-emo"><input class="cv-in" data-cv="emojis" value="${esc(k.emojis)}" maxlength="16" placeholder="es. 🤬⚠️">
            ${["😱", "🔥", "🤬", "⚠️", "😂", "💰", "🇹🇭", "✈️", "👀", "🚨"].map((e) => `<button class="chip" data-cv-emo="${e}">${emojiHTML(e)}</button>`).join("")}
            <button class="chip" data-cv-emo="">✕</button></div>
          <div class="section-title">Colore della riga piccola</div>
          <div class="cv-sw">${SW.map((h) => `<button class="sw${accent.toUpperCase() === h ? " on" : ""}" style="background:${h}" data-cv-accent="${h}" title="${h}"></button>`).join("")}
            <label class="sw pick" title="Altro colore"><input type="color" data-cv-accent-pick value="${esc(accent)}"></label></div>
          <div class="section-title">Font</div>
          <select class="cv-in" data-cv="font">${c.fonts.map((f, i) => `<option value="${i === 0 ? "" : esc(f)}" ${(k.font ?? "") === (i === 0 ? "" : f) ? "selected" : ""}>${esc(f)}${i === 0 ? " · apertura del video" : " · sottotitoli"}</option>`).join("")}</select>
          <div class="section-title">Fotogramma</div>
          <div class="cv-frame"><img src="${esc(c.frame_url)}" alt="">
            <div><div class="meta">${k.frame_ms == null ? "Apertura del video" : `a ${showTime(k.frame_ms)}`}</div>
              <button class="btn small" data-ex="frame-here" title="Usa il fotogramma dove c'è la testina">Usa la testina (${showTime(nowMs())})</button>
              ${k.frame_ms == null ? "" : `<button class="btn small" data-ex="frame-open">Torna all'apertura</button>`}</div></div>
          <div class="tx-hint">Gratis e in locale (Remotion, ~10 s): stesso font, contorno e ombra dell'apertura del video.</div>
          ${err}`;
  return `
    <div class="ex-box${viral ? " viral" : ""}" role="dialog" aria-label="Esporta">
      <div class="ex-head"><b>Esporta · Copertina</b><span class="meta">${esc(S.look?.style_name ?? "nessuno stile")}</span>
        ${viral ? `<span class="hf-state">Copertina verticale · fotogramma + frase d'esordio</span>` : `<span class="hf-state">${hf}</span>`}
        <button class="icon-btn" data-ex="close" title="Chiudi (Esc)">✕</button></div>
      ${notReady}
      <div class="ex-body">
        <div class="ex-form">${viral ? viralForm : `
          <div class="cv-person">
            <span class="cv-face">${c.person.face_url ? `<img src="${esc(c.person.face_url)}" alt="">` : "🙂"}</span>
            <div><input class="cv-in" data-cv-person="name" value="${esc(c.person.name)}" placeholder="Nome (tuo o del cliente)">
              <input class="cv-in small" data-cv-person="soul_id" value="${esc(c.person.soul_id ?? "")}" placeholder="Soul ID su Higgsfield (facoltativo)"></div>
            <button class="btn small" data-ex="face" title="Foto frontale del volto: tiene la stessa identità">Foto volto</button>
            <input type="file" id="cv-face-file" accept="image/*" hidden>
          </div>
          <div class="section-title">Di cosa parla il video</div>
          <textarea class="cv-in" rows="2" data-cv="topic" placeholder="es. voglio andare a vivere in Thailandia">${esc(k.topic)}</textarea>
          <button class="btn ai wide" data-ex="concept" ${S.coverThinking ? "disabled" : ""}>${S.coverThinking ? "Claude sta pensando…" : "✦ Proponi frase e sfondo con Claude"}</button>
          <div class="section-title">Frase</div>
          <input class="cv-in" data-cv="kicker" value="${esc(k.kicker)}" maxlength="40" placeholder="Riga piccola · es. ME NE VADO IN">
          <input class="cv-in big" data-cv="title" value="${esc(k.title)}" maxlength="28" placeholder="Scritta grande · es. THAILANDIA">
          <div class="section-title">Sfondo <span class="meta">(in inglese per Higgsfield)</span></div>
          <textarea class="cv-in" rows="3" data-cv="scene" placeholder="Krabi, Thailand at golden hour — limestone cliffs, turquoise water, a longtail boat">${esc(k.scene)}</textarea>
          <div class="section-title">Espressione e vestiti</div>
          <input class="cv-in" data-cv="expression" value="${esc(k.expression)}">
          <input class="cv-in" data-cv="wardrobe" value="${esc(k.wardrobe)}" placeholder="es. open-collar cream linen shirt">
          <div class="tx-hint">Genera costa ${esc(c.cost_hint)} (Higgsfield): parte solo quando confermi.</div>
          ${err}`}
        </div>
        <div class="ex-previews">${(c.ratios ?? ["9:16", "16:9"]).map(coverCard).join("")}</div>
      </div>
      <div class="ex-foot">${exportFoot()}</div>
    </div>`;
}

// Video intero: render con tutto quello che hai fatto, copertina scelta dentro il file.
function exportFoot() {
  const x = S.data?.export;
  const job = x?.job ?? {};
  if (job.status === "running") {
    const secs = Math.round(Date.now() / 1000 - (job.started ?? Date.now() / 1000));
    return `<span class="ex-run"><i></i><span><b>Esporto il video… ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}</b>
      <span class="meta">${esc(job.phase === "cover" ? "metto la copertina nel file" : job.log || "render con Remotion: qualche minuto")}</span></span></span>
      <button class="btn export" disabled>Esportazione in corso</button>`;
  }
  const err = job.status === "error" ? `<span class="tx-hint err">Esportazione non riuscita: ${esc(job.error)}</span>` : "";
  const last = x?.last ? `<a class="btn" href="${esc(x.last.url)}" download="${esc(x.last.name)}">⬇ Scarica ${esc(x.last.name)} (${String(x.last.mb).replace(".", ",")} MB)</a>` : "";
  const cov = coverChosen(S.portrait ? "9:16" : "16:9");
  return `${err || `<span class="tx-hint">${cov ? "La copertina scelta va dentro il file MP4." : "Senza copertina scelta il video esce senza miniatura."} Tagli, testo, sticker, immagini, effetti, audio e filtri: tutto come nell'editor.</span>`}
    <span class="ex-actions">${last}<button class="btn export" data-ex="video" ${S.data?.style ? "" : "disabled"}>⬆ Esporta video</button></span>`;
}

function renderExport() {
  const m = $("#export-modal");
  if (!m || m.hidden) return;
  if (m.contains(document.activeElement) && document.activeElement.matches("input, textarea")) return; // stai scrivendo
  m.innerHTML = exportHTML();
}

function openExport() {
  video.pause();
  const m = $("#export-modal");
  m.hidden = false;
  m.innerHTML = exportHTML();
  const c = S.data?.covers;
  loadAiStatus(true).then(renderExport);
  if (c?.ready && !c.concept.title && !S.coverThinking) coverConcept(); // prima volta: Claude propone
}

// Mentre esporta: aggiorna il tempo ogni secondo e lo stato ogni 4 (polling generale).
function exportTicker() {
  clearInterval(S.exportTimer);
  S.exportTimer = setInterval(() => {
    if (S.data?.export?.job?.status !== "running") { clearInterval(S.exportTimer); renderExport(); return; }
    const foot = $("#export-modal .ex-foot");
    if (foot) foot.innerHTML = exportFoot();
  }, 1000);
}

// Ricollega Higgsfield: si apre il login nel browser; ricontrollo finché non è collegato.
async function hfLogin() {
  try {
    await api("/api/higgsfield/login", {});
  } catch (e) {
    toast(`Non riesco ad aprire il login: ${e.message}`, true);
    return;
  }
  S.hfLogin = true;
  renderExport();
  toast("Si è aperto il login di Higgsfield nel browser: accedi e torna qui");
  for (let i = 0; i < 60 && S.hfLogin; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    await loadAiStatus(true);
    if (S.aiStatus?.higgsfield === "connected") break;
  }
  S.hfLogin = false;
  renderExport();
  if (S.aiStatus?.higgsfield === "connected") toast("Higgsfield collegato");
}

function closeExport() {
  $("#export-modal").hidden = true;
  S.coverArm = null;
}

async function coverConcept() {
  const hint = $("#export-modal [data-cv=topic]")?.value ?? "";
  S.coverThinking = true;
  renderExport();
  try {
    apply(await api("/api/covers/concept", { hint }));
    toast("Frase e sfondo proposti da Claude: cambiali come vuoi");
  } catch (e) {
    toast(`Claude non ha risposto: ${e.message}`, true);
  } finally {
    S.coverThinking = false;
    document.activeElement?.blur?.();
    renderExport();
  }
}

async function saveCover(extra) {
  const f = coverFields();
  await mutate("/api/covers/save", { ...f, concept: { ...f.concept, ...extra } });
  document.activeElement?.blur?.();
  renderExport();
}

function coverFields() {
  const m = $("#export-modal");
  const concept = {};
  m.querySelectorAll("[data-cv]").forEach((el) => { concept[el.dataset.cv] = el.value; });
  const person = {};
  m.querySelectorAll("[data-cv-person]").forEach((el) => { person[el.dataset.cvPerson] = el.value.trim() || null; });
  return { concept, person };
}

function wireExport() {
  const m = $("#export-modal");
  $("#btn-export").addEventListener("click", openExport);
  m.addEventListener("click", async (e) => {
    if (e.target === m) { closeExport(); return; }
    const b = e.target.closest("[data-ex],[data-cv-gen],[data-cv-choose],[data-cv-emo],[data-cv-accent]");
    if (!b || b.disabled) return;
    const d = b.dataset;
    if (d.ex === "close") closeExport();
    else if (d.ex === "premium") { await mutate("/api/style", { id: "premium" }, "Stile Premium"); renderExport(); }
    else if (d.ex === "viral") { await mutate("/api/style", { id: "viral" }, "Stile Viral"); renderExport(); }
    else if (d.ex === "frame-here") { await saveCover({ frame_ms: Math.round(nowMs()) }); }
    else if (d.ex === "frame-open") { await saveCover({ frame_ms: null }); }
    else if ("cvEmo" in d) {
      const inp = m.querySelector("[data-cv=emojis]");
      const cur = emojiParts(inp.value);
      inp.value = d.cvEmo === "" ? "" : [...cur, d.cvEmo].slice(-2).join("");
      await saveCover({ emojis: inp.value });
    } else if (d.cvAccent) { await saveCover({ accent: d.cvAccent }); }
    else if (d.ex === "login") hfLogin();
    else if (d.ex === "video") { await mutate("/api/export/video", {}, "Esportazione avviata: ci vuole qualche minuto"); exportTicker(); }
    else if (d.ex === "concept") coverConcept();
    else if (d.ex === "face") m.querySelector("#cv-face-file").click();
    else if (d.cvChoose) mutate("/api/covers/choose", { ratio: d.cvChoose, index: Number(d.i) }).then(renderExport);
    else if (d.cvGen && S.data?.covers?.mode === "viral") {
      await mutate("/api/covers/save", coverFields());
      await mutate("/api/covers/generate", { ratio: d.cvGen }, "Creo la copertina…");
      renderExport();
    } else if (d.cvGen) {
      if (S.coverArm !== d.cvGen) { // primo clic: chiede conferma (costa crediti)
        S.coverArm = d.cvGen;
        renderExport();
        setTimeout(() => { if (S.coverArm === d.cvGen) { S.coverArm = null; renderExport(); } }, 5000);
        return;
      }
      S.coverArm = null;
      if (S.aiStatus?.higgsfield !== "connected") {
        await loadAiStatus(true);
        if (S.aiStatus?.higgsfield !== "connected") { toast("Higgsfield non è collegato: premi Ricollega", true); renderExport(); return; }
      }
      await mutate("/api/covers/save", coverFields());
      await mutate("/api/covers/generate", { ratio: d.cvGen }, "Genero la copertina con Higgsfield…");
      renderExport();
    }
  });
  m.addEventListener("change", async (e) => {
    if (e.target.id === "cv-face-file") {
      const f = e.target.files?.[0];
      e.target.value = "";
      if (!f) return;
      const fr = new FileReader();
      fr.onload = async () => { await mutate("/api/covers/face", { data: fr.result, name: f.name }, "Foto del volto salvata"); renderExport(); };
      fr.readAsDataURL(f);
      return;
    }
    if (e.target.matches("[data-cv-accent-pick]")) { await saveCover({ accent: e.target.value.toUpperCase() }); return; }
    if (e.target.matches("[data-cv],[data-cv-person]")) {
      await mutate("/api/covers/save", coverFields());
    }
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !m.hidden) { e.preventDefault(); e.stopImmediatePropagation(); closeExport(); }
  }, true);
}

// --- audio: voce, effetti sonori, suoni nella timeline (pannello Audio) ------------------
// I suoni li sceglie lo stile; qui si alzano, si abbassano, si spostano, si cambiano, se ne
// aggiungono. L'anteprima li suona con la stessa normalizzazione della voce del render.

const SND = { ctx: null, voice: null, out: null, buffers: new Map(), playing: [], prev: null };

const audioData = () => S.data?.audio ?? null;
const soundItem = (id) => (audioData()?.sounds ?? []).find((s) => s.id === id) ?? null;
const dbTxt = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(Math.round(v * 10) / 10).toString().replace(".", ",")} dB`;
const FAMILY_ICON = { whooshes: "💨", textures: "✨", risers: "📈", hits: "💥" };

function ensureAudio() {
  if (SND.ctx) { if (SND.ctx.state === "suspended") SND.ctx.resume(); return; }
  if (!window.AudioContext) return;
  try {
    const ctx = new AudioContext();
    const lim = ctx.createDynamicsCompressor(); // limitatore come nel render
    lim.threshold.value = -2; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.002; lim.release.value = 0.12;
    lim.connect(ctx.destination);
    const voice = ctx.createGain();
    ctx.createMediaElementSource(video).connect(voice);
    voice.connect(lim);
    Object.assign(SND, { ctx, voice, out: lim });
    applyVoiceGain();
  } catch (e) {
    console.warn("audio dell'anteprima non disponibile", e);
  }
}

function applyVoiceGain(liveDb) {
  const a = audioData();
  if (!a) return;
  const db = (a.voice_norm_db ?? 0) + (liveDb ?? a.voice_db);
  const g = a.voice_muted || BR.duck ? 0 : Math.pow(10, db / 20); // BR.duck: parla un voice-over
  if (SND.voice) SND.voice.gain.value = g;
  else video.volume = Math.max(0, Math.min(1, g));
}

function sndBuffer(url) {
  if (!SND.buffers.has(url)) {
    SND.buffers.set(url, fetch(url).then((r) => r.arrayBuffer()).then((b) => SND.ctx.decodeAudioData(b)));
  }
  return SND.buffers.get(url);
}

function playUrl(url, gainDb, offsetMs = 0) {
  ensureAudio();
  if (!SND.ctx) return;
  sndBuffer(url).then((buf) => {
    const src = SND.ctx.createBufferSource();
    src.buffer = buf;
    const g = SND.ctx.createGain();
    g.gain.value = Math.pow(10, gainDb / 20);
    src.connect(g);
    g.connect(SND.out);
    src.start(0, Math.max(0, offsetMs / 1000));
    SND.playing.push(src);
    src.onended = () => { SND.playing = SND.playing.filter((x) => x !== src); };
  }).catch(() => {});
}

function stopSounds() {
  SND.playing.forEach((s) => { try { s.stop(); } catch { /* già finito */ } });
  SND.playing = [];
}

// Suona gli effetti quando la testina li attraversa (anche saltando le parti tolte).
function updateSounds(cur) {
  const a = audioData();
  if (video.paused || !a || !SND.ctx) { SND.prev = null; return; }
  const prev = SND.prev;
  SND.prev = cur;
  if (prev === null || cur <= prev) return;
  for (const s of a.sounds) {
    if (s.muted) continue;
    const start = s.at_ms - s.lead_ms;
    const late = S.mode === "edited" && isCut(start); // l'attacco cade in una parte tolta
    const trig = late ? s.at_ms : start;
    if (prev < trig && trig <= cur && cur - trig < 350) playUrl(s.url, s.gain_db, cur - trig + (late ? s.lead_ms : 0));
  }
}

function renderAudioTrack() {
  const el = $("#track-audio");
  const a = audioData();
  if (!el) return;
  if (!a) { el.innerHTML = ""; return; }
  el.innerHTML = a.sounds.map((s) => {
    const left = xOf(s.at_ms - s.lead_ms);
    const width = Math.max(10, (s.duration_ms / 1000) * S.pps);
    const cls = ["snd", `f-${s.family}`, s.muted ? "muted" : "", s.id === S.sndSel ? "sel" : "", s.origin === "user" ? "user" : "", isCut(s.at_ms) ? "cut" : ""].join(" ");
    return `<div class="${cls}" data-snd="${esc(s.id)}" style="left:${left}px;width:${width}px" title="${esc(s.label)} · ${esc(s.reason)} · ${dbTxt(s.gain_db)}${s.muted ? " · muto" : ""}">
      <i>${FAMILY_ICON[s.family] ?? "♪"}</i><span>${width > 46 ? esc(s.label) : ""}</span></div>`;
  }).join("") + musicTrackHTML() + (a.voice_muted ? `<div class="snd-note">voce muta</div>` : "");
}

function selectSound(id, { open = true } = {}) {
  S.sndSel = id;
  renderAudioTrack();
  if (!open) return;
  if (S.viewer) toggleViewerPanel(true, "audio");
  else if (S.leftTab !== "audio") { S.leftTab = "audio"; renderLeft(); }
  else renderTextPanels();
}

const saveAudio = (body, msg) => mutate("/api/audio", body, msg);

function audioPanelHTML() {
  const a = audioData();
  if (!a) {
    return `<div class="placeholder"><b>Audio</b><br>L'editor in esecuzione è una versione vecchia.
      Chiudilo (Ctrl+C nel terminale) e rilancia <code>autocut editor ${esc(S.data?.project ?? "")}</code>.</div>`;
  }
  const slider = (key, val, min, max) => `
    <input type="range" class="tx-range" data-au-range="${key}" min="${min * 10}" max="${max * 10}" step="5" value="${Math.round(val * 10)}">`;
  const sel = soundItem(S.sndSel);
  const lib = a.library ?? [];
  let selBox = "";
  if (sel) {
    const opts = lib.map((l) => `<option value="${esc(l.type)}" ${l.type === sel.type ? "selected" : ""}>${esc(l.family_label)} · ${esc(l.label)}</option>`).join("");
    selBox = `
      <div class="st-sel">
        <div class="st-sel-head"><span class="st-thumb">${FAMILY_ICON[sel.family] ?? "♪"}</span><div><b>${esc(sel.label)}</b>
          <div class="meta">a ${showTime(sel.at_ms)} · ${esc(sel.reason)}${sel.origin === "auto" ? " · scelto dallo stile" : ""}</div></div>
          <button class="icon-btn" data-au="close" title="Deseleziona">✕</button></div>
        <div class="btn-row tx-actions">
          <button class="btn" data-au="play">▶ Ascolta</button>
          <button class="btn${sel.own_muted ? " on" : ""}" data-au="mute">${sel.own_muted ? "🔇 Muto" : "🔊 Attivo"}</button>
          <button class="btn" data-au="here" title="Il suono parte dove c'è la testina">Sposta qui</button>
          <button class="btn" data-au="left" title="0,1 s prima">◀</button><button class="btn" data-au="right" title="0,1 s dopo">▶</button>
        </div>
        <div class="section-title">Volume di questo suono <span class="tx-val" id="au-snd-val">${dbTxt(sel.offset_db)}</span></div>
        ${slider("snd", sel.offset_db, -30, 12)}
        <div class="section-title">Cambia suono</div>
        <select class="au-select" data-au-type>${opts}</select>
        <div class="btn-row tx-actions">
          ${sel.origin === "user" ? `<button class="btn danger" data-au="delete">Elimina</button>`
            : sel.edited ? `<button class="btn" data-au="reset">Torna com'era</button>` : ""}
        </div>
        <div class="tx-hint">Puoi anche trascinarlo nella traccia audio della timeline.</div>
      </div>`;
  }
  const list = a.sounds.map((s) => `
    <button class="st-item${s.id === S.sndSel ? " on" : ""}${s.muted ? " dim" : ""}" data-au-pick="${esc(s.id)}">
      <span class="t-ico on">${FAMILY_ICON[s.family] ?? "♪"}</span>
      <span class="st-item-t">${showTime(s.at_ms)} · ${esc(s.label)}
        <span class="meta">${s.muted ? "muto · " : ""}${dbTxt(s.gain_db)} · ${esc(s.reason)}</span></span>
    </button>`).join("");
  const fams = {};
  for (const l of lib) (fams[l.family_label] ??= []).push(l);
  const libHTML = Object.entries(fams).map(([fam, items]) => `
    <div class="st-sub">${esc(fam)}</div>
    <div class="au-lib">${items.map((l) => `
      <div class="au-lib-item" title="${esc(l.usage)}">
        <button class="icon-btn" data-au-lib-play="${esc(l.url)}" title="Ascolta">▶</button>
        <span>${esc(l.label)}</span>
        <button class="btn small" data-au-add="${esc(l.type)}" title="Aggiungi alla testina">+ Aggiungi</button>
      </div>`).join("")}</div>`).join("");
  return `
    ${selBox}
    <div class="au-card">
      <div class="au-head"><b>🎙 Voce</b>
        <button class="chip${a.voice_muted ? " on" : ""}" data-au="voice-mute">${a.voice_muted ? "🔇 Muta" : "🔊 Attiva"}</button></div>
      <div class="section-title">Volume <span class="tx-val" id="au-voice_db-val">${dbTxt(a.voice_db)}</span></div>
      ${slider("voice_db", a.voice_db, -24, 12)}
      <div class="tx-hint">${a.voice_norm_db ? `Già portata al livello del render (${dbTxt(a.voice_norm_db)}): qui la alzi o abbassi rispetto a quello.` : "Rispetto al livello normalizzato del render."}</div>
    </div>
    <div class="au-card">
      <div class="au-head"><b>✨ Effetti sonori</b>
        <button class="chip${a.sfx_muted ? " on" : ""}" data-au="sfx-mute">${a.sfx_muted ? "🔇 Tutti muti" : "🔊 Attivi"}</button></div>
      <div class="section-title">Volume di tutti <span class="tx-val" id="au-sfx_db-val">${dbTxt(a.sfx_db)}</span></div>
      ${slider("sfx_db", a.sfx_db, -30, 12)}
      ${a.style ? "" : `<div class="tx-hint">Scegli uno stile (Viral o Premium) per avere i suoni automatici.</div>`}
    </div>
    ${voiceCardHTML()}
    ${musicCardHTML()}
    <div class="st-sub">Suoni nel video (${a.sounds.length})</div>
    <div class="st-list">${list || `<div class="tx-hint">Nessun suono: aggiungine uno qui sotto.</div>`}</div>
    <div class="section-title" style="margin-top:14px">Aggiungi un suono alla testina (${showTime(nowMs())})</div>
    ${libHTML || `<div class="tx-hint">Libreria suoni vuota (library/sfx).</div>`}`;
}

function wireAudioPanel(box) {
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-au],[data-au-pick],[data-au-add],[data-au-lib-play]");
    if (!b || b.disabled) return;
    const d = b.dataset;
    if (d.auLibPlay) { playUrl(d.auLibPlay, -12); return; }
    if (d.auPick) {
      const s = soundItem(d.auPick);
      if (s) { video.pause(); seekMs(s.at_ms - s.lead_ms - 400); }
      selectSound(d.auPick);
      return;
    }
    if (d.auAdd) {
      video.pause();
      const before = new Set((audioData()?.sounds ?? []).map((s) => s.id));
      await saveAudio({ target: "add", fields: { type: d.auAdd, at_ms: Math.round(nowMs()) } }, "Suono aggiunto alla testina");
      const added = (audioData()?.sounds ?? []).find((s) => !before.has(s.id));
      if (added) selectSound(added.id);
      return;
    }
    const a = audioData();
    const sel = soundItem(S.sndSel);
    switch (d.au) {
      case "voice-mute": saveAudio({ target: "mix", fields: { voice_muted: !a.voice_muted } }); break;
      case "sfx-mute": saveAudio({ target: "mix", fields: { sfx_muted: !a.sfx_muted } }); break;
      case "close": S.sndSel = null; renderTextPanels(); renderAudioTrack(); break;
      case "play": if (sel) playUrl(sel.url, sel.gain_db); break;
      case "mute": if (sel) saveAudio({ target: "sound", item: sel.id, fields: { muted: !sel.own_muted } }); break;
      case "here": if (sel) saveAudio({ target: "sound", item: sel.id, fields: { shift_ms: Math.round(nowMs() + sel.lead_ms - sel.at_ms) } }, "Suono spostato"); break;
      case "left": if (sel) saveAudio({ target: "sound", item: sel.id, fields: { shift_ms: -100 } }); break;
      case "right": if (sel) saveAudio({ target: "sound", item: sel.id, fields: { shift_ms: 100 } }); break;
      case "delete": if (sel) { S.sndSel = null; saveAudio({ target: "remove", item: sel.id }, "Suono eliminato"); } break;
      case "reset": if (sel) saveAudio({ target: "reset", item: sel.id }, "Suono com'era"); break;
    }
  });
  box.addEventListener("input", (e) => {
    const r = e.target.closest("[data-au-range]");
    if (!r) return;
    S.txSliding = r;
    const k = r.dataset.auRange;
    const v = Number(r.value) / 10;
    box.querySelector(`#au-${k}-val`).textContent = dbTxt(v);
    if (k === "voice_db") applyVoiceGain(v);
  });
  box.addEventListener("change", async (e) => {
    const t = e.target.closest("[data-au-type]");
    if (t && S.sndSel) { saveAudio({ target: "sound", item: S.sndSel, fields: { type: t.value } }, "Suono cambiato"); return; }
    const r = e.target.closest("[data-au-range]");
    if (!r) return;
    S.txSliding = null;
    const k = r.dataset.auRange;
    const v = Number(r.value) / 10;
    if (k === "snd") { if (S.sndSel) await saveAudio({ target: "sound", item: S.sndSel, fields: { gain_db: v } }); }
    else await saveAudio({ target: "mix", fields: { [k]: v } });
    const s = soundItem(S.sndSel);
    if (k === "snd" && s) playUrl(s.url, s.gain_db); // senti subito il nuovo volume
  });
}

// --- tagli a mano: dividi alla testina, togli o rimetti un pezzo --------------------------

function pieceKey(p) { return p ? `${p.start}-${p.end}` : ""; }

function selectPiece(start, end, manual) {
  S.piece = { start, end, manual };
  S.selected = null;
  renderRanges();
  updateToggle();
}

async function splitHere() {
  const ms = Math.round(nowMs());
  video.pause();
  const data = await mutate("/api/cuts", { action: "split", ms }, "Diviso: clicca un pezzo e premi Togli (Canc)");
  if (!data) return;
  // seleziona il pezzo dopo la divisione, pronto da togliere
  const piece = visiblePieces().find((p) => p.start === ms && p.keep);
  if (piece) selectPiece(piece.start, piece.end, false);
}

function togglePiece() {
  const p = S.piece;
  if (!p) return;
  S.piece = null;
  if (p.manual) mutate("/api/cuts", { action: "restore", start: p.start, end: p.end }, "Pezzo rimesso");
  else mutate("/api/cuts", { action: "remove", start: p.start, end: p.end }, "Pezzo tolto");
}

// Pezzi come si vedono nella traccia video: le parti tenute divise ai punti di divisione.
function visiblePieces() {
  const splits = S.data?.cuts?.splits ?? [];
  const out = [];
  S.eff.forEach((r, i) => {
    if (r.state !== "keep") { out.push({ i, start: r.start_ms, end: r.end_ms, keep: false, r }); return; }
    let a = r.start_ms;
    for (const s of splits) {
      if (s > a + 20 && s < r.end_ms - 20) { out.push({ i, start: a, end: s, keep: true, r }); a = s; }
    }
    out.push({ i, start: a, end: r.end_ms, keep: true, r });
  });
  return out;
}

function openCaptionEditor(i) {
  const c = S.chunks[i];
  if (!c) return;
  video.pause();
  seekMs(c.start + 30);
  S.txChunk = i;
  S.txScope = "scene";
  S.txSel = true;
  S.popSel = null;
  if (S.viewer) toggleViewerPanel(true, "text");
  else if (S.leftTab !== "text") { S.leftTab = "text"; renderLeft(); }
  else renderTextPanels();
  renderTextTrack();
  setTimeout(() => {
    const ta = (S.viewer ? $("#viewer-panel") : $("#left-content")).querySelector("#tx-text");
    if (ta && !ta.disabled) { ta.focus(); ta.select(); }
  }, 30);
}

// --- immagini: cerca sul web, scontorna, metti nel video (pannello Immagini) ------------
// Solo l'utente mette le immagini: Claude non le inserisce mai da solo.

const IMG_PHASE = {
  queued: "In coda…", reading: "Leggo il file…", downloading: "Scarico la foto…",
  model: "Scarico il modello per scontornare (solo la prima volta)", loading: "Preparo lo scontorno…",
  cutting: "Scontorno…", done: "Fatto",
};  // prettier-ignore
const IMG_HINTS = ["Francesco Totti", "Leonardo DiCaprio", "Lamborghini Urus", "Colosseo"];

const isPhoto = (p) => Boolean(p?.image && p.image.startsWith("images/"));

function imgJobLine(j) {
  const pct = j.progress != null ? Math.round(j.progress * 100) : null;
  const what = j.status === "error" ? `Non riuscito: ${j.error}` : `${IMG_PHASE[j.phase] ?? "…"}${pct != null ? ` ${pct}%` : ""}`;
  return `
    <div class="img-job${j.status === "error" ? " err" : ""}">
      ${j.thumb ? `<img src="${esc(j.thumb)}" alt="">` : `<span class="st-thumb">🖼</span>`}
      <div class="img-job-t"><b>${esc(j.title || "Immagine")}</b><span class="meta">${esc(what)}</span>
        ${j.status === "error" ? "" : `<div class="img-bar"><i style="width:${pct ?? 35}%" class="${pct == null ? "indef" : ""}"></i></div>`}</div>
      ${j.status === "error" ? `<button class="icon-btn" data-img-act="drop-job" data-v="${esc(j.id)}" title="Chiudi">✕</button>` : ""}
    </div>`;
}

// --- Genera con Higgsfield: effetti AI dentro la ripresa vera (skill higgsfield-vfx) ----
// La clip AI sostituisce il video per quei secondi; la voce resta l'originale.
const vfxData = () => S.data?.vfx ?? { shots: [], max_ms: 3000, qualities: {}, ref_credits: 0 };
const VFX_SPARK = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3 1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/></svg>`;
const vfxSec = (ms) => `${(ms / 1000).toFixed(1).replace(".", ",")} s`;

function vfxForm() {
  S.vfx ??= { dur: 3000, protect: true, quality: "auto", text: "", at: null, sel: null, answers: {} };
  return S.vfx;
}

// costo indicativo di una clip: la ricetta scelta da Claude, oppure la qualità manuale
function vfxCost(s) {
  const v = vfxData();
  if (s.quality === "auto" && s.recipe && v.recipes?.[s.recipe]) return v.recipes[s.recipe].credits;
  return v.qualities[s.quality]?.credits ?? 12;
}

const VFX_PROTECT = {
  person: "persona vera rimessa sopra",
  head: "testa vera rimessa sopra",
  none: "persona dell'AI",
};

function vfxCard(s) {
  const f = vfxForm();
  const span = `${clock(s.start_ms)} → ${clock(s.start_ms + s.dur_ms)}`;
  const credits = (s.credits ? ` · ${String(s.credits).replace(".", ",")} crediti` : "") + (s.usd ? ` · ${String(s.usd).replace(".", ",")} $ API` : "");
  let body = "";
  if (s.status === "running") {
    body = `<div class="vfx-run"><i></i><span><b>${esc(s.phase_label)}…</b></span></div>`;
  } else if (s.status === "asking") {
    const qs = s.plan?.questions ?? [];
    const ans = f.answers[s.id] ?? [];
    body = `<div class="vfx-ask"><div class="meta">Prima di spendere crediti Claude vuole sapere:</div>
      ${qs.map((q, i) => `<label>${esc(q)}<input type="text" data-q="${i}" data-id="${esc(s.id)}" maxlength="300" value="${esc(ans[i] ?? "")}"></label>`).join("")}
      <div class="acts"><button class="btn vfx-go" data-vfx="answer" data-id="${esc(s.id)}">${VFX_SPARK} Rispondi e genera</button>
      <button class="btn" data-vfx="skip" data-id="${esc(s.id)}" title="Claude decide da solo quello che manca">Genera così</button></div></div>`;
  } else if (s.status === "error") {
    body = `<div><span class="vfx-badge error">Non riuscita</span></div><div class="tx-hint err">${esc(s.error)}</div>`;
  } else {
    const rv = s.review ?? {};
    const badge = { ok: ["ok", "Revisione: ok"], retry: ["retry", "Da correggere"], fail: ["fail", "Non va bene"] }[rv.verdict] ?? ["q", "Senza revisione"];
    body = `${s.final_url ? `<video src="${esc(s.final_url)}" controls loop muted playsinline preload="metadata"></video>` : ""}
      <div><span class="vfx-badge ${badge[0]}">${badge[1]}</span></div>
      ${(rv.issues ?? []).length ? `<ul class="vfx-issues">${rv.issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${s.sheet_url ? `<details><summary class="meta">Prima / dopo</summary><a href="${esc(s.sheet_url)}" target="_blank"><img class="vfx-sheet" src="${esc(s.sheet_url)}" alt="prima e dopo"></a></details>` : ""}`;
  }
  const risk = s.plan?.risk ? `<div class="vfx-risk">⚠ ${esc(s.plan.risk)}</div>` : "";
  const fid = s.plan?.fidelity ? ` (fedeltà ${String(s.plan.fidelity.median).replace(".", ",")})` : "";
  const pm = s.plan?.protect_mode;
  const mode = s.plan?.mode === "direct" && pm !== "none" ? ` · clip AI diretta${fid}` : pm ? ` · ${VFX_PROTECT[pm] ?? pm}${pm === "person" ? fid : ""}` : "";
  const recipe = s.plan?.recipe_label ? `<div class="vfx-recipe">${VFX_SPARK} ${esc(s.plan.recipe_label)}</div>` : "";
  const cost = vfxCost(s);
  const acts = s.status === "running" || s.status === "asking" ? (s.status === "asking" ? `<div class="acts"><button class="btn" data-vfx="del" data-id="${esc(s.id)}">Elimina</button></div>` : "") : `<div class="acts">
      ${s.final_url ? `<button class="btn ${s.enabled ? "" : "vfx-go"}" data-vfx="${s.enabled ? "off" : "on"}" data-id="${esc(s.id)}">${s.enabled ? "Togli dalla timeline" : "⬇ Metti in timeline"}</button>` : ""}
      <button class="btn" data-vfx="seek" data-id="${esc(s.id)}">Vai al punto</button>
      ${s.review?.fix_prompt ? `<button class="btn" data-vfx="fix" data-id="${esc(s.id)}" title="Rigenera con il prompt corretto da Claude">Rigenera corretta · ${cost} cr.</button>` : ""}
      <button class="btn" data-vfx="again" data-id="${esc(s.id)}" title="Stesso prompt, nuova versione">Rigenera · ${cost} cr.</button>
      <button class="btn" data-vfx="del" data-id="${esc(s.id)}">Elimina</button>
    </div>`;
  return `<div class="vfx-card${f.sel === s.id ? " sel" : ""}" data-card="${esc(s.id)}">
    <div class="top"><b>${esc(s.title || s.request.slice(0, 48))}</b><span class="meta">${span}</span></div>
    <div class="meta">«${esc(s.request.slice(0, 160))}»${mode}${credits}${s.attempt > 1 ? ` · tentativo ${s.attempt}` : ""}</div>
    ${recipe}${body}${risk}${acts}</div>`;
}

function vfxPanelHTML() {
  const v = vfxData();
  const f = vfxForm();
  const at = f.at ?? nowMs();
  const running = v.shots.some((s) => s.status === "running");
  const auto = f.quality === "auto";
  const q = v.qualities[f.quality] ?? { credits: 12 };
  const opts = Object.entries(v.qualities).sort(([a], [b]) => (a === "auto" ? -1 : b === "auto" ? 1 : 0)).map(([k, x]) =>
    `<option value="${k}"${k === f.quality ? " selected" : ""}>${esc(x.label)}${x.usd || k === "auto" ? "" : ` · ${x.credits} crediti`}</option>`).join("");
  const costs = Object.values(v.recipes ?? {}).map((r) => r.credits);
  const range = costs.length ? `${String(Math.min(...costs)).replace(".", ",")}–${String(Math.max(...costs)).replace(".", ",")} crediti` : "circa 12 crediti";
  const label = auto ? `Genera · ${range}` : `Genera · ${q.usd ? `circa ${String(q.usd).replace(".", ",")} $` : `circa ${q.credits} crediti`}`;
  const recipes = Object.values(v.recipes ?? {}).map((r) => `<li>${esc(r.label)} · ~${String(r.credits).replace(".", ",")} cr.</li>`).join("");
  const list = v.shots.slice().reverse().map(vfxCard).join("");
  return `<div class="vfx-panel">
    <h4>${VFX_SPARK}<span>Genera con <b>Higgsfield</b></span></h4>
    <p class="tx-hint">Scrivi cosa vuoi in questo punto, come lo diresti a un regista. Claude completa la richiesta (camera, tono, azione, luce, texture), ti fa una domanda se manca qualcosa, sceglie il modello migliore ed economico, genera, porta la clip a 1080p e la rivede. La tua voce resta sempre quella vera.</p>
    <div class="vfx-at"><span>Parte da <b>${clock(at)}</b>${f.at === null ? " (testina)" : ""}</span>
      <button class="btn" data-vfx="here">Usa la testina</button></div>
    <label class="vfx-row">Durata <input type="range" id="vfx-dur" min="500" max="${v.max_ms}" step="100" value="${f.dur}"><b>${vfxSec(f.dur)}</b></label>
    <textarea id="vfx-text" maxlength="1200" placeholder="es. dietro di me compare un dragone cinese che sputa fuoco · mettimi una giacca di pelle nera · trasformami in un alieno">${esc(f.text)}</textarea>
    <button class="btn vfx-go" data-vfx="go"${running ? " disabled" : ""}>${VFX_SPARK} ${running ? "Sto generando…" : label}</button>
    ${auto && recipes ? `<details class="vfx-adv"><summary class="meta">Cosa sa fare</summary><ul class="vfx-recipes">${recipes}</ul></details>` : ""}
    <details class="vfx-adv"${auto ? "" : " open"}><summary class="meta">Avanzate</summary>
      <label class="vfx-row">Qualità <select id="vfx-quality">${opts}</select><span></span></label>
      <label class="vfx-chk"><input type="checkbox" id="vfx-protect"${f.protect ? " checked" : ""}><span><b>Proteggi la persona</b><br><span class="tx-hint">Lascia acceso: Claude rimette sopra la tua persona vera (o solo la testa quando cambia i vestiti). Spegnilo solo se vuoi che l'AI ridisegni anche te.</span></span></label>
    </details>
    <div class="vfx-list">${list || `<div class="tx-hint">Nessuna clip AI ancora.</div>`}</div>
  </div>`;
}

function openVfx(id) {
  const f = vfxForm();
  f.sel = id;
  if (S.viewer) toggleViewerPanel(true, "vfx");
  else if (S.leftTab !== "vfx") { S.leftTab = "vfx"; renderLeft(); }
  else renderTextPanels();
  renderVfxTrack();
  requestAnimationFrame(() => document.querySelector(`.vfx-card[data-card="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" }));
}

function wireVfxPanel(box) {
  box.addEventListener("input", (e) => {
    const f = vfxForm();
    if (e.target.id === "vfx-text") f.text = e.target.value;
    else if (e.target.dataset.q !== undefined) {
      const a = (f.answers[e.target.dataset.id] ??= []);
      a[Number(e.target.dataset.q)] = e.target.value;
    } else if (e.target.id === "vfx-dur") {
      f.dur = Number(e.target.value);
      const b = e.target.parentElement.querySelector("b");
      if (b) b.textContent = vfxSec(f.dur);
    }
  });
  box.addEventListener("change", (e) => {
    const f = vfxForm();
    if (e.target.id === "vfx-protect") f.protect = e.target.checked;
    else if (e.target.id === "vfx-quality") { f.quality = e.target.value; renderTextPanels(); }
  });
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-vfx]");
    if (!b || !box.contains(b)) return;
    const f = vfxForm();
    const id = b.dataset.id;
    const shot = vfxData().shots.find((s) => s.id === id);
    switch (b.dataset.vfx) {
      case "here": f.at = nowMs(); renderTextPanels(); break;
      case "go": {
        if (!f.text.trim()) { toast("Scrivi cosa vuoi vedere nel video", true); return; }
        const qc = vfxData().qualities[f.quality]?.credits ?? 4;
        const qu = vfxData().qualities[f.quality]?.usd ?? 0;
        if (qc >= 20 && !confirm(`Questa generazione costa circa ${qc} crediti Higgsfield. Procedo?`)) return;
        if (qu > 0 && !confirm(`Questa generazione usa l'API a consumo: circa ${String(qu).replace(".", ",")} $. Procedo?`)) return;
        const body = { start_ms: Math.round(f.at ?? nowMs()), dur_ms: f.dur, request: f.text.trim(), protect: f.protect, quality: f.quality };
        const ok = await mutate("/api/vfx", body, "Generazione avviata: ci vuole qualche minuto");
        if (ok) { f.text = ""; f.at = null; renderTextPanels(); }
        break;
      }
      case "answer": case "skip": {
        const n = shot?.plan?.questions?.length ?? 0;
        const given = b.dataset.vfx === "skip" ? [] : Array.from({ length: n }, (_, i) => (f.answers[id]?.[i] ?? "").trim());
        if (b.dataset.vfx === "answer" && !given.some(Boolean)) { toast("Scrivi almeno una risposta, oppure premi «Genera così»", true); return; }
        if (await mutate(`/api/vfx/${id}/answer`, { answers: given }, "Claude completa il piano e genera")) delete f.answers[id];
        break;
      }
      case "on": await mutate(`/api/vfx/${id}/enable`, { enabled: true }, "Clip AI nella timeline"); break;
      case "off": await mutate(`/api/vfx/${id}/enable`, { enabled: false }, "Clip AI tolta dalla timeline"); break;
      case "seek": if (shot) { seekMs(shot.start_ms); f.sel = id; renderVfxTrack(); renderTextPanels(); } break;
      case "fix": await mutate(`/api/vfx/${id}/retry`, { use_fix: true }, "Rigenero con la correzione"); break;
      case "again": await mutate(`/api/vfx/${id}/retry`, { use_fix: false }, "Rigenero una nuova versione"); break;
      case "del":
        if (confirm("Togliere questa clip AI dall'elenco? I file vanno nel cestino del progetto (work/vfx/_cestino), non vengono cancellati.")) await mutate(`/api/vfx/${id}/delete`, {}, "Clip AI spostata nel cestino");
        break;
    }
  });
}

function renderVfxTrack() {
  const el = $("#track-vfx");
  if (!el) return;
  const f = vfxForm();
  el.innerHTML = vfxData().shots.map((s) => {
    const cls = ["vfx-blk", s.status === "running" ? "running" : s.status === "asking" ? "asking" : s.status === "error" ? "error" : s.enabled ? "" : "off", f.sel === s.id ? "sel" : ""].join(" ");
    const w = Math.max(14, (s.dur_ms / 1000) * S.pps);
    const state = s.status === "running" ? s.phase_label : s.status === "error" ? "non riuscita" : s.enabled ? "nella timeline" : "pronta, non in timeline";
    return `<div class="${cls}" data-vfxblk="${esc(s.id)}" style="left:${xOf(s.start_ms)}px;width:${w}px" title="${esc(`${s.title || s.request} · ${state}`)}">✦<span>${w > 50 ? esc(s.title || "AI") : ""}</span></div>`;
  }).join("");
}

// Anteprima: nei secondi di una clip attiva si vede la clip AI sopra il video (stesso zoom e colore).
function updateVfxOverlay(cur) {
  const el = $("#vfx-video");
  if (!el) return;
  const s = (S.data?.vfx?.shots ?? []).find((x) => x.enabled && x.final_url && cur >= x.start_ms && cur < x.start_ms + x.dur_ms);
  if (!s) {
    if (el.classList.contains("on")) { el.classList.remove("on"); el.pause(); }
    return;
  }
  if (el.dataset.src !== s.final_url) { el.dataset.src = s.final_url; el.src = s.final_url; }
  el.classList.add("on");
  const t = (cur - s.start_ms) / 1000;
  if (Math.abs(el.currentTime - t) > (video.paused ? 0.02 : 0.15)) el.currentTime = t;
  if (video.paused && !el.paused) el.pause();
  else if (!video.paused && el.paused) el.play().catch(() => {});
  if (el.style.transform !== video.style.transform) el.style.transform = video.style.transform;
  if (el.style.filter !== video.style.filter) el.style.filter = video.style.filter;
}

// --- B-roll e voice-over -----------------------------------------------------------------------
// B-roll: foto o video caricati che coprono la ripresa per un tratto (la voce continua).
// Voice-over: un audio registrato a parte (telefono) che parte in un punto e commenta le immagini.
// I tempi sono sull'asse della camera, come tutto il resto: restano giusti se cambi i tagli.

const BR = { sel: null, selVo: null, busy: "", duck: false, audios: new Map(), drag: null };
const brData = () => S.data?.broll ?? { clips: [], voices: [], limits: {} };
const brClip = (id) => brData().clips.find((c) => c.id === id) ?? null;
const brVoice = (id) => brData().voices.find((v) => v.id === id) ?? null;
const brSec = (ms) => `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
const brSave = (id, fields, msg) => mutate(`/api/broll/${id}`, { fields }, msg);
const BR_ICON = { video: "🎞", image: "🖼" };

function brThumb(c) {
  return c.kind === "image"
    ? `<img src="${esc(c.url)}" alt="" loading="lazy" draggable="false">`
    : `<video src="${esc(c.url)}#t=0.4" preload="metadata" muted playsinline></video>`;
}

function brollPanelHTML() {
  const d = brData();
  const sel = brClip(BR.sel);
  let selBox = "";
  if (sel) {
    const room = sel.kind === "video" && sel.media_ms ? Math.max(500, sel.media_ms - sel.src_ms) : 60000;
    selBox = `<div class="st-sel">
      <div class="st-sel-head"><span class="st-thumb br-thumb">${brThumb(sel)}</span>
        <div><b>${esc(sel.name || "B-roll")}</b><div class="meta">a ${showTime(sel.at_ms)} · ${brSec(sel.duration_ms)}${sel.enabled ? "" : " · spento"}</div></div>
        <button class="icon-btn" data-br="close" title="Deseleziona">✕</button></div>
      <div class="btn-row tx-actions">
        <button class="btn" data-br="seek" data-id="${esc(sel.id)}">▶ Vedi nel video</button>
        <button class="btn" data-br="here" data-id="${esc(sel.id)}" title="Parte dove c'è la testina">Sposta qui</button>
        <button class="btn" data-br="nudge" data-id="${esc(sel.id)}" data-ms="-100" title="0,1 s prima">◀</button>
        <button class="btn" data-br="nudge" data-id="${esc(sel.id)}" data-ms="100" title="0,1 s dopo">▶</button>
      </div>
      <div class="section-title">Durata <span class="tx-val" id="br-duration_ms-val">${brSec(sel.duration_ms)}</span></div>
      <input type="range" class="tx-range" data-br-range="duration_ms" data-id="${esc(sel.id)}" min="500" max="${Math.min(30000, room)}" step="100" value="${Math.min(sel.duration_ms, 30000)}">
      ${sel.kind === "video" && sel.media_ms > 1000 ? `
        <div class="section-title">Parte da <span class="tx-val" id="br-src_ms-val">${brSec(sel.src_ms)}</span></div>
        <input type="range" class="tx-range" data-br-range="src_ms" data-id="${esc(sel.id)}" min="0" max="${Math.max(0, sel.media_ms - 500)}" step="100" value="${sel.src_ms}">
        <div class="tx-hint">Il video caricato dura ${brSec(sel.media_ms)}: scegli da che secondo prenderlo.</div>` : ""}
      <div class="btn-row tx-actions">
        <button class="btn${sel.enabled ? "" : " on"}" data-br="toggle" data-id="${esc(sel.id)}">${sel.enabled ? "Spegni" : "Riaccendi"}</button>
        <button class="btn danger" data-br="del" data-id="${esc(sel.id)}">Elimina</button>
      </div></div>`;
  }
  const list = d.clips.slice().sort((a, b) => a.at_ms - b.at_ms).map((c) => `
    <button class="st-item${c.id === BR.sel ? " on" : ""}${c.enabled ? "" : " dim"}" data-br="pick" data-id="${esc(c.id)}">
      <span class="st-thumb br-thumb">${brThumb(c)}</span>
      <span class="st-item-t">${BR_ICON[c.kind]} ${showTime(c.at_ms)} · ${brSec(c.duration_ms)}
        <span class="meta">${esc(c.name || c.file)}${c.enabled ? "" : " · spento"}</span></span></button>`).join("");
  const lim = d.limits ?? {};
  return `<div class="br-panel">
    <p class="tx-hint">Il <b>B-roll</b> sono le immagini che mostrano quello che dici: un dettaglio, un oggetto, un paesaggio. Carica un video o una foto e va <b>sopra la ripresa</b> dalla testina (${clock(nowMs())}); la tua voce continua.</p>
    <div class="btn-row"><button class="btn vfx-go" data-br="add"${BR.busy ? " disabled" : ""}>${BR.busy ? esc(BR.busy) : "＋ Carica video o foto"}</button></div>
    <div class="tx-hint">Anche trascinando i file qui. Video fino a ${lim.video_mb ?? 1500} MB, foto fino a ${lim.image_mb ?? 40} MB. Poi trascina il blocco azzurro nella timeline per spostarlo.</div>
    ${selBox}
    <div class="st-sub">B-roll nel video (${d.clips.length})</div>
    <div class="st-list">${list || `<div class="tx-hint">Nessun B-roll ancora.</div>`}</div>
    <div class="tx-hint" style="margin-top:10px">Vuoi commentare le immagini con la tua voce? Nella scheda <b>Audio</b> c'è «🎤 Voice-over»: carichi la registrazione fatta col telefono.</div>
  </div>`;
}

function voiceCardHTML() {
  const d = brData();
  const sel = brVoice(BR.selVo);
  const rows = d.voices.map((v) => `
    <div class="br-vo${v.id === BR.selVo ? " on" : ""}${v.enabled ? "" : " dim"}">
      <button class="icon-btn" data-br="vo-play" data-id="${esc(v.id)}" title="Ascolta dal punto in cui parte">▶</button>
      <button class="br-vo-t" data-br="vo-pick" data-id="${esc(v.id)}"><b>${esc(v.name || v.file)}</b>
        <span class="meta">${showTime(v.at_ms)} · ${brSec(v.duration_ms)} · ${dbTxt(v.gain_db)}${v.enabled ? "" : " · spento"}</span></button>
    </div>`).join("");
  let selBox = "";
  if (sel) {
    selBox = `<div class="br-vo-edit">
      <div class="btn-row tx-actions">
        <button class="btn" data-br="vo-here" data-id="${esc(sel.id)}" title="Parte dove c'è la testina">Sposta qui</button>
        <button class="btn" data-br="vo-nudge" data-id="${esc(sel.id)}" data-ms="-100">◀</button>
        <button class="btn" data-br="vo-nudge" data-id="${esc(sel.id)}" data-ms="100">▶</button>
        <button class="btn${sel.enabled ? "" : " on"}" data-br="vo-toggle" data-id="${esc(sel.id)}">${sel.enabled ? "Spegni" : "Riaccendi"}</button>
        <button class="btn danger" data-br="vo-del" data-id="${esc(sel.id)}">Elimina</button>
      </div>
      <div class="section-title">Volume <span class="tx-val" id="br-gain_db-val">${dbTxt(sel.gain_db)}</span></div>
      <input type="range" class="tx-range" data-br-range="gain_db" data-id="${esc(sel.id)}" min="-240" max="120" step="5" value="${Math.round(sel.gain_db * 10)}">
      <label class="vfx-chk"><input type="checkbox" data-br-mutecam data-id="${esc(sel.id)}"${sel.mute_camera ? " checked" : ""}><span><b>Zittisci la voce della ripresa</b> mentre parla il voice-over<br><span class="tx-hint">Lascia acceso se commenti le immagini: senti solo la tua registrazione.</span></span></label>
    </div>`;
  }
  return `<div class="au-card">
    <div class="au-head"><b>🎤 Voice-over</b>
      <button class="btn small vfx-go" data-br="voice"${BR.busy ? " disabled" : ""}>${BR.busy ? esc(BR.busy) : "＋ Carica audio"}</button></div>
    <div class="tx-hint">Registra col telefono (app Memo vocali) e carica qui il file: parte dalla testina (${clock(nowMs())}) e suona sopra il video. Anche un video: se ne usa la voce.</div>
    ${rows ? `<div class="br-vo-list">${rows}</div>` : ""}${selBox}
  </div>`;
}

function renderBrollTrack() {
  const d = brData();
  const el = $("#track-broll"), vo = $("#track-vo");
  if (el) {
    el.innerHTML = d.clips.map((c) => `<div class="br-blk${c.enabled ? "" : " off"}${c.id === BR.sel ? " sel" : ""}" data-brblk="${esc(c.id)}"
      style="left:${xOf(c.at_ms)}px;width:${Math.max(14, (c.duration_ms / 1000) * S.pps)}px" title="${esc(`${c.name || "B-roll"} · ${brSec(c.duration_ms)}`)}">${BR_ICON[c.kind]}<span>${(c.duration_ms / 1000) * S.pps > 60 ? esc(c.name || "B-roll") : ""}</span></div>`).join("");
  }
  if (vo) {
    vo.innerHTML = d.voices.map((v) => `<div class="vo-blk${v.enabled ? "" : " off"}${v.id === BR.selVo ? " sel" : ""}" data-voblk="${esc(v.id)}"
      style="left:${xOf(v.at_ms)}px;width:${Math.max(14, (v.duration_ms / 1000) * S.pps)}px" title="${esc(`${v.name || "Voice-over"} · ${brSec(v.duration_ms)}`)}">🎤<span>${(v.duration_ms / 1000) * S.pps > 60 ? esc(v.name || "Voice-over") : ""}</span></div>`).join("");
  }
}

function openBroll(id) {
  BR.sel = id;
  renderBrollTrack();
  if (S.viewer) toggleViewerPanel(true, "broll");
  else if (S.leftTab !== "broll") { S.leftTab = "broll"; renderLeft(); }
  else renderTextPanels();
}

function openVoice(id) {
  BR.selVo = id;
  renderBrollTrack();
  if (S.viewer) toggleViewerPanel(true, "audio");
  else if (S.leftTab !== "audio") { S.leftTab = "audio"; renderLeft(); }
  else renderTextPanels();
}

async function brUpload(files, kind) {
  const list = [...files];
  if (!list.length || BR.busy) return;
  for (const [i, f] of list.entries()) {
    BR.busy = `Carico ${f.name.slice(0, 24)}… (${i + 1}/${list.length})`;
    renderTextPanels();
    try {
      const at = Math.round(nowMs());
      const res = await fetch(`/api/broll/upload?name=${encodeURIComponent(f.name)}&at_ms=${at}&kind=${kind}`, {
        method: "POST", headers: { "content-type": "application/octet-stream" }, body: f,
      });
      if (!res.ok) {
        let msg = res.statusText;
        try { msg = (await res.json()).detail || msg; } catch { /* vuoto */ }
        throw new Error(msg);
      }
      apply(await res.json());
      const added = kind === "voice" ? brData().voices.at(-1) : brData().clips.at(-1);
      if (added) { if (kind === "voice") BR.selVo = added.id; else BR.sel = added.id; }
      toast(kind === "voice" ? "Voice-over aggiunto" : "B-roll aggiunto: trascinalo o regola la durata");
    } catch (e) {
      toast(`${f.name}: ${e.message}`, true);
    }
  }
  BR.busy = "";
  renderBrollTrack();
  renderTextPanels();
}

function brPick(kind) {
  const input = Object.assign(document.createElement("input"), {
    type: "file", multiple: kind !== "voice",
    accept: kind === "voice" ? "audio/*,video/*,.m4a,.mp3,.wav,.aac,.caf" : "video/*,image/*",
  });
  input.addEventListener("change", () => brUpload(input.files, kind));
  input.click();
}

function wireBrollPanel(box) {
  const tabOf = () => (box.id === "viewer-panel" ? S.viewerTab : S.leftTab);
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-br]");
    if (!b || b.disabled) return;
    const d = b.dataset, id = d.id;
    switch (d.br) {
      case "add": brPick("broll"); break;
      case "voice": brPick("voice"); break;
      case "close": BR.sel = null; renderBrollTrack(); renderTextPanels(); break;
      case "pick": { const c = brClip(id); if (c) { video.pause(); seekMs(Math.max(S.axisStart, c.at_ms - 300)); } openBroll(id); break; }
      case "seek": { const c = brClip(id); if (c) { seekMs(c.at_ms); video.play(); S.stopAt = c.at_ms + c.duration_ms + 300; } break; }
      case "here": brSave(id, { at_ms: Math.round(nowMs()) }, "B-roll spostato"); break;
      case "nudge": { const c = brClip(id); if (c) brSave(id, { at_ms: Math.max(0, c.at_ms + Number(d.ms)) }); break; }
      case "toggle": { const c = brClip(id); if (c) brSave(id, { enabled: !c.enabled }); break; }
      case "del": BR.sel = null; await mutate(`/api/broll/${id}/delete`, {}, "B-roll tolto (Annulla lo rimette)"); break;
      case "vo-pick": { const v = brVoice(id); if (v) { video.pause(); seekMs(Math.max(S.axisStart, v.at_ms - 300)); } openVoice(id); break; }
      case "vo-play": { const v = brVoice(id); if (v) { BR.selVo = id; seekMs(v.at_ms); video.play(); S.stopAt = null; } break; }
      case "vo-here": brSave(id, { at_ms: Math.round(nowMs()) }, "Voice-over spostato"); break;
      case "vo-nudge": { const v = brVoice(id); if (v) brSave(id, { at_ms: Math.max(0, v.at_ms + Number(d.ms)) }); break; }
      case "vo-toggle": { const v = brVoice(id); if (v) brSave(id, { enabled: !v.enabled }); break; }
      case "vo-del": BR.selVo = null; await mutate(`/api/broll/${id}/delete`, {}, "Voice-over tolto (Annulla lo rimette)"); break;
    }
  });
  box.addEventListener("input", (e) => {
    const r = e.target.closest("[data-br-range]");
    if (!r) return;
    S.txSliding = r;
    const k = r.dataset.brRange, v = Number(r.value);
    const label = box.querySelector(`#br-${k}-val`);
    if (label) label.textContent = k === "gain_db" ? dbTxt(v / 10) : brSec(v);
  });
  box.addEventListener("change", (e) => {
    const m = e.target.closest("[data-br-mutecam]");
    if (m) { brSave(m.dataset.id, { mute_camera: m.checked }); return; }
    const r = e.target.closest("[data-br-range]");
    if (!r) return;
    S.txSliding = null;
    const k = r.dataset.brRange, v = Number(r.value);
    brSave(r.dataset.id, { [k]: k === "gain_db" ? v / 10 : v });
  });
  // trascinare file sul pannello: B-roll (video/foto) nella scheda B-roll, audio nella scheda Audio
  box.addEventListener("dragover", (e) => {
    if (["broll", "audio"].includes(tabOf()) && [...(e.dataTransfer?.types ?? [])].includes("Files")) { e.preventDefault(); box.classList.add("img-drop"); }
  });
  box.addEventListener("dragleave", () => box.classList.remove("img-drop"));
  box.addEventListener("drop", (e) => {
    const tab = tabOf();
    box.classList.remove("img-drop");
    if (!["broll", "audio"].includes(tab) || !e.dataTransfer?.files?.length) return;
    e.preventDefault();
    brUpload(e.dataTransfer.files, tab === "audio" ? "voice" : "broll");
  });
}

// trascinare i blocchi nella timeline = spostare il B-roll o il voice-over
function wireBrollTracks() {
  for (const sel of ["#track-broll", "#track-vo"]) {
    const el = $(sel);
    el.addEventListener("mousedown", (e) => {
      const b = e.target.closest("[data-brblk],[data-voblk]");
      if (!b) return;
      e.stopPropagation();
      e.preventDefault();
      const id = b.dataset.brblk ?? b.dataset.voblk;
      const item = brClip(id) ?? brVoice(id);
      if (!item) return;
      BR.drag = { id, x0: e.clientX, at0: item.at_ms, moved: false, el: b };
    });
  }
  window.addEventListener("mousemove", (e) => {
    const g = BR.drag;
    if (!g) return;
    const dx = e.clientX - g.x0;
    if (Math.abs(dx) > 3) g.moved = true;
    if (g.moved) g.el.style.left = `${xOf(g.at0) + dx}px`;
  });
  window.addEventListener("mouseup", (e) => {
    const g = BR.drag;
    if (!g) return;
    BR.drag = null;
    if (g.moved) {
      const at = Math.max(0, Math.round(g.at0 + ((e.clientX - g.x0) / S.pps) * 1000));
      brSave(g.id, { at_ms: at }, g.id.startsWith("vo_") ? "Voice-over spostato" : "B-roll spostato");
    } else if (g.id.startsWith("vo_")) openVoice(g.id);
    else openBroll(g.id);
  });
}

// Anteprima: sopra il video si vede il B-roll del momento; il voice-over suona in sincrono col montato.
function updateBroll(cur) {
  const d = S.data?.broll;
  const vEl = $("#broll-video"), iEl = $("#broll-img");
  if (!d || !vEl) return;
  const c = d.clips.filter((x) => x.enabled && cur >= x.at_ms && cur < x.at_ms + x.duration_ms).at(-1);
  if (!c) {
    if (vEl.classList.contains("on")) { vEl.classList.remove("on"); vEl.pause(); }
    iEl.classList.remove("on");
  } else if (c.kind === "image") {
    if (vEl.classList.contains("on")) { vEl.classList.remove("on"); vEl.pause(); }
    if (iEl.dataset.src !== c.url) { iEl.dataset.src = c.url; iEl.src = c.url; }
    iEl.classList.add("on");
  } else {
    iEl.classList.remove("on");
    if (vEl.dataset.src !== c.url) { vEl.dataset.src = c.url; vEl.src = c.url; }
    vEl.classList.add("on");
    const t = Math.min((c.src_ms + cur - c.at_ms) / 1000, Math.max(0, (c.media_ms || 1e9) / 1000 - 0.05));
    if (Math.abs(vEl.currentTime - t) > (video.paused ? 0.02 : 0.2)) vEl.currentTime = t;
    if (video.paused && !vEl.paused) vEl.pause();
    else if (!video.paused && vEl.paused) vEl.play().catch(() => {});
  }
  // voice-over: tempo di riproduzione sul montato (i tagli non lo allungano né lo accorciano)
  let duck = false;
  const ids = new Set();
  for (const v of d.voices) {
    ids.add(v.id);
    let au = BR.audios.get(v.id);
    if (!au || au.dataset.src !== v.url) {
      au = Object.assign(new Audio(v.url), { preload: "auto" });
      au.dataset.src = v.url;
      BR.audios.set(v.id, au);
    }
    const pos = S.mode === "edited" ? editedAt(cur) - editedAt(v.at_ms) : cur - v.at_ms;
    const on = v.enabled && pos >= 0 && pos < v.duration_ms;
    if (on && v.mute_camera) duck = true;
    au.volume = Math.min(1, Math.pow(10, v.gain_db / 20));
    if (on && !video.paused) {
      if (Math.abs(au.currentTime * 1000 - pos) > 250) au.currentTime = pos / 1000;
      if (au.paused) au.play().catch(() => {});
    } else if (!au.paused) au.pause();
  }
  for (const [id, au] of BR.audios) if (!ids.has(id)) { au.pause(); BR.audios.delete(id); }
  if (duck !== BR.duck) { BR.duck = duck; applyVoiceGain(); }
}

function imagesPanelHTML() {
  const sel = popItem(S.popSel);
  const photo = isPhoto(sel) ? sel : null;
  const jobs = Object.values(S.imgJobs).map(imgJobLine).join("");
  const res = S.imgRes ?? [];
  const results = res.map((r, i) => `
    <button class="img-res" data-img-add="${i}" title="${esc(r.title)}${r.license ? ` · ${esc(r.license)}` : ""}">
      <img src="${esc(r.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer" draggable="false">
      <span class="img-src">${esc(r.license ? "✓ libera · " + r.source : r.source)}</span></button>`).join("");
  const mine = (S.data?.images ?? []).map((m) => `
    <button class="img-res mine" data-img-mine="${esc(m.image)}" title="${esc(m.title || "")}">
      <img src="${esc(m.url)}" alt="" loading="lazy" draggable="false"></button>`).join("");
  let selBox = "";
  if (photo) {
    const spec = stickerSpec(photo.id);
    const meta = (S.data?.images ?? []).find((m) => m.image === photo.image) ?? {};
    selBox = `
      ${stickerEditHTML(photo, "Immagine selezionata")}
      <div class="st-sel img-fix">
        <div class="section-title">Scontorno ${meta.cutout === false ? "· foto intera" : meta.quality === "best" ? "· qualità massima" : "· qualità rapida"}</div>
        <div class="btn-row tx-actions">
          ${meta.quality !== "best" || meta.cutout === false ? `<button class="btn" data-img-act="redo-best" ${S.imgRedo ? "disabled" : ""} title="Più lento (~20 s) ma bordi e capelli molto più puliti">✂ Qualità massima</button>` : ""}
          ${meta.cutout === false ? `<button class="btn" data-img-act="redo-fast" ${S.imgRedo ? "disabled" : ""}>✂ Scontorna</button>`
            : `<button class="btn" data-img-act="redo-full" ${S.imgRedo ? "disabled" : ""}>Foto intera</button>`}
        </div>
        ${meta.source ? `<div class="tx-hint">Da ${esc(meta.source)}${meta.license ? ` · ${esc(meta.license)}` : ""}${meta.page ? ` · <a href="${esc(meta.page)}" target="_blank" rel="noopener noreferrer">pagina</a>` : ""}</div>` : ""}
      </div>
      <div class="st-sel" data-fx-scope="sticker">
        <div class="section-title">Animazione <button class="link" data-fx-act="preview-sticker">▶ Anteprima</button></div>
        ${S.data?.effects ? fxPhaseBlock("in", "sticker", spec) + fxPhaseBlock("out", "sticker", spec)
          : `<div class="tx-hint">Scegli uno stile (Viral o Premium) per avere le animazioni di entrata e uscita.</div>`}
      </div>`;
  }
  return `
    <div class="img-ask">
      <div class="img-ask-row">
        <input id="img-q" placeholder="Chiedi un'immagine… es. Francesco Totti che esulta" value="${esc(S.imgQ)}" autocomplete="off">
        <button class="btn ai" data-img-act="search" ${S.imgBusy ? "disabled" : ""}>${S.imgBusy ? "Cerco…" : "Cerca"}</button>
      </div>
      <div class="img-opts">
        <button class="chip${S.imgCut ? " on" : ""}" data-img-opt="cut" title="Toglie lo sfondo e lascia solo la persona o l'oggetto">✂ Scontorna</button>
        ${S.imgCut ? `<span class="seg-toggle small img-q">
          <button data-img-quality="fast" class="${S.imgQuality === "fast" ? "on" : ""}" title="~2 secondi">Rapida</button>
          <button data-img-quality="best" class="${S.imgQuality === "best" ? "on" : ""}" title="~20 secondi, bordi e capelli più puliti">Massima</button></span>` : ""}
        <button class="chip${S.imgTransp ? " on" : ""}" data-img-opt="transp" title="Solo PNG che sono già senza sfondo">Già trasparenti</button>
        <button class="chip${S.imgFree ? " on" : ""}" data-img-opt="free" title="Solo foto con licenza libera (Wikimedia Commons)">Licenza libera</button>
        <button class="chip" data-img-act="upload" title="Usa una foto del tuo PC (puoi anche trascinarla qui)">⬆ Dal PC</button>
        <input type="file" id="img-file" accept="image/*" hidden>
      </div>
    </div>
    ${jobs ? `<div class="img-jobs">${jobs}</div>` : ""}
    ${selBox}
    ${S.imgErr ? `<div class="tx-hint err">${esc(S.imgErr)}</div>` : ""}
    ${res.length ? `<div class="st-sub">Risultati per «${esc(S.imgShown)}» · clic = scontorna e metti nel video a ${showTime(nowMs())}</div>
      <div class="img-grid">${results}</div>`
      : S.imgShown && !S.imgBusy ? `<div class="tx-hint">Nessuna immagine trovata per «${esc(S.imgShown)}».</div>`
      : !photo ? `<div class="tx-hint" style="margin-top:0">Scrivi chi o cosa ti serve: cerco sul web come nel browser. Clicchi una foto, la scontorno e la metto nel video dove c'è la testina; poi la sposti, la ingrandisci e le dai un'animazione.</div>
        <div class="img-ideas">${IMG_HINTS.map((h) => `<button class="chip" data-img-try="${esc(h)}">${esc(h)}</button>`).join("")}</div>` : ""}
    ${mine ? `<div class="st-sub">Le tue immagini</div><div class="img-grid mine">${mine}</div>` : ""}
    <div class="tx-hint">Le foto del web hanno quasi sempre un copyright: per i video da pubblicare preferisci «Licenza libera» o foto tue.</div>`;
}

async function imgSearch(q) {
  q = (q ?? S.imgQ).trim();
  if (!q) { toast("Scrivi cosa cercare", true); return; }
  S.imgQ = q;
  S.imgBusy = true;
  S.imgErr = "";
  renderTextPanels();
  try {
    const params = new URLSearchParams({ q, transparent: S.imgTransp ? "1" : "0", free: S.imgFree ? "1" : "0" });
    const data = await api(`/api/images/search?${params}`);
    S.imgRes = data.results;
    S.imgShown = data.query;
  } catch (e) {
    S.imgErr = `Ricerca non riuscita: ${e.message}`;
    S.imgRes = []; // niente risultati vecchi spacciati per nuovi
    S.imgShown = "";
  } finally {
    S.imgBusy = false;
    renderTextPanels();
  }
}

// Dove mettere una foto scontornata: in basso, appoggiata al bordo (come i meme con i
// personaggi in fila). Accanto alle altre foto dello stesso momento.
function photoSpot(atMs, w, h) {
  const fw = S.portrait ? 9 : 16, fh = S.portrait ? 16 : 9;
  const width = 0.64; // taglia L = 64% della larghezza
  let scale = 1;
  let hPct = width * (h / Math.max(1, w)) * (fw / fh) * 100;
  const maxH = S.portrait ? 48 : 62;
  if (hPct > maxH) { scale = maxH / hPct; hPct = maxH; }
  const busy = (S.data?.popups ?? []).filter((p) => isPhoto(p) && p.status !== "rejected"
    && p.at_ms < atMs + 2500 && atMs < p.at_ms + p.duration_ms);
  const xs = [50, 24, 76, 37, 63];
  const x = xs.find((v) => busy.every((p) => Math.abs(p.x_pct - v) > 10)) ?? xs[busy.length % xs.length];
  return { x_pct: x, y_pct: Math.round((100 - hPct / 2 + 1) * 10) / 10, scale: Math.round(scale * 100) / 100 };
}

// Se la testina è su una parte tagliata, la foto parte dall'inizio del pezzo tenuto dopo.
function keptMs(ms) {
  const r = (S.eff ?? []).find((x) => x.state === "keep" && x.end_ms > ms);
  return r && ms < r.start_ms ? r.start_ms + 80 : ms;
}

async function placePhoto(image, atMs, w, h, cutout) {
  atMs = keptMs(atMs);
  const spot = cutout ? photoSpot(atMs, w, h) : { x_pct: 50, y_pct: S.portrait ? 30 : 40, scale: 0.8 };
  const data = await mutate("/api/popups/add", { kind: "image", image, cutout, at_ms: atMs, size: "large", duration_ms: 2500, sound: false, ...spot });
  if (!data?.added) return;
  S.popSel = data.added;
  S.justAdded = data.added;
  setTimeout(() => { if (S.justAdded === data.added) S.justAdded = null; $("#popup-layer").dataset.key = ""; }, 1400);
  $("#popup-layer").dataset.key = "";
  seekMs(atMs + 400);
  renderTextPanels();
  toast(`Immagine messa a ${showTime(atMs)}: trascinala nel video dove vuoi`);
}

async function runImageJob(body, card, onDone) {
  let job;
  try {
    job = await api("/api/images/add", body);
  } catch (e) {
    toast(`Non riesco a preparare l'immagine: ${e.message}`, true);
    return;
  }
  S.imgJobs[job.id] = { ...job, ...card };
  renderTextPanels();
  for (;;) {
    await new Promise((r) => setTimeout(r, 450));
    try { job = await api(`/api/images/job/${job.id}`); } catch { continue; }
    S.imgJobs[job.id] = { ...job, ...card };
    if (job.status !== "running") break;
    renderTextPanels();
  }
  if (job.status === "done") {
    delete S.imgJobs[job.id];
    await onDone(job);
  }
  renderTextPanels();
}

function imgAddResult(r) {
  video.pause();
  const atMs = Math.round(nowMs());
  const body = { url: r.url, thumb: r.thumb, page: r.page, title: r.title, source: r.source, license: r.license, cutout: S.imgCut, quality: S.imgQuality };
  runImageJob(body, { title: r.title || S.imgShown, thumb: r.thumb }, (job) => placePhoto(job.image, atMs, job.width, job.height, job.cutout));
}

function imgUpload(file) {
  if (!file || !file.type.startsWith("image/")) { toast("Scegli un file immagine (JPG, PNG, WebP)", true); return; }
  if (file.size > 25 * 1024 * 1024) { toast("Immagine troppo pesante (oltre 25 MB)", true); return; }
  video.pause();
  const atMs = Math.round(nowMs());
  const fr = new FileReader();
  fr.onload = () => runImageJob({ data: fr.result, title: file.name, source: "il tuo PC", cutout: S.imgCut, quality: S.imgQuality },
    { title: file.name, thumb: fr.result }, (job) => placePhoto(job.image, atMs, job.width, job.height, job.cutout));
  fr.readAsDataURL(file);
}

function imgRedo(photo, cutout, quality) {
  S.imgRedo = true;
  renderTextPanels();
  const meta = (S.data?.images ?? []).find((m) => m.image === photo.image) ?? {};
  runImageJob({ redo: photo.image, cutout, quality }, { title: cutout ? (quality === "best" ? "Scontorno in qualità massima" : "Scontorno") : "Foto intera", thumb: meta.url },
    async () => { await savePop(photo.id, { cutout }, cutout ? "Scontorno rifatto" : "Ora è la foto intera"); })
    .finally(() => { S.imgRedo = false; renderTextPanels(); });
}

function wireImagesPanel(box) {
  box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-img-act],[data-img-add],[data-img-mine],[data-img-opt],[data-img-quality],[data-img-try]");
    if (!b || b.disabled) return;
    const d = b.dataset;
    if (d.imgAdd) { const r = S.imgRes?.[Number(d.imgAdd)]; if (r) imgAddResult(r); return; }
    if (d.imgMine) {
      video.pause();
      const atMs = Math.round(nowMs());
      const img = new Image();
      img.onload = () => placePhoto(d.imgMine, atMs, img.naturalWidth, img.naturalHeight, ((S.data.images ?? []).find((m) => m.image === d.imgMine)?.cutout) !== false);
      img.src = b.querySelector("img").src;
      return;
    }
    if (d.imgTry) { S.imgQ = d.imgTry; imgSearch(d.imgTry); return; }
    if (d.imgQuality) { S.imgQuality = d.imgQuality; renderTextPanels(); return; }
    if (d.imgOpt === "cut") S.imgCut = !S.imgCut;
    else if (d.imgOpt === "transp") { S.imgTransp = !S.imgTransp; if (S.imgTransp) S.imgFree = false; }
    else if (d.imgOpt === "free") { S.imgFree = !S.imgFree; if (S.imgFree) S.imgTransp = false; }
    if (d.imgOpt) { renderTextPanels(); if (S.imgShown && d.imgOpt !== "cut") imgSearch(S.imgQ); return; }
    const photo = popItem(S.popSel);
    if (d.imgAct === "search") imgSearch(box.querySelector("#img-q").value);
    else if (d.imgAct === "upload") box.querySelector("#img-file").click();
    else if (d.imgAct === "drop-job") { delete S.imgJobs[d.v]; renderTextPanels(); }
    else if (photo && d.imgAct === "redo-best") imgRedo(photo, true, "best");
    else if (photo && d.imgAct === "redo-fast") imgRedo(photo, true, S.imgQuality);
    else if (photo && d.imgAct === "redo-full") imgRedo(photo, false, "fast");
  });
  box.addEventListener("input", (e) => { if (e.target.id === "img-q") S.imgQ = e.target.value; });
  box.addEventListener("keydown", (e) => {
    if (e.target.id === "img-q" && e.key === "Enter") { e.preventDefault(); imgSearch(e.target.value); }
  });
  box.addEventListener("change", (e) => {
    if (e.target.id === "img-file") { imgUpload(e.target.files?.[0]); e.target.value = ""; }
  });
  box.addEventListener("dragover", (e) => {
    if (!isImagesBox(box) || !e.dataTransfer?.types.includes("Files")) return;
    e.preventDefault();
    box.classList.add("img-drop");
  });
  box.addEventListener("dragleave", () => box.classList.remove("img-drop"));
  box.addEventListener("drop", (e) => {
    box.classList.remove("img-drop");
    if (!isImagesBox(box) || !e.dataTransfer?.files?.length) return;
    e.preventDefault();
    imgUpload(e.dataTransfer.files[0]);
  });
}

function isImagesBox(box) {
  return box.id === "viewer-panel" ? S.viewerTab === "images" : S.leftTab === "images";
}

// --- effetti: animazioni di testo e sticker, transizioni (pannello Effetti) -------------
// Le animazioni usano lo stesso motore del render (/anim.js = motion/src/anim.js).
// Le transizioni nell'anteprima sono un'approssimazione su un solo video; il render le fa vere.

const FX_PHASE = { in: "Entrata", out: "Uscita", loop: "In loop" };
const KIND_LABEL = { cut: "taglio", scene: "cambio scena" };

function fxRes() {
  return S.data?.effects?.resolved ?? null;
}

function captionSpec() {
  const r = fxRes();
  if (r) return r.captions;
  const a = S.look?.captions.animation;
  return { in: { type: a === "pop" ? "pop" : a === "blur_in" ? "words_blur" : "none", ms: 320 }, out: { type: "none", ms: 200 } };
}

function stickerSpec(id) {
  const r = fxRes();
  if (!r) return null;
  return r.stickers[id] ?? r.sticker_default;
}

// Parole della frase con il loro tempo (il testo riscritto a mano si spalma sulla frase).
function chunkWordTimes(chunk, count) {
  const ws = chunk.ws ?? [chunk.start];
  if (count === ws.length) return ws;
  const a = ws[0], b = ws[ws.length - 1];
  return Array.from({ length: count }, (_, k) => Math.round(a + ((b - a) * k) / Math.max(1, count - 1)));
}

function applyCss(el, css) {
  el.style.opacity = String(css.opacity);
  el.style.transform = css.transform === "none" ? "" : css.transform;
  el.style.filter = css.filter === "none" ? "" : css.filter;
  el.style.clipPath = css.clipPath === "none" ? "" : css.clipPath;
}

function updateCaptionFx(cur) {
  const capEl = $("#caption");
  const chunk = S.chunks[S.lastChunk];
  if (!S.look || !chunk) { applyCss(capEl, { opacity: 1, transform: "none", filter: "none", clipPath: "none" }); return; }
  const spec = captionSpec();
  const dur = chunk.end + 250 - chunk.start;
  const t = restT(cur - chunk.start, spec, dur);
  const perWord = spec.in.type === "words_blur" || spec.in.type === "words_pop";
  const st = animState({ inSpec: perWord ? null : spec.in, outSpec: spec.out, t, dur });
  applyCss(capEl, animCss(st, chunkCaps(chunk)?.emphasis?.color ?? "#FFFFFF"));
  const words = capEl.querySelectorAll(".cw");
  if (perWord) {
    const times = chunkWordTimes(chunk, words.length);
    words.forEach((w, i) => applyCss(w, animCss(wordState(spec.in.type, video.paused ? spec.in.ms : cur - times[i], spec.in.ms))));
  } else if (words.length && words[0].style.opacity) {
    words.forEach((w) => applyCss(w, { opacity: 1, transform: "none", filter: "none", clipPath: "none" }));
  }
}

// In pausa si sta modificando: l'elemento si vede intero (fuori da entrata e uscita).
// In riproduzione fa l'animazione vera, come nel render.
function restT(t, spec, dur) {
  if (!video.paused) return t;
  const a = spec.in && spec.in.type !== "none" ? spec.in.ms : 0;
  const b = spec.out && spec.out.type !== "none" ? spec.out.ms : 0;
  return Math.max(a, Math.min(t, dur - b - 1));
}

function updatePopupFx(cur) {
  document.querySelectorAll(".pop-el[data-id]").forEach((el) => {
    const p = popItem(el.dataset.id);
    const spec = p && stickerSpec(p.id);
    if (!spec || S.popLive?.id === p.id) return;
    const t = restT(cur - p.at_ms, spec, p.duration_ms);
    const st = animState({ inSpec: spec.in, outSpec: spec.out, loopSpec: spec.loop, t, dur: p.duration_ms });
    applyCss(el, animCss(st));
  });
}

// Transizione nell'anteprima: vicino a una giunta del montato muove il video (approssimato).
function transitionFx(cur) {
  const pts = S.data?.effects?.points ?? [];
  if (S.mode !== "edited" || !pts.length) return null;
  const e = editedAt(cur);
  for (const b of pts) {
    const tr = b.transition;
    if (!tr) continue;
    const je = editedAt(b.at_ms);
    const half = tr.ms / 2;
    if (e < je - half || e > je + half) continue;
    const k = (e - (je - half)) / tr.ms;
    const peak = 1 - Math.abs(k - 0.5) * 2;
    const side = k < 0.5 ? -k * 2 : (1 - k) * 2; // -1..0..1
    switch (tr.type) {
      case "zoom": return { tf: `scale(${1 + 0.3 * peak})`, blur: peak * 6 };
      case "whip": case "slide_left": case "push_cut": return { tf: `translateX(${side * 35}%)`, blur: peak * (tr.type === "whip" ? 10 : 2), flash: tr.type === "push_cut" ? peak * 0.6 : 0 };
      case "slide_up": return { tf: `translateY(${side * 35}%)`, blur: peak * 2 };
      case "flash": return { flash: peak };
      case "blur": return { blur: peak * 10, dim: peak * 0.2 };
      case "cube": case "flip": return { tf: `perspective(600px) rotateY(${side * 60}deg)`, dim: peak * 0.4 };
      default: return { dim: peak }; // fade, passaggio al nero, tendina, iride, orologio
    }
  }
  return null;
}

function updateTransitionFx(cur) {
  const fx = transitionFx(cur);
  S.transTf = fx?.tf ?? "";
  const grade = S.look ? S.look.grade.css_filter : "";
  const blur = fx?.blur ? ` blur(${fx.blur.toFixed(1)}px)` : "";
  const filter = (grade + blur).trim();
  if (video.style.filter !== filter) video.style.filter = filter;
  const ov = $("#trans-fx");
  ov.style.background = fx?.flash ? "#fff" : "#000";
  ov.style.opacity = String(fx?.flash ?? fx?.dim ?? 0);
}

// --- timeline: un rombo a ogni giunta (pieno se c'è una transizione) ------------------------

function renderTransitionMarks() {
  const box = $("#tl-trans");
  if (!box) return;
  const pts = S.data?.effects?.points ?? [];
  box.innerHTML = pts.map((b) => `
    <button class="tmark${b.transition ? " on" : ""}${b.id === S.fxPoint ? " sel" : ""}${b.kind === "scene" ? " scene" : ""}"
      data-fx-point="${esc(b.id)}" style="left:${xOf(b.at_ms)}px"
      title="${b.transition ? esc(transLabel(b.transition.type)) : "Taglio netto"} · ${KIND_LABEL[b.kind]}${b.block ? " (nuovo blocco)" : ""}"></button>`).join("");
}

function transLabel(id) {
  return (S.data?.effects?.transitions ?? []).find((t) => t.id === id)?.label ?? id;
}

// --- pannello ---------------------------------------------------------------------------

function fxGallery(phase, target, current) {
  const fx = S.data.effects;
  const sid = fx.style ?? "viral";
  const text = target === "captions";
  const list = fx.anims.filter((a) => a.phase === phase && (S.fxAll || a.sets.includes(sid)) && (text || !a.text_only));
  return `<div class="fx-grid">${list.map((a) => `
    <button class="fx-card${a.id === current.type ? " on" : ""}" data-fx-pick="${a.id}" data-fx-phase="${phase}" data-fx-demo="${a.id}">
      <span class="fx-demo"><span class="fx-demo-in">${text ? "Aa" : emojiHTML("🔥")}</span></span>
      <span class="fx-name">${esc(a.label)}</span></button>`).join("")}</div>`;
}

function fxPhaseBlock(phase, target, spec) {
  const cur = spec[phase] ?? { type: "none", ms: 300, speed: 1 };
  const slider = phase === "loop"
    ? `<div class="section-title">Velocità <span class="tx-val" id="fx-${phase}-val">${cur.speed.toFixed(2).replace(".", ",")}×</span></div>
       <input type="range" class="tx-range" data-fx-range="${phase}" data-fx-key="speed" min="25" max="400" value="${Math.round(cur.speed * 100)}">`
    : `<div class="section-title">Durata <span class="tx-val" id="fx-${phase}-val">${(cur.ms / 1000).toFixed(2).replace(".", ",")} s</span></div>
       <input type="range" class="tx-range" data-fx-range="${phase}" data-fx-key="ms" min="100" max="${phase === "in" ? 1500 : 1200}" step="10" value="${cur.ms}">`;
  return `<div class="fx-phase"><div class="fx-phase-title">${FX_PHASE[phase]}</div>${fxGallery(phase, target, cur)}${cur.type !== "none" ? slider : ""}</div>`;
}

function effectsPanelHTML() {
  if (!S.look || !S.data?.effects) {
    const btns = (S.data?.styles ?? []).map((s) => `<button class="btn" data-tx-style="${esc(s.id)}">${esc(s.name)}</button>`).join("");
    return `<div class="placeholder"><svg viewBox="0 0 24 24"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/></svg>
      <b>Effetti</b><br>Scegli prima uno stile: ogni preset ha la sua galleria di effetti.</div><div class="btn-row tx-styles">${btns}</div>`;
  }
  const fx = S.data.effects;
  const res = fx.resolved;
  const claude = `
    <div class="fx-claude">
      <button class="btn ai" data-fx-act="suggest" ${S.fxBusy ? "disabled" : ""}>${S.fxBusy ? "Claude sta componendo…" : "✦ Fai scegliere a Claude"}</button>
      <div class="tx-hint">${S.fxBusy ? "Guarda parlato, tagli e sticker e sceglie effetti e transizioni per lo stile " + esc(S.look.style_name) + "."
        : res.note ? esc(res.note) : res.suggested ? "Effetti scelti da Claude: cambiali come vuoi." : "Valori di partenza del preset " + esc(S.look.style_name) + "."}</div>
    </div>`;
  const tabs = `
    <div class="seg-toggle st-tabs">
      <button data-fx-tab="text" class="${S.fxTab === "text" ? "on" : ""}">Testo</button>
      <button data-fx-tab="stickers" class="${S.fxTab === "stickers" ? "on" : ""}">Sticker</button>
      <button data-fx-tab="trans" class="${S.fxTab === "trans" ? "on" : ""}">Transizioni (${fx.points.filter((b) => b.transition).length})</button>
    </div>`;
  const all = `<label class="fx-all"><input type="checkbox" data-fx-all ${S.fxAll ? "checked" : ""}> mostra anche gli effetti dell'altro stile</label>`;
  let body = "";
  if (S.fxTab === "text") {
    body = `<div class="tx-hint">Valgono per tutti i sottotitoli. <button class="link" data-fx-act="preview-text">▶ Anteprima</button></div>
      ${fxPhaseBlock("in", "captions", res.captions)}${fxPhaseBlock("out", "captions", res.captions)}${all}`;
  } else if (S.fxTab === "stickers") {
    const sel = popItem(S.popSel);
    const own = sel && res.stickers[sel.id];
    const spec = sel ? stickerSpec(sel.id) : res.sticker_default;
    body = `
      <div class="seg-toggle st-layer">
        <button data-fx-starget="default" class="${!sel ? "on" : ""}">Tutti gli sticker</button>
        <button data-fx-starget="sel" class="${sel ? "on" : ""}" ${S.popSel || S.fxLastPop ? "" : "disabled"}>${sel ? `Selezionato ${popThumb(sel)}` : "Sticker selezionato"}</button>
      </div>
      <div class="tx-hint">${sel ? `${own ? "Ha effetti suoi." : "Usa gli effetti di tutti gli sticker."} <button class="link" data-fx-act="preview-sticker">▶ Anteprima</button>${own ? ` · <button class="link" data-fx-act="reset-sticker">Ripristina</button>` : ""}`
        : "Clicca uno sticker nel video per dargli effetti suoi."}</div>
      ${fxPhaseBlock("in", "sticker", spec)}${fxPhaseBlock("out", "sticker", spec)}${fxPhaseBlock("loop", "sticker", spec)}${all}`;
  } else {
    const pt = fx.points.find((b) => b.id === S.fxPoint) ?? null;
    const list = fx.points.map((b) => `
      <button class="st-item${b.id === S.fxPoint ? " on" : ""}" data-fx-point="${esc(b.id)}">
        <span class="t-ico${b.transition ? " on" : ""}">◆</span>
        <span class="st-item-t">${showTime(b.at_ms)} · ${b.transition ? esc(transLabel(b.transition.type)) : "taglio netto"}
          <span class="meta">${KIND_LABEL[b.kind]}${b.block ? " · nuovo blocco" : ""}${b.gap_ms ? ` · tolti ${(b.gap_ms / 1000).toFixed(1).replace(".", ",")} s` : ""}</span></span>
      </button>`).join("");
    let editor = "";
    if (pt) {
      const sid = fx.style ?? "viral";
      const cur = pt.transition ?? { type: "none", ms: 300 };
      const own = res.transitions[pt.id];
      const cards = fx.transitions.filter((t) => S.fxAll || t.sets.includes(sid)).map((t) => `
        <button class="fx-card tr${t.id === cur.type ? " on" : ""}" data-fx-trans="${t.id}">
          <span class="fx-demo tr-demo" data-tr="${t.id}"><i class="a"></i><i class="b"></i></span>
          <span class="fx-name">${esc(t.label)}${t.source === "remotion" ? ' <em class="src">Remotion</em>' : ""}</span></button>`).join("");
      editor = `
        <div class="st-sel">
          <div class="st-sel-head"><span class="st-thumb">◆</span><div><b>Giunta a ${showTime(pt.at_ms)}</b>
            <div class="meta">${KIND_LABEL[pt.kind]}${pt.block ? " dopo una pausa lunga" : ""}${pt.diff != null ? ` · differenza immagine ${pt.diff}` : ""}</div></div>
            <button class="icon-btn" data-fx-act="close-point" title="Chiudi">✕</button></div>
          <div class="fx-grid">${cards}</div>
          ${cur.type !== "none" ? `<div class="section-title">Durata <span class="tx-val" id="fx-trans-val">${(cur.ms / 1000).toFixed(2).replace(".", ",")} s</span></div>
            <input type="range" class="tx-range" data-fx-trange min="100" max="1500" step="10" value="${cur.ms}">` : ""}
          <div class="btn-row tx-actions">
            <button class="btn" data-fx-act="preview-trans">▶ Anteprima</button>
            <button class="btn" data-fx-act="all-trans" ${cur.type === "none" ? "disabled" : ""}>Applica a tutte</button>
            ${own ? `<button class="btn" data-fx-act="auto-trans">Torna all'automatico</button>` : ""}
          </div>
          <div class="tx-hint">Nell'anteprima la transizione è approssimata; nel render è quella vera.</div>
        </div>`;
    }
    body = `${editor}<div class="tx-hint">${fx.points.length} punti dove due clip si toccano: clicca un punto (anche il rombo nella timeline) per scegliere la transizione.</div>
      <div class="st-list">${list || `<div class="tx-hint">Nessun taglio nel montato.</div>`}</div>${all}`;
  }
  return claude + tabs + body;
}

async function saveFx(body, msg) {
  await mutate("/api/effects", body, msg);
}

function fxTarget(el) {
  if (S.fxTab === "text" && !el?.closest('[data-fx-scope="sticker"]')) return { target: "captions" };
  return S.popSel ? { target: "sticker", item: S.popSel } : { target: "sticker_default" };
}

async function fxSuggest() {
  if (S.fxBusy) return;
  S.fxBusy = true;
  renderTextPanels();
  try {
    const data = await api("/api/effects/suggest", {});
    apply(data);
    toast(data.message ?? "Effetti scelti da Claude");
  } catch (e) {
    toast(`Claude non ha risposto: ${e.message}`, true);
  } finally {
    S.fxBusy = false;
    renderTextPanels();
  }
}

// Anteprima di un effetto sulla card: l'"Aa" (o l'emoji) si anima con lo stesso motore.
function runCardDemo(card) {
  const el = card.querySelector(".fx-demo-in");
  if (!el) return;
  const type = card.dataset.fxDemo, phase = card.dataset.fxPhase;
  const t0 = performance.now();
  const step = () => {
    if (!card.matches(":hover")) { applyCss(el, { opacity: 1, transform: "none", filter: "none", clipPath: "none" }); return; }
    const t = (performance.now() - t0) % 1600;
    const spec = { type, ms: 600, speed: 1 };
    const st = phase === "in" ? animState({ inSpec: spec, t, dur: 1600 })
      : phase === "out" ? animState({ outSpec: spec, t: t + 600, dur: 1600 })
      : animState({ loopSpec: spec, t, dur: 1600 });
    applyCss(el, animCss(type.startsWith("words") ? wordState(type, t, 600) : st, "#1FD3CF"));
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function wireEffectsPanel(box) {
  box.addEventListener("mouseover", (e) => {
    const card = e.target.closest("[data-fx-demo]");
    if (card && !card.dataset.running) {
      card.dataset.running = "1";
      runCardDemo(card);
      card.addEventListener("mouseleave", () => delete card.dataset.running, { once: true });
    }
  });
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-fx-tab],[data-fx-pick],[data-fx-act],[data-fx-point],[data-fx-trans],[data-fx-starget],[data-fx-all]");
    if (!b || b.disabled) return;
    const d = b.dataset;
    if (d.fxTab) { S.fxTab = d.fxTab; renderTextPanels(); return; }
    if ("fxAll" in d) { S.fxAll = b.checked; renderTextPanels(); return; }
    if (d.fxStarget) {
      if (d.fxStarget === "default") { S.fxLastPop = S.popSel ?? S.fxLastPop; S.popSel = null; }
      else S.popSel = S.popSel ?? S.fxLastPop;
      renderTextPanels();
      return;
    }
    if (d.fxPick) {
      const phase = d.fxPhase;
      const tg = fxTarget(b);
      const base = (tg.target === "captions" ? captionSpec() : S.popSel ? stickerSpec(S.popSel) : fxRes().sticker_default)[phase];
      const ms = d.fxPick === "none" ? 0 : base && base.type !== "none" ? base.ms : phase === "loop" ? 0 : 350;
      await saveFx({ ...tg, phase, spec: { type: d.fxPick, ms, speed: base?.speed ?? 1 } });
      return;
    }
    if (d.fxPoint) { selectPoint(d.fxPoint); return; }
    if (d.fxTrans) {
      const cur = (S.data.effects.points.find((x) => x.id === S.fxPoint)?.transition) ?? null;
      const dflt = (S.data.effects.style === "premium" ? 500 : 300);
      await saveFx({ target: "transition", item: S.fxPoint, spec: { type: d.fxTrans, ms: cur?.ms ?? dflt } });
      return;
    }
    const act = d.fxAct;
    if (act === "suggest") fxSuggest();
    else if (act === "close-point") { S.fxPoint = null; renderTextPanels(); renderTransitionMarks(); }
    else if (act === "reset-sticker") {
      for (const phase of ["in", "out", "loop"]) await saveFx({ target: "sticker", item: S.popSel, phase, spec: null });
    } else if (act === "auto-trans") saveFx({ target: "transition", item: S.fxPoint, spec: null });
    else if (act === "all-trans") {
      const cur = S.data.effects.points.find((x) => x.id === S.fxPoint)?.transition;
      if (cur) saveFx({ target: "all_transitions", spec: { type: cur.type, ms: cur.ms } }, "Transizione applicata a tutte le giunte");
    } else if (act === "preview-trans") {
      const pt = S.data.effects.points.find((x) => x.id === S.fxPoint);
      if (pt) { setMode("edited"); playWindow(prevKept(pt.at_ms, 1200), pt.end_ms + 1200); }
    } else if (act === "preview-text") {
      const c = S.chunks[S.txChunk] ?? S.chunks.find((x) => x.start >= nowMs());
      if (c) playWindow(c.start - 150, c.end + 600);
    } else if (act === "preview-sticker") {
      const p = popItem(S.popSel);
      if (p) playWindow(p.at_ms - 300, p.at_ms + p.duration_ms + 300);
    }
  });
  box.addEventListener("input", (e) => {
    const r = e.target.closest("[data-fx-range],[data-fx-trange]");
    if (!r) return;
    const v = Number(r.value);
    if ("fxTrange" in r.dataset) { box.querySelector("#fx-trans-val").textContent = `${(v / 1000).toFixed(2).replace(".", ",")} s`; return; }
    const label = box.querySelector(`#fx-${r.dataset.fxRange}-val`);
    label.textContent = r.dataset.fxKey === "speed" ? `${(v / 100).toFixed(2).replace(".", ",")}×` : `${(v / 1000).toFixed(2).replace(".", ",")} s`;
  });
  box.addEventListener("change", async (e) => {
    const r = e.target.closest("[data-fx-range],[data-fx-trange]");
    if (!r) return;
    const v = Number(r.value);
    if ("fxTrange" in r.dataset) {
      const cur = S.data.effects.points.find((x) => x.id === S.fxPoint)?.transition;
      if (cur) await saveFx({ target: "transition", item: S.fxPoint, spec: { type: cur.type, ms: v } });
      return;
    }
    const phase = r.dataset.fxRange;
    const tg = fxTarget(r);
    const base = (tg.target === "captions" ? captionSpec() : S.popSel ? stickerSpec(S.popSel) : fxRes().sticker_default)[phase];
    const spec = { type: base.type, ms: base.ms, speed: base.speed ?? 1 };
    if (r.dataset.fxKey === "speed") spec.speed = v / 100; else spec.ms = v;
    await saveFx({ ...tg, phase, spec });
  });
}

function selectPoint(id) {
  S.fxPoint = id;
  S.fxTab = "trans";
  const pt = S.data.effects.points.find((x) => x.id === id);
  if (pt) { video.pause(); seekMs(prevKept(pt.at_ms, 300)); }
  if (S.viewer) toggleViewerPanel(true, "effects");
  else if (S.leftTab !== "effects" && S.leftTab !== "transitions") { S.leftTab = "effects"; renderLeft(); }
  else renderTextPanels();
  renderTransitionMarks();
}

// Un po' prima di un taglio, dentro la parte tenuta.
function prevKept(ms, back) {
  const i = S.eff.findIndex((r) => r.end_ms >= ms);
  const r = i >= 0 ? S.eff[i] : null;
  return r ? Math.max(r.start_ms, ms - back) : ms - back;
}

function maybeAutoFx() {
  const fx = S.data?.effects;
  const sid = fx?.style;
  if (!sid || fx.resolved.suggested || S.fxAuto[sid] || S.fxBusy) return;
  S.fxAuto[sid] = true;
  setTimeout(fxSuggest, 0);
}

// --- importa un raw (dal PC o da iCloud) e premontaggio ------------------------------------
// Il video si carica dal computer (anche uno scaricato da iCloud) o si sceglie fra quelli già
// nei Download / iCloud Drive; poi parte ingest + trascrizione + tagli e si apre il progetto nuovo.

const IMP = { cands: null, folders: [], scanning: false, busy: "", opening: false };
const impJob = () => S.data?.import ?? { status: "idle" };

function importHTML() {
  const j = impJob();
  const running = j.status === "running" || Boolean(IMP.busy);
  let status = "";
  if (running) {
    status = `<div class="imp-box run"><i class="spinner"></i><div><b>${esc(j.file ?? "")}</b>${j.project ? ` → progetto <code>${esc(j.project)}</code>` : ""}
      <div class="meta">${esc(IMP.busy || j.label || "")}</div></div></div>`;
  } else if (j.status === "done") {
    status = `<div class="imp-box ok"><div>✓ Premontaggio pronto: progetto <b>${esc(j.project)}</b>.
      ${j.can_open ? `<div class="btn-row"><button class="btn vfx-go" data-imp="open" data-p="${esc(j.project)}"${IMP.opening ? " disabled" : ""}>Apri il progetto</button></div>`
        : `<div class="meta">Chiudi l'editor e lancia <code>autocut editor ${esc(j.project)}</code>.</div>`}</div></div>`;
  } else if (j.status === "error") {
    status = `<div class="imp-box err"><div>Non riuscito: ${esc(j.error ?? "errore")}
      <div class="meta">Il video è comunque in <code>raw/${esc(j.project ?? "")}/</code>: sistema il problema (es. la chiave ElevenLabs nel file .env) e rilancia da terminale <code>autocut ingest</code>, <code>transcribe</code>, <code>cuts</code>.</div></div></div>`;
  }
  const cands = IMP.cands === null ? "" : IMP.cands.length
    ? `<div class="st-list">${IMP.cands.map((c) => `
        <button class="st-item${c.placeholder ? " dim" : ""}" data-imp="path" data-path="${esc(c.path)}"${running || c.placeholder ? " disabled" : ""}
          title="${esc(c.path)}"><span class="t-ico on">🎞</span>
          <span class="st-item-t">${esc(c.name)}<span class="meta">${c.placeholder ? "iCloud: non ancora scaricato" : `${c.size_mb} MB`} · ${esc(c.where)}</span></span></button>`).join("")}</div>`
    : `<div class="tx-hint">Nessun video trovato in ${esc(IMP.folders.join(", ") || "Download")}.</div>`;
  return `<div class="imp">
    <div class="btn-row"><button class="btn vfx-go" data-imp="pick"${running ? " disabled" : ""}>＋ Importa un video</button>
      <button class="btn" data-imp="scan"${running || IMP.scanning ? " disabled" : ""}>${IMP.scanning ? "Cerco…" : "🔎 Cerca nei Download e iCloud"}</button></div>
    ${status}${cands}
    <div class="tx-hint"><b>Da iCloud:</b> scarica il video sul PC (icloud.com → Scarica, oppure iCloud per Windows → «Scarica sempre sul dispositivo»), poi sceglilo qui o cercalo nei Download.
      Il video viene copiato in <code>raw/</code> (l'originale non si tocca) e parte il premontaggio: riconosce il file, trascrive il parlato (ElevenLabs Scribe, a pagamento) e toglie le pause.</div>
  </div>`;
}

async function impUpload(file) {
  if (!file || IMP.busy) return;
  IMP.busy = `Carico ${file.name.slice(0, 30)}… (resta aperta la pagina)`;
  renderLeft();
  try {
    const res = await fetch(`/api/import/upload?name=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { "content-type": "application/octet-stream" }, body: file,
    });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch { /* vuoto */ }
      throw new Error(msg);
    }
    S.data.import = await res.json();
    toast("Video caricato: parte il premontaggio");
  } catch (e) {
    toast(e.message, true);
  }
  IMP.busy = "";
  renderLeft();
  managePolling();
}

async function impFromPath(path) {
  try {
    S.data.import = await api("/api/import/from-path", { path });
    toast("Parte il premontaggio");
  } catch (e) { toast(e.message, true); }
  renderLeft();
  managePolling();
}

async function impScan() {
  IMP.scanning = true;
  renderLeft();
  try {
    const d = await api("/api/import/candidates");
    IMP.cands = d.items;
    IMP.folders = d.folders ?? [];
  } catch (e) { toast(e.message, true); }
  IMP.scanning = false;
  renderLeft();
}

async function impOpen(project) {
  if (IMP.opening) return;
  IMP.opening = true;
  try {
    await api("/api/import/open", { project });
  } catch (e) { IMP.opening = false; toast(e.message, true); renderLeft(); return; }
  $("#loading").textContent = `Apro il progetto ${project}: preparo l'anteprima, può volerci qualche minuto…`;
  $("#loading").classList.remove("off");
  await new Promise((r) => setTimeout(r, 2000));
  for (let i = 0; i < 600; i++) {
    try { await api("/api/import"); location.reload(); return; } catch { /* non ancora su */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  $("#loading").textContent = "L'editor non è ripartito: guarda il terminale.";
}

function wireImport(box) {
  box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-imp]");
    if (!b || b.disabled) return;
    switch (b.dataset.imp) {
      case "pick": {
        const input = Object.assign(document.createElement("input"), { type: "file", accept: "video/*,.mov,.mp4,.m4v,.mkv,.avi,.webm" });
        input.addEventListener("change", () => impUpload(input.files[0]));
        input.click();
        break;
      }
      case "scan": impScan(); break;
      case "path": impFromPath(b.dataset.path); break;
      case "open": impOpen(b.dataset.p); break;
    }
  });
  box.addEventListener("dragover", (e) => {
    if (S.leftTab === "media" && [...(e.dataTransfer?.types ?? [])].includes("Files")) { e.preventDefault(); box.classList.add("img-drop"); }
  });
  box.addEventListener("dragleave", () => box.classList.remove("img-drop"));
  box.addEventListener("drop", (e) => {
    box.classList.remove("img-drop");
    if (S.leftTab !== "media" || !e.dataTransfer?.files?.length) return;
    e.preventDefault();
    impUpload(e.dataTransfer.files[0]);
  });
}

// --- Salva: punti di ripristino con nome ---------------------------------------------------
// Ogni modifica si salva da sola nei file del progetto; qui si fissa una versione con un nome,
// a cui si torna quando si vuole (anche dopo aver chiuso e riaperto l'editor).

const VER = { open: false, name: "" };

function renderVersions() {
  const pop = $("#ver-pop");
  if (!pop) return;
  pop.hidden = !VER.open;
  $("#btn-save")?.classList.toggle("on", VER.open);
  if (!VER.open) return;
  const when = (iso) => new Date(iso).toLocaleString("it-IT", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const list = (S.data?.versions ?? []).map((v) => `
    <div class="ver-row"><div><b>${esc(v.name)}</b><div class="meta">${esc(when(v.created_at))}</div></div>
      <button class="btn" data-ver="restore" data-id="${esc(v.id)}">Ripristina</button>
      <button class="icon-btn" data-ver="del" data-id="${esc(v.id)}" title="Elimina questa versione">✕</button></div>`).join("");
  const keep = document.activeElement?.id === "ver-name";
  pop.innerHTML = `<div class="ver-head"><b>Salva il progetto</b><button class="icon-btn" data-ver="close" title="Chiudi">✕</button></div>
    <p class="tx-hint">Ogni modifica è già salvata da sola. Qui fissi una <b>versione con un nome</b>: ci torni quando vuoi, anche dopo aver chiuso e riaperto l'editor (e Annulla annulla anche il ritorno).</p>
    <div class="ver-new"><input id="ver-name" maxlength="60" placeholder="Nome, es. Prima delle grafiche" value="${esc(VER.name)}">
      <button class="btn vfx-go" data-ver="save">💾 Salva</button></div>
    <div class="st-sub">Versioni salvate (${(S.data?.versions ?? []).length})</div>
    ${list || `<div class="tx-hint">Ancora nessuna versione.</div>`}`;
  if (keep) { const t = $("#ver-name"); t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
}

function wireVersions() {
  $("#btn-save").addEventListener("click", () => { VER.open = !VER.open; renderVersions(); if (VER.open) $("#ver-name")?.focus(); });
  const pop = $("#ver-pop");
  pop.addEventListener("input", (e) => { if (e.target.id === "ver-name") VER.name = e.target.value; });
  pop.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter" && e.target.id === "ver-name") saveVersion();
    if (e.key === "Escape") { VER.open = false; renderVersions(); }
  });
  pop.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-ver]");
    if (!b) return;
    const id = b.dataset.id;
    if (b.dataset.ver === "close") { VER.open = false; renderVersions(); }
    else if (b.dataset.ver === "save") saveVersion();
    else if (b.dataset.ver === "restore") {
      if (confirm("Tornare a questa versione? Quello che hai fatto dopo si può recuperare con Annulla.")) {
        await mutate(`/api/versions/${id}/restore`, {}, "Versione ripristinata");
      }
    } else if (b.dataset.ver === "del") {
      if (confirm("Eliminare questa versione salvata?")) await mutate(`/api/versions/${id}/delete`, {}, "Versione eliminata");
    }
  });
  document.addEventListener("mousedown", (e) => {
    if (VER.open && !e.target.closest("#ver-pop, #btn-save")) { VER.open = false; renderVersions(); }
  });
}

async function saveVersion(quick = false) {
  const name = quick ? "" : VER.name.trim();
  const d = new Date();
  const label = name || `Versione ${d.toLocaleDateString("it-IT", { day: "numeric", month: "short" })} ${d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}`;
  if (await mutate("/api/versions", { name: label }, `Salvato: ${label}`)) VER.name = "";
  renderVersions();
}

// --- icone a sinistra della timeline: cliccabili --------------------------------------------

function openLeftTab(tab) {
  if (S.viewer) { toggleViewerPanel(true, tab); return; }
  if (S.leftTab !== tab) { S.leftTab = tab; renderLeft(); } else renderTextPanels();
}

function wireTimelineHeads() {
  $(".tl-heads").addEventListener("click", (e) => {
    const mute = e.target.closest("[data-head-mute]");
    if (mute) {
      const a = audioData();
      if (a) saveAudio({ target: "mix", fields: { voice_muted: !a.voice_muted } }, a.voice_muted ? "Voce attiva" : "Voce muta");
      return;
    }
    const h = e.target.closest(".head");
    const cur = nowMs();
    if (h?.classList.contains("text-head")) {
      // modifica testo: la frase sotto la testina (o la prossima) si seleziona e si scrive nel pannello
      let i = S.chunks.findIndex((c) => cur >= c.start && cur < c.end);
      if (i < 0) i = S.chunks.findIndex((c) => c.start > cur);
      if (i < 0) i = S.chunks.length - 1;
      if (i >= 0) openCaptionEditor(i); else openLeftTab("text");
    } else if (h?.classList.contains("video-head")) {
      // la clip sotto la testina si seleziona: poi Togli (Canc), Dividi (Ctrl+B), o trascina i bordi
      const p = visiblePieces().find((x) => x.keep && cur >= x.start && cur < x.end);
      if (p) { selectPiece(p.start, p.end, false); toast("Clip selezionata: Dividi (Ctrl+B) o Togli (Canc)"); }
      else toast("Qui non c'è nessuna clip tenuta: sposta la testina", true);
    } else if (h?.classList.contains("audio-head") || h?.classList.contains("vo-head")) {
      openLeftTab("audio");
    } else if (h?.classList.contains("vfx-head")) openLeftTab("vfx");
    else if (h?.classList.contains("broll-head")) openLeftTab("broll");
  });
}

function renderHeadMute() {
  const b = $("#head-mute");
  if (!b) return;
  const m = Boolean(audioData()?.voice_muted);
  b.textContent = m ? "🔇" : "🔊";
  b.classList.toggle("on", m);
  b.title = m ? "La voce è muta: clic per riattivarla" : "Voce della clip: clic per mutarla (il volume è nella scheda Audio)";
}

// --- pannelli ridimensionabili (stile CapCut) --------------------------------------------
// Maniglie fra i pannelli: si trascinano per ingrandire o rimpicciolire (doppio clic = misura
// originale, frecce da tastiera = 20 px). Le misure restano salvate nel browser.

const LAYOUT_KEY = "autocut-layout";
const LAYOUT_DEF = { left: 330, right: 380, tl: 370, viewer: 340, askW: 400, askH: 560 };
const LAYOUT_VAR = { left: "--left-w", right: "--right-w", tl: "--tl-h", viewer: "--viewer-w", askW: "--ask-w", askH: "--ask-h" };
const L = { ...LAYOUT_DEF };

function layoutLimits(k) {
  const w = window.innerWidth, h = window.innerHeight;
  const hi = {
    left: w - L.right - 12 - 320, right: w - L.left - 12 - 320, tl: h - 44 - 18 - 220,
    viewer: w - 360, askW: w - 36, askH: h - 36,
  }[k];
  const lo = { left: 200, right: 240, tl: 230, viewer: 240, askW: 300, askH: 300 }[k];
  return [lo, Math.max(lo, hi)];
}

function layoutSet(k, v) {
  const [lo, hi] = layoutLimits(k);
  L[k] = Math.round(Math.min(hi, Math.max(lo, Number(v) || LAYOUT_DEF[k])));
  document.documentElement.style.setProperty(LAYOUT_VAR[k], `${L[k]}px`);
}

function layoutSave() {
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(L)); } catch { /* archivio non disponibile */ }
}

function layoutRefit() { // il lettore si adatta alla nuova misura del pannello
  if (layoutRefit.raf) return;
  layoutRefit.raf = requestAnimationFrame(() => { layoutRefit.raf = 0; fitFrame(); });
}

/** Rende `el` una maniglia: `axes` = [{key, axis: "x"|"y", dir}] (dir -1 = trascinando verso sinistra/alto cresce). */
function wireResizer(el, axes) {
  if (!el) return;
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    const start = { x: e.clientX, y: e.clientY }, base = Object.fromEntries(axes.map((a) => [a.key, L[a.key]]));
    el.classList.add("drag");
    document.body.classList.add("resizing", axes[0].axis === "x" ? "col" : "row");
    const move = (ev) => {
      for (const a of axes) layoutSet(a.key, base[a.key] + a.dir * (a.axis === "x" ? ev.clientX - start.x : ev.clientY - start.y));
      layoutRefit();
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.classList.remove("drag");
      document.body.classList.remove("resizing", "col", "row");
      layoutSave();
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  });
  el.addEventListener("dblclick", () => { axes.forEach((a) => layoutSet(a.key, LAYOUT_DEF[a.key])); layoutSave(); layoutRefit(); });
  el.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: -20, ArrowUp: -20, ArrowRight: 20, ArrowDown: 20 }[e.key];
    if (step == null) return;
    e.preventDefault();
    const a = axes[0];
    if ((a.axis === "x") !== (e.key === "ArrowLeft" || e.key === "ArrowRight")) return;
    layoutSet(a.key, L[a.key] + a.dir * step);
    layoutSave();
    layoutRefit();
  });
}

function wireLayout() {
  try { Object.assign(L, JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}")); } catch { /* misure di default */ }
  if (L.tl === 300) L.tl = LAYOUT_DEF.tl; // misura vecchia: ora la timeline ha due tracce in più (B-roll, voice-over)
  Object.keys(LAYOUT_VAR).forEach((k) => layoutSet(k, L[k]));
  wireResizer($("#rz-left"), [{ key: "left", axis: "x", dir: 1 }]);
  wireResizer($("#rz-right"), [{ key: "right", axis: "x", dir: -1 }]);
  wireResizer($("#rz-tl"), [{ key: "tl", axis: "y", dir: -1 }]);
  wireResizer($("#rz-viewer"), [{ key: "viewer", axis: "x", dir: -1 }]);
  window.addEventListener("resize", () => Object.keys(LAYOUT_VAR).forEach((k) => layoutSet(k, L[k])));
}

// --- avvio ---------------------------------------------------------------------

async function init() {
  try {
    const data = await api("/api/project");
    apply(data);
    video.src = data.media.video_url;
    S.wave = await (await fetch(data.media.waveform_url)).json();
    try {
      const emo = await api("/api/emoji");
      S.emoCats = emo.categories;
      for (const c of emo.categories) for (const i of c.items) S.emoMap.set(emoKey(i.e), i.img);
      $("#popup-layer").dataset.key = "";
      renderLeft();
    } catch { /* senza libreria: emoji col font */ }
    wireLayout();
    wireEvents();
    wireAsk();
    fitFrame();
    fitZoom();
    $("#loading").classList.add("off");
    requestAnimationFrame(tick);
  } catch (e) {
    $("#loading").textContent = `Errore nel caricare il progetto: ${e.message}`;
  }
}

// --- Musica di sottofondo (libreria gratuita Audio Library su YouTube) ----------------------
// Claude ascolta il parlato e lo stile, sceglie il mood e 5 brani (già scaricati: si ascoltano
// subito), e il punto da cui farli partire. La musica va su tutto il video o su un tratto; volume,
// muto, partenza e dissolvenze si cambiano qui. I crediti per la descrizione sono pronti da copiare.

const MU = { range: null, note: "", q: "", results: null, searching: false, audios: new Map(), preview: null, sel: null };
const muData = () => S.data?.music ?? { items: [], suggestion: null, job: { status: "idle" }, credits: "", catalog_count: 0 };
const muSec = (s) => `${Math.floor((s ?? 0) / 60)}:${String(Math.round((s ?? 0) % 60)).padStart(2, "0")}`;
const muRange = (a, b) => (a == null && b == null ? "tutto il video" : `${a == null ? "inizio" : showTime(a)} → ${b == null ? "fine" : showTime(b)}`);

function muStopPreview() {
  if (MU.preview) { MU.preview.pause(); MU.preview = null; }
  document.querySelectorAll("[data-mu=preview].on").forEach((b) => b.classList.remove("on"));
}

function muPreview(url, offsetMs, db, btn) {
  const same = MU.preview && MU.preview.dataset.src === url;
  muStopPreview();
  if (same) return;
  const au = Object.assign(new Audio(url), { preload: "auto" });
  au.dataset.src = url;
  au.volume = Math.max(0.05, Math.min(1, Math.pow(10, (db + 14) / 20))); // ascolto: un po' più forte del mix
  au.currentTime = (offsetMs ?? 0) / 1000;
  au.play().catch(() => {});
  MU.preview = au;
  btn?.classList.add("on");
}

function muTrackLine(t) {
  if (!t) return "";
  return `<b>${esc(t.song || t.id)}</b> <span class="meta">${esc(t.artist || "")} · ${muSec(t.duration_s)}</span>
    <div class="meta">${esc(t.mood || "")}${t.uses ? ` · per ${esc(t.uses)}` : ""}</div>`;
}

function musicCardHTML() {
  const m = muData();
  const job = m.job ?? {};
  const running = job.status === "running";
  const range = MU.range;
  const items = m.items.map((it) => {
    const t = it.track_info ?? {};
    const secs = (t.breakdown ?? []).map((b) => `<option value="${b.at_s * 1000}"${Math.abs(b.at_s * 1000 - it.offset_ms) < 500 ? " selected" : ""}>${muSec(b.at_s)} · ${esc(b.text)}</option>`).join("");
    return `<div class="mu-item${it.muted ? " dim" : ""}${MU.sel === it.id ? " on" : ""}">
      <div class="mu-row"><button class="icon-btn" data-mu="preview" data-url="${esc(t.url || "")}" data-off="${it.offset_ms}" data-db="${it.preview_db}" title="Ascolta">▶</button>
        <div class="mu-t">${muTrackLine(t)}<div class="meta">${esc(muRange(it.start_ms, it.end_ms))} · parte da ${muSec(it.offset_ms / 1000)}${it.origin === "ai" ? " · scelta da Claude" : ""}</div></div></div>
      <div class="section-title">Volume <span class="tx-val" id="mu-val-${esc(it.id)}">${dbTxt(it.gain_db)}</span></div>
      <input type="range" class="tx-range" data-mu-gain="${esc(it.id)}" min="-300" max="120" step="5" value="${Math.round(it.gain_db * 10)}">
      ${secs ? `<div class="section-title">Parte da</div><select class="au-select" data-mu-offset="${esc(it.id)}"><option value="0"${it.offset_ms === 0 ? " selected" : ""}>0:00 · inizio del brano</option>${secs}</select>` : ""}
      <div class="btn-row tx-actions">
        <button class="btn${it.muted ? " on" : ""}" data-mu="mute" data-id="${esc(it.id)}">${it.muted ? "🔇 Muta" : "🔊 Attiva"}</button>
        <button class="btn" data-mu="range" data-id="${esc(it.id)}" title="Usa il tratto scelto qui sotto (o tutto il video)">Tratto: ${range ? "quello scelto" : "tutto"}</button>
        <button class="btn" data-mu="regen" title="Claude propone altri brani">↻ Rigenera</button>
        <button class="btn danger" data-mu="remove" data-id="${esc(it.id)}">Togli</button>
      </div></div>`;
  }).join("");
  const sug = m.suggestion;
  const cands = (sug?.candidates ?? []).map((c, i) => {
    const t = c.track_info ?? {};
    const used = m.items.some((it) => it.track === c.id);
    return `<div class="mu-cand${used ? " used" : ""}">
      <button class="icon-btn" data-mu="preview" data-url="${esc(t.url || "")}" data-off="${c.offset_ms}" data-db="${c.preview_db}" title="Ascolta dal punto scelto">▶</button>
      <div class="mu-t">${i === 0 ? `<span class="chip on">consigliata</span> ` : ""}${muTrackLine(t)}
        <div class="meta">${c.section ? `parte da ${muSec(c.offset_ms / 1000)} (${esc(c.section)}) · ` : ""}${esc(c.why)}</div></div>
      <button class="btn small" data-mu="use" data-track="${esc(c.id)}" data-off="${c.offset_ms}">${used ? "Di nuovo" : "Usa"}</button>
    </div>`;
  }).join("");
  const res = (MU.results ?? []).map((t) => `
    <div class="mu-cand">
      <button class="icon-btn" data-mu="dl-play" data-track="${esc(t.id)}" title="${t.downloaded ? "Ascolta" : "Scarica e ascolta"}">${t.downloaded ? "▶" : "⤓"}</button>
      <div class="mu-t">${muTrackLine({ ...t, duration_s: t.duration_s })}</div>
      <button class="btn small" data-mu="use" data-track="${esc(t.id)}" data-off="0">Usa</button>
    </div>`).join("");
  const status = running ? `<div class="vfx-run"><i></i><span><b>${esc(job.progress || "scelgo la musica")}…</b></span></div>`
    : job.status === "error" ? `<div class="tx-hint err">${esc(job.message)}</div>`
      : job.message ? `<div class="tx-hint">${esc(job.message)}</div>` : "";
  return `<div class="au-card mu-card">
    <div class="au-head"><b>🎵 Musica di sottofondo</b><span class="meta">Audio Library · gratis</span></div>
    ${m.style_music === false ? `<div class="tx-hint">Questo stile è pensato senza musica, ma puoi aggiungerla.</div>` : ""}
    ${items || `<div class="tx-hint">Nessuna musica nel video.</div>`}
    <div class="section-title">Dove</div>
    <div class="btn-row tx-actions">
      <button class="btn${range ? "" : " on"}" data-mu="all">Tutto il video</button>
      <button class="btn" data-mu="from" title="L'inizio del tratto è dove c'è la testina">Da qui</button>
      <button class="btn" data-mu="to" title="La fine del tratto è dove c'è la testina">A qui</button>
    </div>
    <div class="meta">Tratto: ${esc(range ? muRange(range.start_ms, range.end_ms) : "tutto il video")}</div>
    <input class="au-select mu-note" data-mu-note placeholder="Facoltativo: es. più energica, niente lo-fi" value="${esc(MU.note)}" maxlength="200">
    <button class="btn vfx-go" data-mu="suggest"${running ? " disabled" : ""}>✦ ${sug ? "Proponi altri brani" : "Scegli la musica con Claude"}</button>
    ${status}
    ${sug ? `<div class="st-sub">Proposte per il mood «${esc(sug.vibe)}» ${sug.start_ms != null || sug.end_ms != null ? `(${esc(muRange(sug.start_ms, sug.end_ms))})` : ""}</div><div class="mu-list">${cands}</div>` : ""}
    <div class="st-sub">Cerca nella libreria (${m.catalog_count || "4000+"} brani)</div>
    <div class="mu-search"><input class="au-select" data-mu-q placeholder="es. motivational cinematic, chill lo-fi" value="${esc(MU.q)}"><button class="btn" data-mu="search"${MU.searching ? " disabled" : ""}>${MU.searching ? "…" : "Cerca"}</button></div>
    ${res ? `<div class="mu-list">${res}</div>` : ""}
    ${m.credits ? `<div class="st-sub">Crediti da incollare nella descrizione</div>
      <textarea class="mu-credits" readonly rows="4">${esc(m.credits)}</textarea>
      <button class="btn small" data-mu="copy">Copia i crediti</button>` : ""}
  </div>`;
}

const saveMusic = (body, msg) => mutate("/api/music/item", body, msg);

function wireMusicPanel(box) {
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-mu]");
    if (!b || b.disabled) return;
    const d = b.dataset;
    const m = muData();
    switch (d.mu) {
      case "preview":
        if (!d.url) { toast("Brano non ancora scaricato", true); return; }
        muPreview(d.url, Number(d.off), Number(d.db), b); break;
      case "all": MU.range = null; renderTextPanels(); break;
      case "from": MU.range = { start_ms: Math.round(nowMs()), end_ms: MU.range?.end_ms ?? null }; renderTextPanels(); break;
      case "to": MU.range = { start_ms: MU.range?.start_ms ?? null, end_ms: Math.round(nowMs()) }; renderTextPanels(); break;
      case "suggest": case "regen": {
        const r = MU.range ?? {};
        const out = await mutate("/api/music/suggest", { start_ms: r.start_ms ?? null, end_ms: r.end_ms ?? null, note: MU.note }, "Claude sceglie la musica (circa un minuto)");
        if (out) managePolling();
        break;
      }
      case "use": {
        muStopPreview();
        const r = MU.range ?? {};
        await saveMusic({ action: "use", track: d.track, fields: { offset_ms: Number(d.off) || 0, start_ms: r.start_ms ?? null, end_ms: r.end_ms ?? null } }, "Musica nel video");
        break;
      }
      case "mute": {
        const it = m.items.find((x) => x.id === d.id);
        if (it) saveMusic({ action: "update", id: it.id, fields: { muted: !it.muted } });
        break;
      }
      case "range": {
        const r = MU.range ?? {};
        saveMusic({ action: "update", id: d.id, fields: { start_ms: r.start_ms ?? null, end_ms: r.end_ms ?? null } }, "Tratto della musica aggiornato");
        break;
      }
      case "remove": muStopPreview(); saveMusic({ action: "remove", id: d.id }, "Musica tolta"); break;
      case "search": {
        MU.searching = true; renderTextPanels();
        try {
          const r = await api(`/api/music/search?q=${encodeURIComponent(MU.q)}`);
          MU.results = r.results;
        } catch (err) { toast(err.message, true); }
        MU.searching = false; renderTextPanels();
        break;
      }
      case "dl-play": {
        b.textContent = "…";
        try {
          const r = await api("/api/music/download", { id: d.track });
          apply(r);
          const hit = (MU.results ?? []).find((x) => x.id === d.track);
          if (hit) hit.downloaded = true;
          renderTextPanels();
          if (r.track?.url) muPreview(r.track.url, 0, -20, null);
        } catch (err) { toast(err.message, true); b.textContent = "⤓"; }
        break;
      }
      case "copy":
        try { await navigator.clipboard.writeText(m.credits); toast("Crediti copiati"); } catch { toast("Selezionali e copiali a mano", true); }
        break;
    }
  });
  box.addEventListener("input", (e) => {
    if (e.target.matches("[data-mu-note]")) MU.note = e.target.value;
    else if (e.target.matches("[data-mu-q]")) MU.q = e.target.value;
    else if (e.target.matches("[data-mu-gain]")) {
      S.txSliding = e.target;
      const v = Number(e.target.value) / 10;
      const lab = box.querySelector(`#mu-val-${CSS.escape(e.target.dataset.muGain)}`);
      if (lab) lab.textContent = dbTxt(v);
    }
  });
  box.addEventListener("keydown", (e) => {
    if (e.target.matches("[data-mu-q]") && e.key === "Enter") { e.preventDefault(); box.querySelector("[data-mu=search]")?.click(); }
  });
  box.addEventListener("change", (e) => {
    if (e.target.matches("[data-mu-gain]")) {
      S.txSliding = null;
      saveMusic({ action: "update", id: e.target.dataset.muGain, fields: { gain_db: Number(e.target.value) / 10 } });
    } else if (e.target.matches("[data-mu-offset]")) {
      saveMusic({ action: "update", id: e.target.dataset.muOffset, fields: { offset_ms: Number(e.target.value) } }, "Punto di partenza cambiato");
    }
  });
}

// Anteprima: la musica suona sotto il video (tempo sul montato, come nel render).
function updateMusic(cur) {
  const m = muData();
  const ids = new Set();
  for (const it of m.items) {
    const url = it.track_info?.url;
    if (!url || it.muted) continue;
    ids.add(it.id);
    let au = MU.audios.get(it.id);
    if (!au || au.dataset.src !== url) {
      au?.pause();
      au = Object.assign(new Audio(url), { preload: "auto", loop: true });
      au.dataset.src = url;
      MU.audios.set(it.id, au);
    }
    const a = it.start_ms ?? S.axisStart, b = it.end_ms ?? S.axisEnd;
    const inside = cur >= a && cur < b && !(S.mode === "edited" && isCut(cur));
    const pos = (S.mode === "edited" ? editedAt(cur) - editedAt(a) : cur - a) + it.offset_ms;
    const dur = (it.track_info?.duration_s ?? 0) * 1000;
    const t = dur > 0 ? pos % dur : pos;
    const fadeIn = Math.min(1, (cur - a) / Math.max(1, it.fade_in_ms)), fadeOut = Math.min(1, (b - cur) / Math.max(1, it.fade_out_ms));
    au.volume = Math.max(0, Math.min(1, Math.pow(10, it.preview_db / 20) * Math.max(0, Math.min(fadeIn, fadeOut))));
    if (inside && !video.paused) {
      if (Math.abs(au.currentTime * 1000 - t) > 300) au.currentTime = t / 1000;
      if (au.paused) au.play().catch(() => {});
    } else if (!au.paused) au.pause();
  }
  for (const [id, au] of MU.audios) if (!ids.has(id)) { au.pause(); MU.audios.delete(id); }
}

function musicTrackHTML() {
  return muData().items.map((it) => {
    const a = it.start_ms ?? S.axisStart, b = it.end_ms ?? S.axisEnd;
    return `<div class="mu-bar${it.muted ? " muted" : ""}" style="left:${xOf(a)}px;width:${Math.max(6, xOf(b) - xOf(a))}px" title="🎵 ${esc(it.track_info?.song || it.track)}${it.muted ? " · muta" : ""}">🎵 ${esc(it.track_info?.song || "")}</div>`;
  }).join("");
}

// --- Chiedi a Claude: chat collegata a Claude Code (Edita il video / Modifica l'editor) -----
// Edita: selezioni un tratto (trascini) o un fotogramma (clic) sulla timeline e chiedi; Claude
// usa gli strumenti dell'editor e le modifiche arrivano con un solo Annulla. Modifica l'editor:
// Claude Code cambia il codice; alla fine la pagina si ricarica (e l'editor si riavvia se serve).

const ASK_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const ASK_MAX_IMAGES = 4, ASK_MAX_BYTES = 8_000_000;
const ASK = {
  open: false, mode: "edit", text: "", sel: null, selecting: false, data: null, images: [],
  timer: null, tick: null, handled: new Set(), first: true, waitingRestart: false,
};
const ASK_KEY = "autocut-ask";
const ASK_STAR = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3 1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>`;

function askLoadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(ASK_KEY) || "{}");
    ASK.open = !!p.open;
    ASK.mode = p.mode === "dev" ? "dev" : "edit";
    (p.handled ?? []).forEach((id) => ASK.handled.add(id));
  } catch { /* niente preferenze salvate */ }
}

function askSavePrefs() {
  try {
    localStorage.setItem(ASK_KEY, JSON.stringify({ open: ASK.open, mode: ASK.mode, handled: [...ASK.handled].slice(-200) }));
  } catch { /* archivio del browser non disponibile */ }
}

const askSec = (s) => (s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`);

function askSelLabel(sel) {
  if (!sel) return "";
  if (sel.start_ms != null && sel.end_ms != null) return `${clock(sel.start_ms)} → ${clock(sel.end_ms)}`;
  if (sel.frame_ms != null) return `fotogramma ${clock(sel.frame_ms)}`;
  return "";
}

function askCaptions(sel) {
  const a = sel.start_ms ?? sel.frame_ms, b = sel.end_ms ?? sel.frame_ms;
  const scenes = S.data?.text?.scenes ?? {};
  return (S.chunks ?? []).filter((c) => c.end >= a && c.start <= b).slice(0, 80)
    .map((c) => ({ id: c.id, text: c.text, start_ms: c.start, end_ms: c.end, scale: scenes[c.id]?.scale ?? 1, edited: !!scenes[c.id] }));
}

function askMessageHTML(m) {
  const sel = m.selection ? `<span class="ask-chip">${esc(askSelLabel(m.selection))}</span>` : "";
  const mode = m.mode === "dev" ? "Modifica l'editor" : "Edita il video";
  const shots = (m.images ?? []).length
    ? `<div class="ask-shots">${m.images.map((n) => `<a class="ask-shot" href="/api/assistant/image/${esc(n)}" target="_blank" rel="noopener"><img src="/api/assistant/image/${esc(n)}" alt="screenshot"></a>`).join("")}</div>` : "";
  const user = `<div class="ask-msg me"><div class="ask-meta">${esc(mode)} ${sel}</div>${shots}<div>${esc(m.prompt)}</div></div>`;
  let body;
  if (m.status === "running") {
    const el = Date.now() / 1000 - (m.t0 ?? Date.now() / 1000);
    const steps = (m.steps ?? []).slice(-5).map((s) => `<li><span>${esc(askSec(s.t))}</span>${esc(s.text)}</li>`).join("");
    body = `<div class="ask-run"><i></i><b>Claude sta lavorando</b><span class="ask-el" data-t0="${m.t0}">${askSec(el)}</span></div>
      ${steps ? `<ul class="ask-steps">${steps}</ul>` : `<div class="ask-meta">Leggo la richiesta…</div>`}`;
  } else if (m.status === "error") {
    body = `<div class="ask-err">Non riuscito: ${esc(m.error || "errore")}</div>`;
  } else {
    const files = m.mode === "dev"
      ? [...(m.files?.changed ?? []), ...(m.files?.added ?? [])]
      : (m.changed ?? []);
    const list = files.length ? `<details><summary class="ask-meta">${files.length} file ${m.mode === "dev" ? "di codice" : "del progetto"} cambiati</summary><div class="ask-files">${files.map(esc).join("<br>")}</div></details>` : "";
    const steps = (m.steps ?? []).length ? `<details><summary class="ask-meta">Cosa ha fatto (${m.steps.length} passi, ${askSec(m.elapsed_s ?? 0)})</summary><ul class="ask-steps">${m.steps.map((s) => `<li><span>${esc(askSec(s.t))}</span>${esc(s.text)}</li>`).join("")}</ul></details>` : "";
    const missing = m.missing ? `<div class="ask-missing">Manca all'editor: ${esc(m.missing)}
      <button class="btn" data-ask="build" data-text="${esc(m.missing)}">Aggiungilo all'editor</button></div>` : "";
    const how = m.how_to_use ? `<div class="ask-meta">Dove lo trovi: ${esc(m.how_to_use)}</div>` : "";
    const tests = m.tests ? `<div class="ask-meta">Controlli: ${esc(m.tests)}</div>` : "";
    const revert = m.mode === "dev" && files.length
      ? (m.reverted ? `<div class="ask-meta">Modifiche annullate.</div>` : `<button class="btn" data-ask="revert" data-id="${esc(m.id)}">Annulla modifiche</button>`)
      : "";
    const undo = m.mode === "edit" && files.length ? `<div class="ask-meta">Applicato: lo togli con Annulla (Ctrl+Z).</div>` : "";
    body = `<div class="ask-sum">${esc(m.summary || "Fatto.").replace(/\n/g, "<br>")}</div>${how}${tests}${missing}${undo}${list}${steps}${revert}`;
  }
  return `${user}<div class="ask-msg claude"><div class="ask-meta">${ASK_STAR} Claude</div>${body}</div>`;
}

function renderAsk() {
  const fab = $("#ask-fab"), panel = $("#ask-panel");
  if (!fab || !panel) return;
  fab.hidden = ASK.open;
  panel.hidden = !ASK.open;
  document.body.classList.toggle("ask-selecting", ASK.selecting);
  renderAskSel();
  if (!ASK.open) return;
  const d = ASK.data ?? { messages: [], running: false };
  const msgs = d.messages.map(askMessageHTML).join("");
  const edit = ASK.mode === "edit";
  const hint = edit
    ? "Es. «la scritta più grande con bagliore e fade» · «bianco e nero e sotto la frase l'emoji del pianto»"
    : "Es. «aggiungi una scheda per…» · «nel pannello Audio voglio un pulsante che…»";
  const selRow = edit ? `<div class="ask-selrow">${ASK.sel
    ? `<span class="ask-chip on">${esc(askSelLabel(ASK.sel))}</span><button class="btn" data-ask="unsel" title="Togli la selezione">✕</button>`
    : `<span class="ask-meta">Nessuna selezione: vale per tutto il video</span>`}
    <button class="btn${ASK.selecting ? " on" : ""}" data-ask="select">${ASK.selecting ? "Trascina sulla timeline…" : "Seleziona sulla timeline"}</button></div>` : "";
  const box = panel.querySelector(".ask-list");
  const keepScroll = box && box.scrollHeight - box.scrollTop - box.clientHeight > 40 ? box.scrollTop : null;
  const focused = document.activeElement?.id === "ask-text";
  panel.innerHTML = `<div class="ask-head">${ASK_STAR}<b>Chiedi a Claude</b>
      <button class="icon-btn" data-ask="clear" title="Nuova conversazione">⟲</button><button class="icon-btn" data-ask="close" title="Chiudi">✕</button></div>
    <div class="ask-tabs"><button class="${edit ? "on" : ""}" data-ask="mode" data-v="edit">Edita il video</button><button class="${edit ? "" : "on"}" data-ask="mode" data-v="dev">Modifica l'editor</button></div>
    <div class="ask-list">${msgs || `<div class="ask-empty">${edit
      ? "Seleziona un tratto o un fotogramma e chiedi cosa fare: Claude sceglie gli strumenti dell'editor (testi, effetti, pop-up, suoni, tagli) e applica le modifiche."
      : "Chiedi una nuova funzione o una modifica all'editor: Claude Code lavora sul codice come in una sessione normale, ti mostra cosa sta facendo e alla fine l'editor si ricarica da solo."}</div>`}</div>
    ${selRow}
    ${ASK.images.length ? `<div class="ask-shots">${ASK.images.map((im, i) => `<div class="ask-shot"><img src="${im}" alt="screenshot ${i + 1}"><button data-ask="rmshot" data-i="${i}" title="Togli l'immagine">✕</button></div>`).join("")}</div>` : ""}
    <div class="ask-tools"><button class="btn" data-ask="shot" title="Fai uno screenshot dell'editor, evidenzia un punto e allegalo qui">📸 Screenshot</button>
      <button class="btn" data-ask="attach" title="Allega un'immagine (o incolla con Ctrl+V, o trascinala qui)">📎 Immagine</button>
      <span class="ask-meta">Mostrami cosa vedi</span></div>
    <div class="ask-input"><textarea id="ask-text" rows="2" maxlength="4000" placeholder="${esc(hint)}">${esc(ASK.text)}</textarea>
      <button class="btn vfx-go" data-ask="send"${d.running ? " disabled" : ""}>${d.running ? "Lavora…" : "Invia"}</button></div>`;
  panel.append(...askHandles); // le maniglie per ingrandire/rimpicciolire non si perdono col ridisegno
  const list = panel.querySelector(".ask-list");
  list.scrollTop = keepScroll ?? list.scrollHeight;
  if (focused) { const t = $("#ask-text"); t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
}

function renderAskSel() {
  const el = $("#ask-sel");
  if (!el) return;
  const sel = ASK.open && ASK.mode === "edit" ? ASK.sel : null;
  if (!sel) { el.hidden = true; return; }
  const a = sel.start_ms ?? sel.frame_ms, b = sel.end_ms ?? sel.frame_ms;
  el.hidden = false;
  el.classList.toggle("point", sel.start_ms == null);
  el.style.left = `${xOf(a)}px`;
  el.style.width = `${Math.max(2, xOf(b) - xOf(a))}px`;
}

async function askRefresh() {
  try {
    askOnData(await api("/api/assistant"));
  } catch { /* l'editor si sta riavviando o è spento: si riprova */ }
}

function askOnData(d) {
  const prev = new Map((ASK.data?.messages ?? []).map((m) => [m.id, m.status]));
  ASK.data = d;
  if (ASK.first) { // all'apertura: quello già finito non fa ricaricare la pagina
    d.messages.filter((m) => m.status !== "running").forEach((m) => ASK.handled.add(m.id));
    ASK.first = false;
    askSavePrefs();
  }
  for (const m of d.messages) {
    if (m.status === "running" || ASK.handled.has(m.id)) continue;
    ASK.handled.add(m.id);
    askSavePrefs();
    if (m.mode === "edit" && prev.get(m.id) === "running" && (m.changed ?? []).length) {
      api("/api/project").then(apply).catch(() => {});
      toast("Claude ha modificato il video");
    }
    if (m.mode === "dev" && m.status === "done" && !m.reverted) {
      const files = [...(m.files?.changed ?? []), ...(m.files?.added ?? [])];
      if (m.restart && d.can_restart) { renderAsk(); askRestart(); return; }
      if (m.restart) toast("Modifica pronta: chiudi e rilancia l'editor per usarla", true);
      else if (files.length) { toast("Modifica pronta: ricarico l'editor"); setTimeout(() => location.reload(), 1200); }
    }
  }
  renderAsk();
  askPolling();
}

async function askRestart() {
  if (ASK.waitingRestart) return;
  ASK.waitingRestart = true;
  $("#loading").textContent = "Claude ha cambiato l'editor: lo riavvio con il codice nuovo…";
  $("#loading").classList.remove("off");
  try { await api("/api/assistant/restart", {}); } catch { /* già in riavvio */ }
  await new Promise((r) => setTimeout(r, 1500));
  for (let i = 0; i < 120; i++) {
    try { await api("/api/assistant"); location.reload(); return; } catch { /* non ancora su */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  $("#loading").textContent = "L'editor non è ripartito: guarda il terminale e rilancialo.";
}

function askPolling() {
  const running = ASK.data?.running;
  if (running && !ASK.timer) ASK.timer = setInterval(askRefresh, 1500);
  else if (!running && ASK.timer) { clearInterval(ASK.timer); ASK.timer = null; }
  if (running && !ASK.tick) {
    ASK.tick = setInterval(() => document.querySelectorAll(".ask-el").forEach((e) => {
      e.textContent = askSec(Date.now() / 1000 - Number(e.dataset.t0));
    }), 1000);
  } else if (!running && ASK.tick) { clearInterval(ASK.tick); ASK.tick = null; }
}

async function askSend() {
  const text = ASK.text.trim(), images = ASK.images;
  if (!text && !images.length) { toast("Scrivi cosa vuoi fare", true); return; }
  const body = { mode: ASK.mode, prompt: text, selection: null, images };
  if (ASK.mode === "edit" && ASK.sel) body.selection = { ...ASK.sel, captions: askCaptions(ASK.sel) };
  try {
    ASK.text = "";
    ASK.images = [];
    askOnData(await api("/api/assistant", body));
  } catch (e) { ASK.text = text; ASK.images = images; renderAsk(); toast(e.message, true); }
}

// screenshot: incolla (Ctrl+V), trascina sul pannello o scegli un file
function askAddFiles(files) {
  const imgs = [...files].filter((f) => f.type.startsWith("image/"));
  if (!imgs.length) return false;
  const ok = [];
  for (const f of imgs) {
    if (!ASK_TYPES.includes(f.type)) { toast("Servono immagini PNG, JPG, WEBP o GIF", true); continue; }
    if (f.size > ASK_MAX_BYTES) { toast("Immagine troppo grande (massimo 8 MB)", true); continue; }
    if (ASK.images.length + ok.length >= ASK_MAX_IMAGES) { toast(`Al massimo ${ASK_MAX_IMAGES} immagini per messaggio`, true); break; }
    ok.push(f);
  }
  Promise.all(ok.map((f) => new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result));
    r.onerror = rej;
    r.readAsDataURL(f);
  }))).then((urls) => {
    ASK.images = [...ASK.images, ...urls].slice(0, ASK_MAX_IMAGES);
    if (!ASK.open) { ASK.open = true; askSavePrefs(); }
    renderAsk();
  }).catch(() => toast("Non riesco a leggere l'immagine", true));
  return true;
}

function askPickFile() {
  const input = Object.assign(document.createElement("input"), { type: "file", accept: ASK_TYPES.join(","), multiple: true });
  input.addEventListener("change", () => askAddFiles(input.files));
  input.click();
}

// --- strumento screenshot: cattura la pagina, ritaglia/evidenzia, e va dritto nella chat ---
// Usa la cattura schermo del browser (getDisplayMedia): si sceglie «questa scheda», si vede
// l'editor com'è (video compreso), si marca il punto e «Allega alla chat» lo mette nel messaggio.

const SHOT = { cv: null, ctx: null, tool: "rect", crop: null, marks: [], cur: null };
const SHOT_RED = "#ff2d55";

async function shotStart() {
  if (!navigator.mediaDevices?.getDisplayMedia) { toast("Questo browser non può catturare lo schermo", true); return; }
  if (ASK.images.length >= ASK_MAX_IMAGES) { toast(`Al massimo ${ASK_MAX_IMAGES} immagini per messaggio`, true); return; }
  document.body.classList.add("shooting"); // la chat non deve finire nello screenshot
  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false, preferCurrentTab: true, selfBrowserSurface: "include" });
  } catch {
    document.body.classList.remove("shooting");
    toast("Screenshot annullato");
    return;
  }
  try {
    await new Promise((r) => setTimeout(r, 400)); // il selettore del browser deve sparire
    const video = Object.assign(document.createElement("video"), { srcObject: stream, muted: true });
    await video.play();
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const cv = document.createElement("canvas");
    cv.width = video.videoWidth; cv.height = video.videoHeight;
    cv.getContext("2d").drawImage(video, 0, 0);
    shotOpen(cv);
  } catch {
    toast("Non sono riuscito a catturare lo schermo", true);
  } finally {
    stream.getTracks().forEach((t) => t.stop());
    document.body.classList.remove("shooting");
  }
}

function shotOpen(src) {
  shotClose();
  Object.assign(SHOT, { src, tool: "rect", crop: null, marks: [], cur: null });
  const el = document.createElement("div");
  el.className = "shot"; el.id = "shot";
  el.innerHTML = `<div class="shot-bar">
      <b>Screenshot</b>
      <div class="seg-toggle" id="shot-tools">
        <button data-shot-tool="crop" title="Trascina per tenere solo un punto della pagina">✂ Ritaglia</button>
        <button data-shot-tool="rect" class="on" title="Cerchia o evidenzia un punto">▭ Evidenzia</button>
        <button data-shot-tool="pen" title="Disegna a mano libera">✎ Penna</button>
      </div>
      <button class="btn" data-shot="undo" title="Toglie l'ultimo segno (Ctrl+Z)">Annulla segno</button>
      <button class="btn" data-shot="full" title="Rimette tutta la pagina">Pagina intera</button>
      <span class="shot-hint">Tutta la pagina, oppure Ritaglia un punto · poi evidenzia</span>
      <button class="btn" data-shot="close" title="Chiudi senza inviare (Esc)">Chiudi</button>
      <button class="btn vfx-go" data-shot="send" title="Mette lo screenshot nella chat (Invio)">Allega alla chat</button>
    </div>
    <div class="shot-stage"><canvas id="shot-cv"></canvas></div>`;
  document.body.append(el);
  SHOT.cv = $("#shot-cv");
  SHOT.cv.width = src.width; SHOT.cv.height = src.height;
  SHOT.ctx = SHOT.cv.getContext("2d");
  shotPaint();
  el.addEventListener("click", (e) => {
    const t = e.target.closest("[data-shot-tool]"), a = e.target.closest("[data-shot]");
    if (t) {
      SHOT.tool = t.dataset.shotTool;
      el.querySelectorAll("[data-shot-tool]").forEach((b) => b.classList.toggle("on", b === t));
    } else if (a?.dataset.shot === "undo") { SHOT.marks.pop(); shotPaint(); }
    else if (a?.dataset.shot === "full") { SHOT.crop = null; shotPaint(); }
    else if (a?.dataset.shot === "close") shotClose();
    else if (a?.dataset.shot === "send") shotSend();
  });
  const pt = (e) => {
    const r = SHOT.cv.getBoundingClientRect();
    return { x: Math.max(0, Math.min(src.width, ((e.clientX - r.left) / r.width) * src.width)),
             y: Math.max(0, Math.min(src.height, ((e.clientY - r.top) / r.height) * src.height)) };
  };
  SHOT.cv.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    SHOT.cv.setPointerCapture(e.pointerId);
    const p = pt(e);
    SHOT.cur = SHOT.tool === "pen" ? { type: "pen", pts: [p] } : { type: SHOT.tool, a: p, b: p };
    shotPaint();
  });
  SHOT.cv.addEventListener("pointermove", (e) => {
    if (!SHOT.cur) return;
    const p = pt(e);
    if (SHOT.cur.type === "pen") SHOT.cur.pts.push(p); else SHOT.cur.b = p;
    shotPaint();
  });
  const end = () => {
    const c = SHOT.cur;
    SHOT.cur = null;
    if (!c) return;
    if (c.type === "pen") { if (c.pts.length > 1) SHOT.marks.push(c); }
    else if (Math.abs(c.a.x - c.b.x) > 6 && Math.abs(c.a.y - c.b.y) > 6) {
      if (c.type === "crop") SHOT.crop = shotRect(c); else SHOT.marks.push(c);
    }
    shotPaint();
  };
  SHOT.cv.addEventListener("pointerup", end);
  SHOT.cv.addEventListener("pointercancel", end);
}

const shotRect = (c) => ({ x: Math.min(c.a.x, c.b.x), y: Math.min(c.a.y, c.b.y), w: Math.abs(c.a.x - c.b.x), h: Math.abs(c.a.y - c.b.y) });

/** Disegna immagine + segni. `ui` = anteprima (ombra fuori dal ritaglio e cornice), altrimenti file finale. */
function shotPaint(ctx = SHOT.ctx, ui = true) {
  const { src } = SHOT, lw = Math.max(3, src.width / 320);
  ctx.drawImage(src, 0, 0);
  const all = SHOT.cur && SHOT.cur.type !== "crop" ? [...SHOT.marks, SHOT.cur] : SHOT.marks;
  ctx.lineWidth = lw; ctx.strokeStyle = SHOT_RED; ctx.lineJoin = ctx.lineCap = "round";
  for (const m of all) {
    ctx.beginPath();
    if (m.type === "pen") m.pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    else { const r = shotRect(m); ctx.rect(r.x, r.y, r.w, r.h); }
    ctx.stroke();
  }
  if (!ui) return;
  const crop = SHOT.cur?.type === "crop" ? shotRect(SHOT.cur) : SHOT.crop;
  if (!crop) return;
  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,.55)";
  ctx.beginPath();
  ctx.rect(0, 0, src.width, src.height);
  ctx.rect(crop.x, crop.y, crop.w, crop.h);
  ctx.fill("evenodd");
  ctx.setLineDash([lw * 3, lw * 2]); ctx.strokeStyle = "#fff"; ctx.lineWidth = Math.max(2, lw * .6);
  ctx.strokeRect(crop.x, crop.y, crop.w, crop.h);
  ctx.restore();
}

function shotClose() {
  $("#shot")?.remove();
  SHOT.cv = SHOT.ctx = SHOT.src = null;
}

function shotSend() {
  if (!SHOT.src) return;
  if (ASK.images.length >= ASK_MAX_IMAGES) { toast(`Al massimo ${ASK_MAX_IMAGES} immagini per messaggio`, true); return; }
  const crop = SHOT.crop ?? { x: 0, y: 0, w: SHOT.src.width, h: SHOT.src.height };
  const scale = Math.min(1, 2400 / crop.w);
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(crop.w * scale)); out.height = Math.max(1, Math.round(crop.h * scale));
  const ctx = out.getContext("2d");
  ctx.scale(scale, scale); ctx.translate(-crop.x, -crop.y);
  shotPaint(ctx, false);
  let url = out.toDataURL("image/png");
  if (url.length * 0.75 > ASK_MAX_BYTES * 0.9) url = out.toDataURL("image/jpeg", 0.88);
  ASK.images.push(url);
  ASK.open = true; ASK.selecting = false; askSavePrefs();
  shotClose();
  renderAsk();
  $("#ask-text")?.focus();
  toast("Screenshot nella chat: scrivi cosa vuoi e premi Invio");
}

window.addEventListener("keydown", (e) => {
  if (!$("#shot")) return;
  e.stopPropagation(); // le scorciatoie dell'editor non devono scattare sotto lo screenshot
  if (e.key === "Escape") shotClose();
  else if (e.key === "Enter") shotSend();
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); SHOT.marks.pop(); shotPaint(); }
}, true);

const askHandles = ["l", "t", "tl"].map((c) => Object.assign(document.createElement("div"), {
  className: `ask-rz ${c}`, title: "Trascina per ingrandire o rimpicciolire la chat (doppio clic: misura originale)",
}));
wireResizer(askHandles[0], [{ key: "askW", axis: "x", dir: -1 }]);
wireResizer(askHandles[1], [{ key: "askH", axis: "y", dir: -1 }]);
wireResizer(askHandles[2], [{ key: "askW", axis: "x", dir: -1 }, { key: "askH", axis: "y", dir: -1 }]);

function wireAsk() {
  askLoadPrefs();
  const fab = $("#ask-fab"), panel = $("#ask-panel");
  if (!fab || !panel) return;
  fab.innerHTML = `${ASK_STAR}<span>Chiedi a Claude</span>`;
  fab.addEventListener("click", () => { ASK.open = true; askSavePrefs(); renderAsk(); $("#ask-text")?.focus(); });
  panel.addEventListener("input", (e) => { if (e.target.id === "ask-text") ASK.text = e.target.value; });
  // Ctrl+V di uno screenshot: vale nella chat e anche con il cursore altrove nell'editor
  document.addEventListener("paste", (e) => {
    if (!ASK.open) return;
    const t = e.target, typing = t.closest?.("input, textarea, [contenteditable]");
    if (typing && !panel.contains(t)) return; // un altro campo di testo dell'editor: incolla normale
    const files = [...(e.clipboardData?.files ?? [])];
    if (files.some((f) => f.type.startsWith("image/")) && askAddFiles(files)) e.preventDefault();
  });
  panel.addEventListener("dragover", (e) => {
    if ([...(e.dataTransfer?.types ?? [])].includes("Files")) { e.preventDefault(); panel.classList.add("dropping"); }
  });
  panel.addEventListener("dragleave", (e) => { if (!panel.contains(e.relatedTarget)) panel.classList.remove("dropping"); });
  panel.addEventListener("drop", (e) => {
    panel.classList.remove("dropping");
    if (e.dataTransfer?.files?.length && askAddFiles(e.dataTransfer.files)) e.preventDefault();
  });
  panel.addEventListener("keydown", (e) => {
    e.stopPropagation(); // le scorciatoie dell'editor (spazio, Canc…) non devono scattare qui
    if (e.target.id === "ask-text" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askSend(); }
  });
  panel.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-ask]");
    if (!b) return;
    switch (b.dataset.ask) {
      case "close": ASK.open = false; ASK.selecting = false; askSavePrefs(); renderAsk(); break;
      case "mode": ASK.mode = b.dataset.v; ASK.selecting = false; askSavePrefs(); renderAsk(); break;
      case "select": ASK.selecting = !ASK.selecting; renderAsk(); break;
      case "unsel": ASK.sel = null; renderAsk(); break;
      case "send": askSend(); break;
      case "attach": askPickFile(); break;
      case "shot": shotStart(); break;
      case "rmshot": ASK.images.splice(Number(b.dataset.i), 1); renderAsk(); break;
      case "build": ASK.mode = "dev"; ASK.text = `Aggiungi all'editor: ${b.dataset.text}`; askSavePrefs(); renderAsk(); $("#ask-text")?.focus(); break;
      case "clear":
        if (confirm("Cominciare una nuova conversazione con Claude?")) {
          try { askOnData(await api("/api/assistant/clear", {})); } catch (err) { toast(err.message, true); }
        }
        break;
      case "revert":
        if (confirm("Rimettere il codice dell'editor com'era prima di questa modifica?")) {
          try {
            const d = await api(`/api/assistant/${b.dataset.id}/revert`, {});
            const py = d.messages.find((x) => x.id === b.dataset.id)?.restart;
            askOnData(d);
            toast(py && d.can_restart ? "Modifiche annullate: riavvio l'editor" : "Modifiche annullate: ricarico l'editor");
            if (py && d.can_restart) askRestart(); else setTimeout(() => location.reload(), 1200);
          } catch (err) { toast(err.message, true); }
        }
        break;
    }
  });
  // selezione sulla timeline: trascina = tratto, clic = fotogramma (prima degli altri gestori)
  const tl = $("#tl-content");
  let drag = null;
  tl.addEventListener("pointerdown", (e) => {
    if (!ASK.selecting) return;
    e.preventDefault(); e.stopPropagation();
    const r = tl.getBoundingClientRect();
    drag = { a: msOf(e.clientX - r.left), r };
    tl.setPointerCapture(e.pointerId);
    ASK.sel = { frame_ms: Math.round(drag.a) };
    renderAskSel();
  }, true);
  tl.addEventListener("pointermove", (e) => {
    if (!drag) return;
    e.stopPropagation();
    const b = msOf(e.clientX - drag.r.left);
    if (Math.abs(xOf(b) - xOf(drag.a)) > 4) ASK.sel = { start_ms: Math.round(Math.min(drag.a, b)), end_ms: Math.round(Math.max(drag.a, b)) };
    renderAskSel();
  }, true);
  tl.addEventListener("pointerup", (e) => {
    if (!drag) return;
    e.stopPropagation();
    drag = null;
    ASK.selecting = false;
    seekMs(ASK.sel.frame_ms ?? ASK.sel.start_ms);
    renderAsk();
    $("#ask-text")?.focus();
  }, true);
  tl.addEventListener("click", (e) => { if (ASK.selecting || drag) { e.stopPropagation(); e.preventDefault(); } }, true);
  renderAsk();
  askRefresh();
}

init();
