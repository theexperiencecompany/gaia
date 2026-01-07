/**
 * TriggerTagInput Component
 *
 * Tag-based input UI with keyboard shortcuts (Space/Enter to add, Backspace to remove)
 */

"use client";

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

    // Validate if validator provided
    if (validate && !validate(trimmed)) {
      return;
    }

    // Format tag if formatter provided
    const formatted = formatTag ? formatTag(trimmed) : trimmed;

    // Add if not duplicate
    if (!values.includes(formatted)) {
      onChange([...values, formatted]);
    }
    setInput("");
  };

  const handleRemove = (valueToRemove: string) => {
    onChange(values.filter((v) => v !== valueToRemove));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleAdd();
    } else if (e.key === "Backspace" && !input && values.length > 0) {
      // Remove last tag on backspace if input is empty
      handleRemove(values[values.length - 1]);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={inputId} className="text-sm font-medium text-zinc-300">
        {label}
      </label>
      <div className="relative group w-full max-w-xl">
        <div className="flex flex-wrap gap-2 p-3 border-2 border-zinc-700/50 rounded-lg bg-gradient-to-br from-zinc-900 to-zinc-900/80 min-h-[52px] transition-all duration-200 focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/20 hover:border-zinc-600/50">
          {values.map((value) => (
            <span
              key={value}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gradient-to-br from-zinc-800 to-zinc-800/80 text-zinc-100 rounded-md border border-zinc-700/50 shadow-sm hover:shadow-md hover:border-zinc-600 transition-all duration-200 group/tag"
            >
              <span className="font-mono text-xs">{value}</span>
              <button
                type="button"
                onClick={() => handleRemove(value)}
                className="ml-0.5 text-zinc-400 hover:text-red-400 hover:bg-red-500/10 rounded px-1 transition-all duration-200 group-hover/tag:text-zinc-300"
                aria-label={`Remove ${value}`}
              >
                <svg
                  className="w-3.5 h-3.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </span>
          ))}
          <input
            id={inputId}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={handleAdd}
            placeholder={values.length > 0 ? placeholder : emptyPlaceholder}
            className="flex-1 min-w-[160px] bg-transparent outline-none text-sm text-zinc-100 placeholder-zinc-500/70"
          />
        </div>
      </div>
      <div className="flex items-center justify-between text-xs text-zinc-500 px-1 max-w-xl">
        <span className="flex items-center gap-2">
          Press{" "}
          <kbd className="px-2 py-1 bg-zinc-800/80 border border-zinc-700/50 rounded shadow-sm font-mono text-zinc-400">
            Space
          </kbd>{" "}
          or{" "}
          <kbd className="px-2 py-1 bg-zinc-800/80 border border-zinc-700/50 rounded shadow-sm font-mono text-zinc-400">
            Enter
          </kbd>{" "}
          to add
        </span>
        {description}
      </div>
    </div>
  );
}
