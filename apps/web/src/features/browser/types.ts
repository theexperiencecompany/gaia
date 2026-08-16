export type BrowserTaskStatus =
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface BrowserTask {
  id: string;
  task: string;
  status: BrowserTaskStatus;
  success: boolean;
  steps: number;
  created_at: string | null;
  conversation_id: string;
  /** Ordered full step-screenshot URLs, used to rebuild the recap slideshow. */
  screenshots: string[];
}

export interface SavedBrowserLogin {
  domain: string;
  updated_at: string | null;
}
