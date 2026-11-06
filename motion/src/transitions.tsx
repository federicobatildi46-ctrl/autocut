import React from "react";
import { AbsoluteFill } from "remotion";
import type { TransitionPresentation, TransitionPresentationComponentProps } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { cube } from "@remotion/transitions/cube";
import { flip } from "@remotion/transitions/flip";
import { clockWipe } from "@remotion/transitions/clock-wipe";
import { iris } from "@remotion/transitions/iris";
import { pushCut } from "@remotion/transitions/push-cut";

// Transizioni tra clip: quelle ufficiali di @remotion/transitions (solo CSS, funzionano nel
// render headless) + alcune in stile CapCut fatte qui (zoom, whip, flash, blur, passaggio al nero).

type Css = (dir: "entering" | "exiting", k: number) => { style: React.CSSProperties; overlay?: React.CSSProperties };

function cssPresentation(fn: Css): TransitionPresentation<Record<string, unknown>> {
  const Comp: React.FC<TransitionPresentationComponentProps<Record<string, unknown>>> = ({
    children, presentationDirection, presentationProgress,
  }) => {
    const { style, overlay } = fn(presentationDirection, presentationProgress);
    return (
      <AbsoluteFill style={style}>
        {children}
        {overlay && <AbsoluteFill style={overlay} />}
      </AbsoluteFill>
    );
  };
  return { component: Comp, props: {} };
}

const ease = (k: number) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);

const zoom = cssPresentation((dir, k) => {
  const e = ease(k);
  return dir === "exiting"
    ? { style: { transform: `scale(${1 + 0.35 * e})`, filter: `blur(${e * 14}px)`, opacity: 1 - e } }
    : { style: { transform: `scale(${1.35 - 0.35 * e})`, filter: `blur(${(1 - e) * 14}px)`, opacity: e } };
});

const whip = cssPresentation((dir, k) => {
  const e = ease(k);
  return dir === "exiting"
    ? { style: { transform: `translateX(${-e * 100}%)`, filter: `blur(${Math.sin(e * Math.PI) * 30}px)` } }
    : { style: { transform: `translateX(${(1 - e) * 100}%)`, filter: `blur(${Math.sin(e * Math.PI) * 30}px)` } };
});

const flash = cssPresentation((dir, k) => {
  // a metà è tutto bianco, poi la nuova scena esce dal lampo
  const peak = 1 - Math.abs(k - 0.5) * 2;
  return dir === "exiting"
    ? { style: { opacity: k < 0.5 ? 1 : 0 } }
    : { style: { opacity: k >= 0.5 ? 1 : 0 }, overlay: { background: "#fff", opacity: Math.max(0, peak) } };
});

const blurDissolve = cssPresentation((dir, k) => {
  const e = ease(k);
  return dir === "exiting"
    ? { style: { filter: `blur(${e * 18}px)`, opacity: 1 - e } }
    : { style: { filter: `blur(${(1 - e) * 18}px)`, opacity: e } };
});

const dipBlack = cssPresentation((dir, k) => (
  dir === "exiting"
    ? { style: { opacity: Math.max(0, 1 - k * 2) } }
    : { style: { opacity: Math.max(0, k * 2 - 1) } }
));

// Ogni giunta ha il suo tipo; width/height servono a iris e orologio.
export function presentationFor(type: string, width: number, height: number): TransitionPresentation<Record<string, unknown>> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const any = (p: TransitionPresentation<any>) => p as unknown as TransitionPresentation<Record<string, unknown>>;
  switch (type) {
    case "fade": return any(fade());
    case "slide_left": return any(slide({ direction: "from-right" }));
    case "slide_up": return any(slide({ direction: "from-bottom" }));
    case "wipe_left": return any(wipe({ direction: "from-right" }));
    case "cube": return any(cube({ direction: "from-right" }));
    case "flip": return any(flip({ direction: "from-right" }));
    case "clock_wipe": return any(clockWipe({ width, height }));
    case "iris": return any(iris({ width, height }));
    case "push_cut": return any(pushCut({}));
    case "zoom": return zoom;
    case "whip": return whip;
    case "flash": return flash;
    case "blur": return blurDissolve;
    case "dip_black": return dipBlack;
    default: return any(fade());
  }
}
