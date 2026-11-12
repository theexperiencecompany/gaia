import { createContext } from "react";

/** "page" is the full artifact (viewer, link, print); "card" is its preview inside a chat card. */
export type ArtifactDensity = "page" | "card";

export const ArtifactDensityContext = createContext<ArtifactDensity>("page");
