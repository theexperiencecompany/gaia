/**
 * The paid-only gate's wire contract.
 *
 * The API returns HTTP 402 with `{ detail: { code, message, checkout_url,
 * discount_code } }` from `app/decorators/entitlements.py`. Every client has to
 * recognise the same shape — web through its axios interceptor and chat-stream
 * client, mobile through its SSE client — so the type and the narrowing live
 * here rather than being re-derived per app.
 */

export const SUBSCRIPTION_REQUIRED_CODE = "subscription_required";

export interface SubscriptionRequiredDetail {
  code: string;
  message: string;
  /** A personal Dodo checkout link, or null when Dodo could not be reached. */
  checkout_url: string | null;
  discount_code: string | null;
}

/**
 * Extracts the `subscription_required` payload a 402 body carries under
 * `detail`, or `undefined` when the body is not shaped that way — an unrelated
 * 402 must fall through to the caller's normal error handling rather than be
 * silently treated as a paywall.
 */
export function getSubscriptionRequiredDetail(
  data: unknown,
): SubscriptionRequiredDetail | undefined {
  const detail =
    data && typeof data === "object" && "detail" in data
      ? (data as { detail: unknown }).detail
      : undefined;

  if (
    detail &&
    typeof detail === "object" &&
    "code" in detail &&
    (detail as { code?: unknown }).code === SUBSCRIPTION_REQUIRED_CODE
  ) {
    return detail as SubscriptionRequiredDetail;
  }
  return undefined;
}

/**
 * Same extraction from a raw response body string. The mobile SSE transport
 * only ever hands back `responseText`, never a parsed object; a body that is
 * not JSON at all is simply "not a paywall", not an error to throw.
 */
export function parseSubscriptionRequiredBody(
  body: string | null | undefined,
): SubscriptionRequiredDetail | undefined {
  if (!body) return undefined;
  try {
    return getSubscriptionRequiredDetail(JSON.parse(body));
  } catch {
    return undefined;
  }
}
