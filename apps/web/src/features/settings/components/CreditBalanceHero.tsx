"use client";

import { Button } from "@heroui/button";
import { Progress } from "@heroui/progress";
import { Skeleton } from "@heroui/skeleton";
import NumberFlow from "@number-flow/react";
import { useState } from "react";
import { useCreditBalance } from "../hooks/useUsage";
import { TopUpModal } from "./TopUpModal";
import { SettingsSection } from "./ui/SettingsSection";

function daysUntil(iso: string): number {
  return Math.max(
    0,
    Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000),
  );
}

export function CreditBalanceHero() {
  const { data, isLoading } = useCreditBalance();
  const [topUpOpen, setTopUpOpen] = useState(false);

  if (isLoading || !data) {
    return (
      <SettingsSection>
        <div className="px-5 py-6">
          <Skeleton className="h-9 w-40 rounded-lg" />
          <Skeleton className="mt-4 h-2 w-full rounded-full" />
        </div>
      </SettingsSection>
    );
  }

  const month = data.periods.month;
  const pct =
    month.limit > 0 ? Math.min(100, (month.used / month.limit) * 100) : 0;
  const color = pct >= 90 ? "danger" : pct >= 75 ? "warning" : "primary";
  const resetDays = daysUntil(month.reset_time);
  const canBuy = data.plan_type !== "free";

  return (
    <>
      <SettingsSection>
        <div className="px-5 py-5">
          <div className="flex items-baseline gap-2">
            <NumberFlow
              value={data.total_remaining}
              className="text-4xl font-semibold tracking-tight text-white"
            />
            <span className="text-sm text-zinc-500">credits left</span>
          </div>

          <Progress
            aria-label="Monthly credits used"
            value={pct}
            color={color}
            size="sm"
            className="mt-4"
          />
          <div className="mt-2 flex items-center justify-between text-xs text-zinc-500">
            <span>
              {month.used.toLocaleString()} / {month.limit.toLocaleString()}{" "}
              used this month
            </span>
            <span>
              Resets in {resetDays} day{resetDays === 1 ? "" : "s"}
            </span>
          </div>

          {data.topup_remaining > 0 ? (
            <div className="mt-4 flex items-center justify-between rounded-xl bg-zinc-800/60 px-3 py-2.5">
              <span className="flex items-baseline gap-1 text-sm text-zinc-300">
                <span className="text-zinc-500">Top-up balance:</span>
                <NumberFlow
                  value={data.topup_remaining}
                  className="font-medium text-white"
                />
              </span>
              {canBuy && (
                <Button
                  size="sm"
                  variant="flat"
                  color="primary"
                  onPress={() => setTopUpOpen(true)}
                >
                  Buy more
                </Button>
              )}
            </div>
          ) : (
            canBuy && (
              <Button
                size="sm"
                variant="flat"
                color="primary"
                className="mt-4 font-medium"
                onPress={() => setTopUpOpen(true)}
              >
                Buy credits
              </Button>
            )
          )}
        </div>
      </SettingsSection>
      <TopUpModal isOpen={topUpOpen} onClose={() => setTopUpOpen(false)} />
    </>
  );
}
