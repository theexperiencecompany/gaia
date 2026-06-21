"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  CircleArrowRight02Icon,
  RedoIcon,
} from "@icons";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { useUser } from "@/features/auth/hooks/useUser";
import { PaymentBackdrop } from "@/features/pricing/components/PaymentBackdrop";
import { LAST_CHECKOUT_PRODUCT_KEY } from "@/features/pricing/constants";
import { useDodoPayments } from "@/features/pricing/hooks/useDodoPayments";
import { usePricing } from "@/features/pricing/hooks/usePricing";
import UseCreateConfetti from "@/hooks/ui/useCreateConfetti";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

type PaymentStatus = "verifying" | "success" | "error";

export default function PaymentSuccessPage() {
  const router = useRouter();
  const { verifyPayment } = usePricing();
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
  const hasVerified = useRef(false);

  useEffect(() => {
    if (hasVerified.current) return;
    hasVerified.current = true;

    const run = async () => {
      try {
        const result = await verifyPayment();
        if (result.payment_completed) {
          trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_COMPLETED);
          setStatus("success");
        } else {
          setStatus("error");
          setErrorMessage(
            "Your payment hasn't completed yet. You can try checking out again.",
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

  // Celebrate an active subscription.
  useEffect(() => {
    if (status === "success") UseCreateConfetti(3500);
  }, [status]);

  // Restart checkout for the plan the user last tried, falling back to pricing.
  const handleTryAgain = () => {
    const productId = localStorage.getItem(LAST_CHECKOUT_PRODUCT_KEY);
    if (productId) createSubscriptionAndRedirect(productId);
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
              You're all set. Every Pro feature is unlocked. Let's get to work.
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
