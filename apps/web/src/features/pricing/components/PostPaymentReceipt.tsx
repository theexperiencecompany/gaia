"use client";

import { CircleArrowRight02Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { RaisedButton } from "@/components/ui/raised-button";
import { ReceiptPrinter } from "@/features/pricing/components/ReceiptPrinter";
import type { ReceiptPrinterStage } from "@/features/pricing/components/receipt-printer.types";
import { CENTS_PER_DOLLAR } from "@/features/pricing/constants";

const easeOut = [0.23, 1, 0.32, 1] as const;

type PostPaymentReceiptProps = {
  /** Current printer stage, driven by useReceiptPrinterStage. */
  stage: ReceiptPrinterStage;
  /** Purchased plan name (e.g. "GAIA Pro"). */
  planName?: string;
  /** Recurring price in minor units (cents), as charged by Dodo. */
  amount?: number | null;
  /** ISO currency code of `amount` (e.g. "USD"). */
  currency?: string;
  /** Billing cycle of the purchased plan ("monthly" | "yearly"). */
  billingPeriod?: string;
  /** ISO date of the next charge, straight from the subscription record. */
  nextBillingDate?: string | null;
  /** Dodo subscription id printed under the barcode. */
  subscriptionRef?: string | null;
  onContinue: () => void;
};

/** Formats minor-unit money with the currency it was actually charged in. */
function formatMoney(amount: number, currency?: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || "USD",
    currencyDisplay: "narrowSymbol",
  }).format(amount / CENTS_PER_DOLLAR);
}

function formatDate(dateString?: string | null): string | null {
  if (!dateString) return null;
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return null;
  // Billing dates can arrive as date-only strings ("2027-08-22"), which JS
  // parses as UTC midnight — format in UTC so the calendar date never shifts
  // a day in UTC-negative timezones.
  return date.toLocaleDateString("en-US", {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function billingPeriodLabel(billingPeriod?: string): string {
  if (billingPeriod === "yearly") return "Annual subscription";
  if (billingPeriod === "monthly") return "Monthly subscription";
  return "Subscription";
}

/**
 * Deterministic pseudo-barcode bar widths (1-3px) derived from the
 * subscription reference, so every checkout prints a distinct pattern.
 */
function barcodeBars(seed: string): Array<{ width: number; barKey: string }> {
  const chars = seed.replace(/[^a-zA-Z0-9]/g, "") || "GAIA";
  return Array.from(chars, (ch, index) => ({
    width: ((ch.charCodeAt(0) * 7) % 3) + 1,
    barKey: `${index}-${ch}`,
  }));
}

/**
 * The GAIA-branded receipt printer shown after checkout: the machine screen
 * carries the plan summary and live status while the paper prints the
 * itemized receipt once the payment webhook has been verified.
 */
export function PostPaymentReceipt({
  stage,
  planName,
  amount,
  currency,
  billingPeriod,
  nextBillingDate,
  subscriptionRef,
  onContinue,
}: PostPaymentReceiptProps) {
  const displayName = planName ?? "GAIA Pro";
  const nextBilling = formatDate(nextBillingDate);
  const price = amount != null ? formatMoney(amount, currency) : null;
  const bars = barcodeBars(subscriptionRef ?? displayName);

  return (
    <div className="flex w-full flex-col items-center">
      <ReceiptPrinter.Root stage={stage}>
        <ReceiptPrinter.Machine>
          <ReceiptPrinter.Header>
            {/* The machine is always the dark charcoal unit, so the white
                lockup sits top-left in both themes. */}
            <Image
              alt="GAIA"
              className="block"
              height={30}
              priority
              src="/images/logos/text_w_logo_white.webp"
              style={{ height: 20, width: "auto" }}
              width={100}
            />
          </ReceiptPrinter.Header>

          <ReceiptPrinter.Screen>
            <div className="space-y-2.5">
              {/* Grouped dark surfaces on the LCD: plan block, then the total.
                  Tonal layering only (zinc-800 on zinc-900) — no borders. */}
              <div className="rounded-lg bg-zinc-800 px-3 py-2.5">
                <p className="text-sm font-semibold leading-snug text-zinc-100">
                  {displayName}
                </p>
                <p className="text-xs text-zinc-400">
                  {billingPeriodLabel(billingPeriod)}
                </p>
              </div>
              <div className="flex items-baseline justify-between rounded-lg bg-zinc-800 px-3 py-2.5">
                <span className="text-sm text-zinc-300">Total</span>
                {price && (
                  <strong className="font-bold text-lg tracking-tight text-zinc-50">
                    {price}
                  </strong>
                )}
              </div>
              <ReceiptPrinter.Status />
            </div>
          </ReceiptPrinter.Screen>
        </ReceiptPrinter.Machine>

        <ReceiptPrinter.Output>
          <ReceiptPrinter.Paper>
            <dl className="space-y-2.5">
              <div className="flex justify-between gap-4">
                <dt className="pt-0.5 text-sm">Total</dt>
                <dd className="text-right font-bold text-xl tracking-tight">
                  {price}
                </dd>
              </div>
              <div className="flex justify-between gap-4 text-xs">
                <dt className="opacity-60">{displayName}</dt>
                <dd className="text-right font-medium">
                  {billingPeriodLabel(billingPeriod)}
                </dd>
              </div>
              {nextBilling && (
                <div className="flex justify-between gap-4 text-xs">
                  <dt className="opacity-60">Next billing</dt>
                  <dd className="text-right font-medium">{nextBilling}</dd>
                </div>
              )}
            </dl>
            <hr />
            <p className="mt-8 text-xs leading-relaxed opacity-70">
              Thanks for subscribing to {displayName}. Every Pro feature is now
              unlocked — welcome aboard.
            </p>
            {subscriptionRef && (
              <div
                aria-hidden="true"
                className="mt-5 flex h-12 items-stretch justify-center gap-[2px]"
              >
                {bars.map((bar) => (
                  <span
                    className="bg-zinc-950"
                    key={bar.barKey}
                    style={{ width: bar.width }}
                  />
                ))}
              </div>
            )}
          </ReceiptPrinter.Paper>
        </ReceiptPrinter.Output>
      </ReceiptPrinter.Root>

      <AnimatePresence>
        {stage === "complete" && (
          <m.div
            animate={{ opacity: 1, transform: "translateY(0px)" }}
            aria-hidden={false}
            className="w-full max-w-[21rem]"
            exit={{ opacity: 0 }}
            initial={{ opacity: 0, transform: "translateY(8px)" }}
            transition={{ duration: 0.24, ease: easeOut }}
          >
            <RaisedButton
              className="mt-6 w-full text-black!"
              color="#00bbff"
              onClick={onContinue}
            >
              Continue to chat
              <CircleArrowRight02Icon className="size-4" />
            </RaisedButton>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
