/**
 * What `gaia update` asks before it changes anything, shared by its flow and
 * its screen.
 * @module commands/update/offer
 */

/** The yes/no the screen answers; Enter alone means no. */
export const UPDATE_CONFIRM_INPUT = "update_confirm";

/** Store key for the offer on screen while the question waits. */
export const UPDATE_OFFER_KEY = "updateOffer";

/** Store key for the one line a run ends with when nothing changed. */
export const UPDATE_NOTICE_KEY = "updateNotice";

export interface UpdateOffer {
  question: string;
  /** What the update brings: the release's highlights, or the new commits. */
  lines: readonly string[];
}
