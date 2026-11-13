/** Types for one-tap onboarding link codes — see `link-codes.ts`. */

import type { GaiaClient } from "./api";
import type { MessageTarget, PlatformName } from "./types";

export interface ParsedLinkCode {
  code: string;
  /** The message with the code (and its separator) removed. */
  text: string;
}

/** `unknown` when the check itself failed — which is not "not linked". */
export type LinkState = "linked" | "unlinked" | "unknown";

/** Why a redemption was refused, as far as the person tapping is concerned.
 *
 * ``failed`` is the one that is not about them: GAIA broke. It still gets an
 * answer, because this is the user's first-ever message. */
export type LinkCodeFailure =
  | "expired"
  | "conflict"
  | "account-has-other"
  | "plan"
  | "failed";

export interface InboundLinkCodeArgs {
  gaia: GaiaClient;
  platform: PlatformName;
  platformUserId: string;
  /** The raw inbound message, possibly ending in ` #<code>`. */
  text: string;
  target: MessageTarget;
  /** Whether this handle is already linked to a GAIA account. */
  linkState: () => Promise<LinkState>;
  profile?: { username?: string; displayName?: string };
}
