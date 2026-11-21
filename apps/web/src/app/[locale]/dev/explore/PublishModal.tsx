"use client";

import { Input, Label, ListBox, Modal, Select, TextField } from "@heroui/react";
import { useState } from "react";

import {
  inputVariants,
  overlayVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { toneVariants } from "@/components/shared/tone";
import { IntegrationStack, TaskIconTile, WhenChip } from "../tasks/TaskParts";
import type { Task } from "../tasks/taskModel";
import { TEMPLATES } from "./templateModel";

/** The categories Explore already files templates under; a publisher picks one, never invents one. */
const CATEGORIES = [
  ...new Set(TEMPLATES.flatMap((template) => template.categories)),
].sort();

export interface PublishInput {
  summary: string;
  category: string;
}

/**
 * Publishing saves a copy of the task as a template. The publisher sees exactly
 * the row Explore will show, writes its one line, files it, and is told what
 * stays private. Unpublishing takes it off Explore; copies people made keep working.
 */
export function PublishModal({
  task,
  isOpen,
  onOpenChange,
  onPublish,
}: {
  task: Task;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onPublish: (input: PublishInput) => void;
}) {
  const [summary, setSummary] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const canPublish = summary.trim().length > 0 && category !== null;

  return (
    <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Backdrop>
        <Modal.Container placement="center" size="md">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header>
              <Modal.Heading className="text-lg font-semibold">
                Publish to the community
              </Modal.Heading>
            </Modal.Header>
            <Modal.Body className="space-y-5">
              <div className="flex gap-3.5 rounded-2xl bg-zinc-900 p-3">
                <TaskIconTile icon={task.icon} size={28} />
                <div className="min-w-0 flex-1">
                  <div className="flex min-h-7 items-center gap-2">
                    <p className="truncate text-[15px] text-zinc-100">
                      {task.title}
                    </p>
                    <IntegrationStack ids={task.integrations} size={15} />
                  </div>
                  <p className="truncate text-[13px] leading-5 text-zinc-500">
                    {summary.trim() || "Your one line shows here"}
                  </p>
                  <span className="mt-2 flex">
                    <WhenChip when={task.when} />
                  </span>
                </div>
              </div>

              <TextField value={summary} onChange={setSummary} isRequired>
                <Label className="text-[13px] text-zinc-400">
                  One line for Explore
                </Label>
                <Input
                  placeholder="What someone gets from this"
                  maxLength={90}
                  className={inputVariants({ variant: "sunken" })}
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
                <Label className="text-[13px] text-zinc-400">Category</Label>
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
                <Select.Popover
                  className={overlayVariants({ surface: "raised" })}
                >
                  <ListBox>
                    {CATEGORIES.map((name) => (
                      <GaiaListBoxItem key={name} id={name} textValue={name} />
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>

              <p className="text-[13px] leading-5 text-zinc-500">
                People get a copy of the name, what GAIA does, when it runs and
                the apps it needs, with your name as the maker. Your notes, runs
                and chat stay private. You can unpublish at any time.
              </p>
            </Modal.Body>
            <Modal.Footer>
              <GaiaButton
                size="sm"
                variant="quiet"
                tone="muted"
                onPress={() => onOpenChange(false)}
                className="h-9"
              >
                Cancel
              </GaiaButton>
              <GaiaButton
                size="sm"
                variant="tertiary"
                tone="strong"
                isDisabled={!canPublish}
                onPress={() => {
                  if (!category) return;
                  onPublish({ summary: summary.trim(), category });
                }}
                className="h-9"
              >
                Publish
              </GaiaButton>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
