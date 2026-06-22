import { PENDING_CHECKOUT_KEY, PENDING_CHECKOUT_TTL_MS } from "../constants";

interface PendingCheckout {
  planId: string;
  ts: number;
}

export const writePendingCheckout = (planId: string): void => {
  const value: PendingCheckout = { planId, ts: Date.now() };
  localStorage.setItem(PENDING_CHECKOUT_KEY, JSON.stringify(value));
};

/**
 * Returns the pending plan id if one was set within the TTL, else null.
 * Does not clear on the happy path (the gates rely on it staying readable
 * until the redirect); only prunes a genuinely stale/corrupt entry.
 */
export const readPendingCheckout = (): string | null => {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(PENDING_CHECKOUT_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingCheckout;
    if (Date.now() - parsed.ts > PENDING_CHECKOUT_TTL_MS) {
      localStorage.removeItem(PENDING_CHECKOUT_KEY);
      return null;
    }
    return parsed.planId;
  } catch {
    localStorage.removeItem(PENDING_CHECKOUT_KEY);
    return null;
  }
};

export const clearPendingCheckout = (): void => {
  localStorage.removeItem(PENDING_CHECKOUT_KEY);
};
