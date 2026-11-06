export type AnimSpec = { type: string; ms: number; speed?: number } | null | undefined;
export type AnimState = {
  o: number; x: number; y: number; s: number; sx: number; sy: number; r: number;
  blur: number; glow: number; bright: number; clip: number;
};
export function animState(args: { inSpec?: AnimSpec; outSpec?: AnimSpec; loopSpec?: AnimSpec; t: number; dur: number }): AnimState;
export function animCss(st: AnimState, glowColor?: string): { opacity: number; transform: string; filter: string; clipPath: string };
export function wordState(type: string, t: number, ms: number): AnimState;
