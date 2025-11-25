"use client";

import { useEffect, useState } from "react";

import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { CheckmarkCircle02Icon, CreditCardIcon, Timer02Icon } from "@/icons";

export function SubscriptionActivationBanner() {
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const [showBanner, setShowBanner] = useState(false);
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  useEffect(() => {
    // Only show banner for subscriptions that are created but payment is being processed
    // Don't show for cancelled or failed payments
    const subscription = subscriptionStatus?.subscription;
    const shouldShow =
      subscription &&
      subscription.status === "created" &&
      !subscriptionStatus.is_subscribed &&
      // Only show if subscription was created recently (within last hour)
      subscription.created_at &&
      new Date(subscription.created_at).getTime() > Date.now() - 3600000;

    if (shouldShow && lastChecked !== subscription?.id) {
      setShowBanner(true);
      setLastChecked(subscription?.id || null);
    } else if (!shouldShow) {
      setShowBanner(false);
    }
  }, [subscriptionStatus, lastChecked]);

  useEffect(() => {
    // Auto-hide banner when subscription becomes active
    if (
      subscriptionStatus?.is_subscribed &&
      subscriptionStatus?.subscription?.status === "active"
    ) {
      setShowBanner(false);
    }
  }, [
    subscriptionStatus?.is_subscribed,
    subscriptionStatus?.subscription?.status,
  ]);

  if (!showBanner) return null;

  return (
    <div className="fixed top-4 right-4 z-50 max-w-sm">
      <div className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-4 shadow-lg backdrop-blur-sm">
        <div className="flex items-start space-x-3">
          <div className="flex-shrink-0">
            <div className="relative">
              <Timer02Icon className="h-5 w-5 text-blue-400" />
              <div className="absolute -top-1 -right-1">
                <div className="h-2 w-2 animate-pulse rounded-full bg-blue-400"></div>
              </div>
            </div>
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="text-sm font-medium text-blue-300">
              Activating Subscription
            </h4>
            <p className="mt-1 text-xs text-blue-200">
              Your payment was successful. We're setting up your Pro
              subscription now.
            </p>
            <div className="mt-2 flex items-center space-x-2">
              <CreditCardIcon className="h-3 w-3 text-blue-400" />
              <span className="text-xs text-blue-300">
                Usually takes 10-30 seconds
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function SubscriptionSuccessBanner() {
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const [showSuccess, setShowSuccess] = useState(false);
  const [hasShownSuccess, setHasShownSuccess] = useState(false);

  useEffect(() => {
    // Show success banner when subscription becomes active for the first time in this session
    if (
      subscriptionStatus?.is_subscribed &&
      subscriptionStatus?.subscription?.status === "active" &&
      !hasShownSuccess
    ) {
      setShowSuccess(true);
      setHasShownSuccess(true);

      // Auto-hide after 5 seconds
      setTimeout(() => {
        setShowSuccess(false);
      }, 5000);
    }
  }, [
    subscriptionStatus?.is_subscribed,
    subscriptionStatus?.subscription?.status,
    hasShownSuccess,
  ]);

  if (!showSuccess) return null;

  return (
    <div className="fixed top-4 right-4 z-50 max-w-sm">
      <div className="rounded-lg border border-green-500/20 bg-green-500/10 p-4 shadow-lg backdrop-blur-sm">
        <div className="flex items-start space-x-3">
          <div className="flex-shrink-0">
            <CheckmarkCircle02Icon className="h-5 w-5 text-green-400" />
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="text-sm font-medium text-green-300">
              🎉 Welcome to GAIA Pro!
            </h4>
            <p className="mt-1 text-xs text-green-200">
              Your subscription is now active. Enjoy unlimited features!
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSuccess(false)}
            className="text-xs text-green-400 hover:text-green-300"
          >
            ×
          </button>
        </div>
      </div>
    </div>
  );
}
