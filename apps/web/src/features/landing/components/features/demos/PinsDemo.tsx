"use client";

import { PinIcon } from "@icons";
import { m, useInView } from "motion/react";
import { useRef } from "react";

interface PinCard {
  id: string;
  message: string;
  timestamp: string;
}

const PINS: PinCard[] = [
  {
    id: "pin1",
    message:
      "The onboarding flow needs 3 more steps — confirmed with Sarah. Add identity verification.",
    timestamp: "2d ago",
  },
  {
    id: "pin2",
    message:
      "GAIA found a bug in the auth middleware — JWT expiry not handled for refresh tokens.",
    timestamp: "5d ago",
  },
  {
    id: "pin3",
    message: "Q2 OKRs: Ship voice mode, reach 500 DAU, launch marketplace.",
    timestamp: "1w ago",
  },
  {
    id: "pin4",
    message: "Deepgram → ElevenLabs latency: ~400ms p95. Acceptable for MVP.",
    timestamp: "1w ago",
  },
  {
    id: "pin5",
    message:
      "Alex confirmed: merge freeze on Thursday before mobile release cut.",
    timestamp: "2w ago",
  },
  {
    id: "pin6",
    message:
      "Context: Legal flagged session token storage. Must comply by April 1.",
    timestamp: "2w ago",
  },
];

export default function PinsDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div ref={ref} className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {PINS.map((pin, index) => (
        <m.div
          key={pin.id}
          initial={{ opacity: 0, y: 16 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
          transition={{
            duration: 0.3,
            delay: index * 0.07,
            ease: "easeOut",
          }}
          className="rounded-xl bg-zinc-800 p-3 flex flex-col gap-1"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs text-zinc-300 leading-relaxed line-clamp-3">
              {pin.message}
            </p>
            <PinIcon className="h-3 w-3 shrink-0 text-zinc-500 mt-0.5" />
          </div>
          <p className="text-xs text-zinc-500 mt-1">{pin.timestamp}</p>
        </m.div>
      ))}
    </div>
  );
}
