"use client";

import { CircleArrowRight02Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { RaisedButton } from "@/components/ui/raised-button";
import {
  ReceiptPrinter,
  type ReceiptPrinterStage,
} from "@/features/pricing/components/ReceiptPrinter";
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
  /** Dodo subscription id printed as the receipt reference. */
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
  return date.toLocaleDateString("en-US", {
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

  const receiptRows: Array<{ term: string; detail: string }> = [
    { term: "Plan", detail: displayName },
    { term: "Billing", detail: billingPeriodLabel(billingPeriod) },
    ...(amount != null
      ? [{ term: "Amount paid", detail: formatMoney(amount, currency) }]
      : []),
    ...(nextBilling ? [{ term: "Next billing", detail: nextBilling }] : []),
    ...(subscriptionRef
      ? [{ term: "Reference", detail: subscriptionRef }]
      : []),
  ];

  return (
    <div className="flex w-full flex-col items-center">
      <ReceiptPrinter.Root stage={stage}>
        <ReceiptPrinter.Machine>
          <ReceiptPrinter.Header>
            {/* The wordmark sits on the machine body: dark plastic in light
                mode takes the white lockup, the light body of dark mode takes
                the black one. */}
            <Image
              alt="GAIA"
              className="block dark:hidden"
              height={30}
              priority
              src="/images/logos/text_w_logo_white.webp"
              style={{ height: 20, width: "auto" }}
              width={100}
            />
            <Image
              alt=""
              aria-hidden="true"
              className="hidden dark:block"
              height={30}
              priority
              src="/images/logos/text_w_logo_black.webp"
              style={{ height: 20, width: "auto" }}
              width={100}
            />
          </ReceiptPrinter.Header>

          <ReceiptPrinter.Screen>
            <div className="space-y-4">
              <div className="flex justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">{displayName}</p>
                  <p className="text-xs opacity-60">
                    {billingPeriodLabel(billingPeriod)}
                  </p>
                </div>
                {amount != null && (
                  <strong className="text-sm">
                    {formatMoney(amount, currency)}
                  </strong>
                )}
              </div>
              <ReceiptPrinter.Status />
            </div>
          </ReceiptPrinter.Screen>
        </ReceiptPrinter.Machine>

        <ReceiptPrinter.Output>
          <ReceiptPrinter.Paper>
            <h2 className="font-serif text-lg font-bold tracking-wide uppercase">
              Receipt
            </h2>
            <hr className="my-4 border-zinc-950/15 dark:border-zinc-50/20" />
            <dl className="space-y-2.5 text-xs leading-none">
              {receiptRows.map((row) => (
                <div className="flex justify-between gap-4" key={row.term}>
                  <dt className="opacity-60">{row.term}</dt>
                  <dd className="text-right font-medium">{row.detail}</dd>
                </div>
              ))}
            </dl>
            <hr className="my-4 border-zinc-950/15 dark:border-zinc-50/20" />
            <p className="text-xs leading-relaxed opacity-70">
              Thanks for subscribing to GAIA Pro. Every Pro feature is now
              unlocked — welcome aboard.
            </p>
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
