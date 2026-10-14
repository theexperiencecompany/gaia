// Daily/weekly briefing artifact types.
// Mirrors the backend `BriefingPayload` (Pydantic-validated) exactly — see
// openspec/changes/daily-briefing-self-executing-todos/specs/briefing-artifacts/spec.md

export interface BriefingStat {
  value: string;
  label: string;
  delta?: string | null;
}

/** The item's state; `text` is only its title. Mirrors `BriefingItemKind`. */
export type BriefingItemKind = "gaia" | "you" | "lookback" | "failed" | "note";

export interface BriefingSectionItem {
  text: string;
  todo_id?: string | null;
  kind: BriefingItemKind;
}

export interface BriefingSection {
  numeral: string;
  title: string;
  items: BriefingSectionItem[];
}

export interface BriefingPayload {
  kicker: string;
  date: string;
  headline: string;
  lede: string;
  stats: BriefingStat[];
  sections: BriefingSection[];
  mood: string;
  caption: string;
  hue: number;
}
