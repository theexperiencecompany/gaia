import type {
  BrowserLoginResponse,
  BrowserTaskResponse,
} from "@shared/api/generated";
import type { BrowserSessionStatus } from "@/types/features/browserTaskTypes";

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

/** What a browser card shows: the run's own status, or that it is waiting on
 * the user (a pending handoff), which the run reports as a handoff, not a status. */
export type BrowserCardStatus = BrowserSessionStatus | "awaiting_user";

/** What every surface asks of a card's status. */
export interface BrowserCardPhase {
  status: BrowserCardStatus;
  /** The run is over: nothing left to watch or act on. */
  ended: boolean;
  /** The agent is driving (not ended, not waiting on the user). */
  working: boolean;
}
