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
  /** Where the task started: "web", "telegram", "whatsapp", … (may be empty). */
  source: string;
  /** Ordered recap frames (screenshot + caption) that rebuild the slideshow. */
  frames: BrowserTaskFrame[];
}

export interface SavedBrowserLogin {
  domain: string;
  updated_at: string | null;
  /** When this session data auto-expires (last use + TTL). */
  expires_at: string | null;
  /** Where the login came from — "import" for CLI imports, null when browsing-acquired. */
  source: string | null;
  /** The browser the CLI read the login from ("Arc", "Chrome", …). */
  source_browser: string | null;
  /** Client IP the import was uploaded from. */
  source_ip: string | null;
}
