"use client";

import { CursorPointer02Icon } from "@icons";
import NumberFlow, { continuous, NumberFlowGroup } from "@number-flow/react";
import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef, useState } from "react";
import { TextMorph } from "torph/react";
import LargeHeader from "../shared/LargeHeader";

const SECONDS_PER_UNIT = {
  hours: 3600,
  days: 86400,
  weeks: 604800,
  months: 2592000,
} as const;

type Unit = keyof typeof SECONDS_PER_UNIT;

const SCALES = [
  { key: "day", mult: 1, label: "per day", unit: "hours" as Unit, frac: 0 },
  { key: "week", mult: 7, label: "per week", unit: "hours" as Unit, frac: 0 },
  { key: "month", mult: 30, label: "per month", unit: "days" as Unit, frac: 1 },
  { key: "year", mult: 365, label: "per year", unit: "weeks" as Unit, frac: 1 },
  {
    key: "decade",
    mult: 3650,
    label: "per decade",
    unit: "months" as Unit,
    frac: 1,
  },
] as const;

// GAIA automates the full workday: ~3 hrs of busywork off your plate every day.
const BASE_SECONDS_PER_DAY = 60 * 60 * 3;
const TICK_MS = 250;
const SECONDS_PER_TICK = 0.05;
const AUTO_CYCLE_MS = 5500;

function toUnit(seconds: number, unit: Unit) {
  return seconds / SECONDS_PER_UNIT[unit];
}

const SPRING_TIMING = {
  duration: 900,
  easing: "cubic-bezier(.2,.8,.2,1)",
} as const;

export default function TimeSavedCounter() {
  const sectionRef = useRef<HTMLElement>(null);
  const hasEntered = useInView(sectionRef, { once: true, amount: 0.3 });
  const isVisible = useInView(sectionRef, { amount: 0.3 });

  const [scaleIdx, setScaleIdx] = useState(0);
  const [ticks, setTicks] = useState(0);
  const [hasStarted, setHasStarted] = useState(false);

  // Kick off the live tick once the section first enters view.
  useEffect(() => {
    if (!hasEntered) return;
    setHasStarted(true);
    const id = setInterval(() => {
      setTicks((t) => t + 1);
    }, TICK_MS);
    return () => clearInterval(id);
  }, [hasEntered]);

  // Auto-cycle scales only while the section is on screen. Re-runs whenever
  // scaleIdx changes (manual click or previous auto-tick), so clicks reset the
  // delay and keep cadence in sync.
  useEffect(() => {
    if (!isVisible) return;
    const id = setTimeout(() => {
      setScaleIdx((i) => (i + 1) % SCALES.length);
    }, AUTO_CYCLE_MS);
    return () => clearTimeout(id);
  }, [isVisible, scaleIdx]);

  const scale = SCALES[scaleIdx];
  const liveBoost = ticks * SECONDS_PER_TICK;
  const totalSeconds = hasStarted
    ? (BASE_SECONDS_PER_DAY + liveBoost) * scale.mult
    : 0;

  const value = toUnit(totalSeconds, scale.unit);
  const unitLabel = scale.unit;
  const maxFrac = scale.frac;

  const cycleScale = () => setScaleIdx((i) => (i + 1) % SCALES.length);

  return (
    <section
      ref={sectionRef}
      className="relative flex w-full flex-col items-center px-4 py-20 sm:px-6 sm:py-24 lg:px-8"
    >
      <div className="flex w-full max-w-6xl flex-col items-center gap-16 sm:gap-24">
        <LargeHeader
          chipText="Do the math"
          headingText={<>Buy back your time.</>}
          subHeadingText="GAIA does the busywork so you can focus on what matters."
          centered
        />

        <m.button
          type="button"
          onClick={cycleScale}
          aria-label={`Time saved ${scale.label}. Click to change scale.`}
          whileTap={{ scale: 0.98 }}
          transition={{ type: "spring", duration: 0.3, bounce: 0 }}
          className="group flex flex-col items-center gap-4 cursor-pointer bg-transparent border-0 outline-0 p-0"
        >
          <NumberFlowGroup>
            <div className="flex items-baseline justify-center gap-4 sm:gap-6 md:gap-8 tabular-nums">
              <span
                style={{
                  fontSize: "clamp(1.75rem, 4.5vw, 4.5rem)",
                  lineHeight: 1,
                  letterSpacing: "-0.02em",
                }}
                className="font-medium text-white"
              >
                save
              </span>
              <span
                aria-hidden="true"
                style={{
                  fontSize: "clamp(1.75rem, 4.5vw, 4.5rem)",
                  lineHeight: 1,
                  letterSpacing: "-0.02em",
                }}
                className="font-medium text-white"
              >
                ~
              </span>
              <NumberFlow
                value={value}
                plugins={[continuous]}
                format={{ maximumFractionDigits: maxFrac }}
                trend={1}
                spinTiming={SPRING_TIMING}
                transformTiming={SPRING_TIMING}
                opacityTiming={{ duration: 350, easing: "ease-out" }}
                willChange
                style={{
                  fontSize: "clamp(6rem, 20vw, 19rem)",
                  lineHeight: 0.85,
                  letterSpacing: "-0.04em",
                  ["--number-flow-mask-height" as string]: "0px",
                  pointerEvents: "none",
                }}
                className="font-medium text-white select-none"
              />
              <div
                className="flex flex-col items-start"
                style={{ gap: "clamp(0.5rem, 1.2vw, 1rem)" }}
              >
                <TextMorph
                  as="span"
                  duration={500}
                  style={{
                    fontSize: "clamp(1.75rem, 4.5vw, 4.5rem)",
                    lineHeight: 1,
                    letterSpacing: "-0.02em",
                  }}
                  className="font-medium text-white"
                >
                  {unitLabel}
                </TextMorph>
                <TextMorph
                  as="span"
                  duration={500}
                  style={{
                    fontSize: "clamp(1rem, 1.6vw, 1.5rem)",
                    lineHeight: 1,
                    letterSpacing: "-0.01em",
                  }}
                  className="font-medium text-primary"
                >
                  {scale.label}
                </TextMorph>
              </div>
            </div>
          </NumberFlowGroup>

          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">
            <CursorPointer02Icon width={12} height={12} />
            click to change
          </span>
        </m.button>
      </div>
    </section>
  );
}
