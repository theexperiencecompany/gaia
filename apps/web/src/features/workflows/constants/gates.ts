/**
 * Copy and limits for a job's rule row, shared by the workflow editor and the
 * tracked-todo sidebar so both read the same way.
 */

/** The API's TRIGGER_GATE_CONDITION_MAX_CHARS; the server refuses a longer condition. */
export const GATE_CONDITION_MAX_CHARS = 300;

/** The API's GMAIL_MESSAGE_TRIGGERS: the triggers whose events a rule reads as new mail. */
export const MAIL_TRIGGER_NAMES: ReadonlySet<string> = new Set([
  "gmail_new_message",
  "gmail_poll_inbox",
]);

/** How a rule's condition reads as a sentence, since GAIA stores it as a clause. */
export const GATE_SENTENCE_PREFIX = "Only when";

export const GATE_EDIT_LABEL = "Edit rule";

export const GATE_EDITED_BY_USER = "Edited by you";

export const GATE_SKIPS_LABEL = "Skipped recently";

export const GATE_NO_SKIPS_NOTE = "Nothing skipped yet";

/** The most skips the detail lists; the API keeps a few more. */
export const GATE_SKIPS_SHOWN = 5;

export const gateSkipCount = (count: number) => `${count} skipped`;

/** Why a skip happened: the rule said no, and how sure it was when the API kept that. */
export const gateSkipReason = (certainty: number | null | undefined) =>
  certainty == null
    ? "Didn't match this rule"
    : `Didn't match this rule, ${Math.round(certainty * 100)}% sure`;

/** What the row, the switch and its helper say, by whether the job watches mail. */
export const GATE_COPY = {
  mail: {
    off: "Checks every email",
    switchLabel: "Filter new mail",
    switchHelper: "When off, GAIA looks at every email.",
  },
  event: {
    off: "Runs on every event",
    switchLabel: "Filter new events",
    switchHelper: "When off, GAIA runs on every event.",
  },
} as const;
