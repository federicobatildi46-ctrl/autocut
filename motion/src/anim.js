// Motore delle animazioni di testo e sticker (entrata, uscita, loop).
// UNICO file usato sia dall'editor (servito come /anim.js) sia dal render Remotion:
// così l'anteprima e il video esportato si muovono allo stesso modo.
//
// animStyle({ inSpec, outSpec, loopSpec, t, dur }) -> stile CSS da applicare all'elemento
//   t   = ms da quando l'elemento compare
//   dur = ms di permanenza totale (l'uscita finisce a dur)
//   spec = { type, ms, speed }  (type "none" = nessun effetto)
// Lo stile usa `transform` (si somma a translate/rotate/scale già usati per la posizione),
// `opacity`, `filter` e `clipPath`.

const clamp01 = (x) => Math.max(0, Math.min(1, x));
const lerp = (a, b, k) => a + (b - a) * k;
const easeOut = (k) => 1 - Math.pow(1 - k, 3);
const easeInOut = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
const backOut = (k) => { const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(k - 1, 3) + c1 * Math.pow(k - 1, 2); };
const elasticOut = (k) => (k === 0 || k === 1 ? k : Math.pow(2, -10 * k) * Math.sin((k * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1);
const bounceOut = (k) => {
  const n = 7.5625, d = 2.75;
  if (k < 1 / d) return n * k * k;
  if (k < 2 / d) return n * (k -= 1.5 / d) * k + 0.75;
  if (k < 2.5 / d) return n * (k -= 2.25 / d) * k + 0.9375;
  return n * (k -= 2.625 / d) * k + 0.984375;
};

const BASE = () => ({ o: 1, x: 0, y: 0, s: 1, sx: 1, sy: 1, r: 0, blur: 0, glow: 0, bright: 1, clip: 1 });

// Stato di ENTRATA con k = 0 (prima) -> 1 (a posto).
function enterState(type, k) {
  const st = BASE();
  const e = easeOut(k);
  switch (type) {
    case "fade": st.o = e; break;
    case "pop": st.s = lerp(0.3, 1, backOut(k)); st.o = clamp01(k * 3); break;
    case "bounce": st.y = lerp(-120, 0, bounceOut(k)); st.o = clamp01(k * 4); break;
    case "drop": st.y = lerp(-60, 0, backOut(k)); st.o = clamp01(k * 3); break;
    case "zoom_in": st.s = lerp(0.2, 1, e); st.o = e; break;
    case "zoom_big": st.s = lerp(2.4, 1, e); st.o = e; st.blur = (1 - e) * 0.25; break;
    case "slide_up": st.y = lerp(70, 0, e); st.o = e; break;
    case "slide_down": st.y = lerp(-70, 0, e); st.o = e; break;
    case "slide_left": st.x = lerp(70, 0, e); st.o = e; break;
    case "slide_right": st.x = lerp(-70, 0, e); st.o = e; break;
    case "rise": { const m = easeInOut(k); st.y = lerp(22, 0, m); st.o = m; st.blur = (1 - m) * 0.12; break; }
    case "blur_in": st.blur = (1 - e) * 0.35; st.o = e; st.s = lerp(1.06, 1, e); break;
    case "glow_in": st.o = clamp01(k * 2.5); st.glow = 1 - e; st.bright = lerp(2.2, 1, e); break;
    case "typewriter": st.clip = Math.round(k * 14) / 14; break;
    case "wipe_in": st.clip = easeInOut(k); break;
    case "spin_in": st.r = lerp(-200, 0, e); st.s = lerp(0.2, 1, backOut(k)); st.o = clamp01(k * 3); break;
    case "stretch": st.sx = lerp(1.6, 1, elasticOut(k)); st.sy = lerp(0.4, 1, elasticOut(k)); st.o = clamp01(k * 3); break;
    // parola per parola: nell'insieme come un fade, le parole le anima chi disegna il testo
    case "words_blur": case "words_pop": st.o = 1; break;
    default: break;
  }
  return st;
}

// Stato di USCITA con k = 0 (a posto) -> 1 (sparito).
function exitState(type, k) {
  const st = BASE();
  const e = easeInOut(k);
  switch (type) {
    case "fade": st.o = 1 - e; break;
    case "pop_out": st.s = lerp(1, 1.5, e); st.o = 1 - e; break;
    case "zoom_out": st.s = lerp(1, 0.2, e); st.o = 1 - clamp01((k - 0.4) / 0.6); break;
    case "slide_up": st.y = lerp(0, -70, e); st.o = 1 - e; break;
    case "slide_down": st.y = lerp(0, 70, e); st.o = 1 - e; break;
    case "slide_left": st.x = lerp(0, -70, e); st.o = 1 - e; break;
    case "slide_right": st.x = lerp(0, 70, e); st.o = 1 - e; break;
    case "blur_out": st.blur = e * 0.35; st.o = 1 - e; break;
    case "spin_out": st.r = lerp(0, 220, e); st.s = lerp(1, 0.2, e); st.o = 1 - clamp01((k - 0.3) / 0.7); break;
    case "glow_out": st.glow = e; st.bright = lerp(1, 2.4, e); st.o = 1 - clamp01((k - 0.5) / 0.5); break;
    case "wipe_out": st.clip = 1 - e; break;
    case "sink": st.y = lerp(0, 25, e); st.o = 1 - e; st.blur = e * 0.1; break;
    default: break;
  }
  return st;
}

// Movimento continuo mentre è a schermo (solo sticker). t in ms, speed 1 = normale.
function loopState(type, t, speed) {
  const st = BASE();
  const w = (t / 1000) * (speed || 1) * Math.PI * 2;
  switch (type) {
    case "float": st.y = Math.sin(w * 0.6) * 6; break;
    case "pulse": st.s = 1 + Math.sin(w) * 0.06; break;
    case "heartbeat": { const p = (w / (Math.PI * 2)) % 1; st.s = 1 + (p < 0.15 ? Math.sin((p / 0.15) * Math.PI) * 0.14 : p < 0.3 ? Math.sin(((p - 0.15) / 0.15) * Math.PI) * 0.08 : 0); break; }
    case "wiggle": st.r = Math.sin(w * 1.2) * 8; break;
    case "shake": st.x = Math.sin(w * 5) * 3; st.r = Math.sin(w * 4.3) * 2; break;
    case "spin": st.r = ((t / 1000) * (speed || 1) * 180) % 360; break;
    case "glow": st.glow = 0.5 + Math.sin(w) * 0.5; break;
    default: break;
  }
  return st;
}

function combine(a, b) {
  return {
    o: a.o * b.o, x: a.x + b.x, y: a.y + b.y, s: a.s * b.s, sx: a.sx * b.sx, sy: a.sy * b.sy, r: a.r + b.r,
    blur: a.blur + b.blur, glow: Math.max(a.glow, b.glow), bright: a.bright * b.bright, clip: Math.min(a.clip, b.clip),
  };
}

// Stato complessivo dell'elemento all'istante t (ms dall'entrata), su una durata dur.
export function animState({ inSpec, outSpec, loopSpec, t, dur }) {
  let st = BASE();
  const inMs = inSpec && inSpec.type !== "none" ? Math.max(1, inSpec.ms) : 0;
  const outMs = outSpec && outSpec.type !== "none" ? Math.max(1, Math.min(outSpec.ms, dur * 0.6)) : 0;
  if (inMs && t < inMs) st = combine(st, enterState(inSpec.type, clamp01(t / inMs)));
  if (outMs && t > dur - outMs) st = combine(st, exitState(outSpec.type, clamp01((t - (dur - outMs)) / outMs)));
  if (loopSpec && loopSpec.type !== "none") st = combine(st, loopState(loopSpec.type, t, loopSpec.speed));
  return st;
}

// Stato -> proprietà CSS. x/y sono in % della grandezza dell'elemento, blur in em.
// glowColor: colore dell'alone per bagliore/neon.
export function animCss(st, glowColor = "#FFFFFF") {
  const filters = [];
  if (st.blur > 0.001) filters.push(`blur(${st.blur.toFixed(3)}em)`);
  if (Math.abs(st.bright - 1) > 0.01) filters.push(`brightness(${st.bright.toFixed(2)})`);
  if (st.glow > 0.01) filters.push(`drop-shadow(0 0 ${(0.35 * st.glow).toFixed(2)}em ${glowColor})`);
  const tf = [];
  if (st.x || st.y) tf.push(`translate(${st.x.toFixed(2)}%, ${st.y.toFixed(2)}%)`);
  if (st.r) tf.push(`rotate(${st.r.toFixed(2)}deg)`);
  const sx = st.s * st.sx, sy = st.s * st.sy;
  if (Math.abs(sx - 1) > 0.0005 || Math.abs(sy - 1) > 0.0005) tf.push(`scale(${sx.toFixed(4)}, ${sy.toFixed(4)})`);
  return {
    opacity: Math.max(0, Math.min(1, st.o)),
    transform: tf.join(" ") || "none",
    filter: filters.join(" ") || "none",
    clipPath: st.clip < 0.999 ? `inset(-20% ${((1 - st.clip) * 100).toFixed(2)}% -20% -20%)` : "none",
  };
}

// Per gli effetti "parola per parola": stato della singola parola (t = ms da quando compare).
export function wordState(type, t, ms) {
  const k = clamp01(t / Math.max(1, ms));
  if (type === "words_pop") return { ...BASE(), s: lerp(0.4, 1, backOut(k)), o: clamp01(k * 3) };
  if (type === "words_blur") { const e = easeOut(k); return { ...BASE(), o: e, blur: (1 - e) * 0.3, y: lerp(18, 0, e) }; }
  return BASE();
}
