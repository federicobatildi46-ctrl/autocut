import React, { useEffect, useState } from "react";
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  Easing,
  Img,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { animCss, animState, wordState } from "./anim.js";
import { presentationFor } from "./transitions";

// Render di un pezzo di video con il look brand × stile (props da autocut style-preview).
// Tutti i tempi delle props sono ms sul montato (0 = inizio del pezzo).

type Emphasis = { font: string | null; weight: number | null; italic: boolean; color: string; scale: number; layout: "line" | "inline" };
// Campi dei sottotitoli; quelli in fondo arrivano dal pannello Testo dell'editor (text_style.json).
type CaptionLook = {
  font: string; weight: number; case: "sentence" | "upper" | "lower"; size_pct: number; bottom_pct: number;
  stroke_px: number; stroke_color: string; shadow: "none" | "soft" | "hard"; colors: string[];
  emphasis: Emphasis | null; animation: "blur_in" | "pop" | "none";
  italic?: boolean; effect?: "none" | "glow" | "box"; fx_color?: string;
  x_pct?: number; y_pct?: number; scale?: number; rotation?: number;
  anim?: { in?: Spec; out?: Spec }; // pannello Effetti
};
type Spec = { type: string; ms: number; speed?: number };
type Look = {
  style: string;
  fonts_url: string | null;
  grade: { css_filter: string; vignette: number };
  pacing: { camera: string; punch_in: { enabled: boolean; scale: number; mode: string; ease_ms: number } };
  captions: CaptionLook;
  hook: {
    duration_ms: number; center_pct: number; size_pct: number; kicker_ratio: number; sub_ratio: number;
    font: string; big_font: string; weight: number; big_weight: number; big_italic: boolean; case: "sentence" | "upper";
    colors: { kicker: string; big: string; sub: string };
    stroke_px: number; stroke_color: string; big_stroke_color: string; shadow: "none" | "soft" | "hard";
    animation: "pop" | "reveal"; dim: number;
  } | null;
  cards: { kind: "liquid_glass" | "sticker" | "none"; accent: string; surface: string; title_font: string };
};
type Caption = {
  from_ms: number; to_ms: number; words: { text: string; from_ms: number }[]; emphasis: number; color: string;
  style?: Partial<CaptionLook>; // modifiche di questa sola scena
};
export type StyledReelProps = {
  fps: number; width: number; height: number; durationInFrames: number;
  look: Look;
  video: { src: string; masks?: { dir: string; count: number }; pieces: { from_ms: number; to_ms: number; src_ms: number }[] };
  phrases: number[];
  captions: Caption[];
  hook: { lines: { text: string; role: "kicker" | "big" | "sub" }[]; to_ms: number } | null;
  cards: {
    id: string; src: string | null; emoji: string | null; from_ms: number; to_ms: number; title: string;
    kind: "image" | "emoji" | "text"; placement: "side" | "above" | "pair" | "center" | "top" | "behind" | "free";
    size: "small" | "medium" | "large"; side: "left" | "right";
    // sticker messi a mano nel pannello Sticker: centro in % del fotogramma, grandezza, rotazione
    x_pct?: number | null; y_pct?: number | null; scale?: number; rotation?: number;
    layer?: "under_text" | "over_text" | "person";
    emoji_imgs?: string[] | null; // emoji stile iPhone (PNG), una per emoji
    cutout?: boolean; // foto scontornata (pannello Immagini): niente cornice
    anim?: { in?: Spec; out?: Spec; loop?: Spec }; // pannello Effetti
  }[];
  // transizioni alle giunte tra pezzi (join = indice del pezzo prima della giunta)
  transitions?: { join: number; at_ms: number; type: string; ms: number }[];
  lowerThird: { name: string; role: string; from_ms: number; to_ms: number; name_font: string; role_font: string } | null;
  sounds: { src: string; from_ms: number; volume: number }[];
};

const f = (ms: number, fps: number) => Math.round((ms / 1000) * fps);
const caseText = (t: string, c: string) => (c === "upper" ? t.toUpperCase() : c === "lower" ? t.toLowerCase() : t);
const ease = Easing.bezier(0.22, 1, 0.36, 1);

// Testo con bordo spesso "alla CapCut": un livello col contorno sotto e il riempimento sopra.
const Stroked: React.FC<{ text: string; color: string; stroke: number; strokeColor: string; style: React.CSSProperties }> = ({ text, color, stroke, strokeColor, style }) => (
  <span style={{ position: "relative", display: "inline-block", ...style }}>
    {stroke > 0 && (
      <span aria-hidden style={{ position: "absolute", inset: 0, WebkitTextStroke: `${stroke * 2}px ${strokeColor}`, color: strokeColor, strokeLinejoin: "round" }}>{text}</span>
    )}
    <span style={{ position: "relative", color }}>{text}</span>
  </span>
);

