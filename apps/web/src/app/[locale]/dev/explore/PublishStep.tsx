"use client";

import { Dropdown, TextArea } from "@heroui/react";
import { ArrowDown01Icon, Share01Icon, Tick02Icon } from "@icons";
import { useRef, useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { toneVariants } from "@/components/shared/tone";
import { PropertyRow } from "../tasks/PropertyRow";
import type { Task } from "../tasks/taskModel";
import { useFocusAfterMenu } from "../tasks/useFocusAfterMenu";
import { TemplateRowBody } from "./TemplateRow";
import { TEMPLATES } from "./templateModel";

/** The categories Explore already files templates under; a publisher picks one, never invents one. */
const CATEGORIES = [
  ...new Set(TEMPLATES.flatMap((template) => template.categories)),
].sort();

/** The longest one line Explore shows in full. */
const SUMMARY_MAX = 90;

export interface PublishInput {
  summary: string;
  category: string;
}

/**
 * Publishing, as a step in the task's sidebar: the publisher sees the row Explore
 * will show, writes its one line, files it, and is told what stays private.
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
  const line = summary.trim();
  const field = useRef<HTMLTextAreaElement>(null);
  useFocusAfterMenu(field);

  return (
    <section aria-label="Publish to the community" className="space-y-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
        <Share01Icon className="size-3.5" />
        Publish to the community
      </p>

      <div className="-mx-2">
        <TemplateRowBody
          icon={task.icon}
          title={task.title}
          apps={task.integrations}
          summary={line || "Your one line shows here"}
          when={task.when}
          isNarrow
        />
      </div>

      <div>
        {/* 8px above and below make the one line a 36px row, like the rows under it. */}
        <div className="py-2">
          <TextArea
            ref={field}
            aria-label="One line for Explore"
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            placeholder="One line: what someone gets from this"
            maxLength={SUMMARY_MAX}
            rows={1}
            className={inputVariants({
              variant: "inline",
              placeholder: "subtle",
              className: toneVariants({
                tone: "muted",
                className:
                  "field-sizing-content block w-full resize-none text-sm leading-5",
              }),
            })}
          />
        </div>
        <PropertyRow label="Category">
          <Dropdown>
            <GaiaButton
              size="sm"
              variant="property"
              tone={category ? "bright" : "faint"}
              inset="tight"
              aria-label="Category"
              className="-ml-2 h-8 min-w-0 flex-1 justify-between gap-1.5 text-sm"
            >
              {category ?? "Choose one"}
              <ArrowDown01Icon className="size-4 shrink-0 opacity-60" />
            </GaiaButton>
            <Dropdown.Popover
              placement="bottom start"
              offset={6}
              className={shapeVariants({ shape: "lg", className: "min-w-44" })}
            >
              <Dropdown.Menu
                aria-label="Category"
                onAction={(key) => setCategory(String(key))}
              >
                {CATEGORIES.map((name) => (
                  <Dropdown.Item
                    key={name}
                    id={name}
                    textValue={name}
                    className="gap-2"
                  >
                    {name}
                    {name === category && (
                      <Tick02Icon className="ml-auto size-4 text-zinc-400" />
                    )}
                  </Dropdown.Item>
                ))}
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
        </PropertyRow>
      </div>

      <p className="text-[13px] leading-5 text-zinc-500">
        People get a copy with your name on it. Your notes, runs and chat stay
        private.
      </p>

      <div className="flex gap-2">
        <GaiaButton
          size="sm"
          shape="md"
          variant="primary"
          className="h-9 font-medium"
          isDisabled={!line || !category}
          onPress={() => {
            if (category) onPublish({ summary: line, category });
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
