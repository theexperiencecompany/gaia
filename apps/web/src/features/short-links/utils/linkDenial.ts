import type { ErrorEnvelope } from "@/types/features/shortLinkTypes";

import { DEAD_LINK_COPY } from "../constants";
import type { DeadLinkState, LinkUnavailableState } from "../types";

function isDeadLinkState(code: string): code is DeadLinkState {
  return Object.hasOwn(DEAD_LINK_COPY, code);
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
    return typeof signedInAs === "string" ? { denial: code, signedInAs } : null;
  }
  return isDeadLinkState(code) ? { denial: code } : null;
}
