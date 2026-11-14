/**
 * Every user-facing string of the chat approval card. What the call does comes
 * from the server's description; these are only the card's own words.
 */

/** Lower-case the first letter so an action reads inside a sentence. */
function inSentence(action: string): string {
  return action.charAt(0).toLowerCase() + action.slice(1);
}

export const APPROVAL_COPY = {
  needsApproval: "Needs your OK",
  inIntegration: (integration: string) => ` in ${integration}`,
  reconfirmApprove: "Yes, still approve",
  back: "Back",
  showAllDetails: "Show all details",
  feedbackPlaceholder: "Tell GAIA why (optional)",
  approve: "Approve",
  deny: "Deny",
  moreOptions: "More approval options",
  optionsMenu: "Approval options",
  alwaysAllow: (action: string) => `Don't ask again to ${inSentence(action)}`,
  alwaysAllowHint: "GAIA will do this without checking from now on.",
  alreadyDecided: "That approval was already decided",
  submitFailed: "Couldn't submit your decision, please try again",
} as const;
