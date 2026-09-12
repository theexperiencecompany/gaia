/**
 * Data for the message being replied to.
 */
import type { Schema } from "@shared/api/generated";

export type ReplyToMessageData = Schema<"ReplyToMessageData">;

/**
 * A workflow the user picked outside the composer (sidebar, workflow page,
 * modal) and attached to the next message.
 */
export type SelectedWorkflowData = Schema<"SelectedWorkflowData-Output">;

export interface WorkflowSelectionOptions {
  /** Immediately run the workflow as a chat turn on arrival at /c. */
  autoSend?: boolean;
}

/** A calendar event attached to the next message. */
export type SelectedCalendarEventData = Schema<"SelectedCalendarEventData">;
