import React from "react";
import { Composition } from "remotion";
import { TitoloTest } from "./TitoloTest";

// Composizioni di prova. Le grafiche vere arriveranno con le reference di stile.
export const RemotionRoot: React.FC = () => (
  <>
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
