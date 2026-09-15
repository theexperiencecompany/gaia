import type { GmailMessageSummary } from "@shared/api/generated";

/**
 * The API forwards each Gmail message with its raw keys alongside the derived
 * ones it declares (`GmailMessageSummary`); `payload` and the rest are Gmail's
 * own schema, which this interface describes. The one place that says so.
 */
export const asEmailData = (
  messages: GmailMessageSummary[] | Record<string, unknown>[],
): EmailData[] => messages as unknown as EmailData[];

export interface EmailData {
  id: string;
  from: string;
  subject: string;
  time: string;
  snippet?: string;
  body?: string;
  labelIds?: string[];
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

// Attachment metadata shown on the compose/sent card (display-only — the
// backend streams just the filename and mimetype, never an s3key).
export type EmailAttachmentMeta = {
  name: string;
  mimetype: string;
};

// Email compose data structure for email intent
export type EmailComposeData = {
  to: string[];
  subject: string;
  body: string;
  draft_id?: string;
  thread_id?: string;
  attachments?: EmailAttachmentMeta[];
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

export type EmailFetchData = {
  from: string;
  subject: string;
  time: string;
  thread_id?: string;
  id: string;
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

export type ContactData = {
  name: string;
  email: string;
  phone?: string;
  resource_name: string;
};

export type PeopleSearchData = {
  name: string;
  email: string;
  phone?: string;
  resource_name: string;
};
