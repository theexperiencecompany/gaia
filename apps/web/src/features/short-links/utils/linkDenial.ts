import type { ErrorEnvelope } from "@/types/features/shortLinkTypes";

import { DEAD_LINK_COPY, LINK_DENIAL_CODES } from "../constants";
import type { DeadLinkDenial, LinkUnavailableState } from "../types";

function isDeadLinkDenial(code: string): code is DeadLinkDenial {
  return Object.hasOwn(DEAD_LINK_COPY, code);
}

/**
 * The page a link denial renders, from the API's error envelope; null when the
 * envelope is not a link denial (a lockout, an outage), which the caller throws.
 */
export function linkUnavailableState(
  slug: string,
  envelope: ErrorEnvelope | undefined,
): LinkUnavailableState | null {
  const code = envelope?.code;
  if (!code) return null;
  if (code === LINK_DENIAL_CODES.signInRequired) return { denial: code, slug };
  if (code === LINK_DENIAL_CODES.forbidden) {
    const signedInAs = envelope.signed_in_as;
    return typeof signedInAs === "string" ? { denial: code, signedInAs } : null;
  }
  return isDeadLinkDenial(code) ? { denial: code } : null;
}
