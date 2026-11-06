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
  else if (["text", "stickers", "images", "effects"].includes(S.leftTab)) renderTextPanels();
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
  if (e.target.closest("input, textarea, select")) return;
  if (e.key === "Escape" && (S.txSel || S.popSel)) { e.preventDefault(); S.txSel = false; S.popSel = null; renderTextPanels(); return; }
  if (S.popSel && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); deletePop(S.popSel); return; }
  if (e.key === "Escape" && S.viewer) { e.preventDefault(); closeViewer(); return; }
  if (e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey) { e.preventDefault(); S.viewer ? closeViewer() : openViewer(); return; }
  if (S.viewer && (e.key === "Delete" || e.key === "Backspace" || e.ctrlKey || e.metaKey)) return; // nel visualizzatore si guarda e basta
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  else if (e.key === "ArrowRight") { e.preventDefault(); video.pause(); seekMs(nowMs() + (e.shiftKey ? 1000 : FPS_STEP)); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); video.pause(); seekMs(nowMs() - (e.shiftKey ? 1000 : FPS_STEP)); }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
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
  if (["text", "stickers", "images", "effects"].includes(S.leftTab)) boxes.push([$("#left-content"), S.leftTab]);
  if (S.viewer && S.txPanel) boxes.push([$("#viewer-panel"), S.viewerTab]);
  for (const [box, tab] of boxes) {
    // non interrompere chi sta scrivendo o trascinando un cursore
    const active = document.activeElement;
    if (box.contains(active) && ["tx-text", "st-custom", "img-q"].includes(active.id)) continue;
    if (S.txSliding && box.contains(S.txSliding)) continue;
    const top = box.scrollTop;
    box.innerHTML = tab === "stickers" ? stickerPanelHTML() : tab === "effects" ? effectsPanelHTML()
      : tab === "images" ? imagesPanelHTML() : textPanelHTML();
    if (tab === "effects") maybeAutoFx();
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
  const t = cur - chunk.start;
  const dur = chunk.end + 250 - chunk.start;
  const perWord = spec.in.type === "words_blur" || spec.in.type === "words_pop";
  const st = animState({ inSpec: perWord ? null : spec.in, outSpec: spec.out, t, dur });
  applyCss(capEl, animCss(st, chunkCaps(chunk)?.emphasis?.color ?? "#FFFFFF"));
  const words = capEl.querySelectorAll(".cw");
  if (perWord) {
    const times = chunkWordTimes(chunk, words.length);
    words.forEach((w, i) => applyCss(w, animCss(wordState(spec.in.type, cur - times[i], spec.in.ms))));
  } else if (words.length && words[0].style.opacity) {
    words.forEach((w) => applyCss(w, { opacity: 1, transform: "none", filter: "none", clipPath: "none" }));
  }
}

function updatePopupFx(cur) {
  document.querySelectorAll(".pop-el[data-id]").forEach((el) => {
    const p = popItem(el.dataset.id);
    const spec = p && stickerSpec(p.id);
    if (!spec || S.popLive?.id === p.id) return;
    const st = animState({ inSpec: spec.in, outSpec: spec.out, loopSpec: spec.loop, t: cur - p.at_ms, dur: p.duration_ms });
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
  else if (S.leftTab !== "effects") { S.leftTab = "effects"; renderLeft(); }
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
