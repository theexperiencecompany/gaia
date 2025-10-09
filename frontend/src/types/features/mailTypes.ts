export interface EmailData {
  id: string;
  from: string;
  subject: string;
  time: string;
  snippet?: string;
  body?: string;
  labelIds?: string[];
  headers: Record<string, string>;
  payload: EmailPayload;
  summary?: string;
  threadId?: string; // Thread ID for grouping related messages
}

export interface EmailsResponse {
  emails: EmailData[];
  nextPageToken?: string;
}

export interface EmailThreadResponse {
  thread_id: string;
  messages_count: number;
  thread: {
    messages: EmailData[];
  };
}

export interface EmailPayload {
  [x: string]: unknown;
  parts: EmailPart[];
  body: EmailBody;
  payload: {
    headers: { name: string; value: string }[];
    parts?: { mimeType: string; body: { data: string } }[];
    body?: { data: string };
  };
}

export interface EmailPart {
  mimeType: string;
  filename?: string;
  headers?: { name: string; value: string }[];
  body?: EmailBody;
  parts?: EmailPart[];
}

export interface EmailBody {
  size: number;
  data?: string;
  attachmentId?: string;
}

// Email compose data structure for email intent
export type EmailComposeData = {
  to: string[];
  subject: string;
  body: string;
  draft_id?: string;
  thread_id?: string;
};

// AI Email Analysis Types
export interface EmailImportanceSummary {
  _id: string;
  user_id: string;
  message_id: string;
  subject: string;
  sender: string;
  date: string;
  labels: string[];
  is_important: boolean;
  importance_level: "URGENT" | "HIGH" | "MEDIUM" | "LOW";
  summary: string;
  semantic_labels: string[];
  category: string;
  intent: string;
  analyzed_at: string;
  content_preview: string;
}

export interface EmailSummariesResponse {
  status: string;
  emails: EmailImportanceSummary[];
  count: number;
  filtered_by_importance?: boolean;
  searched_labels?: string[];
}

export interface SemanticLabelsStats {
  status: string;
  semantic_labels: Array<{ _id: string; count: number }>;
  categories: Array<{ _id: string; count: number }>;
  intents: Array<{ _id: string; count: number }>;
}

export type EmailFetchData = {
  from: string;
  subject: string;
  time: string;
  thread_id?: string;
};

export type EmailThreadData = {
  thread_id: string;
  messages: Array<{
    id: string;
    from: string;
    subject: string;
    time: string;
    snippet: string;
    body: string;
    content?: { text: string; html: string };
  }>;
  messages_count: number;
};

export type EmailSentData = {
  message_id?: string;
  message: string;
  timestamp?: string;
  recipients?: string[];
  subject?: string;
};
