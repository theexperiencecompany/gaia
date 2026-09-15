/**
 * Data for the message being replied to.
 */
import type { SelectedWorkflowDataOutput } from "@shared/api/generated";

export type {
  ReplyToMessageData,
  SelectedCalendarEventData,
} from "@shared/api/generated";

/**
 * A workflow the user picked outside the composer (sidebar, workflow page,
 * modal) and attached to the next message.
 */
export type SelectedWorkflowData = SelectedWorkflowDataOutput;

export interface WorkflowSelectionOptions {
  /** Immediately run the workflow as a chat turn on arrival at /c. */
  autoSend?: boolean;
}

/** A calendar event attached to the next message. */
