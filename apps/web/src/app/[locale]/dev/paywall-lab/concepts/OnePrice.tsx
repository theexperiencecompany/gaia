"use client";

import { SquareLock01Icon } from "@icons";
import { formatWholeOrCents } from "@/features/pricing/utils/money";
import {
  MONTHLY_PRICE_MINOR,
  type PaywallConceptProps,
  PRICE_CURRENCY,
} from "../labData";
import { CheckoutDock } from "./CheckoutDock";

/** The three questions replays show people leaving to answer, answered where they ask them. */
const STRAIGHT_ANSWERS = [
  {
    question: "Is there a free plan?",
    answer: "No. I'm paid by you, so I work for you.",
  },
  {
    question: "Can I stop?",
    answer: "Any time, from settings. No email, no call.",
  },
  {
    question: "Monthly or yearly?",
    answer: "Monthly. If I earn it, I'll offer you a year later.",
  },
];

/** Concept 3: one price, one button, no period toggle, the objections answered inline. */
export function OnePrice({ subject, onCheckout }: PaywallConceptProps) {
  const price = formatWholeOrCents(MONTHLY_PRICE_MINOR, PRICE_CURRENCY);
  const jobCount = subject.startingJobs.length;

  return (
    <div className="flex flex-1 flex-col gap-8 pt-4">
      <div>
        <p className="text-base text-zinc-400">
          {subject.firstName ? `${subject.firstName}, here's` : "Here's"} the
          whole deal.
        </p>
        <p className="mt-4 flex items-baseline gap-3">
          <span className="text-[5.5rem] leading-none font-semibold tracking-tight text-zinc-100 tabular-nums @max-md:text-7xl">
            {price}
          </span>
          <span className="text-lg text-zinc-400">a month</span>
        </p>
        <p className="mt-3 text-base text-zinc-300">
          Everything I do.{" "}
          {jobCount > 0
            ? `Your ${jobCount} starting ${jobCount === 1 ? "job runs" : "jobs run"} the minute you're in.`
            : "I start the minute you're in."}
        </p>
      </div>

      <dl className="space-y-4">
        {STRAIGHT_ANSWERS.map(({ question, answer }) => (
          <div key={question}>
            <dt className="text-sm font-medium text-zinc-200">{question}</dt>
            <dd className="text-sm text-zinc-500">{answer}</dd>
          </div>
        ))}
      </dl>

      <CheckoutDock
        label={`Hire GAIA for ${price}`}
        onPress={() => onCheckout("monthly")}
      >
        <p className="flex items-center gap-1.5 text-[13px] text-zinc-500">
          <SquareLock01Icon className="h-3.5 w-3.5" />
          Secure checkout, cancel any time
        </p>
      </CheckoutDock>
    </div>
  );
}
