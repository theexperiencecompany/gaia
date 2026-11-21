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

/** Where a newly chosen limit starts: ten runs, or a month from today. */
const FIRST_RUNS = 10;
const FIRST_DATE_DAYS = 30;

const modeOf = (ends?: TaskEnds): EndMode =>
  ends?.afterRuns ? "runs" : ends?.onDate ? "date" : "never";

/**
 * When a repeating task stops on its own: never, after a number of runs
 * (max_occurrences) or on a date (stop_after). One of the two, never both.
 */
export default function WhenEnds({
  ends,
  onChange,
}: {
  ends?: TaskEnds;
  onChange: (ends?: TaskEnds) => void;
}) {
  const mode = modeOf(ends);
  const choose = (next: EndMode) => {
    if (next === "never") onChange(undefined);
    if (next === "runs") onChange({ afterRuns: FIRST_RUNS });
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
        <Field label="Runs">
          <InputGroup
            className={inputVariants({ variant: "sunken", className: "w-44" })}
          >
            <InputGroup.Input
              aria-label="Number of runs"
              inputMode="numeric"
              value={String(ends?.afterRuns ?? "")}
              onChange={(event) => {
                const runs = Number(event.target.value.replace(/\D/g, ""));
                onChange({ afterRuns: runs > 0 ? runs : FIRST_RUNS });
              }}
              className={toneVariants({
                tone: "white",
                className: "text-sm tabular-nums",
              })}
            />
            <InputGroup.Suffix>
              <span className="pe-2 text-sm text-zinc-500">runs</span>
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
