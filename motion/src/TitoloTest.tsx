import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

// Titolo animato di prova (verticale 1080x1920), solo per verificare che Remotion funzioni.
export const TitoloTest: React.FC<{ testo: string }> = ({ testo }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const entrata = spring({ frame, fps, config: { damping: 14 } });
  const opacita = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: "#121215", justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          color: "#fff",
          fontFamily: "Segoe UI, Inter, sans-serif",
          fontWeight: 800,
          fontSize: 96,
          opacity: opacita,
          transform: `translateY(${(1 - entrata) * 80}px) scale(${0.8 + entrata * 0.2})`,
          textAlign: "center",
          padding: "0 80px",
        }}
      >
        {testo}
        <div style={{ height: 10, marginTop: 24, borderRadius: 6, background: "#1fd3cf", width: `${entrata * 100}%` }} />
      </div>
    </AbsoluteFill>
  );
};
