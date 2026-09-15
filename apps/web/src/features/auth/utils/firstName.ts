/**
 * The given name of the signed-in user, for copy that addresses them.
 *
 * Login stores ``name`` as "first last" from the identity provider's profile,
 * so the first word is the given name. An email-only account has an empty
 * name (or, defensively, the email itself); then there is no name to use and
 * the copy must read fine without one.
 */
export function firstNameOf(
  name: string | undefined,
  email: string | undefined,
): string | undefined {
  const trimmed = name?.trim() ?? "";
  if (!trimmed || trimmed.includes("@") || trimmed === email) return undefined;
  const [first] = trimmed.split(/\s+/);
  return first || undefined;
}
