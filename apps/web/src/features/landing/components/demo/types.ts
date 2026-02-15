// ─── Demo component types ─────────────────────────────────────────────────────

export type DemoPage =
  | "dashboard"
  | "calendar"
  | "integrations"
  | "workflows"
  | "todos"
  | "goals"
  | "chats";

export type FinalCardType =
  | "email"
  | "workflow"
  | "tools"
  | "tasks"
  | "briefing";

export type Phase =
  | "idle"
  | "user_sent"
  | "thinking"
  | "loading1"
  | "loading2"
  | "tool_calls"
  | "responding"
  | "final_card"
  | "done";

export interface ToolStep {
  category: string;
  name: string;
  message: string;
}

export interface UseCase {
  id: string;
  label: string;
  emoji: string;
  userMessage: string;
  tools: ToolStep[];
  loadingTexts: [string, string, string];
  botResponse: string;
  finalCard: FinalCardType;
}
