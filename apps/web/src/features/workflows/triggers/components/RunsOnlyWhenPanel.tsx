"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Switch } from "@heroui/switch";
import { FilterHorizontalIcon, PencilEdit01Icon } from "@icons";
import type {
  AuthoredGateView,
  GateSkipRecord,
  SystemGateView,
} from "@shared/api/generated";
import { formatDistanceToNowStrict } from "date-fns";
import { type KeyboardEvent, useState } from "react";
import { PanelRow } from "@/components/shared/PanelRow";
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
  RUNS_ONLY_WHEN_LABEL,
} from "../../constants/gates";
import { gateAuthorLine } from "../../utils/gateEdit";

interface RunsOnlyWhenPanelProps {
  /** The rule the user reads; a system gate's is its preset's wording. */
  condition: string;
  enabled: boolean;
  /** The gate as last saved; its author, state and skips describe the rule only while it is unchanged. */
  saved: AuthoredGateView | SystemGateView | null;
  /** False for a system gate: GAIA owns its wording, so it can only be switched. */
  editable: boolean;
  onConditionSave: (condition: string) => void;
  onEnabledChange: (enabled: boolean) => void;
  isDisabled?: boolean;
}

/** A job's "Runs only when" rule as one row; who wrote it, what it skipped and the edit open on demand. */
export function RunsOnlyWhenPanel({
  condition,
  enabled,
  saved,
  editable,
  onConditionSave,
  onEnabledChange,
  isDisabled = false,
}: RunsOnlyWhenPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const hasRule = condition.trim() !== "";
  const shown = saved && saved.display_condition === condition ? saved : null;
  const author = shown ? gateAuthorLine(shown) : "user";
  const enforced = shown?.enforced;

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
    <PanelRow
      icon={FilterHorizontalIcon}
      label={hasRule ? RUNS_ONLY_WHEN_LABEL : GATE_EMPTY_TITLE}
      summary={hasRule ? condition : GATE_EMPTY_NOTE}
      isExpanded={isExpanded}
      onPress={() => setIsExpanded((open) => !open)}
      isDimmed={hasRule && !enabled}
      trailing={
        hasRule && (
          <Switch
            size="sm"
            isSelected={enabled}
            onValueChange={onEnabledChange}
            isDisabled={isDisabled}
            aria-label={GATE_SWITCH_LABEL}
          />
        )
      }
    >
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
          <div className="flex flex-col gap-1">
            <p className="text-xs text-zinc-400">{GATE_AUTHOR_LINES[author]}</p>
            <p className="text-pretty text-xs leading-relaxed text-zinc-500">
              {status}
            </p>
          </div>
        )
      )}

      {hasRule && draft === null && enabled && enforced !== false && (
        <RecentSkips skips={shown?.recent_skips ?? []} />
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
    </PanelRow>
  );
}

/** The latest events the rule kept from running the job, newest first. */
function RecentSkips({ skips }: { skips: GateSkipRecord[] }) {
  if (skips.length === 0) {
    return <p className="text-xs text-zinc-500">{GATE_NO_SKIPS_NOTE}</p>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs font-medium text-zinc-400">
        {GATE_RECENT_SKIPS_LABEL}
      </p>
      <ul className="flex flex-col gap-1">
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
