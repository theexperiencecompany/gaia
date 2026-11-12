/**
 * TriggerTagInput Component
 *
 * Tag-based input built from HeroUI primitives: type a value and press Enter to
 * add it as a removable Chip. Used for manually entering repos, channel IDs, etc.
 */

"use client";

import { Chip, InputGroup, Label, TextField } from "@heroui/react";
import { Cancel01Icon } from "@icons";
import { useId, useState } from "react";

import type { TriggerTagInputProps } from "./types";

export function TriggerTagInput({
  label,
  values,
  onChange,
  placeholder = "Add item...",
  emptyPlaceholder = "Add items",
  prefix,
  validate,
  formatTag,
  description,
}: TriggerTagInputProps) {
  const [input, setInput] = useState("");
  const inputId = useId();

  const handleAdd = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    if (validate && !validate(trimmed)) return;

    const formatted = formatTag ? formatTag(trimmed) : trimmed;
    if (!values.includes(formatted)) {
      onChange([...values, formatted]);
    }
    setInput("");
  };

  const handleRemove = (valueToRemove: string) => {
    onChange(values.filter((v) => v !== valueToRemove));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      // IME users press Enter to confirm a candidate mid-composition; don't
      // commit a half-typed tag until the composition is finished.
      if (e.nativeEvent.isComposing) return;
      e.preventDefault();
      handleAdd();
    } else if (e.key === "Backspace" && !input && values.length > 0) {
      handleRemove(values[values.length - 1]);
    }
  };

  return (
    <div className="flex w-full flex-col gap-2">
      <TextField id={inputId}>
        {label ? <Label>{label}</Label> : null}
        <InputGroup>
          {prefix ? (
            <InputGroup.Prefix>
              <span className="pointer-events-none shrink-0 text-sm text-zinc-500">
                {prefix}
              </span>
            </InputGroup.Prefix>
          ) : undefined}
          <InputGroup.Input
            aria-label={label ?? "Add value"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={handleAdd}
            placeholder={values.length > 0 ? placeholder : emptyPlaceholder}
          />
        </InputGroup>
      </TextField>

      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((value) => (
            <Chip key={value} variant="soft">
              <span className="font-mono text-xs">{value}</span>
              <button
                type="button"
                aria-label={`Remove ${value}`}
                className="ml-0.5 shrink-0 cursor-pointer text-zinc-500 hover:text-zinc-300"
                onClick={() => handleRemove(value)}
              >
                <Cancel01Icon className="size-3" />
              </button>
            </Chip>
          ))}
        </div>
      )}

      {description ? (
        <div className="flex justify-end px-1 text-xs">{description}</div>
      ) : null}
    </div>
  );
}
