"use client";

import { DateField, InputGroup, Skeleton } from "@heroui/react";
import { parseDate } from "@internationalized/date";
import { format, parseISO, setHours } from "date-fns";
import type { ReactNode } from "react";

import {
  inputVariants,
  skeletonVariants,
} from "@/components/shared/controlVariants";
import { toneVariants } from "@/components/shared/tone";
import { cn } from "@/lib/utils";
import PickMenu from "./PickMenu";
import type { TaskEnds, TaskWatch, WatchCondition } from "./taskModel";
import { WatchIcon } from "./WatchIcon";
import WhenEnds from "./WhenEnds";
import { EDITOR_FIELD, Field } from "./WhenParts";
import {
  amount,
  cadenceChoices,
  cadenceLabel,
  DEADLINE_HOUR,
} from "./watchModel";

/** A fact that is read, not set: on the line a control would take, text where a control's text starts. */
function Reading({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-9 w-44 min-w-0 items-center gap-2 px-2 text-sm text-zinc-100">
      {children}
    </span>
  );
}

/** What it tells you on, set in the control its kind takes. */
function TellMe({
  watch,
  onChange,
}: {
  watch: TaskWatch;
  onChange: (condition: WatchCondition) => void;
}) {
  const { condition } = watch;
  switch (watch.kind) {
    case "threshold":
      return (
        <Field label="Tell me">
          <InputGroup
            className={inputVariants({ variant: "sunken", className: "w-44" })}
          >
            <InputGroup.Prefix>
              <span className="text-sm text-zinc-500">
                {condition.direction === "above" ? "Over" : "Under"}
              </span>
            </InputGroup.Prefix>
            <InputGroup.Input
              aria-label="Amount"
              inputMode="decimal"
              value={amount(condition.value ?? 0, condition.unit)}
              onChange={(event) => {
                const value = Number(event.target.value.replace(/[^\d.]/g, ""));
                onChange({ ...condition, value });
              }}
              className={toneVariants({
                tone: "white",
                className: "text-sm tabular-nums",
              })}
            />
          </InputGroup>
        </Field>
      );
    case "state":
      return (
        <Field label="Tell me">
          <PickMenu
            label="Tell me"
            summary={condition.target ?? ""}
            options={(condition.states ?? []).map((state) => ({
              id: state,
              label: state,
            }))}
            selected={condition.target ? [condition.target] : []}
            isMultiple={false}
            onPick={(target) => onChange({ ...condition, target })}
          />
        </Field>
      );
    case "reply_by":
      return (
        <Field label="No reply by">
          <DateField
            aria-label="No reply by"
            value={parseDate(
              format(parseISO(condition.deadline ?? ""), "yyyy-MM-dd"),
            )}
            onChange={(day) =>
              day &&
              onChange({
                ...condition,
                deadline: setHours(
                  parseISO(day.toString()),
                  DEADLINE_HOUR,
                ).toISOString(),
              })
            }
            className="w-44"
          >
            <DateField.Group className={EDITOR_FIELD}>
              <DateField.Input>
                {(segment) => <DateField.Segment segment={segment} />}
              </DateField.Input>
            </DateField.Group>
          </DateField>
        </Field>
      );
    default:
      return (
        <Field label="Tell me">
          <Reading>
            {watch.kind === "new_items"
              ? "Each new one"
              : watch.kind === "uptime"
                ? "When it's down"
                : "When GAIA finds it"}
          </Reading>
        </Field>
      );
  }
}

/** The fine print, in one quiet line: a second read, a final state, the expiry. */
function finePrint(watch: TaskWatch, ends?: TaskEnds): string {
  const lines: string[] = [];
  if (watch.confirmTwice)
    lines.push("Checks twice, a minute apart, to be sure.");
  const final = watch.condition.finalStates;
  if (final?.length)
    lines.push(
      `Also ends once it's ${final.map((state) => state.toLowerCase()).join(" or ")}.`,
    );
  if (!ends?.onDate && watch.kind !== "reply_by")
    lines.push(
      `Stops by ${format(parseISO(watch.expiresAt), "MMM d")} unless you renew it.`,
    );
  return lines.join(" ");
}

const LABELS = ["Watches", "Right now", "Tell me", "Checks", "Ends"];

/** The proposal's lines while the first check runs: the same rows, values still coming. */
export function WatchProposalSkeleton({ footnote }: { footnote: ReactNode }) {
  return (
    <div className="space-y-2">
      {LABELS.map((label) => (
        <Field key={label} label={label}>
          <Reading>
            <Skeleton
              className={skeletonVariants({
                surface: "raised",
                className: "h-3.5 w-24",
              })}
            />
          </Reading>
        </Field>
      ))}
      <div className="min-h-7">{footnote}</div>
    </div>
  );
}

/**
 * What GAIA will watch, as five plain lines, each editable where it can be:
 * what it reads, the reading now, what it tells you on, how often, and the end.
 */
export default function WatchProposal({
  watch,
  ends,
  onChange,
  isStale,
  footnote,
}: {
  watch: TaskWatch;
  ends?: TaskEnds;
  onChange: (watch: TaskWatch, ends?: TaskEnds) => void;
  /** The sentence was edited since this was read, so it waits on a new check. */
  isStale: boolean;
  /** Replaces the fine print, as the way to check again. */
  footnote?: ReactNode;
}) {
  const choices = cadenceChoices(watch);
  return (
    <div className="space-y-2">
      <div className={cn("space-y-2", isStale && "opacity-50")}>
        <Field label="Watches">
          <Reading>
            <WatchIcon source={watch.source} size={15} />
            <span className="truncate">{watch.source.label}</span>
          </Reading>
        </Field>
        <Field label="Right now">
          <Reading>
            <span className="truncate tabular-nums">
              {watch.reading?.value}
            </span>
          </Reading>
        </Field>
        <TellMe
          watch={watch}
          onChange={(condition) => onChange({ ...watch, condition }, ends)}
        />
        <Field label="Checks">
          {choices.length > 1 ? (
            <PickMenu
              label="Checks"
              summary={cadenceLabel(watch.everyMinutes)}
              options={choices.map((minutes) => ({
                id: String(minutes),
                label: cadenceLabel(minutes),
              }))}
              selected={[String(watch.everyMinutes)]}
              isMultiple={false}
              onPick={(id) =>
                onChange({ ...watch, everyMinutes: Number(id) }, ends)
              }
            />
          ) : (
            <Reading>{cadenceLabel(watch.everyMinutes)}</Reading>
          )}
        </Field>
        {watch.kind === "reply_by" ? (
          <Field label="Ends">
            <Reading>
              <span className="truncate">
                When {watch.condition.from} replies
              </span>
            </Reading>
          </Field>
        ) : (
          <WhenEnds
            ends={ends}
            unit="alerts"
            onChange={(next) => onChange(watch, next)}
          />
        )}
      </div>
      <div className="min-h-7">
        {footnote ?? (
          <p className="px-1 pt-1 text-xs leading-5 text-zinc-500">
            {finePrint(watch, ends)}
          </p>
        )}
      </div>
    </div>
  );
}
