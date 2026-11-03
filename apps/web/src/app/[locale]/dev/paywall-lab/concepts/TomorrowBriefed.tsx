"use client";

import { Chip } from "@heroui/chip";
import * as m from "motion/react-m";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import type { PaywallConceptProps } from "../labData";
import { ConnectGate } from "./ConnectGate";
import { PriceDock } from "./PriceDock";
import { RunProgress } from "./RunProgress";
import { SkippedPrice } from "./SkippedPrice";
import { useStagedRun } from "./useStagedRun";
import { ValueHeadline } from "./ValueHeadline";

const RUN_MS = 4000;
const KEEP_LABEL = "Brief me every day";

/** Concept 2: a read-only calendar connect, then tomorrow's meetings each briefed, then the price. */
export function TomorrowBriefed({ mock, onCheckout }: PaywallConceptProps) {
  const { day } = mock;
  const { stage, progress, start, skip } = useStagedRun(RUN_MS);
  const flagged = day.meetings.find((meeting) => meeting.flag);

  if (stage === "connect")
    return (
      <ConnectGate
        logoSrc="/images/icons/googlecalendar.webp"
        logoAlt="Google Calendar"
        headline="Let me get you ready for tomorrow."
        line="Connect Google Calendar and I'll brief every meeting you have tomorrow, right now."
        connectLabel="Connect Google Calendar"
        scopeNote="Read-only. I can't create, move or decline anything."
        onConnect={start}
        onSkip={skip}
      />
    );

  if (stage === "skipped")
    return (
      <SkippedPrice
        headline="Walk into every meeting ready."
        line="Ten minutes before each one: who, why, what changed and what to ask."
        keepLabel={KEEP_LABEL}
        onCheckout={onCheckout}
      />
    );

  if (stage === "working")
    return (
      <RunProgress
        label="Preparing tomorrow"
        items={day.meetings.map((meeting) => meeting.title)}
        total={day.meetings.length}
        unit="meetings"
        progress={progress}
      />
    );

  return (
    <m.div className="flex flex-1 flex-col gap-6" {...MOTION_FADE_UP}>
      <ValueHeadline
        headline={`Tomorrow's ${day.meetings.length} meetings, briefed.`}
        line={
          flagged
            ? `${flagged.title} needs something from you first. For the rest, just show up.`
            : "You walk into every one knowing who, why and what to ask."
        }
      />

      <div className="rounded-2xl bg-zinc-800 p-4">
        <p className="mb-3 text-[13px] text-zinc-500">{day.label}</p>
        <ol className="flex flex-col gap-2">
          {day.meetings.map((meeting) => (
            <li
              key={meeting.time}
              className="grid grid-cols-[3rem_1fr] gap-3 rounded-xl bg-zinc-900 p-3"
            >
              <span className="text-sm text-zinc-500 tabular-nums">
                {meeting.time}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium text-zinc-100">
                    {meeting.title}
                  </p>
                  {meeting.flag && (
                    <Chip size="sm" variant="flat" color="warning">
                      {meeting.flag}
                    </Chip>
                  )}
                </div>
                <p className="mt-1 text-sm leading-relaxed text-zinc-400">
                  {meeting.brief}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <PriceDock keepLabel={KEEP_LABEL} onCheckout={onCheckout} />
    </m.div>
  );
}
