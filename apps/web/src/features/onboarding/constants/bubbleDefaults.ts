/**
 * Placeholder props passed to ChatBubbleBot/ChatBubbleUser inside onboarding.
 * These bubbles are read-only (no actions, no attachments, etc.) so every
 * field except text/message_id/date is set to its inert default. Defined
 * once and spread at the call site so all onboarding bubbles stay in sync.
 */

import { noop } from "./noop";

const BASE_BUBBLE_DEFAULTS = {
  message_id: "",
  date: undefined,
  pinned: undefined,
  fileIds: undefined,
  fileData: undefined,
  selectedTool: undefined,
  toolCategory: undefined,
  selectedWorkflow: undefined,
  selectedCalendarEvent: undefined,
  isConvoSystemGenerated: undefined,
  follow_up_actions: undefined,
  image_data: undefined,
  memory_data: undefined,
  todo_progress: undefined,
  replyToMessage: undefined,
  disableActions: true,
} as const;

export const BOT_BUBBLE_DEFAULTS = {
  ...BASE_BUBBLE_DEFAULTS,
  setOpenImage: noop,
  setImageData: noop,
} as const;

export const USER_BUBBLE_DEFAULTS = BASE_BUBBLE_DEFAULTS;
