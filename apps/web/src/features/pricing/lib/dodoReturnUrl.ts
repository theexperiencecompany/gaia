/**
 * What Dodo appends to a checkout's return URL: the subscription it created,
 * the charge's outcome (`succeeded`, `failed`, `processing`), the payment id
 * and the customer's email.
 */
export const DODO_RETURN_PARAM = {
  subscriptionId: "subscription_id",
  status: "status",
  paymentId: "payment_id",
  email: "email",
} as const;

/** The return params that identify the customer or their payment; analytics masks them. */
export const DODO_RETURN_IDENTIFYING_PARAMS = [
  DODO_RETURN_PARAM.subscriptionId,
  DODO_RETURN_PARAM.paymentId,
  DODO_RETURN_PARAM.email,
] as const;

/**
 * Removes Dodo's params, and any of the caller's own (`extra`), from the
 * address bar, leaving the rest of the URL untouched. The email must not
 * outlive the load: everything that reads the address afterwards (pageview
 * capture, a reload, a shared link) would carry it.
 */
export function stripCheckoutReturnParams(extra: readonly string[] = []): void {
  const owned = [...Object.values(DODO_RETURN_PARAM), ...extra];
  const params = new URLSearchParams(window.location.search);
  if (!owned.some((param) => params.has(param))) return;
  for (const param of owned) params.delete(param);
  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
  );
}
