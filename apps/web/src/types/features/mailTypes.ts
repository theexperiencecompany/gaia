import type {
  AttachmentDisplay,
  EmailComposeCard,
  EmailSentDraftCard,
  GmailMessageSummary,
} from "@shared/api/generated";

/**
 * The API forwards each Gmail message with its raw keys alongside the derived
 * ones it declares (`GmailMessageSummary`); `payload` and the rest are Gmail's
 * own schema, which this interface describes. The one place that says so.
 */
export const asEmailData = (
  messages: GmailMessageSummary[] | Record<string, unknown>[],
): EmailData[] => messages as unknown as EmailData[];

export type EmailData = GmailMessageSummary & {
  payload: EmailPayload;
  summary?: string;
};

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

export type {
  ContactData,
  EmailFetchData,
  EmailThreadData,
  PeopleSearchData,
} from "@shared/chat";

export type EmailComposeData = EmailComposeCard;

export type EmailSentData = EmailComposeCard | EmailSentDraftCard;

export type EmailAttachmentMeta = AttachmentDisplay;