// Larghezza reale del testo (font già caricati): serve per far stare la riga grande su una riga.
let measureCtx: CanvasRenderingContext2D | null = null;
function fitSize(text: string, family: string, weight: number, italic: boolean, size: number, maxWidth: number, extra = 0): number {
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx) return size;
  measureCtx.font = `${italic ? "italic " : ""}${weight} ${size}px "${family}"`;
  const w = measureCtx.measureText(text).width + extra;
  return w > maxWidth ? (size * maxWidth) / w : size;
}

function useFonts(url: string | null, families: string[]): boolean {
  const [handle] = useState(() => delayRender("font del brand/stile"));
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let done = false;
    const finish = () => { if (!done) { done = true; setReady(true); continueRender(handle); } };
    if (!url) { finish(); return; }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = url;
    link.onload = () => {
      Promise.all(families.flatMap((fam) =>
        ["400", "600", "700", "800", "italic 400"].map((w) => document.fonts.load(`${w} 40px "${fam}"`)),
      )).then(finish, finish);
    };
    link.onerror = finish;
    document.head.appendChild(link);
    const t = setTimeout(finish, 15000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle, url]);
  return ready;
}

function punchScale(t: number, p: StyledReelProps): number {
  const pi = p.look.pacing.punch_in;
  if (!pi.enabled) return 1;
  if (pi.mode === "cut_alternate") {
    const i = p.video.pieces.findIndex((x) => t >= x.from_ms && t < x.to_ms);
    return i % 2 === 1 ? pi.scale : 1;
  }
  // phrase_alternate: zoom diverso per ogni frase, passaggio morbido + leggero push continuo
  let i = -1;
  for (let k = 0; k < p.phrases.length; k++) if (p.phrases[k] <= t) i = k;
  if (i < 0) return 1;
  const target = i % 2 === 1 ? pi.scale : 1.0;
  const prev = i % 2 === 1 ? 1.0 : pi.scale;
  const since = t - p.phrases[i];
  const k = i === 0 ? 1 : interpolate(since, [0, Math.max(1, pi.ease_ms)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const push = 1 + Math.min(since, 8000) * 0.0000045;
  return (prev + (target - prev) * k) * push;
}

const TransitionVideo: React.FC<{ p: StyledReelProps }> = ({ p }) => {
  const { width, height } = useVideoConfig();
  const fps = p.fps;
  const byJoin = new Map((p.transitions ?? []).map((x) => [x.join, x]));
  const D = (j: number) => {
    const x = byJoin.get(j);
    return x ? Math.max(2, Math.round(f(x.ms, fps) / 2) * 2) : 0;
  };
  const n = p.video.pieces.length;
  const items: React.ReactNode[] = [];
  p.video.pieces.forEach((x, i) => {
    const before = i > 0 ? D(i - 1) / 2 : 0;
    const after = i < n - 1 ? D(i) / 2 : 0;
    const len = Math.max(1, f(x.to_ms, fps) - f(x.from_ms, fps));
    items.push(
      <TransitionSeries.Sequence key={`s${i}`} durationInFrames={len + before + after}>
        <OffthreadVideo src={staticFile(p.video.src)} trimBefore={Math.max(0, f(x.src_ms, fps) - before)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </TransitionSeries.Sequence>,
    );
    const tr = byJoin.get(i);
    if (tr && i < n - 1) {
      items.push(
        <TransitionSeries.Transition key={`t${i}`} presentation={presentationFor(tr.type, width, height)} timing={linearTiming({ durationInFrames: D(i) })} />,
      );
    }
  });
  return (
    <>
      <TransitionSeries>{items}</TransitionSeries>
      {/* l'audio resta a taglio netto (niente voce doppia durante la transizione) */}
      {p.video.pieces.map((x, i) => (
        <Sequence key={`a${i}`} from={f(x.from_ms, fps)} durationInFrames={Math.max(1, f(x.to_ms, fps) - f(x.from_ms, fps))}>
          <Audio src={staticFile(p.video.src)} trimBefore={f(x.src_ms, fps)} />
        </Sequence>
      ))}
    </>
  );
};

const VideoLayer: React.FC<{ p: StyledReelProps; src?: string; transparent?: boolean }> = ({ p, src, transparent }) => {
  const frame = useCurrentFrame();
  const t = (frame / p.fps) * 1000;
  const scale = punchScale(t, p);
  if (!transparent && (p.transitions ?? []).length > 0) {
    return (
      <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: "50% 38%", filter: p.look.grade.css_filter }}>
        <TransitionVideo p={p} />
      </AbsoluteFill>
    );
  }
  // la persona ritagliata serve solo mentre c'è una grafica dietro
  if (transparent && !p.cards.some((c) => c.placement === "behind" && t >= c.from_ms - 50 && t <= c.to_ms + 50)) return null;
  return (
    <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: "50% 38%", filter: p.look.grade.css_filter }}>
      {p.video.pieces.map((x, i) => (
        <Sequence key={i} from={f(x.from_ms, p.fps)} durationInFrames={Math.max(1, f(x.to_ms, p.fps) - f(x.from_ms, p.fps))}>
          <OffthreadVideo src={staticFile(src ?? p.video.src)} trimBefore={f(x.src_ms, p.fps)} transparent={transparent} muted={transparent} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

const CaptionLayer: React.FC<{ p: StyledReelProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = (frame / fps) * 1000;
  const c = p.captions.find((x) => t >= x.from_ms && t < x.to_ms);
  if (!c) return null;
  const cap: CaptionLook = { ...p.look.captions, ...(c.style ?? {}) };
  const size = (width * cap.size_pct) / 100;
  const fx = cap.fx_color ?? "#000000";
  const shadow = cap.effect === "glow"
    ? `0 0 ${size * 0.12}px ${fx}, 0 0 ${size * 0.4}px ${fx}, 0 0 ${size * 0.9}px ${fx}`
    : cap.shadow === "soft" ? "0 4px 22px rgba(0,0,0,.55), 0 1px 3px rgba(0,0,0,.6)" : cap.shadow === "hard" ? "0 7px 0 rgba(0,0,0,.55)" : "none";
  const base: React.CSSProperties = {
    fontFamily: `"${cap.font}", sans-serif`, fontWeight: cap.weight, fontStyle: cap.italic ? "italic" : "normal",
    fontSize: size, lineHeight: 1.08, textShadow: cap.stroke_px > 0 ? "none" : shadow,
  };
  const emph = cap.emphasis;

  // entrata e uscita (pannello Effetti); senza scelte: pop (viral) o parola per parola (premium)
  const inSpec: Spec = cap.anim?.in ?? { type: cap.animation === "pop" ? "pop" : cap.animation === "blur_in" ? "words_blur" : "none", ms: 320 };
  const outSpec = cap.anim?.out;
  const local = frame - f(c.from_ms, fps);
  const springPop = inSpec.type === "pop";
  const pop = springPop ? spring({ frame: local, fps, config: { damping: 9, stiffness: 220, mass: 0.6 } }) : 1;
  const popScale = springPop ? 0.55 + 0.45 * pop : 1;
  const perWord = inSpec.type === "words_blur" || inSpec.type === "words_pop";
  const st = animState({ inSpec: springPop || perWord ? null : inSpec, outSpec, t: t - c.from_ms, dur: c.to_ms - c.from_ms });
  const fxCss = animCss(st, emph?.color ?? cap.fx_color ?? "#FFFFFF");

  const word = (w: Caption["words"][number], i: number) => {
    const isEmph = emph && i === c.emphasis;
    const appear = frame - f(w.from_ms, fps);
    let style: React.CSSProperties = {};
    if (perWord) {
      const ws = animCss(wordState(inSpec.type, (appear / fps) * 1000, inSpec.ms));
      style = { opacity: ws.opacity, filter: ws.filter, transform: ws.transform, display: "inline-block" };
    }
    const text = caseText(w.text, cap.case).replace(/[,.]$/, "");
    const emphFamily = emph?.font ?? cap.font;
    const emphSize = isEmph
      ? fitSize(text, emphFamily, emph!.weight ?? cap.weight, emph!.italic, size * emph!.scale, width * 0.8)
      : size;
    const s: React.CSSProperties = isEmph
      ? {
          ...base, ...style,
          fontFamily: `"${emphFamily}", sans-serif`,
          fontWeight: emph!.weight ?? base.fontWeight,
          fontStyle: emph!.italic ? "italic" : "normal",
          fontSize: emphSize,
          lineHeight: 1.0,
          letterSpacing: emph!.layout === "line" ? "-0.02em" : undefined,
          textShadow: cap.stroke_px > 0 ? "none" : cap.effect && cap.effect !== "none" ? shadow : `0 0 40px ${emph!.color}40, 0 6px 30px rgba(0,0,0,.5)`,
        }
      : { ...base, ...style };
    const color = isEmph ? emph!.color : c.color;
    return <Stroked key={i} text={text} color={color} stroke={cap.stroke_px * (width / 1080) * (isEmph ? emphSize / size : 1)} strokeColor={cap.stroke_color} style={{ ...s, margin: `0 ${size * 0.14}px` }} />;
  };

  const lineMode = emph && emph.layout === "line" && c.emphasis >= 0;
  const rest = c.words.map((w, i) => ({ w, i })).filter(({ i }) => !lineMode || i !== c.emphasis);
  // box: fondo colorato dietro ogni riga (come nell'editor)
  const box: React.CSSProperties = cap.effect === "box"
    ? { display: "inline-block", background: fx, padding: `${size * 0.06}px ${size * 0.18}px`, borderRadius: size * 0.22, fontSize: size, lineHeight: 1.15 }
    : {};
  // posizione, rotazione e grandezza scelte trascinando il testo nell'editor
  const dx = ((cap.x_pct ?? 0) / 100) * width;
  const dy = ((cap.y_pct ?? 0) / 100) * height;
  const userScale = cap.scale ?? 1;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center" }}>
      <div style={{
        position: "absolute", bottom: `${cap.bottom_pct}%`, left: "50%", width: "max-content", maxWidth: "76%", textAlign: "center",
        transform: `translate(calc(-50% + ${dx}px), ${dy}px) rotate(${cap.rotation ?? 0}deg) scale(${popScale * userScale}) ${fxCss.transform === "none" ? "" : fxCss.transform}`,
        transformOrigin: "50% 50%", fontSize: size, opacity: fxCss.opacity, filter: fxCss.filter, clipPath: fxCss.clipPath,
      }}>
        {rest.length > 0 && <div><span style={box}>{rest.map(({ w, i }) => word(w, i))}</span></div>}
        {lineMode && <div style={{ marginTop: size * 0.05 }}><span style={box}>{word(c.words[c.emphasis], c.emphasis)}</span></div>}
      </div>
    </AbsoluteFill>
  );
};

const HookLayer: React.FC<{ p: StyledReelProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const h = p.look.hook;
  if (!h || !p.hook) return null;
  const end = f(p.hook.to_ms, fps);
  if (frame > end) return null;
  // Copertina: blocco centrato, gerarchia aggancio (piccolo) → riga GRANDE → sottotitolo.
  const out = interpolate(frame, [end - 7, end], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const u = width / 1080;
  const maxW = width * (h.animation === "pop" ? 0.88 : 0.84);
  const big = (width * h.size_pct) / 100;
  const shadow = h.shadow === "hard" ? "drop-shadow(0 9px 0 rgba(0,0,0,.5))" : "none";
  const order = { kicker: 0, big: 1, sub: 2 } as const;

  const lines = p.hook.lines.map((line, i) => {
    const role = line.role;
    const isBig = role === "big";
    const text = role === "sub" || h.case === "sentence" ? line.text : line.text.toUpperCase();
    const family = isBig ? h.big_font : h.font;
    const weight = isBig ? h.big_weight : h.weight;
    const italic = isBig && h.big_italic;
    const stroke = (isBig ? h.stroke_px * 1.5 : role === "sub" ? h.stroke_px * 0.8 : h.stroke_px) * u;
    const ratio = role === "kicker" ? h.kicker_ratio : role === "sub" ? h.sub_ratio : 1;
    const size = fitSize(text, family, weight, italic, big * ratio, maxW, stroke * 2);
    const color = h.colors[role];
    const strokeColor = isBig ? h.big_stroke_color : h.stroke_color;
    const delay = order[role] * (h.animation === "pop" ? 4 : 7);
    const local = frame - delay;
    const gap = isBig ? size * 0.02 : size * 0.12;

    if (h.animation === "pop") {
      // viral: ogni riga "salta" dentro con rimbalzo, poi respira leggermente
      const k = spring({ frame: local, fps, config: { damping: 9, stiffness: 210, mass: 0.6 } });
      const breathe = isBig && local > 12 ? 1 + 0.025 * Math.sin((local - 12) / 6) : 1;
      const tilt = role === "kicker" ? -3 : role === "big" ? -1.5 : 0;
      return (
        <div key={i} style={{ transform: `rotate(${tilt}deg) scale(${(0.3 + 0.7 * k) * breathe})`, opacity: Math.min(1, k * 1.6), lineHeight: 1.0, margin: `${gap}px 0`, filter: shadow }}>
          <Stroked text={text} color={color} stroke={stroke} strokeColor={strokeColor}
            style={{ fontFamily: `"${family}", sans-serif`, fontWeight: weight, fontStyle: italic ? "italic" : "normal", fontSize: size, whiteSpace: "nowrap" }} />
        </div>
      );
    }
    // premium: aggancio e sottotitolo entrano sfocati, la riga grande lettera per lettera
    const soft = `0 0 ${size * 0.35}px ${color}38, 0 ${size * 0.05}px ${size * 0.3}px rgba(0,0,0,.5)`;
    const common: React.CSSProperties = { fontFamily: `"${family}", sans-serif`, fontWeight: weight, fontStyle: italic ? "italic" : "normal", fontSize: size, color, lineHeight: 1.0, whiteSpace: "nowrap", letterSpacing: isBig ? "-0.025em" : "0.005em", textShadow: h.shadow === "none" ? "none" : soft };
    if (!isBig) {
      const k = interpolate(local, [0, 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
      return <div key={i} style={{ ...common, margin: `${gap}px 0`, opacity: k, filter: `blur(${(1 - k) * 12}px)`, transform: `translateY(${(1 - k) * 18}px)` }}>{text}</div>;
    }
    const settle = interpolate(local, [0, 45], [1.07, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
    return (
      <div key={i} style={{ ...common, margin: `${gap}px 0`, transform: `scale(${settle})` }}>
        {Array.from(text).map((ch, j) => {
          const k = interpolate(local - j * 1.6, [0, 9], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
          return <span key={j} style={{ display: "inline-block", whiteSpace: "pre", opacity: k, filter: `blur(${(1 - k) * 10}px)`, transform: `translateY(${(1 - k) * 0.22}em)` }}>{ch}</span>;
        })}
      </div>
    );
  });

  return (
    <AbsoluteFill>
      {h.dim > 0 && <AbsoluteFill style={{ background: `rgba(0,0,0,${h.dim * out})` }} />}
      <div style={{ position: "absolute", top: `${h.center_pct}%`, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center",
        transform: `translateY(-50%) scale(${h.animation === "pop" ? out : 1})`, opacity: h.animation === "pop" ? 1 : out, filter: h.animation === "pop" ? "none" : `blur(${(1 - out) * 8}px)` }}>
        {lines}
      </div>
    </AbsoluteFill>
  );
};

type Card = StyledReelProps["cards"][number];
const EMOJI_FONT = `"Noto Color Emoji", "Segoe UI Emoji", sans-serif`;
const graphemes = (t: string) =>
  Array.from(new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(t)).map((x) => x.segment).filter((x) => x.trim());

// Grandezza (frazione della larghezza) per tipo e taglia.
const SIZE = {
  emoji: { small: 0.11, medium: 0.17, large: 0.4 },
  image: { small: 0.24, medium: 0.36, large: 0.64 },
  text: { small: 0.14, medium: 0.22, large: 0.36 },
} as const;

// Pop-up nei punti dei reference: accanto/sopra il sottotitolo, coppia ai lati, grande al
// centro sotto il testo, in alto, oppure DIETRO la persona (livello "behind").
const cardLayer = (c: Card): "behind" | "under" | "over" =>
  c.layer === "person" || c.placement === "behind" ? "behind" : c.layer === "over_text" ? "over" : "under";

// behind = dietro la persona (con la sagoma), under = dietro ai sottotitoli, over = davanti
const PopupLayer: React.FC<{ p: StyledReelProps; layer: "behind" | "under" | "over" }> = ({ p, layer }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const t = (frame / fps) * 1000;
  const premium = p.look.cards.kind === "liquid_glass";
  const cap = p.look.captions;
  const capSize = (W * cap.size_pct) / 100;
  const capLineY = H * (1 - cap.bottom_pct / 100) - capSize * 0.55;
  const hooking = Boolean(p.hook && p.look.hook && t < p.hook.to_ms);
  const hookTop = p.look.hook ? (H * p.look.hook.center_pct) / 100 - ((W * p.look.hook.size_pct) / 100) * 1.25 : 0;

  return (
    <>
      {p.cards.filter((c) => cardLayer(c) === layer).map((c: Card) => {
        const a = f(c.from_ms, fps), b = f(c.to_ms, fps);
        if (frame < a || frame > b) return null;
        const local = frame - a;
        const out = interpolate(frame, [b - 7, b], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        const pop = spring({ frame: local, fps, config: { damping: 8, stiffness: 210, mass: 0.6 } });
        const soft = spring({ frame: local, fps, config: { damping: 18, stiffness: 80 } });
        const kind: "image" | "emoji" | "text" = c.src ? "image" : c.kind === "text" && !c.emoji ? "text" : "emoji";
        const w = W * SIZE[kind][c.size];
        const fxs = c.anim ? animCss(animState({ inSpec: c.anim.in, outSpec: c.anim.out, loopSpec: c.anim.loop, t: ((frame - a) / fps) * 1000, dur: c.to_ms - c.from_ms })) : null;
        const enter: React.CSSProperties = fxs
          ? { opacity: fxs.opacity, transform: fxs.transform, filter: fxs.filter, clipPath: fxs.clipPath, fontSize: W * 0.04 }
          : premium
            ? { opacity: Math.min(1, soft * 1.3) * out, filter: `blur(${(1 - soft) * 10}px)`, transform: `translateY(${(1 - soft) * 50}px) scale(${0.94 + 0.06 * soft})` }
            : { opacity: Math.min(1, pop * 2) * out, transform: `scale(${(0.25 + 0.75 * pop) * (0.6 + 0.4 * out)})` };
        const shadow = premium ? "drop-shadow(0 24px 40px rgba(0,0,0,.45))" : "drop-shadow(0 8px 0 rgba(0,0,0,.35))";

        // emoji: immagini stile iPhone se ci sono, altrimenti il font emoji
        const emojiEl = (e: string, size: number, i?: number) => {
          const imgs = c.emoji_imgs ?? null;
          if (imgs && imgs.length) {
            const list = i === undefined ? imgs : [imgs[Math.min(i, imgs.length - 1)]];
            return (
              <span style={{ display: "inline-flex", gap: size * 0.04, filter: shadow }}>
                {list.map((src, k) => <Img key={k} src={staticFile(src)} style={{ width: size, height: size, display: "block" }} />)}
              </span>
            );
          }
          return <span style={{ fontFamily: EMOJI_FONT, fontSize: size, lineHeight: 1, display: "inline-block", filter: shadow }}>{e}</span>;
        };
        // etichetta solo sugli elementi da mostrare: mai sulle emoji piccole (come nei reference)
        const label = c.title && kind !== "text" && c.placement !== "behind" && !(kind === "emoji" && c.size === "small") ? (
          premium
            ? <div style={{ fontFamily: `"${p.look.cards.title_font}", sans-serif`, fontWeight: 800, fontSize: W * 0.045, color: "#fff", textShadow: "0 2px 16px rgba(0,0,0,.5)", marginTop: 10, textAlign: "center" }}>{c.title}</div>
            : <div style={{ display: "inline-block", marginTop: -W * 0.03, background: "#FFD60A", border: "5px solid #000", borderRadius: 16, padding: "6px 18px", transform: "rotate(-4deg)", fontFamily: `"${cap.font}", sans-serif`, fontSize: W * 0.042, color: "#000", whiteSpace: "nowrap", position: "relative" }}>{c.title.toUpperCase()}</div>
        ) : null;

        let body: React.ReactNode;
        if (kind === "image" && c.cutout) {
          // foto scontornata: solo la figura, con un'ombra morbida che la stacca dal video
          body = <Img src={staticFile(c.src!)} style={{ width: "100%", display: "block", filter: "drop-shadow(0 18px 30px rgba(0,0,0,.45))" }} />;
        } else if (kind === "image") {
          const feather = premium && (c.placement === "behind" || c.placement === "top");
          const mask = "radial-gradient(ellipse 72% 70% at 50% 50%, #000 55%, transparent 100%)";
          const img = (
            <Img src={staticFile(c.src!)} style={{
              width: "100%", display: "block", objectFit: "cover", borderRadius: premium ? 28 : 18,
              aspectRatio: c.placement === "center" || c.placement === "behind" ? "4 / 3" : "4 / 5",
              ...(feather ? { WebkitMaskImage: mask, maskImage: mask } : {}),
            }} />
          );
          body = premium && c.placement === "side"
            ? <div style={{ padding: W * 0.014, borderRadius: 38, background: "linear-gradient(140deg, rgba(255,255,255,.34), rgba(255,255,255,.08) 45%, rgba(255,255,255,.16))", backdropFilter: "blur(22px) saturate(170%)", border: "1.5px solid rgba(255,255,255,.55)", boxShadow: "0 40px 90px rgba(0,0,0,.38), inset 0 1.5px 0 rgba(255,255,255,.75)" }}>{img}{label}</div>
            : premium
              ? <div style={{ filter: shadow }}>{img}{label}</div>
              : <div style={{ textAlign: "center" }}><div style={{ background: "#fff", padding: W * 0.012, borderRadius: 24, filter: shadow }}>{img}</div>{label}</div>;
        } else if (kind === "text" && !premium) {
          // viral: etichetta gialla col bordo nero (come nel pannello Sticker dell'editor)
          body = (
            <div style={{
              display: "inline-block", background: "#FFD60A", color: "#000", border: `${W * 0.0055}px solid #000`,
              borderRadius: W * 0.016, padding: `${W * 0.006}px ${W * 0.025}px`, rotate: "-4deg", whiteSpace: "nowrap",
              fontFamily: `"${cap.font}", sans-serif`, fontWeight: 800, lineHeight: 1.05,
              fontSize: W * ({ small: 0.05, medium: 0.07, large: 0.11 } as const)[c.size], filter: shadow,
            }}>{c.title}</div>
          );
        } else if (kind === "text") {
          // numero/parola enorme (es. «60s» dietro la persona), riempimento a righe come il reference
          body = (
            <div style={{
              fontFamily: `"${p.look.hook?.big_font ?? cap.font}", sans-serif`, fontWeight: 800, fontSize: W * SIZE.text[c.size],
              lineHeight: 0.9, letterSpacing: "-0.04em", whiteSpace: "nowrap", color: "transparent",
              backgroundImage: "repeating-linear-gradient(180deg, rgba(255,255,255,.97) 0 6px, rgba(255,255,255,.72) 6px 9px)",
              WebkitBackgroundClip: "text", backgroundClip: "text", filter: "drop-shadow(0 18px 40px rgba(0,0,0,.35))",
            }}>{c.title}</div>
          );
        } else {
          body = <div style={{ textAlign: "center" }}>{emojiEl(c.emoji ?? "✨", w)}{label && <div>{label}</div>}</div>;
        }

        const box = (style: React.CSSProperties, extra: React.CSSProperties = {}) => (
          <div key={c.id} style={{ position: "absolute", ...style, ...enter, ...extra, transformOrigin: "50% 60%" }}>{body}</div>
        );
        if (c.placement === "free") {
          // centro nel punto scelto, poi grandezza e rotazione dell'utente (sopra l'animazione)
          return (
            <div key={c.id} style={{
              position: "absolute", left: ((c.x_pct ?? 50) / 100) * W, top: ((c.y_pct ?? 40) / 100) * H,
              width: kind === "image" ? w : undefined, translate: "-50% -50%",
              rotate: `${c.rotation ?? 0}deg`, scale: String(c.scale ?? 1),
            }}>
              <div style={{ ...enter, transformOrigin: "50% 50%", textAlign: "center" }}>{body}</div>
            </div>
          );
        }
        switch (c.placement) {
          case "pair": {
            const [l, r] = graphemes(c.emoji ?? "");
            const s = W * SIZE.emoji[c.size];
            const one = (e: string, cx: number, rot: number, k: string, i: number) => (
              <div key={k} style={{ position: "absolute", left: cx - s / 2, top: capLineY - s * 0.55, ...enter, rotate: `${rot}deg` }}>{emojiEl(e, s, i)}</div>
            );
            return (
              <React.Fragment key={c.id}>
                {one(l ?? "✨", W * 0.17, -8, "l", 0)}
                {one(r ?? l ?? "✨", W * 0.83, 8, "r", r ? 1 : 0)}
              </React.Fragment>
            );
          }
          case "above": {
            const bottom = hooking ? hookTop - 10 : capLineY - capSize * 0.9;
            return box({ left: (W - w) / 2, width: w, top: bottom - (kind === "image" ? w * 1.25 : w) });
          }
          case "center":
            return box({ left: (W - w) / 2, width: w, top: capLineY - capSize * 0.3 });
          case "top":
            return box({ left: (W - w) / 2, width: w, top: H * 0.13 });
          case "behind":
            return kind === "text"
              ? box({ left: 0, right: 0, top: H * 0.21, display: "flex", justifyContent: "center" })
              : box({ left: W * 0.11, width: W * 0.78, top: H * 0.07 });
          default: {
            // side: emoji piccola accanto al sottotitolo; card/immagini di lato, sopra il testo
            if (kind === "emoji" && c.size === "small") {
              const cx = c.side === "right" ? W * 0.8 : W * 0.2;
              return box({ left: cx - w / 2, top: capLineY - w * 0.55, width: w });
            }
            const top = premium ? H * 0.14 : capLineY - capSize * 1.4 - (kind === "image" ? w * 1.25 : w);
            const pos: React.CSSProperties = c.side === "right" ? { right: W * 0.06, width: w, top } : { left: W * 0.06, width: w, top };
            return box(pos, premium ? {} : { rotate: c.side === "right" ? "6deg" : "-6deg" });
          }
        }
      })}
    </>
  );
};

// Maschera del fotogramma sorgente giusto (bianco = sfondo), scalata come il punch-in del video.
const BehindMask: React.FC<{ p: StyledReelProps; children: React.ReactNode }> = ({ p, children }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const m = p.video.masks;
  const t = (frame / fps) * 1000;
  if (!p.cards.some((c) => cardLayer(c) === "behind" && t >= c.from_ms - 50 && t <= c.to_ms + 50)) return null;
  if (!m) return <AbsoluteFill>{children}</AbsoluteFill>;
  const piece = p.video.pieces.find((x) => t >= x.from_ms && t < x.to_ms) ?? p.video.pieces[p.video.pieces.length - 1];
  const idx = Math.max(1, Math.min(m.count, Math.round(((piece.src_ms + t - piece.from_ms) / 1000) * fps) + 1));
  const src = staticFile(`${m.dir}/${String(idx).padStart(5, "0")}.jpg`);
  const s = punchScale(t, p);
  const mask: React.CSSProperties = {
    maskImage: `url("${src}")`, WebkitMaskImage: `url("${src}")`, maskMode: "luminance",
    maskSize: `${W * s}px ${H * s}px`, WebkitMaskSize: `${W * s}px ${H * s}px`,
    maskPosition: `${W * 0.5 * (1 - s)}px ${H * 0.38 * (1 - s)}px`, WebkitMaskPosition: `${W * 0.5 * (1 - s)}px ${H * 0.38 * (1 - s)}px`,
    maskRepeat: "no-repeat", WebkitMaskRepeat: "no-repeat",
  };
  return (
    <>
      {/* l'Img fa aspettare a Remotion che la maschera sia caricata prima dello scatto */}
      <Img src={src} style={{ position: "absolute", width: 2, height: 2, opacity: 0 }} />
      <AbsoluteFill style={mask}>{children}</AbsoluteFill>
    </>
  );
};

const LowerThird: React.FC<{ p: StyledReelProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const lt = p.lowerThird;
  if (!lt) return null;
  const a = f(lt.from_ms, fps), b = f(lt.to_ms, fps);
  if (frame < a || frame > b) return null;
  const k = spring({ frame: frame - a, fps, config: { damping: 18 } });
  return (
    <div style={{ position: "absolute", left: width * 0.07, bottom: height * 0.27, opacity: k, transform: `translateX(${(1 - k) * -40}px)`,
      padding: "18px 28px", borderRadius: 24, background: "rgba(14,20,48,.45)", backdropFilter: "blur(18px)", border: "1px solid rgba(255,255,255,.35)" }}>
      <div style={{ fontFamily: `"${lt.name_font}", sans-serif`, fontWeight: 600, fontSize: width * 0.036, color: "#fff" }}>{lt.name}</div>
      <div style={{ fontFamily: `"${lt.role_font}", sans-serif`, fontSize: width * 0.024, color: "rgba(255,255,255,.75)" }}>{lt.role}</div>
    </div>
  );
};

export const StyledReel: React.FC<StyledReelProps> = (p) => {
  const sceneFonts = p.captions.flatMap((c) => [c.style?.font, c.style?.emphasis?.font]);
  const fams = ["Noto Color Emoji", p.look.captions.font, p.look.captions.emphasis?.font, ...sceneFonts, p.look.hook?.font, p.look.hook?.big_font, p.look.cards.title_font, p.lowerThird?.name_font]
    .filter((x): x is string => Boolean(x));
  const ready = useFonts(p.look.fonts_url, fams);
  const { fps } = useVideoConfig();
  const v = p.look.grade.vignette;
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <VideoLayer p={p} />
      {/* grafiche DIETRO la persona: ritagliate con la sagoma, si vedono solo dove non ci sei */}
      {ready && <BehindMask p={p}><PopupLayer p={p} layer="behind" /></BehindMask>}
      {v > 0 && <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 42%, transparent 48%, rgba(0,0,0,${0.85 * v}) 100%)` }} />}
      {p.look.style === "premium" && <AbsoluteFill style={{ background: "linear-gradient(to top, rgba(0,0,0,.42), transparent 42%)" }} />}
      {ready && (
        <>
          <PopupLayer p={p} layer="under" />
          <LowerThird p={p} />
          <CaptionLayer p={p} />
          <PopupLayer p={p} layer="over" />
          <HookLayer p={p} />
        </>
      )}
      {p.sounds.map((s, i) => (
        <Sequence key={i} from={f(s.from_ms, fps)}>
          <Audio src={staticFile(s.src)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
