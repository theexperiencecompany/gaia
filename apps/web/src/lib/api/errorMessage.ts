import { ApiError } from "@shared/api";

/**
 * The API's own words for a failed call (its error envelope's message).
 * Undefined when the API never answered or answered without one, so the
 * caller shows its own copy instead of a transport string like "Network Error".
 */
export function apiErrorMessage(err: unknown): string | undefined {
  return err instanceof ApiError
    ? (err.envelope?.message ?? undefined)
    : undefined;
}
