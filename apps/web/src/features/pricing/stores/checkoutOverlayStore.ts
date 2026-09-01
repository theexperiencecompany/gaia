import type { CheckoutEvent } from "dodopayments-checkout";
import { create } from "zustand";
import { devtools } from "zustand/middleware";

import { type CheckoutSource, pricingApi } from "../api/pricingApi";
import {
  CHECKOUT_CONFIRM_BACKOFF_FACTOR,
  CHECKOUT_CONFIRM_INITIAL_DELAY_MS,
  CHECKOUT_CONFIRM_MAX_DELAY_MS,
  CHECKOUT_CONFIRM_TOTAL_BUDGET_MS,
  CHECKOUT_CONFIRM_VISIBLE_BUDGET_MS,
} from "../constants";
import { closeDodoOverlay, openDodoOverlay } from "../lib/dodoOverlay";

/**
 * Where an embedded checkout is in its life.
 *
 * The webhook remains the single source of truth for subscription state — the
 * overlay's events only tell us *when to start asking the server*, never what
 * the answer is. That is why `closed` and `redirect` both land in `confirming`
 * rather than declaring success: the user can close the overlay having paid,
 * and Dodo's `redirect` fires before our webhook has landed.
 */
export type CheckoutPhase =
  | "idle"
  | "creating" // minting the Dodo session
  | "open" // the overlay is up, the user is paying
  | "confirming" // overlay gone, polling the server for the webhook's effect
  | "confirmed" // the server says the subscription is active
  | "timeout"; // past the visible budget, still polling in the background

export type CheckoutBillingCycle = "monthly" | "yearly";

interface CheckoutOverlayStore {
  phase: CheckoutPhase;
  error: string | null;
  startCheckout: (
    billingCycle: CheckoutBillingCycle,
    source: CheckoutSource,
  ) => Promise<void>;
  handleCheckoutEvent: (event: CheckoutEvent) => void;
  reset: () => void;
}

/** Cancels the in-flight confirmation loop when a new checkout starts or the
 *  machine is reset — without it a stale loop could resolve over a newer one. */
let confirmationRun = 0;

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

export const useCheckoutOverlayStore = create<CheckoutOverlayStore>()(
  devtools(
    (set, get) => {
      /** Polls the authoritative subscription status until the webhook has
       *  landed. Past the visible budget the copy changes to admit the delay,
       *  but the polling continues — the access unlocks the moment it lands. */
      const confirmPayment = async () => {
        confirmationRun += 1;
        const run = confirmationRun;
        const startedAt = Date.now();
        let delay = CHECKOUT_CONFIRM_INITIAL_DELAY_MS;

        while (Date.now() - startedAt < CHECKOUT_CONFIRM_TOTAL_BUDGET_MS) {
          await sleep(delay);
          if (run !== confirmationRun) return;

          try {
            const status = await pricingApi.getSubscriptionStatus();
            if (run !== confirmationRun) return;
            if (status.plan_type === "pro") {
              set({ phase: "confirmed", error: null }, false, "confirmed");
              void closeDodoOverlay();
              return;
            }
          } catch {
            // A failed status read is indistinguishable from "not yet active"
            // here — both mean keep asking. The next poll is the recovery.
          }

          if (
            get().phase === "confirming" &&
            Date.now() - startedAt >= CHECKOUT_CONFIRM_VISIBLE_BUDGET_MS
          ) {
            set({ phase: "timeout" }, false, "confirmTimeout");
          }
          delay = Math.min(
            delay * CHECKOUT_CONFIRM_BACKOFF_FACTOR,
            CHECKOUT_CONFIRM_MAX_DELAY_MS,
          );
        }
      };

      return {
        phase: "idle",
        error: null,

        startCheckout: async (billingCycle, source) => {
          confirmationRun += 1;
          set({ phase: "creating", error: null }, false, "startCheckout");
          try {
            // `source` is what the server stamps onto
            // `payment:checkout_started` — the single emitter for this action.
            const session = await pricingApi.createCheckoutSession({
              billing_cycle: billingCycle,
              source,
            });
            if (!session.payment_link)
              throw new Error("Checkout session has no URL");

            await openDodoOverlay(session.payment_link, (event) =>
              get().handleCheckoutEvent(event),
            );
            set({ phase: "open" }, false, "overlayOpened");
          } catch (err) {
            set(
              {
                phase: "idle",
                error:
                  err instanceof Error
                    ? err.message
                    : "Could not start checkout",
              },
              false,
              "checkoutFailed",
            );
            throw err;
          }
        },

        handleCheckoutEvent: (event) => {
          switch (event.event_type) {
            case "checkout.closed":
            case "checkout.redirect":
              // Neither event proves payment either way — only the webhook
              // does. Ask the server until it answers.
              if (get().phase === "open") {
                set({ phase: "confirming" }, false, "confirming");
                void confirmPayment();
              }
              break;
            case "checkout.error":
            case "checkout.link_expired":
              set(
                {
                  phase: "idle",
                  error:
                    event.event_type === "checkout.link_expired"
                      ? "That checkout link expired. Please try again."
                      : "Checkout failed. Please try again.",
                },
                false,
                "checkoutError",
              );
              break;
            default:
              break;
          }
        },

        reset: () => {
          confirmationRun += 1;
          set({ phase: "idle", error: null }, false, "reset");
        },
      };
    },
    { name: "checkoutOverlay-store" },
  ),
);
