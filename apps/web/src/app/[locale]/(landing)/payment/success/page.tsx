"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  CircleArrowRight02Icon,
  RedoIcon,
} from "@icons";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { useUser } from "@/features/auth/hooks/useUser";
import { PaymentBackdrop } from "@/features/pricing/components/PaymentBackdrop";
import { LAST_CHECKOUT_PRODUCT_KEY } from "@/features/pricing/constants";
import { useDodoPayments } from "@/features/pricing/hooks/useDodoPayments";
import { usePricing } from "@/features/pricing/hooks/usePricing";
import UseCreateConfetti from "@/hooks/ui/useCreateConfetti";

type PaymentStatus = "verifying" | "success" | "error";

export default function PaymentSuccessPage() {
  const router = useRouter();
  const { verifyPayment } = usePricing();
  const { createSubscriptionAndRedirect, isLoading: isRestarting } =
    useDodoPayments();
  const user = useUser();
  // Dodo appends the subscription it just activated. The server treats it as a
  // hint to reconcile against Dodo when no webhook ever landed, and verifies
  // ownership before acting on it.
  const subscriptionId = useSearchParams().get("subscription_id");

  // Off-page rails (Cashfree's bank mandate, for one) navigate the top-level
  // page away mid-onboarding, so this is where an unfinished flow is picked
  // back up: `/onboarding` rehydrates its persisted stage machine and the
  // payment stage — now seeing an active subscription — advances itself.
  // Read from the user record the onboarding guard already uses, never from a
  // URL parameter the client could forge.
  const isOnboardingIncomplete = Boolean(
    user.onboarding && !user.onboarding.completed,
  );
  const continueDestination = isOnboardingIncomplete ? "/onboarding" : "/c";

  const [status, setStatus] = useState<PaymentStatus>("verifying");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const hasVerified = useRef(false);

  // The charge is verified exactly once per page load — `hasVerified` is the
  // only guard, and it is deliberately NOT paired with a cancel-on-cleanup
  // flag. The two together strand the page: StrictMode's double-invoke (and
  // any re-render that hands `verifyPayment` a fresh identity) cancels the
  // single in-flight run while the ref short-circuits the replacement, so no
  // branch ever calls `setStatus` and the spinner never ends.
  useEffect(() => {
    if (hasVerified.current) return;
    hasVerified.current = true;

    verifyPayment(subscriptionId)
      .then((result) => {
        if (result.payment_completed) {
          setStatus("success");
          return;
        }
        setStatus("error");
        setErrorMessage(
          "Your payment hasn't completed yet. You can try checking out again.",
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

  // Celebrate an active subscription.
  useEffect(() => {
    if (status !== "success") return;
    const interval = UseCreateConfetti(3500);
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [status]);

  // Restart checkout for the plan the user last tried. A user who has not
  // finished onboarding pays inside the wizard, so send them back to it; a
  // wall-hit for anyone else restarts the same plan, or falls back to pricing.
  const handleTryAgain = () => {
    if (isOnboardingIncomplete) {
      router.push("/onboarding");
      return;
    }
    const productId = localStorage.getItem(LAST_CHECKOUT_PRODUCT_KEY);
    if (productId)
      createSubscriptionAndRedirect(productId, { source: "payment_retry" });
    else router.push("/pricing");
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4">
      <PaymentBackdrop />

      <div className="relative z-10 w-full max-w-md rounded-3xl bg-zinc-900/60 p-8 text-center backdrop-blur-2xl">
        {status === "verifying" && (
          <>
            <Spinner size="lg" className="mb-5" />
            <h1 className="mb-2 text-xl font-semibold text-white">
              Verifying payment
            </h1>
            <p className="text-balance text-sm font-light text-zinc-400">
              Hang tight while we confirm your payment with Dodo.
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <CheckmarkCircle02Icon className="mx-auto mb-5 size-16 text-primary" />
            <h1 className="mb-2 text-2xl font-semibold text-white">
              Welcome to GAIA Pro!
            </h1>
            <p className="mb-6 text-balance text-sm font-light text-zinc-400">
              You're on Pro. Everything is unlocked.
            </p>
            <RaisedButton
              color="#00bbff"
              className="w-full text-black!"
              onClick={() => router.push(continueDestination)}
            >
              {isOnboardingIncomplete
                ? "Finish setting up"
                : "Continue to chat"}
              <CircleArrowRight02Icon className="size-4" />
            </RaisedButton>
          </>
        )}

        {status === "error" && (
          <>
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
          </>
        )}
      </div>
    </div>
  );
}
