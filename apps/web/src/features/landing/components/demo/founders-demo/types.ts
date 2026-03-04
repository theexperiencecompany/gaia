import type { ReactNode } from "react";
import type { ToolStep } from "../types";

export type MessageRole = "user" | "assistant" | "thinking" | "tools" | "card";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  tools?: ToolStep[];
  cardContent?: ReactNode;
  delay?: number;
}
