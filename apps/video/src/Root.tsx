import React from "react";
import { Composition } from "remotion";
import { GaiaPromo } from "./GaiaPromo";
import "./fonts"; // module-level font loading with delayRender/continueRender

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
