import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";

export interface FixtureIntegration {
  id: string;
  name: string;
  tools: IntegrationToolEntry[];
}

const gmailTools: IntegrationToolEntry[] = [
  { name: "GMAIL_SEND_EMAIL", label: "Send Email", destructive: true },
  {
    name: "GMAIL_REPLY_TO_THREAD",
    label: "Reply To Thread",
    destructive: true,
  },
  { name: "GMAIL_DELETE_MESSAGE", label: "Delete Message", destructive: true },
  {
    name: "GMAIL_BATCH_DELETE_MESSAGES",
    label: "Batch Delete Messages",
    destructive: true,
  },
  {
    name: "GMAIL_CREATE_EMAIL_DRAFT",
    label: "Create Email Draft",
    destructive: false,
  },
  { name: "GMAIL_FETCH_MESSAGES", label: "Fetch Messages", destructive: false },
  {
    name: "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
    label: "Fetch Message By Id",
    destructive: false,
  },
  { name: "GMAIL_GET_CONTACTS", label: "Get Contacts", destructive: false },
  { name: "GMAIL_LIST_THREADS", label: "List Threads", destructive: false },
  {
    name: "GMAIL_ADD_LABEL_TO_EMAIL",
    label: "Add Label To Email",
    destructive: false,
  },
  { name: "GMAIL_CREATE_LABEL", label: "Create Label", destructive: false },
  { name: "GMAIL_DELETE_LABEL", label: "Delete Label", destructive: true },
  {
    name: "GMAIL_FORWARD_MESSAGE",
    label: "Forward Message",
    destructive: true,
  },
  { name: "GMAIL_GET_ATTACHMENT", label: "Get Attachment", destructive: false },
  { name: "GMAIL_MARK_AS_READ", label: "Mark As Read", destructive: false },
];

// Trello-scale stress list: enough rows to make the scaling problem visible.
const trelloTools: IntegrationToolEntry[] = Array.from(
  { length: 120 },
  (_, i) => ({
    name: `TRELLO_TOOL_${i + 1}`,
    label: `Trello Action ${i + 1}`,
    destructive: i % 7 === 0,
  }),
);

export const FIXTURES: FixtureIntegration[] = [
  {
    id: "posthog",
    name: "PostHog (1 tool)",
    tools: [{ name: "exec", label: "Exec", destructive: false }],
  },
  { id: "gmail", name: "Gmail (15 tools)", tools: gmailTools },
  { id: "trello", name: "Trello (120 tools)", tools: trelloTools },
];
