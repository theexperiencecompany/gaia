import type { SetupStatusResponse } from "@gaia/shared/api/generated";

/** Which local signup the page offers: the instance's first (admin) account, a member account, or a closed notice. */
export type SignupMode = "first_account" | "member" | "closed";

export function resolveSignupMode(
  status: SetupStatusResponse,
  invite: string | undefined,
): SignupMode {
  if (!status.has_admin_account) return "first_account";
  if (invite || status.registration_policy === "open") return "member";
  return "closed";
}
