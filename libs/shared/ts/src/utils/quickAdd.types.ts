import type { Priority } from "../types/todo";

export interface QuickAddProject {
  id: string;
  name: string;
}

export interface QuickAddProjectMatch {
  id?: string;
  name: string;
}

export interface QuickAddOptions {
  projects?: QuickAddProject[];
  /** Override "now" — useful for tests. Defaults to `new Date()`. */
  now?: Date;
  /** IANA timezone string. Defaults to the runtime's resolved timezone. */
  timezone?: string;
}

export interface QuickAddResult {
  cleanedText: string;
  project?: QuickAddProjectMatch;
  labels: string[];
  priority?: Priority;
  dueDate: Date | null;
  timezone?: string;
}
