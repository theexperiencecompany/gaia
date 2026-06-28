/**
 * TriggerTagInput Component
 *
 * Tag-based input built from HeroUI primitives: type a value and press Enter to
 * add it as a removable Chip. Used for manually entering repos, channel IDs, etc.
 */

"use client";

import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
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
      e.preventDefault();
      handleAdd();
    } else if (e.key === "Backspace" && !input && values.length > 0) {
      handleRemove(values[values.length - 1]);
    }
  };

  return (
    <div className="flex w-full flex-col gap-2">
      <Input
        id={inputId}
        label={label}
        labelPlacement={label ? "outside" : undefined}
        aria-label={label ?? "Add value"}
        size="sm"
        variant="flat"
        value={input}
        onValueChange={setInput}
        onKeyDown={handleKeyDown}
        onBlur={handleAdd}
        placeholder={values.length > 0 ? placeholder : emptyPlaceholder}
        startContent={
          prefix ? (
            <span className="pointer-events-none shrink-0 text-sm text-zinc-500">
              {prefix}
            </span>
          ) : undefined
        }
      />

      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((value) => (
            <Chip
              key={value}
              variant="flat"
              onClose={() => handleRemove(value)}
              classNames={{ content: "font-mono text-xs" }}
            >
              {value}
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
