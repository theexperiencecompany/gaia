"use client";

import { DateField, InputGroup } from "@heroui/react";
import { parseDate, today } from "@internationalized/date";
import { addDays, format } from "date-fns";

import { inputVariants } from "@/components/shared/controlVariants";
import { toneVariants } from "@/components/shared/tone";
import { getUserHomeTimezone } from "@/lib/timezone";
import Segmented from "./Segmented";
import type { TaskEnds } from "./taskModel";
import { EDITOR_FIELD, Field } from "./WhenParts";

type EndMode = "never" | "runs" | "date";

const END_MODES: { key: EndMode; label: string }[] = [
  { key: "never", label: "Never" },
  { key: "runs", label: "After" },
  { key: "date", label: "On" },
];

/** What a limit counts: a repeat's runs, or the times a watch tells you. */
type Unit = "runs" | "alerts";

const COUNTED: Record<
  Unit,
  { label: string; one: string; many: string; first: number }
> = {
  runs: { label: "Runs", one: "run", many: "runs", first: 10 },
  alerts: { label: "Alerts", one: "alert", many: "alerts", first: 1 },
};

/** Where a newly chosen date limit starts: a month from today. */
const FIRST_DATE_DAYS = 30;

const modeOf = (ends?: TaskEnds): EndMode =>
  ends?.afterRuns ? "runs" : ends?.onDate ? "date" : "never";

/**
 * When a repeating task or a watch stops on its own: never, after a number of
 * runs or alerts (max_occurrences) or on a date (stop_after). One, never both.
 */
export default function WhenEnds({
  ends,
  onChange,
  unit = "runs",
}: {
  ends?: TaskEnds;
  onChange: (ends?: TaskEnds) => void;
  unit?: Unit;
}) {
  const mode = modeOf(ends);
  const counted = COUNTED[unit];
  const choose = (next: EndMode) => {
    if (next === "never") onChange(undefined);
    if (next === "runs") onChange({ afterRuns: counted.first });
    if (next === "date")
      onChange({
        onDate: format(addDays(new Date(), FIRST_DATE_DAYS), "yyyy-MM-dd"),
      });
  };

  return (
    <div className="space-y-2">
      <Field label="Ends">
        <div className="w-44">
          <Segmented
            label="Ends"
            options={END_MODES}
            value={mode}
            onChange={choose}
          />
        </div>
      </Field>
      {mode === "runs" && (
        <Field label={counted.label}>
          <InputGroup
            className={inputVariants({ variant: "sunken", className: "w-44" })}
          >
            <InputGroup.Input
              aria-label={`Number of ${counted.many}`}
              inputMode="numeric"
              value={String(ends?.afterRuns ?? "")}
              onChange={(event) => {
                const count = Number(event.target.value.replace(/\D/g, ""));
                onChange({ afterRuns: count > 0 ? count : counted.first });
              }}
              className={toneVariants({
                tone: "white",
                className: "text-sm tabular-nums",
              })}
            />
            <InputGroup.Suffix>
              <span className="pe-2 text-sm text-zinc-500">
                {ends?.afterRuns === 1 ? counted.one : counted.many}
              </span>
            </InputGroup.Suffix>
          </InputGroup>
        </Field>
      )}
      {mode === "date" && ends?.onDate && (
        <Field label="Last day">
          <DateField
            aria-label="Last day"
            value={parseDate(ends.onDate)}
            minValue={today(getUserHomeTimezone())}
            onChange={(day) => day && onChange({ onDate: day.toString() })}
            className="w-44"
          >
            <DateField.Group className={EDITOR_FIELD}>
              <DateField.Input>
                {(segment) => <DateField.Segment segment={segment} />}
              </DateField.Input>
            </DateField.Group>
          </DateField>
        </Field>
      )}
    </div>
  );
}
