export type BrowserTaskStatus =
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface BrowserTaskFrame {
  url: string;
  /** What the agent was doing at this step ("Searching for …"). */
  caption: string | null;
}

export interface BrowserTask {
  id: string;
  task: string;
  status: BrowserTaskStatus;
  success: boolean;
  steps: number;
  created_at: string | null;
  conversation_id: string;
  /** Ordered recap frames (screenshot + caption) that rebuild the slideshow. */
  frames: BrowserTaskFrame[];
}

export interface SavedBrowserLogin {
  domain: string;
  updated_at: string | null;
}
