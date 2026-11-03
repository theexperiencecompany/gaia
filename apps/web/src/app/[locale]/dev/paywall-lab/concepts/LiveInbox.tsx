"use client";

import { Chip } from "@heroui/chip";
import * as m from "motion/react-m";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import type { PaywallConceptProps } from "../labData";
import { ConnectGate } from "./ConnectGate";
import { MONTHLY_PRICE_LABEL, PriceDock } from "./PriceDock";
import { RunProgress } from "./RunProgress";
import { SkippedPrice } from "./SkippedPrice";
import { useStagedRun } from "./useStagedRun";
import { ValueHeadline } from "./ValueHeadline";

const RUN_MS = 4500;
const KEEP_LABEL = "Keep this every morning";

/** Concept 1: a read-only Gmail connect, a live triage of their own inbox, then the price. */
export function LiveInbox({ mock, onCheckout }: PaywallConceptProps) {
  const { inbox } = mock;
  const { stage, progress, start, skip } = useStagedRun(RUN_MS);
  const [first, ...rest] = inbox.needYou;

  if (stage === "connect")
    return (
      <ConnectGate
        logoSrc="/images/icons/gmail.webp"
        logoAlt="Gmail"
        headline="Let me show you on your own inbox."
        line="Connect Gmail and I'll go through your last 100 emails right now, while you watch."
        connectLabel="Connect Gmail"
        scopeNote="Read-only. I can't send, delete or archive anything."
        onConnect={start}
        onSkip={skip}
      />
    );

  if (stage === "skipped")
    return (
      <SkippedPrice
        headline="Your inbox, handled before you're up."
        line="Every morning I read it, drop the noise and draft the replies that need you."
        keepLabel={KEEP_LABEL}
        onCheckout={onCheckout}
      />
    );

  if (stage === "working")
    return (
      <RunProgress
        label="Reading your inbox"
        items={inbox.needYou.map((email) => email.from)}
        total={inbox.scanned}
        unit="emails"
        progress={progress}
      />
    );

  return (
    <m.div className="flex flex-1 flex-col gap-6" {...MOTION_FADE_UP}>
      <ValueHeadline
        headline={`${inbox.needYou.length} emails need you today. The replies are already drafted.`}
        line={`I read ${inbox.scanned}. ${inbox.noise} were noise, the rest can wait. Every morning, this is done before you're up.`}
      />

      <ol className="flex flex-col gap-2">
        {first && (
          <li className="rounded-2xl bg-zinc-800 p-4">
            <p className="text-sm font-medium text-zinc-100">{first.from}</p>
            <p className="text-[13px] text-zinc-500">{first.subject}</p>
            <p className="mt-2 text-sm text-zinc-300">{first.why}</p>
            <div className="mt-3 rounded-xl bg-zinc-900 p-3">
              <p className="text-[13px] text-zinc-500">
                My draft, waiting for your ok
              </p>
              <p className="mt-1 text-sm leading-relaxed text-zinc-200">
                {first.draft}
              </p>
            </div>
          </li>
        )}
        {rest.map((email) => (
          <li
            key={email.subject}
            className="flex items-start justify-between gap-3 rounded-2xl bg-zinc-800 p-4"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-zinc-100">
                {email.from}
              </p>
              <p className="mt-0.5 line-clamp-2 text-sm text-zinc-400">
                {email.why}
              </p>
            </div>
            <Chip size="sm" variant="flat" className="shrink-0">
              Handled
            </Chip>
          </li>
        ))}
      </ol>

      <p className="text-[13px] text-zinc-500">
        That's one morning. {MONTHLY_PRICE_LABEL} a month is every morning.
      </p>
      <PriceDock keepLabel={KEEP_LABEL} onCheckout={onCheckout} />
    </m.div>
  );
}
