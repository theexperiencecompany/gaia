/**
 * TriggerTagInput Component
 *
 * Tag-based input built from HeroUI primitives: type a value and press Enter to
 * add it as a removable Chip. Used for manually entering repos, channel IDs, etc.
 */

"use client";

import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import { useId, useState } from "react";

import type { TriggerTagInputProps } from "./types";

export function TriggerTagInput({
  label,
  values,
  onChange,
  placeholder = "Add item...",
  emptyPlaceholder = "Add items",
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
    <div className="flex w-full max-w-xl flex-col gap-2">
      <Input
        id={inputId}
        label={label}
        labelPlacement="outside"
        size="sm"
        variant="flat"
        value={input}
        onValueChange={setInput}
        onKeyDown={handleKeyDown}
        onBlur={handleAdd}
        placeholder={values.length > 0 ? placeholder : emptyPlaceholder}
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

      <div className="flex items-center justify-between gap-2 px-1 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5">
          Press <Kbd keys={["enter"]}>Enter</Kbd> to add
        </span>
        {description}
      </div>
    </div>
  );
}
