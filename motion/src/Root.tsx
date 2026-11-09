import React from "react";
import { Composition } from "remotion";
import { StyledReel, StyledReelProps } from "./StyledReel";
import { TitoloTest } from "./TitoloTest";
import { ViralCover, ViralCoverProps } from "./ViralCover";

export const RemotionRoot: React.FC = () => (
  <>
    {/* Pezzo di video con il look brand × stile: le props arrivano da `autocut style-preview`. */}
    <Composition
      id="StyledReel"
      component={StyledReel as unknown as React.FC<Record<string, unknown>>}
      durationInFrames={120}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{} as Record<string, unknown>}
      calculateMetadata={({ props }) => {
        const p = props as unknown as StyledReelProps;
        return { durationInFrames: p.durationInFrames, fps: p.fps, width: p.width, height: p.height };
      }}
    />
    {/* Copertina verticale Viral: fotogramma + frase d'esordio (autocut, finestra Esporta). */}
    <Composition
      id="ViralCover"
      component={ViralCover as unknown as React.FC<Record<string, unknown>>}
      durationInFrames={1}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{} as Record<string, unknown>}
      calculateMetadata={({ props }) => {
        const p = props as unknown as ViralCoverProps;
        return { width: p.width ?? 1080, height: p.height ?? 1920 };
      }}
    />
    <Composition
      id="TitoloTest"
      component={TitoloTest}
      durationInFrames={90}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{ testo: "autocut + Remotion" }}
    />
  </>
);
