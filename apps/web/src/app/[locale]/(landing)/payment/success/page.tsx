"use client";

import { Button } from "@heroui/button";
import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  CircleArrowRight02Icon,
  RedoIcon,
} from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { useUser } from "@/features/auth/hooks/useUser";
import { PaymentBackdrop } from "@/features/pricing/components/PaymentBackdrop";
import { PostPaymentReceipt } from "@/features/pricing/components/PostPaymentReceipt";
import { LAST_CHECKOUT_PRODUCT_KEY } from "@/features/pricing/constants";
import { useDodoPayments } from "@/features/pricing/hooks/useDodoPayments";
import { usePricing } from "@/features/pricing/hooks/usePricing";
import { useReceiptPrinterStage } from "@/features/pricing/hooks/useReceiptPrinterStage";
import { verifyPaymentWithRetry } from "@/features/pricing/utils/verifyPaymentWithRetry";
import UseCreateConfetti from "@/hooks/ui/useCreateConfetti";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

type PaymentStatus = "verifying" | "success" | "error";

export default function PaymentSuccessPage() {
  const router = useRouter();
  const { plans, subscriptionStatus, verifyPayment } = usePricing();
  const { createSubscriptionAndRedirect, isLoading: isRestarting } =
    useDodoPayments();
  const user = useUser();

  // Send the user straight to onboarding when we already know it's incomplete,
  // so they don't land on /c and get bounced by the onboarding guard a couple
  // seconds later (once the user-info fetch resolves). Default to chat.
  const continueDestination =
    user.onboarding && !user.onboarding.completed ? "/onboarding" : "/c";

  const [status, setStatus] = useState<PaymentStatus>("verifying");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastProductId, setLastProductId] = useState<string | null>(null);
  const hasVerified = useRef(false);

  // The remembered checkout product is browser-only state; read it after mount
  // so the server-rendered pass doesn't touch localStorage.
  useEffect(() => {
    setLastProductId(localStorage.getItem(LAST_CHECKOUT_PRODUCT_KEY));
  }, []);

  const printerStage = useReceiptPrinterStage(status === "success");

  useEffect(() => {
    if (hasVerified.current) return;
    hasVerified.current = true;

    const run = async () => {
      try {
        // The Dodo redirect can beat the webhook, so a single "not
        // completed" is not a failure — retry with growing delays while the
        // printer shows "Processing your order", and only then give up.
        const result = await verifyPaymentWithRetry(() => verifyPayment());
        if (result.payment_completed) {
          trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_COMPLETED);
          setStatus("success");
        } else {
          setStatus("error");
          setErrorMessage(
            "We haven't received your payment confirmation yet. You can try checking out again.",
          );
        }
      } catch (error) {
        console.error("Payment verification failed:", error);
        setStatus("error");
        setErrorMessage(
          "We couldn't verify your payment. Please try checking out again.",
        );
      }
    };
    run();
  }, [verifyPayment]);

  // Celebrate an active subscription — confetti fires as the receipt starts
  // printing.
  useEffect(() => {
    if (status === "success") UseCreateConfetti(3500);
  }, [status]);

  // Restart checkout for the plan the user last tried, falling back to pricing.
  const handleTryAgain = () => {
    const productId = localStorage.getItem(LAST_CHECKOUT_PRODUCT_KEY);
    if (productId) createSubscriptionAndRedirect(productId);
    else router.push("/pricing");
  };

  // Receipt details: the webhook-verified subscription record is the source of
  // truth — every printed row comes from this one endpoint, so the reference
  // can never describe a different subscription than the plan/amount next to
  // it. While verifying we preview the plan from the remembered checkout click.
  const previewPlan =
    plans.find((plan) => plan.dodo_product_id === lastProductId) ?? undefined;
  const activePlan = subscriptionStatus?.current_plan;
  const subscription = subscriptionStatus?.subscription;
  const isSubscribed = subscriptionStatus?.is_subscribed === true;

  const receipt = {
    planName:
      (isSubscribed ? activePlan?.name : undefined) ?? previewPlan?.name,
    amount:
      (isSubscribed
        ? (subscription?.recurring_pre_tax_amount ?? activePlan?.amount)
        : previewPlan?.amount) ?? null,
    currency:
      (isSubscribed
        ? (subscription?.currency ?? activePlan?.currency)
        : previewPlan?.currency) ?? undefined,
    billingPeriod:
      (isSubscribed ? activePlan?.duration : undefined) ??
      previewPlan?.duration,
    nextBillingDate: isSubscribed
      ? (subscription?.next_billing_date ?? null)
      : null,
    subscriptionRef: isSubscribed
      ? (subscription?.dodo_subscription_id ?? null)
      : null,
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4 pt-24 pb-16">
      <PaymentBackdrop />

      {status !== "error" && (
        <div className="relative z-10 w-full max-w-sm">
          <AnimatePresence>
            {printerStage === "complete" && (
              <m.div
                animate={{ height: "auto", opacity: 1 }}
                className="overflow-hidden"
                exit={{ height: 0, opacity: 0 }}
                initial={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.32, ease: [0.23, 1, 0.32, 1] }}
              >
                <div className="mb-6 rounded-3xl bg-zinc-900/60 p-8 text-center backdrop-blur-2xl">
                  <CheckmarkCircle02Icon className="mx-auto mb-5 size-16 text-primary" />
                  <h1 className="mb-2 text-2xl font-semibold text-white">
                    Welcome to GAIA Pro!
                  </h1>
                  <p className="mb-6 text-balance text-sm font-light text-zinc-400">
                    You're all set. Every Pro feature is unlocked. Let's get to
                    work.
                  </p>
                  <RaisedButton
                    color="#00bbff"
                    className="w-full text-black!"
                    onClick={() => router.push(continueDestination)}
                  >
                    Continue to chat
                    <CircleArrowRight02Icon className="size-4" />
                  </RaisedButton>
                </div>
              </m.div>
            )}
          </AnimatePresence>
          <PostPaymentReceipt
            billingPeriod={receipt.billingPeriod}
            amount={receipt.amount}
            currency={receipt.currency}
            nextBillingDate={receipt.nextBillingDate}
            planName={receipt.planName}
            stage={printerStage}
            subscriptionRef={receipt.subscriptionRef}
          />
        </div>
      )}

      {status === "error" && (
        <div className="relative z-10 w-full max-w-md rounded-3xl bg-zinc-900/60 p-8 text-center backdrop-blur-2xl">
          <div className="mx-auto mb-5 flex size-16 items-center justify-center rounded-full bg-red-500/15">
            <Alert02Icon className="size-8 text-red-400" />
          </div>
          <h1 className="mb-2 text-2xl font-semibold text-white">
            Payment not completed
          </h1>
          <p className="mb-6 text-balance text-sm font-light text-zinc-400">
            {errorMessage ?? "Something went wrong with your payment."}
          </p>
          <div className="flex flex-col gap-2">
            <RaisedButton
              color="#00bbff"
              className="w-full text-black!"
              onClick={handleTryAgain}
              disabled={isRestarting}
            >
              {isRestarting ? "Starting checkout" : "Try again"}
              {!isRestarting && <RedoIcon className="size-4" />}
            </RaisedButton>
            <Button
              variant="flat"
              className="w-full rounded-xl"
              onPress={() => router.push("/pricing")}
            >
              Back to pricing
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
