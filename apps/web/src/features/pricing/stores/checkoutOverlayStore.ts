import type { CheckoutEvent } from "dodopayments-checkout";
import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { track } from "@/lib/analytics";

import { type CheckoutSource, pricingApi } from "../api/pricingApi";
import {
  CHECKOUT_CONFIRM_BACKOFF_FACTOR,
  CHECKOUT_CONFIRM_INITIAL_DELAY_MS,
  CHECKOUT_CONFIRM_MAX_DELAY_MS,
  CHECKOUT_CONFIRM_TOTAL_BUDGET_MS,
  CHECKOUT_CONFIRM_VISIBLE_BUDGET_MS,
  CHECKOUT_DECLINED_COPY,
  CHECKOUT_DISMISS_CONFIRM_BUDGET_MS,
  CHECKOUT_NOT_LOADED_COPY,
  CHECKOUT_OVERLAY_LOAD_TIMEOUT_MS,
} from "../constants";
import { closeDodoOverlay, openDodoOverlay } from "../lib/dodoOverlay";

/**
 * Where an embedded checkout is in its life. Only the server makes a
 * subscription real, so a charge Dodo reports as succeeded lands in
 * `confirming`; a closed overlay gets a short `confirming` grace
 * (`CHECKOUT_DISMISS_CONFIRM_BUDGET_MS`) before the plans come back.
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

/** How far into the overlay the user got, in the order Dodo walks them. */
export type CheckoutStep =
  | "not_loaded"
  | "opened"
  | "details_submitted"
  | "payment_page"
  | "pay_pressed";

const STEP_ORDER: readonly CheckoutStep[] = [
  "not_loaded",
  "opened",
  "details_submitted",
  "payment_page",
  "pay_pressed",
];

const STEP_REACHED_BY: Partial<
  Record<CheckoutEvent["event_type"], CheckoutStep>
> = {
  "checkout.opened": "opened",
  "checkout.customer_details_submitted": "details_submitted",
  "checkout.payment_page_opened": "payment_page",
  "checkout.pay_button_clicked": "pay_pressed",
};

/** What the overlay run in flight is buying, from where, and how far it got. */
interface OpenCheckout {
  billingCycle: CheckoutBillingCycle;
  source: CheckoutSource;
  furthestStep: CheckoutStep;
}

/** The charge outcome Dodo reports on `checkout.status` under `manualRedirect`. */
type ChargeStatus = "succeeded" | "failed" | "processing";

/** Dodo nests every event's payload under `data.message`. */
function messageOf(event: CheckoutEvent): Record<string, unknown> | null {
  const message = event.data?.message;
  return typeof message === "object" && message !== null
    ? (message as Record<string, unknown>)
    : null;
}

function chargeStatusOf(event: CheckoutEvent): ChargeStatus | null {
  const status = messageOf(event)?.status;
  return status === "succeeded" ||
    status === "failed" ||
    status === "processing"
    ? status
    : null;
}

function redirectTargetOf(event: CheckoutEvent): URL | null {
  const target = messageOf(event)?.redirect_to;
  return typeof target === "string" ? URL.parse(target) : null;
}

interface CheckoutOverlayStore {
  phase: CheckoutPhase;
  error: string | null;
  /** The user pressed pay (or Dodo asked to redirect) in this overlay run.
   *  Without it a close is just a close: nothing at all to confirm. */
  paymentAttempted: boolean;
  /** The overlay run in flight; null once it has closed or settled. */
  openCheckout: OpenCheckout | null;
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
  (await pricingApi.getSubscriptionStatus({ background: true })).plan_type ===
  "pro";

/** Without an id the server resolves the user's recent checkout sessions
 *  against Dodo, which is what settles an overlay charge before its webhook. */
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

      /** The user is leaving an overlay run that took no money. */
      const abandon = () => {
        const run = get().openCheckout;
        if (!run) return;
        track("payment:checkout_abandoned", {
          source: run.source,
          billing_cycle: run.billingCycle,
          furthest_step: run.furthestStep,
        });
        set({ openCheckout: null }, false, "abandoned");
      };

