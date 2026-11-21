"use client";

import { Input, Label, ListBox, Select, TextField } from "@heroui/react";
import { Share01Icon } from "@icons";
import { useState } from "react";

import {
  inputVariants,
  overlayVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { toneVariants } from "@/components/shared/tone";
import { IntegrationStack } from "../tasks/AppIcon";
import { TaskIconTile } from "../tasks/TaskIconTile";
import type { Task } from "../tasks/taskModel";
import { WhenChip } from "../tasks/WhenChip";
import { TEMPLATES } from "./templateModel";

/** The categories Explore already files templates under; a publisher picks one, never invents one. */
const CATEGORIES = [
  ...new Set(TEMPLATES.flatMap((template) => template.categories)),
].sort();

export interface PublishInput {
  summary: string;
  category: string;
}

const fieldLabel = toneVariants({ tone: "muted", className: "text-[13px]" });

/**
 * Publishing, as a step in the task's sidebar: the publisher sees exactly the row
 * Explore will show, writes its one line, files it, and is told what stays private.
 */
export function PublishStep({
  task,
  onPublish,
  onCancel,
}: {
  task: Task;
  onPublish: (input: PublishInput) => void;
  onCancel: () => void;
}) {
  const [summary, setSummary] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const canPublish = summary.trim().length > 0 && category !== null;

  return (
    <section
      aria-label="Publish to the community"
      className="space-y-4 rounded-2xl bg-zinc-800 p-4"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
        <Share01Icon className="size-3.5" />
        Publish to the community
      </p>

      <div className="flex gap-3.5 rounded-2xl bg-zinc-900 p-3">
        <TaskIconTile icon={task.icon} size={28} />
        <div className="min-w-0 flex-1">
          <div className="flex min-h-7 items-center gap-2">
            <p className="truncate text-[15px] text-zinc-100">{task.title}</p>
            <IntegrationStack ids={task.integrations} size={15} />
          </div>
          <p className="line-clamp-2 text-[13px] leading-5 text-zinc-500">
            {summary.trim() || "Your one line shows here"}
          </p>
          <span className="mt-2 flex">
            <WhenChip when={task.when} />
          </span>
        </div>
      </div>

      <TextField value={summary} onChange={setSummary} isRequired>
        <Label className={fieldLabel}>One line for Explore</Label>
        <Input
          autoFocus
          placeholder="What someone gets from this"
          maxLength={90}
          className={inputVariants({
            variant: "sunken",
            placeholder: "faint",
            className: toneVariants({ tone: "white", className: "text-sm" }),
          })}
        />
      </TextField>

      <Select
        selectedKey={category}
        onSelectionChange={(key) =>
          setCategory(key === null ? null : String(key))
        }
        placeholder="Choose one"
        isRequired
      >
        <Label className={fieldLabel}>Category</Label>
        <Select.Trigger
          className={inputVariants({
            variant: "sunken",
            className: "w-full cursor-pointer",
          })}
        >
          <GaiaSelectValue
            className={toneVariants({
              tone: category ? "white" : "muted",
              className: "text-sm",
            })}
          />
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover className={overlayVariants({ surface: "raised" })}>
          <ListBox>
            {CATEGORIES.map((name) => (
              <GaiaListBoxItem key={name} id={name} textValue={name} />
            ))}
          </ListBox>
        </Select.Popover>
      </Select>

      <p className="text-[13px] leading-5 text-zinc-500">
        People get a copy of the name, what GAIA does, when it runs and the apps
        it needs, with your name as the maker. Your notes, runs and chat stay
        private. You can unpublish at any time.
      </p>

      <div className="flex gap-2">
        <GaiaButton
          size="sm"
          shape="md"
          variant="primary"
          className="h-9 font-medium"
          isDisabled={!canPublish}
          onPress={() => {
            if (!category) return;
            onPublish({ summary: summary.trim(), category });
          }}
        >
          Publish
        </GaiaButton>
        <GaiaButton
          size="sm"
          shape="md"
          variant="default-soft"
          className="h-9"
          onPress={onCancel}
        >
          Cancel
        </GaiaButton>
      </div>
    </section>
  );
}
