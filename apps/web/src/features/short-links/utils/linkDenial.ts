import type { ErrorEnvelope } from "@/types/features/shortLinkTypes";

import { GATED_LINK_DENIALS } from "../constants";
import { LINK_CONSTANTS } from "../link-constants.generated";
import type { DeadLinkState, LinkUnavailableState } from "../types";

const GATED_CODES: ReadonlySet<string> = new Set(GATED_LINK_DENIALS);

function isDeadLinkState(code: string): code is DeadLinkState {
  return Object.hasOwn(LINK_CONSTANTS.pageCopy, code) && !GATED_CODES.has(code);
}

/**
 * The page a refused open renders, from the API's error body (a LinkDenialEnvelope,
 * or the lockout's envelope); null for anything else (an outage), which the caller throws.
 */
export function linkUnavailableState(
  slug: string,
  envelope: ErrorEnvelope | undefined,
): LinkUnavailableState | null {
  const code = envelope?.code;
  if (!code) return null;
  if (code === "link_sign_in_required") return { denial: code, slug };
  if (code === "link_forbidden") {
    const signedInAs = envelope.signed_in_as;
    return typeof signedInAs === "string"
      ? { denial: code, signedInAs, slug }
      : null;
  }
  return isDeadLinkState(code) ? { denial: code } : null;
}