      /** Dodo's verdict on the charge. A decline hands the plans back with
       *  the reason, in place; anything else is the server's to confirm. The
       *  phase moves first, so the close this triggers reads as settled. */
      const settleCharge = (status: ChargeStatus) => {
        if (status === "failed") {
          set(
            {
              phase: "idle",
              openCheckout: null,
              error: `${CHECKOUT_DECLINED_COPY.heading} ${CHECKOUT_DECLINED_COPY.body}`,
            },
            false,
            "chargeDeclined",
          );
        } else {
          set(
            { phase: "confirming", openCheckout: null },
            false,
            "chargeConfirming",
          );
          void confirmPayment(verifySettles());
        }
        void closeDodoOverlay();
      };

      /** An overlay that never rendered is a transparent sheet over the page:
       *  take it down and say so rather than leave every click swallowed. */
      const closeIfNeverLoaded = (run: number) => {
        const { phase, openCheckout } = get();
        if (run !== confirmationRun || phase !== "open") return;
        if (openCheckout?.furthestStep !== "not_loaded") return;
        abandon();
        set(
          { phase: "idle", error: CHECKOUT_NOT_LOADED_COPY },
          false,
          "overlayNotLoaded",
        );
        void closeDodoOverlay();
      };

      return {
        phase: "idle",
        error: null,
        paymentAttempted: false,
        openCheckout: null,

        startCheckout: async (billingCycle, source) => {
          confirmationRun += 1;
          const run = confirmationRun;
          set(
            {
              phase: "creating",
              error: null,
              paymentAttempted: false,
              openCheckout: null,
            },
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
            set(
              {
                phase: "open",
                openCheckout: {
                  billingCycle,
                  source,
                  furthestStep: "not_loaded",
                },
              },
              false,
              "overlayOpened",
            );
            setTimeout(
              () => closeIfNeverLoaded(run),
              CHECKOUT_OVERLAY_LOAD_TIMEOUT_MS,
            );
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
          const reached = STEP_REACHED_BY[event.event_type];
          const openRun = get().openCheckout;
          if (
            reached &&
            openRun &&
            STEP_ORDER.indexOf(reached) >
              STEP_ORDER.indexOf(openRun.furthestStep)
          )
            set(
              { openCheckout: { ...openRun, furthestStep: reached } },
              false,
              "stepReached",
            );

          switch (event.event_type) {
            case "checkout.pay_button_clicked":
              set({ paymentAttempted: true }, false, "paymentAttempted");
              break;
            case "checkout.status": {
              const status = chargeStatusOf(event);
              if (status && get().phase === "open") settleCharge(status);
              break;
            }
            case "checkout.redirect_requested": {
              // The outcome arrives as checkout.status: a redirect back into
              // the app would only add a reload and the customer's email in
              // the URL. Elsewhere is a bank's 3-D Secure page, which needs the tab.
              set({ paymentAttempted: true }, false, "paymentAttempted");
              const target = redirectTargetOf(event);
              if (target && target.origin !== window.location.origin)
                window.location.assign(target);
              break;
            }
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
              abandon();
              // A close before pay was ever pressed is the user backing out:
              // there is no payment to confirm, so the wizard is theirs again.
              if (!get().paymentAttempted) {
                set({ phase: "idle" }, false, "overlayDismissed");
                break;
              }
              // Pressing pay isn't evidence of having paid — the charge's outcome
              // arrives as checkout.status, so a close after pay is almost
              // always changing their mind; give an in-flight charge a short grace, then hand the plans back.
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
                  openCheckout: null,
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
            {
              phase: "idle",
              error: null,
              paymentAttempted: false,
              openCheckout: null,
            },
            false,
            "reset",
          );
        },
      };
    },
    { name: "checkoutOverlay-store" },
  ),
);
