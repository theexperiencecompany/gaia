"use client";

import Image from "next/image";
import { ReceiptPrinter } from "@/features/pricing/components/ReceiptPrinter";
import type { ReceiptPrinterStage } from "@/features/pricing/components/receipt-printer.types";
import { CENTS_PER_DOLLAR } from "@/features/pricing/constants";

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
  /** ISO date the charge was taken, from the subscription record. */
  purchasedAt?: string | null;
  /** Email the subscription is billed to. */
  customerEmail?: string;
  /** Seats purchased, from the subscription record. */
  quantity?: number;
};

/** Formats minor-unit money with the currency it was actually charged in. */
function formatMoney(amount: number, currency?: string): string {
  // The currency arrives from webhook data; a malformed code makes Intl throw
  // (RangeError), which must never take down the payment screen — degrade to
  // "amount CURRENCY" instead.
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
      currencyDisplay: "narrowSymbol",
    }).format(amount / CENTS_PER_DOLLAR);
  } catch {
    return `${amount / CENTS_PER_DOLLAR} ${currency || "USD"}`;
  }
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

function billingCycleLabel(billingPeriod?: string): string | null {
  if (billingPeriod === "yearly") return "Annual";
  if (billingPeriod === "monthly") return "Monthly";
  return null;
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
  purchasedAt,
  customerEmail,
  quantity = 1,
}: PostPaymentReceiptProps) {
  const displayName = planName ?? "GAIA Pro";
  const nextBilling = formatDate(nextBillingDate);
  const purchased = formatDate(purchasedAt);
  const cycle = billingCycleLabel(billingPeriod);
  const price = amount != null ? formatMoney(amount, currency) : null;
  const lineTotal =
    amount != null ? formatMoney(amount * quantity, currency) : null;
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
            <div className="space-y-4">
              <div>
                <p className="text-sm font-semibold leading-snug text-zinc-100">
                  {displayName}
                </p>
                <p className="text-xs text-zinc-400">
                  {billingPeriodLabel(billingPeriod)}
                </p>
              </div>
              {price && (
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-zinc-300">Total</span>
                  <strong className="text-base tracking-tight text-zinc-50">
                    {price}
                  </strong>
                </div>
              )}
              <ReceiptPrinter.Status />
            </div>
          </ReceiptPrinter.Screen>
        </ReceiptPrinter.Machine>

        <ReceiptPrinter.Output>
          <ReceiptPrinter.Paper>
            <div className="flex items-baseline justify-between gap-4 text-xs">
              <span className="font-semibold tracking-[0.2em]">RECEIPT</span>
              {purchased && <span className="opacity-60">{purchased}</span>}
            </div>
            {customerEmail && (
              <p className="mt-1 truncate text-xs opacity-60">
                {customerEmail}
              </p>
            )}
            <hr className="my-3 border-dashed border-zinc-300" />
            <dl className="space-y-2">
              <div className="flex justify-between gap-4 text-xs">
                <dt className="min-w-0">
                  <span className="font-medium">{displayName}</span>
                  {cycle && <span className="opacity-60"> ({cycle})</span>}
                  {quantity > 1 && (
                    <span className="opacity-60"> x{quantity}</span>
                  )}
                </dt>
                <dd className="shrink-0 text-right font-medium">{price}</dd>
              </div>
            </dl>
            <hr className="my-3 border-dashed border-zinc-300" />
            <dl className="space-y-2">
              <div className="flex justify-between gap-4">
                <dt className="pt-0.5 text-sm">Total</dt>
                <dd className="text-right text-lg tracking-tight">
                  {lineTotal}
                </dd>
              </div>
              <div className="flex justify-between gap-4 text-xs">
                <dt className="opacity-60">Billing</dt>
                <dd className="text-right font-medium">
                  {billingPeriodLabel(billingPeriod)}
                </dd>
              </div>
              {nextBilling && (
                <div className="flex justify-between gap-4 text-xs">
                  <dt className="opacity-60">Next charge</dt>
                  <dd className="text-right font-medium">{nextBilling}</dd>
                </div>
              )}
              <div className="flex justify-between gap-4 text-xs">
                <dt className="opacity-60">Status</dt>
                <dd className="text-right font-medium">Active</dd>
              </div>
              {subscriptionRef && (
                <div className="flex justify-between gap-4 text-xs">
                  <dt className="opacity-60">Ref</dt>
                  <dd className="min-w-0 break-all text-right font-medium">
                    {subscriptionRef}
                  </dd>
                </div>
              )}
            </dl>
            <hr className="my-3 border-dashed border-zinc-300" />
            <p className="text-xs leading-relaxed opacity-70">
              Thanks for subscribing to {displayName}. Everything is unlocked.
              Welcome aboard.
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
    </div>
  );
}
