import type { UserInfo } from "@/features/auth/api/authApi";

/**
 * The given name of the signed-in user, for copy that addresses them.
 *
 * Login stores ``name`` as "first last" from the identity provider's profile,
 * so the first word is the given name. An email-only account has an empty
 * name (or, defensively, the email itself); then there is no name to use and
 * the copy must read fine without one.
 */
export function firstNameOf(
  user: Pick<UserInfo, "name" | "email"> | undefined,
): string | undefined {
  const trimmed = user?.name?.trim() ?? "";
  if (!trimmed || trimmed.includes("@") || trimmed === user?.email) {
    return undefined;
  }
  const [first] = trimmed.split(/\s+/);
  return first || undefined;
}
