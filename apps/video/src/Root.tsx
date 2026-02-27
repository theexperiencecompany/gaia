import React from "react";
import { Composition } from "remotion";
import { GaiaPromo } from "./GaiaPromo";
import { loadLocalFonts } from "./fonts";

// Load local fonts at module level (Remotion requirement)
loadLocalFonts();

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="GaiaPromo"
        component={GaiaPromo}
        durationInFrames={3253}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{}}
      />
    </>
  );
};
