"use client";

import { Button } from "@heroui/button";
import { Divider } from "@heroui/divider";
import type { ReactNode } from "react";
import { formatWholeOrCents } from "@/features/pricing/utils/money";
import {
  MONTHLY_PRICE_MINOR,
  type PaywallConceptProps,
  type PaywallSubject,
  PRICE_CURRENCY,
  YEARLY_PRICE_MINOR,
} from "../labData";
import { NEED_COPY } from "../needCopy";
import { CheckoutDock } from "./CheckoutDock";

const MAX_DUTIES = 3;

/** The letter's duties: the drafted jobs when they exist, else the picked needs in GAIA's words. */
function dutiesFor(subject: PaywallSubject): string[] {
  const duties = subject.startingJobs.length
    ? subject.startingJobs.map((job) => job.description)
    : subject.needs.map((need) => NEED_COPY[need].duty);
  return duties.slice(0, MAX_DUTIES);
}

interface TermProps {
  label: string;
  children: ReactNode;
}

function Term({ label, children }: TermProps) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3 @max-md:grid-cols-1 @max-md:gap-0.5">
      <dt className="text-[13px] text-zinc-500">{label}</dt>
      <dd className="text-sm leading-relaxed text-zinc-800">{children}</dd>
    </div>
  );
}

/** Concept 2: the paywall is an offer letter; paying is signing it. */
export function OfferLetter({ subject, onCheckout }: PaywallConceptProps) {
  const employer = subject.firstName ?? "you";
  const today = new Date().toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });

  return (
    <div className="flex flex-1 flex-col gap-5">
      <article className="rounded-2xl bg-zinc-100 px-7 py-6 text-zinc-900 @max-md:px-5 @max-md:py-6">
        <p className="text-[13px] text-zinc-500">{today}</p>
        <h2 className="mt-3 font-serif text-3xl font-normal text-zinc-900">
          An offer, for {employer}
        </h2>
        <p className="mt-3 max-w-[60ch] text-sm leading-relaxed text-zinc-700">
          You told me what's eating your week. Here's the job as I understand
          it. If it reads right, sign and I start today.
        </p>

        <dl className="mt-5 space-y-2.5">
          <Term label="Role">Chief of staff to {employer}</Term>
          <Term label="Duties">
            <ul className="space-y-1.5">
              {dutiesFor(subject).map((duty) => (
                <li key={duty}>{duty}</li>
              ))}
            </ul>
          </Term>
          <Term label="Hours">Every hour, including the ones you sleep</Term>
          <Term label="Pay">
            {formatWholeOrCents(MONTHLY_PRICE_MINOR, PRICE_CURRENCY)} a month.
            About a dollar a day.
          </Term>
          <Term label="Notice">
            None. Let me go any time from settings, two taps.
          </Term>
        </dl>

        <Divider className="my-5 bg-zinc-300" />

        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="font-serif text-2xl text-zinc-900 italic">GAIA</p>
            <p className="text-[13px] text-zinc-500">
              Signed, waiting on yours
            </p>
          </div>
        </div>
      </article>

      <CheckoutDock
        label="Sign and hire GAIA"
        onPress={() => onCheckout("monthly")}
      >
        <Button
          size="sm"
          variant="light"
          className="text-zinc-500"
          onPress={() => onCheckout("yearly")}
        >
          Sign for a year instead,{" "}
          {formatWholeOrCents(YEARLY_PRICE_MINOR, PRICE_CURRENCY)}
        </Button>
      </CheckoutDock>
    </div>
  );
}
