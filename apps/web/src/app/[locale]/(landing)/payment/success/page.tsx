"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  CircleArrowRight02Icon,
  RedoIcon,
} from "@icons";
import * as m from "motion/react-m";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { useUser } from "@/features/auth/hooks/useUser";
import { PaymentBackdrop } from "@/features/pricing/components/PaymentBackdrop";
import { PostPaymentReceipt } from "@/features/pricing/components/PostPaymentReceipt";
import { LAST_CHECKOUT_PRODUCT_KEY } from "@/features/pricing/constants";
import { useDodoPayments } from "@/features/pricing/hooks/useDodoPayments";
import { usePricing } from "@/features/pricing/hooks/usePricing";
import { useReceiptPrinterStage } from "@/features/pricing/hooks/useReceiptPrinterStage";
import { buildReceiptDetails } from "@/features/pricing/utils/receiptDetails";
import { verifyPaymentWithRetry } from "@/features/pricing/utils/verifyPaymentWithRetry";
import UseCreateConfetti from "@/hooks/ui/useCreateConfetti";

type PaymentStatus = "verifying" | "success" | "error";

export default function PaymentSuccessPage() {
  const router = useRouter();
  // Dodo appends the subscription id to the return URL. It is a hint the
  // server verifies against Dodo before trusting, and it lets verification
  // recover a paid user whose webhook never landed.
  const subscriptionId = useSearchParams().get("subscription_id") ?? undefined;
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
    // The charge is verified exactly once per page load. `hasVerified` is the
    // only guard, deliberately NOT paired with a cancel-on-cleanup flag: the
    // two together strand the page, because StrictMode's double-invoke (and
    // any re-render that hands `verifyPayment` a fresh identity) cancels the
    // single in-flight run while the ref short-circuits the replacement, so
    // nothing ever calls `setStatus` and the spinner never ends.
    if (hasVerified.current) return;
    hasVerified.current = true;

    // The Dodo redirect can beat the webhook, so a single "not completed" is
    // not a failure: retry with growing delays while the printer shows
    // "Processing your order", and only then give up.
    verifyPaymentWithRetry(() => verifyPayment(subscriptionId))
      .then((result) => {
        if (result.payment_completed) {
          setStatus("success");
          return;
        }
        setStatus("error");
        setErrorMessage(
          "We haven't received your payment confirmation yet. You can try checking out again.",
        );
      })
      .catch((error: unknown) => {
        console.error("Payment verification failed:", error);
        setStatus("error");
        setErrorMessage(
          "We couldn't verify your payment. Please try checking out again.",
        );
      });
  }, [verifyPayment, subscriptionId]);

  // Celebrate an active subscription — confetti fires as the receipt starts
  // printing.
  useEffect(() => {
    if (status !== "success") return;
    const interval = UseCreateConfetti(3500);
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [status]);

  // Restart checkout for the plan the user last tried. Mid-onboarding the
  // checkout lives in the wizard, so that is where a retry goes; otherwise
  // fall back to pricing.
  const handleTryAgain = () => {
    if (continueDestination === "/onboarding") {
      router.push("/onboarding");
      return;
    }
    const productId = localStorage.getItem(LAST_CHECKOUT_PRODUCT_KEY);
    if (productId)
      createSubscriptionAndRedirect(productId, { source: "payment_retry" });
    else router.push("/pricing");
  };

  const previewPlan = plans.find(
    (plan) => plan.dodo_product_id === lastProductId,
  );
  const receipt = buildReceiptDetails(subscriptionStatus, previewPlan);

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4 pt-24 pb-16">
      <PaymentBackdrop />

      {status !== "error" && (
        <div className="relative z-10 mt-8 w-full max-w-sm">
          <div className="rounded-3xl bg-zinc-900/60 p-8 text-center backdrop-blur-2xl">
            {status === "verifying" ? (
              <>
                <Spinner size="lg" className="mb-5" />
                <h1 className="mb-2 text-xl font-semibold text-white">
                  Verifying payment
                </h1>
                <p className="text-balance text-sm font-light text-zinc-400">
                  Hang tight while we confirm your payment with Dodo.
                </p>
              </>
            ) : (
              <>
                <CheckmarkCircle02Icon className="mx-auto mb-5 size-16 text-primary" />
                <h1 className="mb-2 text-2xl font-semibold text-white">
                  Welcome to GAIA
                </h1>
                <p className="mb-6 text-balance text-sm font-light text-zinc-400">
                  You're all set. Everything is unlocked. Let's get to work.
                </p>
                <RaisedButton
                  color="#00bbff"
                  className="w-full text-black!"
                  onClick={() => router.push(continueDestination)}
                >
                  Continue to chat
                  <CircleArrowRight02Icon className="size-4" />
                </RaisedButton>
              </>
            )}
          </div>
          {status === "success" && (
            <m.div
              animate={{ opacity: 1, transform: "translateY(0px)" }}
              className="mt-6"
              initial={{ opacity: 0, transform: "translateY(8px)" }}
              transition={{ duration: 0.32, ease: [0.23, 1, 0.32, 1] }}
            >
              <PostPaymentReceipt
                billingPeriod={receipt.billingPeriod}
                amount={receipt.amount}
                currency={receipt.currency}
                nextBillingDate={receipt.nextBillingDate}
                planName={receipt.planName}
                purchasedAt={receipt.purchasedAt}
                customerEmail={user.email || undefined}
                quantity={receipt.quantity}
                stage={printerStage}
                subscriptionRef={receipt.subscriptionRef}
              />
            </m.div>
          )}
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
