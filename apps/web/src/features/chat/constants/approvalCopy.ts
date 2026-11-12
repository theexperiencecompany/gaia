/**
 * Every user-facing string of the chat approval cards, the review sheet and the
 * loading label after a decision. Outcome sentences live with the shared card
 * contract (`approvalOutcomeLabel` in @shared/chat), which mobile renders too.
 */

/** Lower-case the first letter so an action reads inside a sentence. */
export function inSentence(action: string): string {
  return action.charAt(0).toLowerCase() + action.slice(1);
}

export const APPROVAL_COPY = {
  needsApproval: "Needs your OK",
  asked: (age: string) => `Asked ${age}`,
  reconfirm: (age: string) => `Asked ${age} — still want this?`,
  reconfirmApprove: "Yes, still approve",
  back: "Back",
  showAllDetails: "Show all details",
  feedbackPlaceholder: "Tell GAIA why (optional)",
  sheetFeedbackPlaceholder: "Why? (optional)",
  sheetTitle: (count: number, totals: string) =>
    `${count} actions need your OK (${totals})`,
  submit: (count: number) => `Submit (${count})`,
  sheetStale: "Some approvals already moved — kept for review",
  approve: "Approve",
  deny: "Deny",
  moreOptions: "More approval options",
  optionsMenu: "Approval options",
  alwaysAllow: (action: string) => `Don't ask again to ${inSentence(action)}`,
  alwaysAllowHint: "GAIA will do this without checking from now on.",
  alwaysAllowedTitle: "GAIA won't ask about this again",
  alwaysAllowedDescription: (action: string) =>
    `It will ${inSentence(action)} without checking. Turn asking back on in that integration's Permissions.`,
  staleTap: "That approval already moved — tap again to confirm",
  submitFailed: "Couldn't submit your decision, please try again",
  groupTitle: (count: number) => `${count} actions need your OK`,
  approveAll: "Approve all",
  declineAll: "Decline all",
  review: (count: number) => `Review ${count}`,
  batchPartlyFailed: "Some approvals couldn't be submitted, please try again",
  batchFailed: "Couldn't submit your decisions, please try again",
  sheetFooter:
    "Nothing is sent until you press Submit. Then GAIA carries on with your decisions.",
  carryingOn: (action: string) => `Carrying on: ${inSentence(action)}`,
  tellingGaiaNo: "Letting GAIA know you said no",
  carryingOnWithDecisions: "Carrying on with your decisions",
} as const;
