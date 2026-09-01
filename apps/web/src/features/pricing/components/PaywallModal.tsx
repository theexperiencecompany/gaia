"use client";

import { Button } from "@heroui/button";
import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { Tag01Icon } from "@icons";
import { useEffect } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { useLogout } from "@/features/auth/hooks/useLogout";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

import { REFUND_WINDOW_COPY } from "../constants";
import { useDodoPayments } from "../hooks/useDodoPayments";
import { useIsPaid } from "../hooks/useIsPaid";
import { usePricing, useUserSubscriptionStatus } from "../hooks/usePricing";
import { isProPlan } from "../utils/planPredicates";
import { CheckoutConfirming } from "./CheckoutConfirming";
import { PlanFeature } from "./PlanFeature";

/** Two audiences hit the same wall for different reasons, so they read
 *  different copy: someone whose subscription ran out is being asked to come
 *  back, while a free user at the paid-only migration is being told the rules
 *  changed. `has_ever_subscribed` is the only thing that separates them. */
const LAPSED_COPY = {
  heading: "Your subscription ended",
  body: "Pick up right where you left off.",
} as const;

const MIGRATION_COPY = {
  heading: "GAIA is Pro-only",
  body: "Subscribe to GAIA Pro to keep chatting and running workflows.",
} as const;

export function PaywallModal() {
  const { open, offer, dismissible, closeModal } = usePaywallModalStore();
  const { plans } = usePricing();
  const { logout } = useLogout();
  const { openCheckoutOverlay, checkoutPhase } = useDodoPayments();
  const { isPaid, isUnknown: isSubscriptionStatusUnknown } = useIsPaid();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const copy = subscriptionStatus?.has_ever_subscribed
    ? LAPSED_COPY
    : MIGRATION_COPY;
  const isConfirming =
    checkoutPhase === "confirming" || checkoutPhase === "timeout";

  // A cold-cache render can open this modal while the subscription-status is
  // still unknown (see useComposerSubmit / useWorkflowModalActions — they let
  // the action proceed while unknown rather than trap the user). Once it
  // resolves paid, close the modal immediately: nothing else in the app ever
  // calls closeModal, so a Pro user who hit this race would otherwise be
  // stuck behind a non-dismissible modal forever.
  useEffect(() => {
    if (open && !isSubscriptionStatusUnknown && isPaid) {
      closeModal();
    }
  }, [open, isSubscriptionStatusUnknown, isPaid, closeModal]);

  // The impression, fired once per open rather than on every render. The
  // server already captures the 402 that opened it; what it cannot see is
  // whether the wall reached the screen, so this is the one client-only half.
  useEffect(() => {
    if (!open) return;
    trackEvent(ANALYTICS_EVENTS.PAYWALL_MODAL_VIEWED, {
      dismissible,
      has_checkout_url: Boolean(offer?.checkoutUrl),
      has_discount_code: Boolean(offer?.discountCode),
    });
  }, [open, dismissible, offer?.checkoutUrl, offer?.discountCode]);

  // Monthly Pro is the default paywall offer — same tier PricingCards leads
  // with, just without the billing-period tabs (this modal has one job).
  const proPlan = plans.find(
    (plan) => isProPlan(plan) && plan.duration === "monthly",
  );

  const handleSubscribe = () => {
    void openCheckoutOverlay("monthly", { source: "paywall_modal" });
  };

  return (
    <Modal
      isOpen={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) closeModal();
      }}
      isDismissable={dismissible}
      isKeyboardDismissDisabled={!dismissible}
      hideCloseButton={!dismissible}
      backdrop="blur"
      className="outline-none"
    >
      <ModalContent className="p-4">
        <ModalBody>
          <div className="mb-2 flex flex-col items-center gap-1.5 text-center">
            <h2 className="font-serif text-4xl font-normal tracking-tight">
              {copy.heading}
            </h2>
            <p className="text-sm font-light text-zinc-400">
              {offer?.message ?? copy.body}
            </p>
          </div>

          {offer?.discountCode && (
            <div className="flex items-center gap-2.5 rounded-2xl bg-success/10 px-4 py-2.5 text-success">
              <Tag01Icon width={18} height={18} aria-hidden />
              <p className="text-sm font-normal">
                Use code{" "}
                <span className="font-semibold">{offer.discountCode}</span> at
                checkout.
              </p>
            </div>
          )}

          {proPlan && (
            <div className="flex flex-col gap-3 rounded-2xl bg-zinc-800/50 p-5">
              <span className="text-lg font-semibold">{proPlan.name}</span>
              <div className="flex flex-col gap-2">
                {proPlan.features.map((feature) => (
                  <div
                    key={feature}
                    className="flex items-start gap-2 text-sm font-light"
                  >
                    <span className="mt-1.5 size-1 shrink-0 rounded-full bg-primary" />
                    <PlanFeature feature={feature} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {isConfirming ? (
            <CheckoutConfirming isLate={checkoutPhase === "timeout"} />
          ) : (
            <>
              <RaisedButton
                className="w-full text-black!"
                color="#00bbff"
                onClick={handleSubscribe}
                disabled={checkoutPhase !== "idle"}
              >
                {checkoutPhase === "idle"
                  ? "Subscribe to GAIA Pro"
                  : "Opening checkout..."}
              </RaisedButton>
              <p className="mt-2 text-center text-xs font-light text-zinc-500">
                {REFUND_WINDOW_COPY}
              </p>
            </>
          )}

          {!dismissible && (
            <Button
              variant="light"
              size="sm"
              className="mx-auto mt-1 h-auto min-w-0 p-0 text-xs text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300 data-[hover=true]:underline"
              onPress={() => logout()}
            >
              Log out
            </Button>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
