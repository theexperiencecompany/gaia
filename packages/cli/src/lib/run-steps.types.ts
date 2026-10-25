/** One line under a running step: a stage of it, or one of the things it works on. */
export interface RunSubstep {
  id: string;
  label: string;
  state: "pending" | "active" | "done" | "failed";
  /** A short dim note at the line's right end: "84 / 112 MB", "unpacking". */
  note?: string;
  /** When the line became the running one; its own clock while it runs. */
  startedAt?: number;
}
