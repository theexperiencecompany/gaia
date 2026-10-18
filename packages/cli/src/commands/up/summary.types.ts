import type { LlmProvider } from "../../lib/llm-flags.js";

export interface UpOutcome {
  /** The address to open first (see primaryWebUrl). */
  webUrl: string;
  /** Every address GAIA answers at, webUrl included. */
  reachableUrls: string[];
  /** http://gaia.local, once other devices on the network can open it. */
  localUrl?: string;
  /** Why gaia.local isn't set up, when this run tried and could not. */
  localNameProblem?: string;
  /** The domain's certificate comes from Caddy's local authority, which devices don't trust yet. */
  localCertificate?: boolean;
  noStart: boolean;
  stillStarting: boolean;
  setupComplete: boolean;
  codeSandbox: boolean;
  savedProvider?: LlmProvider;
  /** The flagged provider whose key this run could not save. */
  unsavedProvider?: LlmProvider;
  joinedDockerGroup: boolean;
  /** How long the whole run took. */
  elapsedMs: number;
  /** Services this run started; 0 means everything was already running. */
  startedServices: number;
}

export type SummaryTone = "success" | "pending";

/** A labelled row of the card; `primary` rows carry the one action to take. */
export interface SummaryRow {
  label: string;
  text: string;
  /** A URL inside text to emphasise and link. */
  url?: string;
  tone?: "primary" | "warn" | "dim";
}

export interface UpSummary {
  tone: SummaryTone;
  headline: string;
  rows: SummaryRow[];
}
