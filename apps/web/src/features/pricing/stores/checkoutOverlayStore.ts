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
  CHECKOUT_DISMISS_CONFIRM_BUDGET_MS,
} from "../constants";
import { closeDodoOverlay, openDodoOverlay } from "../lib/dodoOverlay";

/**
 * Where an embedded checkout is in its life.
 *
 * The webhook remains the single source of truth for subscription state — the
 * overlay's events only tell us *when to start asking the server*, never what
 * the answer is. That is why `redirect` lands in `confirming` rather than
 * declaring success: it fires before our webhook has landed.
 *
 * A `closed` is weaker evidence still, and is treated as such: a charge that
 * went through leaves via Dodo's return URL, so an overlay that closed on us
 * is a checkout the user walked away from. It gets a short grace in
 * `confirming` for the rare charge that landed without the redirect, then the
 * plans come back — see `CHECKOUT_DISMISS_CONFIRM_BUDGET_MS`.
 */
export type CheckoutPhase =
  | "idle"
  | "creating" // minting the Dodo session
  | "open" // the overlay is up, the user is paying
  | "confirming" // overlay gone, polling the server for the webhook's effect
  | "confirmed" // the server says the subscription is active
  | "timeout" // past the visible budget, still polling in the background
  | "unconfirmed"; // the whole budget passed with nothing landing; polling stopped

/** A checkout can start from here: nothing is minting, open, or being confirmed. */
export const isCheckoutSettled = (phase: CheckoutPhase): boolean =>
  phase === "idle" || phase === "unconfirmed";

export type CheckoutBillingCycle = "monthly" | "yearly";

interface CheckoutOverlayStore {
  phase: CheckoutPhase;
  error: string | null;
  /** The user pressed pay (or Dodo asked to redirect) in this overlay run.
   *  Without it a close is just a close: nothing at all to confirm. */
  paymentAttempted: boolean;
  startCheckout: (
    billingCycle: CheckoutBillingCycle,
    source: CheckoutSource,
  ) => Promise<void>;
  handleCheckoutEvent: (event: CheckoutEvent) => void;
  /** Dodo sent the browser back with the subscription it created (the
   *  redirect path, no overlay in this page's life). Settles the charge with
   *  the server directly, which asks Dodo when the webhook is late or lost. */
  confirmReturnedCheckout: (subscriptionId?: string) => void;
  reset: () => void;
}

/** One read of "is the subscription real yet?"; the loop keeps asking until it says yes. */
type PaidProbe = () => Promise<boolean>;

const subscriptionIsActive: PaidProbe = async () =>
  (await pricingApi.getSubscriptionStatus()).plan_type === "pro";

const verifySettles =
  (subscriptionId?: string): PaidProbe =>
  async () =>
    (await pricingApi.verifyPayment(subscriptionId)).payment_completed;

/** Cancels the in-flight confirmation loop when a new checkout starts or the
 *  machine is reset — without it a stale loop could resolve over a newer one. */
let confirmationRun = 0;

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

export const useCheckoutOverlayStore = create<CheckoutOverlayStore>()(
  devtools(
    (set, get) => {
      /** The one loop that waits for a payment to become a subscription.
       *  Past the visible budget the copy changes to admit the delay but the
       *  polling continues; past `budgetMs` it stops and says so. */
      const confirmPayment = async (
        isPaid: PaidProbe,
        budgetMs = CHECKOUT_CONFIRM_TOTAL_BUDGET_MS,
      ) => {
        confirmationRun += 1;
        const run = confirmationRun;
        const startedAt = Date.now();
        let delay = CHECKOUT_CONFIRM_INITIAL_DELAY_MS;

        while (Date.now() - startedAt < budgetMs) {
          // Clamped to what is left of the budget: an unclamped backoff sleeps
          // straight past the deadline, so "hand the plans back after 15s"
          // would last however long the next gap happened to be.
          await sleep(Math.min(delay, budgetMs - (Date.now() - startedAt)));
          if (run !== confirmationRun) return;

          try {
            const paid = await isPaid();
            if (run !== confirmationRun) return;
            if (paid) {
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
        set({ phase: "unconfirmed" }, false, "unconfirmed");
      };

      return {
        phase: "idle",
        error: null,
        paymentAttempted: false,

        startCheckout: async (billingCycle, source) => {
          confirmationRun += 1;
          set(
            { phase: "creating", error: null, paymentAttempted: false },
            false,
            "startCheckout",
          );
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
            case "checkout.pay_button_clicked":
            case "checkout.redirect_requested":
              set({ paymentAttempted: true }, false, "paymentAttempted");
              break;
            case "checkout.redirect":
              // Dodo is taking the browser to the return URL, which it only
              // does once the charge exists. Only the webhook makes it a
              // subscription, so ask the server until it answers.
              if (get().phase !== "open") break;
              set({ phase: "confirming" }, false, "confirming");
              void confirmPayment(subscriptionIsActive);
              break;
            case "checkout.closed": {
              if (get().phase !== "open") break;
              // A close before pay was ever pressed is the user backing out:
              // there is no payment to confirm, so the wizard is theirs again.
              if (!get().paymentAttempted) {
                set({ phase: "idle" }, false, "overlayDismissed");
                break;
              }
              // Pressing pay is not evidence of having paid — a charge that
              // goes through leaves via the return URL rather than closing
              // the sheet on us. So this is almost always someone changing
              // their mind, and holding the whole surface hostage to a
              // five-minute spinner is a lie. Give a charge already in
              // flight its short grace, then hand the plans back.
              set({ phase: "confirming" }, false, "confirmingDismissed");
              void confirmPayment(
                subscriptionIsActive,
                CHECKOUT_DISMISS_CONFIRM_BUDGET_MS,
              );
              break;
            }
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

        confirmReturnedCheckout: (subscriptionId) => {
          set({ phase: "confirming", error: null }, false, "confirmReturned");
          void confirmPayment(verifySettles(subscriptionId));
        },

        reset: () => {
          confirmationRun += 1;
          set(
            { phase: "idle", error: null, paymentAttempted: false },
            false,
            "reset",
          );
        },
      };
    },
    { name: "checkoutOverlay-store" },
  ),
);
