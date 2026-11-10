"use client";

import { Button } from "@heroui/button";
import { Divider } from "@heroui/divider";
import { Textarea } from "@heroui/input";
import { Switch } from "@heroui/switch";
import type { GateSkipRecord } from "@shared/api/generated";
import { type KeyboardEvent, useState } from "react";
import {
  GATE_CONDITION_MAX_CHARS,
  type GATE_COPY,
  GATE_EDIT_LABEL,
  GATE_EDITED_BY_USER,
} from "../../constants/gates";
import { gateSentence } from "../../utils/gateEdit";
import { GateSkipList } from "./GateSkipList";

/** What a rule row and its detail both take: the rule, its switch and its edit. */
export interface GateRuleProps {
  /** The rule the user reads; a system gate's is its preset's wording. */
  condition: string;
  enabled: boolean;
  /** False for a system gate: GAIA owns its wording, so it can only be switched. */
  editable: boolean;
  onConditionSave: (condition: string) => void;
  onEnabledChange: (enabled: boolean) => void;
  isDisabled?: boolean;
}

type GateDetailProps = GateRuleProps & {
  skips: GateSkipRecord[];
  editedByUser: boolean;
  copy: (typeof GATE_COPY)[keyof typeof GATE_COPY];
};

/** The rule in full: what it skipped, its switch, and its inline edit. */
export function GateDetail({
  condition,
  enabled,
  editable,
  onConditionSave,
  onEnabledChange,
  isDisabled = false,
  skips,
  editedByUser,
  copy,
}: GateDetailProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const edited = draft?.trim() ?? "";

  const save = () => {
    setDraft(null);
    if (edited && edited !== condition) onConditionSave(edited);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      setDraft(null);
    }
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) save();
  };

  return (
    <div className="flex w-full flex-col gap-4 p-4">
      {draft === null ? (
        <div className="flex flex-col gap-1">
          <p className="text-sm leading-snug text-pretty text-zinc-200">
            {gateSentence(condition)}
          </p>
          {(editedByUser || editable) && (
            <div className="flex min-h-6 items-center justify-between gap-2">
              <span className="text-xs text-zinc-500">
                {editedByUser && GATE_EDITED_BY_USER}
              </span>
              {editable && (
                <Button
                  size="sm"
                  variant="light"
                  aria-label={GATE_EDIT_LABEL}
                  className="h-6 min-w-0 px-2 text-xs text-zinc-400 data-[hover=true]:text-zinc-200"
                  onPress={() => setDraft(condition)}
                  isDisabled={isDisabled}
                >
                  Edit
                </Button>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <Textarea
            aria-label={GATE_EDIT_LABEL}
            value={draft}
            onValueChange={setDraft}
            onKeyDown={onKeyDown}
            maxLength={GATE_CONDITION_MAX_CHARS}
            minRows={2}
            maxRows={5}
            variant="flat"
            autoFocus
            classNames={{
              inputWrapper: "bg-zinc-800 data-[hover=true]:bg-zinc-800",
              input: "text-sm",
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
              isDisabled={!edited || edited === condition}
            >
              Save
            </Button>
          </div>
        </div>
      )}

      <GateSkipList skips={skips} />

      <Divider className="bg-zinc-800" />

      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm text-zinc-200">{copy.switchLabel}</span>
          <span className="text-xs text-zinc-500">{copy.switchHelper}</span>
        </div>
        <Switch
          size="sm"
          isSelected={enabled}
          onValueChange={onEnabledChange}
          isDisabled={isDisabled}
          aria-label={copy.switchLabel}
          className="mt-0.5"
        />
      </div>
    </div>
  );
}
