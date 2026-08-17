"use client";

import { Button } from "@heroui/button";
import { useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import type { Subscription } from "@/features/pricing/api/pricingApi";
import { pricingApi } from "@/features/pricing/api/pricingApi";
import { useConfirmation } from "@/hooks/useConfirmation";

interface CancelSubscriptionActionProps {
  subscription: Subscription;
  refetchStatus: () => Promise<unknown>;
}

export function CancelSubscriptionAction({
  subscription,
  refetchStatus,
}: CancelSubscriptionActionProps) {
  const { confirm, confirmationProps } = useConfirmation();
  const [isCancelling, setIsCancelling] = useState(false);

  const cancellationScheduled =
    subscription.cancel_at_next_billing_date === true;

  const performCancellation = async () => {
    setIsCancelling(true);
    try {
      await pricingApi.cancelSubscription();
      await refetchStatus();
    } finally {
      setIsCancelling(false);
    }
  };

  const handleCancelSubscription = async () => {
    const confirmed = await confirm({
      title: "Cancel subscription?",
      message:
        "You'll keep Pro access until the end of your current billing period, then your subscription won't renew. You can resubscribe anytime.",
      confirmText: "Cancel subscription",
      variant: "destructive",
    });
    if (!confirmed) return;
    await performCancellation();
  };

  return (
    <>
      {subscription.status === "active" && !cancellationScheduled && (
        <Button
          color="danger"
          variant="light"
          size="sm"
          className="w-full"
          isLoading={isCancelling}
          onPress={handleCancelSubscription}
        >
          Cancel subscription
        </Button>
      )}
      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}
