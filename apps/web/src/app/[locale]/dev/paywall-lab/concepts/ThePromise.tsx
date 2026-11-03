"use client";

import { CheckmarkCircle02Icon } from "@icons";
import { OnboardingBotBubble } from "@/features/onboarding/components/OnboardingBotBubble";
import { formatWholeOrCents } from "@/features/pricing/utils/money";
import {
  MONTHLY_PRICE_MINOR,
  type PaywallConceptProps,
  PRICE_CURRENCY,
} from "../labData";
import { NEED_COPY } from "../needCopy";
import { CheckoutDock } from "./CheckoutDock";

const PROMISE_DAYS = 7;
const MAX_PROMISES = 3;
const DAY_MS = 24 * 60 * 60 * 1000;

function promiseDeadline(): string {
  return new Date(Date.now() + PROMISE_DAYS * DAY_MS).toLocaleDateString(
    "en-US",
    { weekday: "long", month: "short", day: "numeric" },
  );
}

/** Concept 4: a checkable week-one promise with the whole month refunded if GAIA misses. */
export function ThePromise({ subject, onCheckout }: PaywallConceptProps) {
  const price = formatWholeOrCents(MONTHLY_PRICE_MINOR, PRICE_CURRENCY);
  const promises = subject.needs
    .map((need) => NEED_COPY[need].promise)
    .slice(0, MAX_PROMISES);
  const timeline = [
    { when: "Today", what: `You pay ${price}` },
    { when: "This week", what: "I do the work" },
    { when: `Day ${PROMISE_DAYS}`, what: "You keep me, or get it back" },
  ];

  return (
    <div className="flex flex-1 flex-col gap-5">
      <OnboardingBotBubble text="I'd rather make you a promise than a pitch." />

      <div className="rounded-2xl bg-zinc-800 p-4">
        <p className="text-base font-semibold text-zinc-100">
          By {promiseDeadline()}
        </p>
        <ul className="mt-3 space-y-2 rounded-xl bg-zinc-900 p-3">
          {promises.map((promise) => (
            <li key={promise} className="flex items-start gap-3">
              <CheckmarkCircle02Icon className="mt-0.5 h-5 w-5 shrink-0 text-zinc-500" />
              <span className="text-sm text-zinc-200">{promise}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm leading-relaxed text-zinc-300">
          If I miss any of it, text me "refund". All {price} back, no form, no
          call.
        </p>
      </div>

      <ol className="grid grid-cols-3 gap-3 @max-md:grid-cols-1 @max-md:gap-2">
        {timeline.map(({ when, what }) => (
          <li
            key={when}
            className="rounded-2xl bg-zinc-900/60 p-3 @max-md:flex @max-md:items-baseline @max-md:gap-3"
          >
            <p className="text-[13px] text-zinc-500 @max-md:w-20 @max-md:shrink-0">
              {when}
            </p>
            <p className="text-sm text-zinc-200">{what}</p>
          </li>
        ))}
      </ol>

      <CheckoutDock
        label={`Hold me to it, ${price}/month`}
        onPress={() => onCheckout("monthly")}
      >
        <p className="text-[13px] text-zinc-500">
          The promise covers your first month. Monthly only.
        </p>
      </CheckoutDock>
    </div>
  );
}
