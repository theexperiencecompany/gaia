// Daily/weekly briefing artifact types.
// Mirrors the backend `BriefingPayload` (Pydantic-validated) exactly — see
// openspec/changes/daily-briefing-self-executing-todos/specs/briefing-artifacts/spec.md

export interface BriefingStat {
  value: string;
  label: string;
  delta?: string;
}

export interface BriefingSectionItem {
  text: string;
  todo_id?: string;
  kind: string;
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

/** The stored envelope returned by `GET /briefings/latest` and `GET /briefings`. */
export interface Briefing {
  id: string;
  user_id: string;
  date: string;
  kind: "daily" | "weekly";
  payload: BriefingPayload;
  created_at: string;
}
