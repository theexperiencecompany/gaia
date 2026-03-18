export interface FileData {
  id?: string;
  name: string;
  url: string;
  type: string;
  size?: number;
  mimeType?: string;
}

export interface ImageData {
  url: string;
  width?: number;
  height?: number;
  alt?: string;
}

export interface ToolSubStep {
  id: string;
  label: string;
  status?: string;
}

export interface ToolData {
  toolName: string;
  toolCallId: string;
  input?: Record<string, unknown>;
  output?: string;
  status: "pending" | "running" | "completed" | "error";
  progress?: string;
  subSteps?: ToolSubStep[];
}

export interface MemoryData {
  id: string;
  content: string;
  timestamp: string;
}

export interface ApiToolCall {
  id: string;
  type: string;
  function: {
    name: string;
    arguments: string;
  };
}

export interface ApiMessage {
  role: "user" | "assistant" | "system";
  content: string;
  tool_calls?: ApiToolCall[];
  tool_call_id?: string;
  id?: string;
  metadata?: Record<string, unknown>;
}

export interface ReplyToMessageData {
  messageId: string;
  content: string;
  role: "user" | "assistant";
}

export interface Message {
  id: string;
  conversationId: string;
  role: "user" | "assistant" | "system";
  content: string;
  toolData?: ToolData[];
  imageData?: ImageData | null;
  fileData?: FileData[];
  replyTo?: ReplyToMessageData | null;
  timestamp: string;
  isStreaming?: boolean;
}

export interface Conversation {
  id: string;
  description?: string;
  starred?: boolean;
  createdAt: string;
  updatedAt: string;
  unread?: boolean;
  lastMessage?: string;
}

export interface GroupedConversations {
  label: string;
  conversations: Conversation[];
}

export interface Suggestion {
  text: string;
  icon?: string;
}

export interface StreamingState {
  isStreaming: boolean;
  isTyping: boolean;
  progress?: string;
  progressToolName?: string;
}
