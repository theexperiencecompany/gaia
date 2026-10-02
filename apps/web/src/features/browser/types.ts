import type {
  BrowserLoginResponse,
  BrowserTaskResponse,
} from "@shared/api/generated";

export type BrowserTask = BrowserTaskResponse;
export type SavedBrowserLogin = BrowserLoginResponse;

/** Where a browser card's live browser is shown, and so what "open" does. */
export type LiveSurface =
  /** The side panel shows it: the card shows neither screen nor open action. */
  | { kind: "panel" }
  /** Desktop: inline in the card; "open" moves it into the side panel. */
  | { kind: "card"; openPanel: () => void }
  /** Inline in the card; "open" opens the live page in a new tab. */
  | { kind: "mobile" };
