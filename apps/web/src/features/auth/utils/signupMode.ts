import type { SetupStatusResponse } from "@gaia/shared/api/generated";

/**
 * Which local signup the page offers: the instance's first (admin) account,
 * a member account, a closed notice, or a plain form when the instance status
 * could not be read and the API has to decide.
 */
export type SignupMode = "first_account" | "member" | "closed" | "unknown";

export function resolveSignupMode(
  status: SetupStatusResponse | null,
  invite: string | undefined,
): SignupMode {
  if (status === null) return "unknown";
  if (!status.has_admin_account) return "first_account";
  if (invite || status.registration_policy === "open") return "member";
  return "closed";
}
