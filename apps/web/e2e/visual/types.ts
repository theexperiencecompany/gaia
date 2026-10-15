/** Which capture phase of a visual-diff run a snapshot belongs to. */
export type Side = "base" | "head";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One visible element: its structural key, document-relative box and the styles the diff compares. */
export interface DomElement {
  /** `body>div:1>p:2`, one `tag:nth-of-type` per level. */
  path: string;
  /** Own text (first 40 chars), else aria-label or alt; empty when it has none. */
  label: string;
  /** The id and role attributes when set; snapshots from before they were recorded lack them. */
  id?: string;
  role?: string;
  rect: Rect;
  styles: Record<string, string>;
}

export interface DomSnapshot {
  id: string;
  title: string;
  side: Side;
  truncated: boolean;
  elements: DomElement[];
}
