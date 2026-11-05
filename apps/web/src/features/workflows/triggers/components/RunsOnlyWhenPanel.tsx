"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Switch } from "@heroui/switch";
import { FilterHorizontalIcon, PencilEdit01Icon } from "@icons";
import type { GateSkipRecord } from "@shared/api/generated";
import { formatDistanceToNowStrict } from "date-fns";
import { type KeyboardEvent, useState } from "react";
import { cn } from "@/lib/utils";
import {
  GATE_AUTHOR_LINES,
  GATE_CONDITION_MAX_CHARS,
  GATE_CONDITION_PLACEHOLDER,
  GATE_EMPTY_NOTE,
  GATE_EMPTY_TITLE,
  GATE_EXPLAINER,
  GATE_NO_SKIPS_NOTE,
  GATE_OFF_NOTE,
  GATE_RECENT_SKIPS_LABEL,
  GATE_SHADOW_NOTE,
  GATE_SWITCH_LABEL,
  type GateAuthorLine,
  RUNS_ONLY_WHEN_LABEL,
} from "../../constants/gates";

interface RunsOnlyWhenPanelProps {
  /** The rule the user reads; a system gate's is its preset's wording. */
  condition: string;
  enabled: boolean;
  /** Who wrote the rule; null while it is only a draft. */
  author: GateAuthorLine | null;
  /** Whether the rule may skip a run yet; unknown until a new rule is saved. */
  enforced?: boolean;
  recentSkips: GateSkipRecord[];
  /** False for a system gate: GAIA owns its wording, so it can only be switched. */
  editable: boolean;
  onConditionSave: (condition: string) => void;
  onEnabledChange: (enabled: boolean) => void;
  isDisabled?: boolean;
}

/** A job's "Runs only when" rule: what GAIA filters, why, what it skipped, and the edit and off controls. */
export function RunsOnlyWhenPanel({
  condition,
  enabled,
  author,
  enforced,
  recentSkips,
  editable,
  onConditionSave,
  onEnabledChange,
  isDisabled = false,
}: RunsOnlyWhenPanelProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const hasRule = condition.trim() !== "";

  const save = () => {
    const edited = draft?.trim() ?? "";
    setDraft(null);
    if (edited && edited !== condition) onConditionSave(edited);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") setDraft(null);
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) save();
  };

  let status = GATE_EXPLAINER;
  if (!enabled) status = GATE_OFF_NOTE;
  else if (enforced === false) status = GATE_SHADOW_NOTE;

  return (
    <section
      aria-label={RUNS_ONLY_WHEN_LABEL}
      className="flex flex-col gap-3 rounded-2xl bg-zinc-800 p-3.5"
    >
      <header className="flex items-center gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary/15">
          <FilterHorizontalIcon className="size-4 text-primary" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-zinc-200">
            {hasRule || draft !== null
              ? RUNS_ONLY_WHEN_LABEL
              : GATE_EMPTY_TITLE}
          </p>
          <p className="truncate text-xs text-zinc-500">
            {hasRule && author ? GATE_AUTHOR_LINES[author] : GATE_EMPTY_NOTE}
          </p>
        </div>
        {hasRule && (
          <Switch
            size="sm"
            isSelected={enabled}
            onValueChange={onEnabledChange}
            isDisabled={isDisabled}
            aria-label={GATE_SWITCH_LABEL}
          />
        )}
      </header>

      {draft !== null ? (
        <div className="flex flex-col gap-2">
          <Textarea
            aria-label={RUNS_ONLY_WHEN_LABEL}
            value={draft}
            onValueChange={setDraft}
            onKeyDown={onKeyDown}
            placeholder={GATE_CONDITION_PLACEHOLDER}
            maxLength={GATE_CONDITION_MAX_CHARS}
            minRows={2}
            maxRows={5}
            variant="flat"
            autoFocus
            classNames={{
              inputWrapper: "bg-zinc-900 data-[hover=true]:bg-zinc-900",
            }}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="light" onPress={() => setDraft(null)}>
              Cancel
            </Button>
            <Button
              size="sm"
              color="primary"
              onPress={save}
              isDisabled={!draft.trim() || draft.trim() === condition}
            >
              Save rule
            </Button>
          </div>
        </div>
      ) : (
        hasRule && (
          <div
            className={cn(
              "flex flex-col gap-1.5 transition-opacity duration-200",
              !enabled && "opacity-60",
            )}
          >
            <p className="text-pretty text-sm leading-relaxed text-zinc-100">
              {condition}
            </p>
            <p className="text-pretty text-xs leading-relaxed text-zinc-500">
              {status}
            </p>
          </div>
        )
      )}

      {hasRule && draft === null && enabled && enforced !== false && (
        <RecentSkips skips={recentSkips} />
      )}

      {editable && draft === null && (
        <div className="flex">
          <Button
            size="sm"
            variant="flat"
            radius="lg"
            className="bg-zinc-700/60 text-zinc-200"
            startContent={<PencilEdit01Icon className="size-3.5" />}
            onPress={() => setDraft(condition)}
            isDisabled={isDisabled}
          >
            {hasRule ? "Edit rule" : "Add a rule"}
          </Button>
        </div>
      )}
    </section>
  );
}

/** The latest events the rule kept from running the job, newest first. */
function RecentSkips({ skips }: { skips: GateSkipRecord[] }) {
  if (skips.length === 0) {
    return <p className="text-xs text-zinc-500">{GATE_NO_SKIPS_NOTE}</p>;
  }
  return (
    <div className="rounded-xl bg-zinc-900 px-3 py-2.5">
      <p className="mb-1.5 text-xs font-medium text-zinc-400">
        {GATE_RECENT_SKIPS_LABEL}
      </p>
      <ul className="flex flex-col gap-1.5">
        {[...skips].reverse().map((skip) => (
          <li
            key={`${skip.at}:${skip.event}`}
            className="flex items-baseline justify-between gap-3 text-xs"
          >
            <span className="min-w-0 truncate text-zinc-300" title={skip.event}>
              {skip.event}
            </span>
            <time
              dateTime={skip.at}
              className="shrink-0 tabular-nums text-zinc-500"
            >
              {formatDistanceToNowStrict(new Date(skip.at), {
                addSuffix: true,
              })}
            </time>
          </li>
        ))}
      </ul>
    </div>
  );
}
