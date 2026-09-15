/**
 * Data for the message being replied to.
 */
export interface ReplyToMessageData {
  id: string;
  content: string;
  role: "user" | "assistant";
}

/**
 * A workflow the user picked outside the composer (sidebar, workflow page,
 * modal) and attached to the next message.
 */
export interface SelectedWorkflowData {
  id: string;
  title: string;
  description: string;
  prompt?: string;
  steps: Array<{
    id: string;
    title: string;
    description: string;
    category: string;
  }>;
}

export interface WorkflowSelectionOptions {
  /** Immediately run the workflow as a chat turn on arrival at /c. */
  autoSend?: boolean;
}

/** A calendar event attached to the next message. */
export interface SelectedCalendarEventData {
  id: string;
  summary: string;
  description: string;
  start: {
    date?: string;
    dateTime?: string;
    timeZone?: string;
  };
  end: {
    date?: string;
    dateTime?: string;
    timeZone?: string;
  };
  calendarId?: string;
  calendarTitle?: string;
  backgroundColor?: string;
  isAllDay?: boolean;
}
