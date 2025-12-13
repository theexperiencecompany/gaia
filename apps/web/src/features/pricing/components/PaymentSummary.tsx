"use client";

import { Card, CardBody, CardHeader } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Skeleton } from "@heroui/skeleton";

import { useUserSubscriptionStatus } from "../hooks/usePricing";
import {
  convertToUSDCents,
  formatUSDFromCents,
} from "../utils/currencyConverter";

export function PaymentSummary() {
  const {
    data: subscriptionStatus,
    isLoading,
    error,
  } = useUserSubscriptionStatus();

  if (isLoading) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardBody className="space-y-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-28" />
        </CardBody>
      </Card>
    );
  }

  // Handle error state
  if (error) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <h3 className="text-lg font-semibold">Subscription Status</h3>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-default-600">
            Unable to load subscription information. Please try refreshing the
            page.
          </p>
        </CardBody>
      </Card>
    );
  }

  // Handle no subscription or no current plan
  if (!subscriptionStatus || !subscriptionStatus.current_plan) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <h3 className="text-lg font-semibold">No Active Subscription</h3>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-default-600">
            You currently don't have an active subscription. Choose a plan above
            to get started.
          </p>
          {subscriptionStatus?.subscription && (
            <div className="mt-2 text-xs text-default-500">
              <p>
                Subscription Status: {subscriptionStatus.subscription.status}
              </p>
            </div>
          )}
        </CardBody>
      </Card>
    );
  }

  const plan = subscriptionStatus.current_plan;

  // Convert to USD and format
  const priceInUSDCents = convertToUSDCents(plan.amount, plan.currency);
  const priceFormatted = formatUSDFromCents(priceInUSDCents);

  const isYearly = plan.duration === "yearly";
  const monthlyEquivalent = isYearly
    ? Math.round(priceInUSDCents / 12)
    : priceInUSDCents;
  const monthlyFormatted = formatUSDFromCents(monthlyEquivalent);

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="flex flex-row items-center justify-between">
        <h3 className="text-lg font-semibold">Current Subscription</h3>
        <Chip
          color={subscriptionStatus.is_subscribed ? "success" : "warning"}
          variant="flat"
          size="sm"
        >
          {subscriptionStatus.is_subscribed ? "Active" : "Inactive"}
        </Chip>
      </CardHeader>
      <CardBody className="space-y-4">
        <div>
          <h4 className="text-lg font-medium">{plan.name}</h4>
          {plan.description && (
            <p className="text-sm text-default-600">{plan.description}</p>
          )}
        </div>

        <Divider />

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm">Price:</span>
            <span className="font-medium">{priceFormatted}</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-sm">Billing:</span>
            <span className="text-sm capitalize">{plan.duration}</span>
          </div>

          {isYearly && (
            <div className="flex items-center justify-between">
              <span className="text-sm">Monthly equivalent:</span>
              <span className="text-sm text-success">
                {monthlyFormatted}/month
              </span>
            </div>
          )}

          {subscriptionStatus.days_remaining !== null &&
            subscriptionStatus.days_remaining !== undefined && (
              <div className="flex items-center justify-between">
                <span className="text-sm">Days remaining:</span>
                <span className="text-sm">
                  {subscriptionStatus.days_remaining} days
                </span>
              </div>
            )}
        </div>
      </CardBody>
    </Card>
  );
}
