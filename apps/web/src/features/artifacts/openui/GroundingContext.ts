import type { GroundingIndex } from "@gaia/artifacts/grounding";
import { createContext } from "react";

/** The parsed program's statements, so text can fill its {slots} from their data. */
export const GroundingContext = createContext<GroundingIndex>(new Map());
