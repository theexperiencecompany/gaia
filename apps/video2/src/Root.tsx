import type React from "react";
import { Composition } from "remotion";
import "./fonts";
import { GaiaFounders } from "./GaiaFounders";
import { FPS, HEIGHT, WIDTH } from "./constants";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="GaiaFounders"
      component={GaiaFounders}
      durationInFrames={2228}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  );
};
