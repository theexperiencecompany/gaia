/** How an artifact is being rendered, for components that adapt to it. */
import { createContext } from "react";

/** "page" is the full artifact (viewer, link, print); "card" is its preview inside a chat card. */
export type ArtifactDensity = "page" | "card";

export const ArtifactDensityContext = createContext<ArtifactDensity>("page");

/** Whether the artifact renders on the dark app or as its light paper copy. */
export const ArtifactAppearanceContext = createContext<"dark" | "light">(
  "dark",
);
