import { createContext } from "react";
import type { GroundingIndex } from "./grounding";

/** The parsed program's statements, so text can fill its {slots} from their data. */
export const GroundingContext = createContext<GroundingIndex>(new Map());
