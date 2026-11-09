import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, staticFile } from "remotion";
import { Stroked, fitSize, useFonts } from "./StyledReel";

// Copertina verticale Viral: un fotogramma del video + la frase d'esordio al centro, con lo
// stesso font, contorno e ombra dell'hook del video. Pulita: niente altro, al massimo 2 emoji.

type HookLook = {
  center_pct: number; size_pct: number; kicker_ratio: number; sub_ratio: number;
  font: string; big_font: string; weight: number; big_weight: number; big_italic: boolean;
  case: "upper" | "sentence"; stroke_px: number; stroke_color: string; big_stroke_color: string;
  shadow: string;
};

export type ViralCoverProps = {
  width: number;
  height: number;
  frame: string; // fotogramma del video (cartella pubblica), se non c'è il pezzo di video
  video?: string | null; // pezzetto del video preparato come nel render: stessi colori
  fonts_url: string | null;
  hook: HookLook;
  accent: string; // colore della riga piccola (evidenziazione del brand)
  lines: { text: string; role: "kicker" | "big" | "sub" }[];
  emojis: string[]; // PNG stile iPhone, al massimo 2: sinistra e destra della prima riga
  grade: string; // stesso look colore del video (css filter dello stile)
};

export const ViralCover: React.FC<ViralCoverProps> = (p) => {
  const h = p.hook;
  const W = p.width;
  const u = W / 1080;
  const ready = useFonts(p.fonts_url, [h.font, h.big_font]);
  const maxW = W * 0.86;
  const base = (W * h.size_pct) / 100 * 1.12; // un filo più grande che nel video: è una copertina
  const shadow = h.shadow === "hard" ? `drop-shadow(0 ${9 * u}px 0 rgba(0,0,0,.55))` : `drop-shadow(0 ${6 * u}px ${18 * u}px rgba(0,0,0,.5))`;
  const firstLine = 0;

  const rows = ready ? p.lines.map((line, i) => {
    const isBig = line.role === "big";
    const text = line.role === "sub" || h.case === "sentence" ? line.text : line.text.toUpperCase();
    const family = isBig ? h.big_font : h.font;
    const weight = isBig ? h.big_weight : h.weight;
    const italic = isBig && h.big_italic;
    const stroke = (isBig ? h.stroke_px * 1.5 : line.role === "sub" ? h.stroke_px * 0.8 : h.stroke_px) * u;
    const ratio = line.role === "kicker" ? h.kicker_ratio * 1.05 : line.role === "sub" ? h.sub_ratio : 1;
    const emojiRoom = i === firstLine && p.emojis.length ? base * ratio * 1.5 * Math.min(2, p.emojis.length) : 0;
    const size = fitSize(text, family, weight, italic, base * ratio, maxW - emojiRoom, stroke * 2);
    // come nei reference: riga piccola nel colore del brand, riga grande bianca con contorno colorato
    const color = line.role === "kicker" ? p.accent : "#FFFFFF";
    const strokeColor = isBig ? p.accent : h.stroke_color;
    const emoji = (src: string | undefined, side: "l" | "r") => src ? (
      <Img src={staticFile(src)} style={{
        width: size * 1.3, height: size * 1.3, margin: side === "l" ? `0 ${size * 0.12}px 0 0` : `0 0 0 ${size * 0.12}px`,
        rotate: side === "l" ? "-10deg" : "8deg", filter: `drop-shadow(0 ${5 * u}px 0 rgba(0,0,0,.4))`, flex: "none",
      }} />
    ) : null;
    return (
      <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "center", lineHeight: 1.0,
        margin: `${isBig ? size * 0.0 : size * 0.1}px 0`, rotate: line.role === "kicker" ? "-2deg" : isBig ? "-1deg" : "0deg" }}>
        {i === firstLine && emoji(p.emojis[0], "l")}
        <Stroked text={text} color={color} stroke={stroke} strokeColor={strokeColor}
          style={{ fontFamily: `"${family}", sans-serif`, fontWeight: weight, fontStyle: italic ? "italic" : "normal", fontSize: size, whiteSpace: "nowrap" }} />
        {i === firstLine && emoji(p.emojis[1], "r")}
      </div>
    );
  }) : null;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {p.video
        ? <OffthreadVideo src={staticFile(p.video)} muted style={{ width: "100%", height: "100%", objectFit: "cover", filter: p.grade || "none" }} />
        : <Img src={staticFile(p.frame)} style={{ width: "100%", height: "100%", objectFit: "cover", filter: p.grade || "none" }} />}
      {/* ombra leggerissima solo dietro la scritta: colori del video intatti */}
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 70% 16% at 50% ${h.center_pct}%, rgba(0,0,0,.16), transparent 75%)` }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: `${h.center_pct}%`, translate: "0 -50%",
        display: "flex", flexDirection: "column", alignItems: "center", filter: shadow }}>
        {rows}
      </div>
    </AbsoluteFill>
  );
};
